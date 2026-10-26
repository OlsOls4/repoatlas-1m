"""Tutorial runner: turn DocDrift findings into executable repro scripts and run them in isolated venvs.

For each finding, Beam writes a minimal script that follows the cited docs literally plus a predicted
failure. The script runs under a stdlib-only harness inside a venv that has the library installed at its
pinned commit, with no network access. The status is decided deterministically from what actually happened.
The model's own opinion never sets the status.

Statuses:
- ``reproduced``: the doc-literal usage raised the predicted exception type (or a documented-behaviour
  ``assert`` failed when an AssertionError was predicted). The exception was not raised by the script itself
  with a ``raise`` statement.
- ``not_reproduced``: the script ran to completion (exit 0), so the documented usage worked.
- ``could_not_run``: setup or install failure, timeout, missing non-library module, network or server need,
  lint violation, self-raised exception, or an exception other than the predicted one (after one retry).
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any, Callable, Protocol

import requests

from repoatlas.client import _close_truncated_json, _exclusive_lock, _extract_message_content, _extract_usage


STATUS_REPRODUCED: str = "reproduced"
STATUS_NOT_REPRODUCED: str = "not_reproduced"
STATUS_COULD_NOT_RUN: str = "could_not_run"
ALL_STATUSES: tuple[str, ...] = (STATUS_REPRODUCED, STATUS_NOT_REPRODUCED, STATUS_COULD_NOT_RUN)

DEFAULT_RUN_TIMEOUT_SECONDS: int = 60
DEFAULT_INSTALL_TIMEOUT_SECONDS: int = 900
DOC_CONTEXT_BEFORE: int = 10
DOC_CONTEXT_AFTER: int = 10
CODE_CONTEXT_BEFORE: int = 10
CODE_CONTEXT_AFTER: int = 30
MAX_REGION_CHARS: int = 7000
ERROR_EXCERPT_CHARS: int = 600

# Exceptions that mean the documented name, parameter or import path does not exist. A doc-literal call that
# fails with one of these is strong evidence on its own. An AssertionError only shows that the model's reading of
# the docs disagrees with the code, so it is reported as weaker evidence.
INTERFACE_ERRORS: frozenset[str] = frozenset({"TypeError", "AttributeError", "ImportError", "ModuleNotFoundError", "NameError"})

# Exceptions that mean "the environment, not the docs": the script could not test the claim.
ENVIRONMENT_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "TimeoutError",
        "socket.gaierror",
        "gaierror",
        "PermissionError",
        "KeyboardInterrupt",
        "MemoryError",
        "RecursionError",
    }
)

NETWORK_MESSAGE_PATTERN: str = (
    r"Network is unreachable|Temporary failure in name resolution|Name or service not known|"
    r"Connection refused|No route to host|nodename nor servname"
)

HARNESS_SOURCE: str = r'''
"""Stdlib-only harness: run a repro script and record the exception it ends with, if any."""
import json, linecache, runpy, sys, traceback

script_path, result_path = sys.argv[1], sys.argv[2]
result = {"completed": False, "exception": None}
sys.argv = [script_path]
try:
    runpy.run_path(script_path, run_name="__main__")
    result["completed"] = True
except BaseException as exc:  # noqa: BLE001 - the harness must see everything
    tb = traceback.extract_tb(exc.__traceback__)
    frames = [
        {"file": f.filename, "line": f.lineno, "name": f.name, "source": (f.line or "").strip()}
        for f in tb
        if not f.filename.endswith("runpy.py") and f.filename != __file__
    ]
    mro = [f"{c.__module__}.{c.__qualname__}" for c in type(exc).__mro__]
    missing = getattr(exc, "name", None) if isinstance(exc, ImportError) else None
    result["exception"] = {
        "type": type(exc).__qualname__,
        "qualified_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "mro": mro,
        "message": str(exc)[:2000],
        "missing_module": missing,
        "frames": frames[-8:],
        "exit_code": exc.code if isinstance(exc, SystemExit) else None,
        "traceback": "".join(traceback.format_exception(exc))[-4000:],
    }
with open(result_path, "w", encoding="utf-8") as fh:
    json.dump(result, fh)
if not result["completed"]:
    sys.stderr.write(result["exception"]["traceback"])
    sys.exit(1)
'''

REPRO_SYSTEM_PROMPT: str = """You are a skeptical maintainer checking a reported documentation drift in a Python library.
You write a minimal, self-contained Python script that follows the documentation LITERALLY and fails if,
and only if, the documentation is wrong. Reply with one JSON object and nothing else."""

REPRO_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "argument_finding_is_false",
        "model_verdict",
        "doc_literal_usage",
        "expected_exception_type",
        "expected_failure",
        "extra_requirements",
        "needs_network_or_server",
        "repro_script",
    ],
    "properties": {
        "argument_finding_is_false": {"type": "string"},
        "model_verdict": {"type": "string", "enum": ["likely_true", "likely_false", "unclear"]},
        "doc_literal_usage": {"type": "string"},
        "expected_exception_type": {"type": "string"},
        "expected_failure": {"type": "string"},
        "extra_requirements": {"type": "array", "items": {"type": "string"}},
        "needs_network_or_server": {"type": "boolean"},
        "repro_script": {"type": "string"},
    },
}

SCRIPT_RULES: str = """Rules for repro_script:
1. The library is pip-installed from the pinned commit (import it normally; never import from a source checkout).
   It runs with Python 3.13, OFFLINE (no network), with a 60 s timeout. Stdlib + the library and its declared
   dependencies only; list any other pip package in extra_requirements (e.g. an optional test client).
2. Do any setup needed, then perform the documented usage EXACTLY as the docs (or docstring) state it: same
   names, same argument names, same import path, same call shape. If the docs make a behavioural claim
   (a default, a return value, a side effect), check it with a plain `assert <documented behaviour>, "<what docs say>"`.
   Mark the doc-literal statement(s) with a trailing `# DOC-LITERAL` comment on each line (or wrap them between
   `# DOC-LITERAL-BEGIN` and `# DOC-LITERAL-END` comment lines). An exception raised anywhere else (setup) does
   NOT count, so setup must be correct: build real objects the documented way (use the library's in-process
   test client or a minimal fake where needed) and drive coroutines with asyncio.run.
3. The doc-literal usage must NOT be wrapped in try/except. Do not `raise` anything yourself, do not call
   sys.exit/os._exit, do not print fake results. Do not start servers or open sockets; use in-process tools.
4. If the docs are correct, the script must exit normally and print "DOCS_OK" as its last line.
5. Keep it short (under 40 lines), with no Markdown fences.
expected_exception_type: the exception class name the doc-literal usage raises if the finding is TRUE
(e.g. "TypeError", "AttributeError", "ImportError", "AssertionError"). Use "none" if you think the docs are right.
argument_finding_is_false: argue, as hard as the evidence allows, that the finding is a false positive
(e.g. the docs describe behaviour that lives elsewhere, a kwargs passthrough, an alias, a historical note).
model_verdict: your honest call after that argument."""


@dataclass(slots=True)
class ReproCase:
    """
    @brief One DocDrift finding plus where to get the library source for it.
    @param case_id Stable id, e.g. ``cattrs-400000:DD-2``.
    @param repo Short repo name.
    @param repo_url Repository URL.
    @param ref Pinned commit SHA used for install.
    @param source_dir Local checkout at ``ref``.
    @param finding Finding dict as emitted by the analyser (doc_citation, code_citation, explanation...).
    """

    case_id: str
    repo: str
    repo_url: str
    ref: str
    source_dir: Path
    finding: dict[str, Any]


@dataclass(slots=True)
class ReproPlan:
    """
    @brief Parsed model answer for one finding.
    """

    repro_script: str
    expected_exception_type: str
    expected_failure: str
    doc_literal_usage: str
    argument_finding_is_false: str
    model_verdict: str
    extra_requirements: list[str] = field(default_factory=list)
    needs_network_or_server: bool = False


@dataclass(slots=True)
class RunResult:
    """
    @brief Raw outcome of running one script under the harness.
    """

    returncode: int | None
    timed_out: bool
    stdout: str
    stderr: str
    harness: dict[str, Any] | None
    duration_seconds: float
    network_isolation: str


@dataclass(slots=True)
class Classification:
    """
    @brief Deterministic verdict for one run.
    @param status One of ALL_STATUSES.
    @param reason Machine-readable reason code.
    @param exception_type Observed exception class name, if any.
    @param error_excerpt Short excerpt of the error or output.
    @param evidence ``exception`` or ``assertion`` for reproduced cases.
    @param retryable Whether one retry with the error fed back is allowed.
    """

    status: str
    reason: str
    exception_type: str | None = None
    error_excerpt: str = ""
    evidence: str | None = None
    retryable: bool = False


class CompletionClient(Protocol):
    """
    @brief Minimal chat-completion interface so tests can stub Beam.
    """

    def complete(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
        """
        @brief Return (content, usage) for a chat request.
        """


# ---------------------------------------------------------------------------------------------------------
# Source regions and prompts
# ---------------------------------------------------------------------------------------------------------


def read_region(source_dir: Path, rel_path: str, start: int, end: int, before: int, after: int) -> str:
    """
    @brief Return a line-numbered excerpt of a file around a cited range.
    @param source_dir Checkout root.
    @param rel_path Repo-relative path.
    @param start First cited line (1-based).
    @param end Last cited line (1-based).
    @param before Context lines before.
    @param after Context lines after.
    """

    path: Path = (source_dir / rel_path).resolve()
    if not str(path).startswith(str(source_dir.resolve())) or not path.is_file():
        return f"<file {rel_path} not found at pinned commit>"
    lines: list[str] = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo: int = max(1, min(start, end) - before)
    hi: int = min(len(lines), max(start, end) + after)
    text: str = "\n".join(f"{n:>5}| {lines[n - 1]}" for n in range(lo, hi + 1))
    return text[:MAX_REGION_CHARS]


def build_repro_messages(case: ReproCase, previous: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """
    @brief Build the chat messages for one finding (and optionally the retry feedback).
    @param case Finding to reproduce.
    @param previous ``{"script": str, "error": str}`` from the failed first attempt, or None.
    """

    finding: dict[str, Any] = case.finding
    doc: dict[str, Any] = finding["doc_citation"]
    code: dict[str, Any] = finding["code_citation"]
    doc_region: str = read_region(
        case.source_dir, doc["path"], int(doc["start_line"]), int(doc["end_line"]), DOC_CONTEXT_BEFORE, DOC_CONTEXT_AFTER
    )
    code_region: str = read_region(
        case.source_dir, code["path"], int(code["start_line"]), int(code["end_line"]), CODE_CONTEXT_BEFORE, CODE_CONTEXT_AFTER
    )
    user: str = (
        f"Library: {case.repo} ({case.repo_url}) installed at commit {case.ref}.\n\n"
        f"Reported finding {finding.get('finding_id')} (kind: {finding.get('drift_kind')}):\n{finding.get('explanation')}\n"
        f"Proposed fix: {finding.get('proposed_fix')}\n\n"
        f"Cited documentation {doc['path']}:{doc['start_line']}-{doc['end_line']} (quote: {doc.get('quote')!r}):\n"
        f"{doc_region}\n\n"
        f"Cited code {code['path']}:{code['start_line']}-{code['end_line']} (quote: {code.get('quote')!r}):\n"
        f"{code_region}\n\n"
        f"{SCRIPT_RULES}\n\n"
        "Return JSON with keys: argument_finding_is_false, model_verdict, doc_literal_usage, expected_exception_type, "
        "expected_failure, extra_requirements, needs_network_or_server, repro_script."
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": REPRO_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    if previous is not None:
        messages.append({"role": "assistant", "content": previous.get("raw_response") or json.dumps({"repro_script": previous["script"]})})
        messages.append(
            {
                "role": "user",
                "content": (
                    "That script could not test the claim. Harness result:\n"
                    f"{previous['error'][:2500]}\n\n"
                    "Fix the script so it still follows the docs literally under the same rules. Do not change what "
                    "is being tested to force a failure; if the docs actually work, the script should print DOCS_OK. "
                    "Return the full JSON object again."
                ),
            }
        )
    return messages


def normalise_verdict(text: str) -> str:
    """
    @brief Map free-text verdicts to likely_true / likely_false / unclear (the endpoint does not enforce the enum).
    @param text Raw verdict.
    """

    lowered: str = text.strip().lower()
    if lowered in {"likely_true", "likely_false", "unclear"}:
        return lowered
    if re.search(r"false[ _-]?positive|likely[ _]false|^false\b|finding is (?:false|wrong|incorrect)|not (?:a )?(?:real|drift)|docs? (?:are|is) (?:right|correct)", lowered):
        return "likely_false"
    if re.search(r"\btrue\b|real|correct|docs? (?:are |is )?wrong|confirmed", lowered):
        return "likely_true"
    return "unclear"


def parse_repro_response(content: str) -> ReproPlan:
    """
    @brief Parse the model's JSON answer (tolerating fences and truncated JSON) into a ReproPlan.
    @param content Raw assistant content.
    """

    text: str = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start: int = text.find("{")
    if start > 0:
        text = text[start:]
    try:
        raw: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        repaired: str | None = _close_truncated_json(text)
        if repaired is None:
            raise ValueError("Model response is not JSON.")
        raw = json.loads(repaired)
    script: str = str(raw.get("repro_script") or "").strip()
    script = re.sub(r"^```(?:python)?\s*\n", "", script)
    script = re.sub(r"\n```\s*$", "", script)
    if not script:
        raise ValueError("Model response has no repro_script.")
    extras = raw.get("extra_requirements") or []
    return ReproPlan(
        repro_script=script + "\n",
        expected_exception_type=str(raw.get("expected_exception_type") or "none").strip(),
        expected_failure=str(raw.get("expected_failure") or ""),
        doc_literal_usage=str(raw.get("doc_literal_usage") or ""),
        argument_finding_is_false=str(raw.get("argument_finding_is_false") or ""),
        model_verdict=normalise_verdict(str(raw.get("model_verdict") or "")),
        extra_requirements=[str(item) for item in extras if str(item).strip()] if isinstance(extras, list) else [],
        needs_network_or_server=bool(raw.get("needs_network_or_server", False)),
    )


# ---------------------------------------------------------------------------------------------------------
# Static checks and classification
# ---------------------------------------------------------------------------------------------------------


def lint_script(script: str) -> list[str]:
    """
    @brief Reject scripts that could fake a result: syntax errors, broad try/except, self-exit.
    @param script Script source.
    """

    try:
        tree: ast.AST = ast.parse(script)
    except SyntaxError as exc:
        return [f"SyntaxError: {exc}"]
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) or (hasattr(ast, "TryStar") and isinstance(node, getattr(ast, "TryStar"))):
            for handler in node.handlers:
                names: list[str] = []
                if handler.type is None:
                    names = ["<bare>"]
                elif isinstance(handler.type, ast.Tuple):
                    names = [ast.unparse(item) for item in handler.type.elts]
                else:
                    names = [ast.unparse(handler.type)]
                problems.append(f"line {handler.lineno}: try/except catching {', '.join(names)} is not allowed")
        if isinstance(node, ast.Call):
            func: str = ast.unparse(node.func)
            if func in {"sys.exit", "exit", "quit", "os._exit", "os.kill", "exit_", "subprocess.run", "subprocess.call", "os.system"}:
                problems.append(f"line {node.lineno}: call to {func} is not allowed")
        if isinstance(node, ast.Raise):
            problems.append(f"line {node.lineno}: explicit raise is not allowed")
    marked: set[int] = doc_literal_lines(script)
    statement_lines: set[int] = {
        line
        for node in ast.walk(tree)
        if isinstance(node, ast.stmt)
        for line in range(node.lineno, (node.end_lineno or node.lineno) + 1)
    }
    if not marked & statement_lines:
        problems.append("no `# DOC-LITERAL` marker on a code line: mark the statement(s) that perform the documented usage")
    return problems


def doc_literal_lines(script: str) -> set[int]:
    """
    @brief Line numbers (1-based) of the statements marked as the doc-literal usage.
    @param script Script source.
    """

    marked: set[int] = set()
    inside: bool = False
    for number, line in enumerate(script.splitlines(), start=1):
        stripped: str = line.strip()
        if stripped.startswith("# DOC-LITERAL-BEGIN"):
            inside = True
            continue
        if stripped.startswith("# DOC-LITERAL-END"):
            inside = False
            continue
        if inside or re.search(r"#\s*DOC-LITERAL\b(?!-)", line):
            marked.add(number)
    return marked


def _name_matches(expected: str, mro: list[str]) -> bool:
    """
    @brief True when the expected exception name matches the observed class or one of its bases.
    """

    wanted: str = expected.strip().split(".")[-1].strip("`'\" ()")
    if not wanted or wanted.lower() == "none":
        return False
    return any(entry.split(".")[-1] == wanted for entry in mro)


def classify_run(
    run: RunResult,
    plan: ReproPlan,
    script_path: Path,
    library_modules: set[str],
    lint_problems: list[str] | None = None,
) -> Classification:
    """
    @brief Decide reproduced / not_reproduced / could_not_run from what the script actually did.
    @param run Raw run result.
    @param plan Model plan (only its predicted exception type is used).
    @param script_path Path of the script that ran (to spot self-raised exceptions).
    @param library_modules Top-level import names provided by the library under test.
    @param lint_problems Static problems found before running.
    """

    if lint_problems:
        return Classification(STATUS_COULD_NOT_RUN, "lint", error_excerpt="; ".join(lint_problems)[:ERROR_EXCERPT_CHARS], retryable=True)
    if run.timed_out:
        return Classification(STATUS_COULD_NOT_RUN, "timeout", error_excerpt=run.stderr[-ERROR_EXCERPT_CHARS:], retryable=True)
    harness: dict[str, Any] | None = run.harness
    if harness is None:
        return Classification(
            STATUS_COULD_NOT_RUN, "no_harness_result", error_excerpt=(run.stderr or run.stdout)[-ERROR_EXCERPT_CHARS:], retryable=True
        )
    if harness.get("completed"):
        excerpt: str = run.stdout.strip()[-ERROR_EXCERPT_CHARS:]
        return Classification(STATUS_NOT_REPRODUCED, "ran_ok", error_excerpt=excerpt)

    exc: dict[str, Any] = harness.get("exception") or {}
    exc_type: str = str(exc.get("type") or "")
    mro: list[str] = [str(item) for item in exc.get("mro") or []]
    message: str = str(exc.get("message") or "")
    excerpt = f"{exc_type}: {message}"[:ERROR_EXCERPT_CHARS]
    frames: list[dict[str, Any]] = list(exc.get("frames") or [])
    last: dict[str, Any] = frames[-1] if frames else {}

    if exc_type == "SystemExit":
        return Classification(STATUS_COULD_NOT_RUN, "script_exit", exc_type, excerpt, retryable=True)
    if exc_type == "SyntaxError" and not any(f.get("file") != str(script_path) for f in frames[1:]):
        return Classification(STATUS_COULD_NOT_RUN, "script_syntax", exc_type, excerpt, retryable=True)
    if re.search(NETWORK_MESSAGE_PATTERN, message) or exc_type in ENVIRONMENT_EXCEPTIONS or any(entry.split(".")[-1] in {"ConnectionError", "TimeoutError"} for entry in mro):
        return Classification(STATUS_COULD_NOT_RUN, "environment", exc_type, excerpt, retryable=True)
    if exc_type == "ModuleNotFoundError":
        missing: str = str(exc.get("missing_module") or "")
        top: str = missing.split(".")[0]
        if top and top not in library_modules:
            return Classification(STATUS_COULD_NOT_RUN, "missing_dependency", exc_type, excerpt, retryable=True)
    if last.get("file") == str(script_path) and str(last.get("source", "")).startswith("raise"):
        return Classification(STATUS_COULD_NOT_RUN, "self_raised", exc_type, excerpt, retryable=True)
    script_frames: list[dict[str, Any]] = [f for f in frames if f.get("file") == str(script_path)]
    marked: set[int] = doc_literal_lines(script_path.read_text(encoding="utf-8") if script_path.is_file() else plan.repro_script)
    if not script_frames or int(script_frames[-1].get("line") or 0) not in marked:
        where: str = f"script line {script_frames[-1].get('line')}" if script_frames else "outside the script"
        return Classification(
            STATUS_COULD_NOT_RUN, "failed_outside_doc_literal", exc_type, f"[{where}, not a DOC-LITERAL line] {excerpt}"[:ERROR_EXCERPT_CHARS], retryable=True
        )
    if _name_matches(plan.expected_exception_type, mro):
        if exc_type == "AssertionError":
            evidence: str = "assertion"
        elif exc_type in INTERFACE_ERRORS:
            evidence = "interface_error"
        else:
            evidence = "other_exception"
        return Classification(STATUS_REPRODUCED, "expected_exception", exc_type, excerpt, evidence=evidence)
    return Classification(STATUS_COULD_NOT_RUN, "unexpected_exception", exc_type, excerpt, retryable=True)


# ---------------------------------------------------------------------------------------------------------
# Environments and execution
# ---------------------------------------------------------------------------------------------------------


def network_isolation_prefix() -> tuple[list[str], str]:
    """
    @brief Return a command prefix that removes network access, and a label for it.
    """

    unshare: str | None = shutil.which("unshare")
    if unshare:
        probe = subprocess.run([unshare, "-rn", "true"], capture_output=True, timeout=10)
        if probe.returncode == 0:
            return [unshare, "-rn"], "unshare-netns"
    return [], "proxy-env-only"


def project_distribution_name(source_dir: Path) -> str | None:
    """
    @brief Read [project].name (or Poetry's name) from pyproject.toml.
    """

    pyproject: Path = source_dir / "pyproject.toml"
    if not pyproject.is_file():
        return None
    data: dict[str, Any] = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    name = data.get("project", {}).get("name") or data.get("tool", {}).get("poetry", {}).get("name")
    return str(name) if name else None


class VenvManager:
    """
    @brief Create and cache one venv per (repo, ref, extra requirements), with the library installed from source.
    """

    def __init__(self, root: Path, python: str = sys.executable, log: Callable[[str], None] = print) -> None:
        """
        @brief Initialise the manager.
        @param root Directory holding cached venvs.
        @param python Base interpreter for new venvs.
        @param log Progress logger.
        """

        self.root: Path = root.resolve()
        self.python: str = python
        self.log: Callable[[str], None] = log
        self.uv: str | None = shutil.which("uv")
        self.root.mkdir(parents=True, exist_ok=True)

    def ensure(self, case: ReproCase, extras: list[str]) -> tuple[Path, set[str], str]:
        """
        @brief Return (python path, library top-level modules, install log) for a case's venv.
        @param case Finding case.
        @param extras Extra pip requirements requested by the script.
        """

        key: str = hashlib.sha256(json.dumps(sorted(extras)).encode()).hexdigest()[:8] if extras else "base"
        venv: Path = self.root / f"{case.repo}-{case.ref[:12]}-{key}"
        marker: Path = venv / ".repro-ready.json"
        py: Path = venv / "bin" / "python"
        if marker.is_file():
            info: dict[str, Any] = json.loads(marker.read_text(encoding="utf-8"))
            return py, set(info.get("modules", [])), info.get("log", "")
        if venv.exists():
            shutil.rmtree(venv)
        logs: list[str] = []
        if self.uv:
            self._run([self.uv, "venv", "--quiet", "--python", self.python, str(venv)], logs)
            install: list[str] = [self.uv, "pip", "install", "--quiet", "--python", str(py), str(case.source_dir), *extras]
        else:
            self._run([self.python, "-m", "venv", str(venv)], logs)
            install = [str(py), "-m", "pip", "install", "--quiet", str(case.source_dir), *extras]
        self.log(f"[venv] installing {case.repo}@{case.ref[:7]} {' '.join(extras)}".rstrip())
        self._run(install, logs)
        modules: set[str] = self._library_modules(py, case.source_dir)
        marker.write_text(json.dumps({"modules": sorted(modules), "log": "\n".join(logs)[-4000:]}), encoding="utf-8")
        return py, modules, "\n".join(logs)

    def _run(self, cmd: list[str], logs: list[str]) -> None:
        """
        @brief Run an install command, raising with its output on failure.
        """

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_INSTALL_TIMEOUT_SECONDS)
        logs.append(f"$ {' '.join(cmd)}\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
        if proc.returncode != 0:
            raise RuntimeError(f"install step failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-3000:]}")

    def _library_modules(self, py: Path, source_dir: Path) -> set[str]:
        """
        @brief Top-level import names shipped by the installed project distribution.
        """

        name: str | None = project_distribution_name(source_dir)
        code: str = (
            "import importlib.metadata as m, json, sys\n"
            "d = m.distribution(sys.argv[1])\n"
            "tops = set()\n"
            "for f in d.files or []:\n"
            "    p = f.parts\n"
            "    if p and not p[0].endswith(('.dist-info', '.data')) and not p[0].startswith('..') and p[0] != '__pycache__':\n"
            "        tops.add(p[0][:-3] if p[0].endswith('.py') else p[0])\n"
            "print(json.dumps(sorted(t for t in tops if t.isidentifier())))\n"
        )
        if not name:
            return set()
        proc = subprocess.run([str(py), "-c", code, name], capture_output=True, text=True, timeout=60)
        return set(json.loads(proc.stdout)) if proc.returncode == 0 and proc.stdout.strip() else set()


def run_script(python: Path, script: str, workdir: Path, timeout: int, isolation: tuple[list[str], str]) -> RunResult:
    """
    @brief Run a script under the harness, offline, with a scrubbed environment and a timeout.
    @param python Venv interpreter.
    @param script Script source.
    @param workdir Empty directory used as cwd and HOME.
    @param timeout Seconds before the process is killed.
    @param isolation (command prefix, label) from network_isolation_prefix().
    """

    workdir.mkdir(parents=True, exist_ok=True)
    script_path: Path = workdir / "repro.py"
    harness_path: Path = workdir / "_harness.py"
    result_path: Path = workdir / "_result.json"
    script_path.write_text(script, encoding="utf-8")
    harness_path.write_text(HARNESS_SOURCE, encoding="utf-8")
    if result_path.exists():
        result_path.unlink()
    env: dict[str, str] = {
        "PATH": f"{python.parent}:/usr/bin:/bin",
        "HOME": str(workdir),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "NO_COLOR": "1",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
        "PIP_NO_INDEX": "1",
    }
    cmd: list[str] = [*isolation[0], str(python), "-I", str(harness_path), str(script_path), str(result_path)]
    started: float = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=workdir, env=env)
        timed_out, rc, out, err = False, proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out, rc = True, None
        out = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    harness: dict[str, Any] | None = None
    if result_path.is_file():
        try:
            harness = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            harness = None
    return RunResult(rc, timed_out, out[-6000:], err[-6000:], harness, round(time.monotonic() - started, 2), isolation[1])


# ---------------------------------------------------------------------------------------------------------
# Beam client
# ---------------------------------------------------------------------------------------------------------


class TokenBudgetExceeded(RuntimeError):
    """
    @brief Raised before a call that would push usage past the configured budget.
    """


class BeamReproClient:
    """
    @brief Sequential, cached, budgeted chat client for the repro prompts (OpenAI-compatible endpoint).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        cache_dir: Path,
        lock_path: Path,
        max_tokens: int = 8000,
        token_budget: int = 2_000_000,
        reasoning_effort: str = "medium",
        max_attempts: int = 6,
    ) -> None:
        """
        @brief Initialise the client. The API key is only ever placed in the Authorization header.
        """

        self.base_url: str = base_url.rstrip("/")
        self.model: str = model
        self._api_key: str = api_key
        self.cache_dir: Path = cache_dir
        self.lock_path: Path = lock_path
        self.max_tokens: int = max_tokens
        self.token_budget: int = token_budget
        self.reasoning_effort: str = reasoning_effort
        self.max_attempts: int = max_attempts
        self.usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cached_calls": 0, "http_429": 0}
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def total_tokens(self) -> int:
        """
        @brief Live tokens spent so far (cached replays are not counted).
        """

        return self.usage["prompt_tokens"] + self.usage["completion_tokens"]

    def complete(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
        """
        @brief One chat completion with response caching, a token budget, a cross-process lock and 429 backoff.
        @param messages Chat messages.
        """

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": {"name": "docdrift_repro", "schema": REPRO_RESPONSE_SCHEMA, "strict": True}},
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
        }
        key: str = hashlib.sha256(json.dumps([self.base_url, payload], sort_keys=True).encode()).hexdigest()
        cache_file: Path = self.cache_dir / f"{key}.json"
        if cache_file.is_file():
            cached: dict[str, Any] = json.loads(cache_file.read_text(encoding="utf-8"))
            self.usage["cached_calls"] += 1
            return _extract_message_content(cached), {**_extract_usage(cached), "cached": 1}
        estimate: int = sum(len(m["content"]) for m in messages) // 3 + self.max_tokens
        if self.total_tokens + estimate > self.token_budget:
            raise TokenBudgetExceeded(f"budget {self.token_budget} would be exceeded (used {self.total_tokens}, next ~{estimate})")
        backoff: float = 5.0
        last_error: str = ""
        for attempt in range(1, self.max_attempts + 1):
            with _exclusive_lock(self.lock_path):
                try:
                    response = requests.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                        json=payload,
                        timeout=300,
                    )
                except requests.Timeout as exc:
                    raise RuntimeError(f"Beam request timed out; not retrying (may have been billed): {exc}") from exc
                except requests.RequestException as exc:
                    last_error = f"request error: {type(exc).__name__}"
                    response = None
            if response is not None and response.status_code == 200:
                body: dict[str, Any] = response.json()
                usage: dict[str, int] = _extract_usage(body)
                self.usage["prompt_tokens"] += usage["input_tokens"]
                self.usage["completion_tokens"] += usage["output_tokens"]
                self.usage["calls"] += 1
                cache_file.write_text(json.dumps(body), encoding="utf-8")
                return _extract_message_content(body), usage
            if response is not None:
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code == 429:
                    self.usage["http_429"] += 1
                    retry_after: str | None = response.headers.get("retry-after")
                    if retry_after and retry_after.isdigit():
                        backoff = max(backoff, float(retry_after))
                elif response.status_code < 500:
                    raise RuntimeError(last_error)
            if attempt < self.max_attempts:
                time.sleep(min(backoff, 120.0))
                backoff *= 2
        raise RuntimeError(f"Beam call failed after {self.max_attempts} attempts: {last_error}")


# ---------------------------------------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------------------------------------


def slugify(case_id: str) -> str:
    """
    @brief Filesystem-safe slug for a case id.
    """

    return re.sub(r"[^A-Za-z0-9._-]+", "_", case_id)


def _attempt_feedback(classification: Classification, run: RunResult | None) -> str:
    """
    @brief Text describing a failed attempt, fed back to the model on retry.
    """

    parts: list[str] = [f"status={classification.status} reason={classification.reason}", classification.error_excerpt]
    if run is not None and run.harness and run.harness.get("exception"):
        parts.append(str(run.harness["exception"].get("traceback", ""))[-1500:])
    elif run is not None:
        parts.append((run.stderr or run.stdout)[-1500:])
    return "\n".join(part for part in parts if part)


def run_case(
    case: ReproCase,
    client: CompletionClient,
    venvs: VenvManager,
    out_dir: Path,
    isolation: tuple[list[str], str],
    timeout: int = DEFAULT_RUN_TIMEOUT_SECONDS,
    max_attempts: int = 2,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """
    @brief Generate, run and classify a repro for one finding, retrying once with the error fed back.
    @param case Finding case.
    @param client Completion client (Beam or a stub).
    @param venvs Venv manager.
    @param out_dir results_live/repros (scripts and logs are written under it).
    @param isolation Network isolation prefix.
    @param timeout Script timeout in seconds.
    @param max_attempts Total attempts (1 + retries).
    @param log Progress logger.
    @return Record for repros.json.
    """

    case_dir: Path = out_dir / slugify(case.case_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    attempts: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    final: Classification | None = None
    plan: ReproPlan | None = None
    script_file: Path | None = None
    for attempt in range(1, max_attempts + 1):
        record: dict[str, Any] = {"attempt": attempt}
        try:
            content, usage = client.complete(build_repro_messages(case, previous))
        except TokenBudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded as could_not_run
            final = Classification(STATUS_COULD_NOT_RUN, "model_call_failed", error_excerpt=str(exc)[:ERROR_EXCERPT_CHARS])
            record.update({"classification": asdict(final)})
            attempts.append(record)
            break
        record["usage"] = usage
        (case_dir / f"response{attempt}.txt").write_text(content, encoding="utf-8")
        try:
            plan = parse_repro_response(content)
        except (ValueError, json.JSONDecodeError) as exc:
            final = Classification(STATUS_COULD_NOT_RUN, "unparseable_response", error_excerpt=str(exc), retryable=True)
            record["classification"] = asdict(final)
            attempts.append(record)
            previous = {"script": "", "error": f"Your reply was not valid JSON with a repro_script: {exc}", "raw_response": content[:4000]}
            continue
        script_file = case_dir / f"attempt{attempt}.py"
        script_file.write_text(plan.repro_script, encoding="utf-8")
        (case_dir / f"plan{attempt}.json").write_text(json.dumps(asdict(plan), indent=2), encoding="utf-8")
        record["plan"] = {k: v for k, v in asdict(plan).items() if k != "repro_script"}
        lint: list[str] = lint_script(plan.repro_script)
        run: RunResult | None = None
        try:
            python, modules, _install_log = venvs.ensure(case, plan.extra_requirements)
        except Exception as exc:  # noqa: BLE001
            final = Classification(STATUS_COULD_NOT_RUN, "install_failed", error_excerpt=str(exc)[-ERROR_EXCERPT_CHARS:], retryable=bool(plan.extra_requirements))
            record["classification"] = asdict(final)
            attempts.append(record)
            previous = {"script": plan.repro_script, "error": _attempt_feedback(final, None), "raw_response": content[:6000]}
            continue
        if lint:
            final = classify_run(RunResult(None, False, "", "", None, 0.0, isolation[1]), plan, script_file, modules, lint)
        else:
            workdir: Path = Path(tempfile.mkdtemp(prefix=f"repro-{slugify(case.case_id)}-"))
            run = run_script(python, plan.repro_script, workdir, timeout, isolation)
            final = classify_run(run, plan, workdir / "repro.py", modules)
            shutil.rmtree(workdir, ignore_errors=True)
            (case_dir / f"attempt{attempt}.log").write_text(
                json.dumps(
                    {
                        "returncode": run.returncode,
                        "timed_out": run.timed_out,
                        "duration_seconds": run.duration_seconds,
                        "network_isolation": run.network_isolation,
                        "stdout": run.stdout,
                        "stderr": run.stderr,
                        "harness": run.harness,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        record["classification"] = asdict(final)
        attempts.append(record)
        log(f"[{case.case_id}] attempt {attempt}: {final.status} ({final.reason}) {final.error_excerpt[:120]!r}")
        if not final.retryable:
            break
        previous = {"script": plan.repro_script, "error": _attempt_feedback(final, run), "raw_response": content[:6000]}

    assert final is not None
    result: dict[str, Any] = {
        "case_id": case.case_id,
        "repo": case.repo,
        "ref": case.ref,
        "status": final.status,
        "reason": final.reason,
        "evidence": final.evidence,
        "exception_type": final.exception_type,
        "expected_exception_type": plan.expected_exception_type if plan else None,
        "error_excerpt": final.error_excerpt,
        "script_path": str(script_file) if script_file else None,
        "attempts": len(attempts),
        "model_verdict": plan.model_verdict if plan else None,
        "argument_finding_is_false": plan.argument_finding_is_false if plan else None,
        "network_isolation": isolation[1],
    }
    (case_dir / "attempts.json").write_text(json.dumps(attempts, indent=2), encoding="utf-8")
    return result


def load_cases_from_traces(traces: list[Path], sources: dict[str, dict[str, str]]) -> list[ReproCase]:
    """
    @brief Build cases from analyser trace JSONs (``{"summary":..., "output": {"findings": [...]}}``).
    @param traces Trace files named ``<repo>-<limit>.json``.
    @param sources ``{repo: {"path": local checkout, "ref": pinned SHA, "repo_url": optional}}``.
    """

    cases: list[ReproCase] = []
    for trace in traces:
        data: dict[str, Any] = json.loads(trace.read_text(encoding="utf-8"))
        case_name: str = trace.stem
        repo: str = case_name.rsplit("-", 1)[0]
        findings: list[dict[str, Any]] = list((data.get("output") or {}).get("findings") or [])
        if not findings:
            continue
        if repo not in sources:
            raise KeyError(f"No source checkout configured for repo '{repo}' ({trace}).")
        src: dict[str, str] = sources[repo]
        for finding in findings:
            cases.append(
                ReproCase(
                    case_id=f"{case_name}:{finding['finding_id']}",
                    repo=repo,
                    repo_url=src.get("repo_url") or str(data.get("summary", {}).get("repo_url", "")),
                    ref=src["ref"],
                    source_dir=Path(src["path"]),
                    finding=finding,
                )
            )
    return cases


def ensure_checkout(repo_url: str, ref: str, root: Path) -> Path:
    """
    @brief Clone ``repo_url`` and check out ``ref`` under ``root`` if no local checkout exists (needs network).
    """

    target: Path = root / (repo_url.rstrip("/").split("/")[-1] + "-" + ref[:12])
    if not (target / ".git").exists():
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", repo_url, str(target)], check=True, timeout=600)
    subprocess.run(["git", "-C", str(target), "checkout", "--quiet", ref], check=True, timeout=120)
    return target


def summarise(results: dict[str, dict[str, Any]], labels: dict[str, str]) -> dict[str, Any]:
    """
    @brief Compare repro statuses with hand labels and compute precision with and without the repro filter.
    @param results case_id -> repros.json record.
    @param labels case_id -> "true" | "false" | "unclear".
    """

    labelled: list[str] = [case for case in results if case in labels]
    true_ids: list[str] = [case for case in labelled if labels[case] == "true"]
    other_ids: list[str] = [case for case in labelled if labels[case] != "true"]
    kept: list[str] = [case for case in labelled if results[case]["status"] == STATUS_REPRODUCED]
    kept_true: int = sum(1 for case in kept if labels[case] == "true")
    strict: list[str] = [case for case in kept if results[case].get("evidence") == "interface_error"]
    strict_true: int = sum(1 for case in strict if labels[case] == "true")

    def counts(ids: list[str]) -> dict[str, int]:
        return {status: sum(1 for case in ids if results[case]["status"] == status) for status in ALL_STATUSES}

    return {
        "findings": len(labelled),
        "hand_true": len(true_ids),
        "hand_false_or_unclear": len(other_ids),
        "true_by_status": counts(true_ids),
        "false_or_unclear_by_status": counts(other_ids),
        "precision_without_filter": round(len(true_ids) / len(labelled), 4) if labelled else None,
        "kept_with_filter": len(kept),
        "kept_true_with_filter": kept_true,
        "precision_with_filter": round(kept_true / len(kept), 4) if kept else None,
        "recall_of_true_with_filter": round(kept_true / len(true_ids), 4) if true_ids else None,
        "reproduced_via_assertion": sum(1 for case in kept if results[case].get("evidence") == "assertion"),
        "strict_filter": "reproduced with an interface error (TypeError/AttributeError/ImportError/NameError)",
        "kept_with_strict_filter": len(strict),
        "kept_true_with_strict_filter": strict_true,
        "precision_with_strict_filter": round(strict_true / len(strict), 4) if strict else None,
        "recall_of_true_with_strict_filter": round(strict_true / len(true_ids), 4) if true_ids else None,
        "model_says_false": {
            "hand_true": sum(1 for case in true_ids if results[case].get("model_verdict") == "likely_false"),
            "hand_false_or_unclear": sum(1 for case in other_ids if results[case].get("model_verdict") == "likely_false"),
        },
    }
