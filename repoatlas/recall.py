"""Planted-drift recall benchmark helpers (DocDrift recall vs doc-to-code token distance).

Everything here reuses the RepoAtlas packer file-block format and token estimator, the DocDrift prompt
wording, the truncated-JSON repair in ``parse_structured_content`` and the citation verifier.
"""

from __future__ import annotations

import ast
import fcntl
import json
import os
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
import tiktoken

from repoatlas.models import RepoFileSnapshot, RepoPack
from repoatlas.packer import FILTER_SIGNATURE, PACK_FORMAT_VERSION, _iter_text_files, _make_file_block, _priority_order
from repoatlas.prompts import SYSTEM_PROMPT

_ENC = tiktoken.get_encoding("cl100k_base")

KEEP_SUFFIXES = (".py", ".md", ".rst")
EXCLUDE_DIRS = {"tests", "test", "testing", "examples", "example", "benchmarks", "bench", "scripts", ".github",
                "docs_src", "_vendor", "__pycache__", ".git", "node_modules", "build", "dist"}
EXCLUDE_NAMES = {"CHANGES.rst", "CHANGES.md", "CHANGELOG.md", "CHANGELOG.rst", "HISTORY.rst", "HISTORY.md",
                 "AI_POLICY.md", "AGENTS.md"}
MAX_FILE_BYTES = 150_000


def tok(text: str) -> int:
    return len(_ENC.encode(text, disallowed_special=()))


# ---------------------------------------------------------------- haystack assembly

def assemble_source(libs: dict[str, Path], dest: Path) -> dict[str, str]:
    """Copy docs+source (no tests/examples/changelogs) of each pinned library into dest/<lib>/."""

    if dest.exists():
        shutil.rmtree(dest)
    shas: dict[str, str] = {}
    for name, root in libs.items():
        shas[name] = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                                    check=True).stdout.strip()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in KEEP_SUFFIXES:
                continue
            rel = path.relative_to(root)
            if any(p in EXCLUDE_DIRS or p.startswith(".") for p in rel.parts[:-1]) or rel.name in EXCLUDE_NAMES:
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            target = dest / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return shas


def file_order(root: Path) -> list[str]:
    """Packer priority order (unchanged RepoAtlas ranking) computed once on the clean tree."""

    paths = _priority_order(root, _iter_text_files(root), repo_url="local://recall-haystack")
    return [str(p.relative_to(root)).replace("\\", "/") for p in paths]


def pack_header(ref: str) -> str:
    return (
        f"# REPOATLAS PACK FORMAT {PACK_FORMAT_VERSION}\n"
        "REPO_URL: local://recall-haystack\n"
        f"REF: {ref}\n"
        f"FILTER_SIGNATURE: {FILTER_SIGNATURE}\n"
        "LINE_FORMAT: <line>|<text>\n"
        "FILES_BEGIN\n"
    )


def read_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def build_ordered_pack(root: Path, order: list[str], est_budget: int, ref: str) -> RepoPack:
    """Same loop as packer.build_pack_from_directory, but with a fixed file order so plants never reorder files."""

    header = pack_header(ref)
    running = tok(header + "FILES_END\n")
    blocks: list[str] = []
    files: list[RepoFileSnapshot] = []
    truncated = False
    for rel in order:
        try:
            lines = read_lines(root / rel)
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        block = _make_file_block(rel, lines)
        n = tok(block)
        if running + n <= est_budget:
            blocks.append(block)
            files.append(RepoFileSnapshot(path=rel, lines=lines, token_count=n))
            running += n
            continue
        truncated = True
        if est_budget - running < 64:
            break
    text = header + "".join(blocks) + "FILES_END\n"
    return RepoPack(repo_url="local://recall-haystack", ref=ref, prefix_hash="", total_tokens=tok(text),
                    token_limit=est_budget, truncated=truncated, packed_at="", files=files, skipped_paths=[],
                    pack_text=text)


def line_positions(pack: RepoPack) -> dict[str, list[int]]:
    """Approximate cl100k token offset of every line (start of line) within pack_text."""

    pos = tok(pack_header(pack.ref))
    out: dict[str, list[int]] = {}
    for f in pack.files:
        pos += tok(f"--- FILE: {f.path} ---\n")
        offs = []
        for i, line in enumerate(f.lines):
            offs.append(pos)
            pos += tok(f"{i + 1}|{line}\n")
        out[f.path] = offs
        pos += tok(f"--- END FILE: {f.path} ---\n")
    return out


# ---------------------------------------------------------------- chunking (natural order, no oracle pairing)

def _chunk_block(path: str, lines: list[str], first: int, total: int) -> str:
    numbered = "\n".join(f"{first + i}|{line}" for i, line in enumerate(lines))
    if first == 1 and len(lines) == total:
        return f"--- FILE: {path} ---\n{numbered}\n--- END FILE: {path} ---\n"
    return (f"--- FILE: {path} (lines {first}-{first + len(lines) - 1} of {total}) ---\n{numbered}\n"
            f"--- END FILE: {path} ---\n")


def build_chunks(pack: RepoPack, est_budget: int) -> list[dict]:
    """Split a pack into consecutive chunks in file order; oversized files split at line boundaries."""

    pieces: list[tuple[str, int, int, str, int]] = []  # path, first_line, last_line, block, tokens
    for f in pack.files:
        block = _chunk_block(f.path, f.lines, 1, len(f.lines))
        n = tok(block)
        if n <= est_budget:
            pieces.append((f.path, 1, len(f.lines), block, n))
            continue
        start = 0
        while start < len(f.lines):
            lo, hi, best = start + 1, len(f.lines), start + 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if tok(_chunk_block(f.path, f.lines[start:mid], start + 1, len(f.lines))) <= est_budget:
                    best, lo = mid, mid + 1
                else:
                    hi = mid - 1
            block = _chunk_block(f.path, f.lines[start:best], start + 1, len(f.lines))
            pieces.append((f.path, start + 1, best, block, tok(block)))
            start = best
    chunks: list[list] = []
    cur: list = []
    cur_tok = 0
    for p in pieces:
        if cur and cur_tok + p[4] > est_budget:
            chunks.append(cur)
            cur, cur_tok = [], 0
        cur.append(p)
        cur_tok += p[4]
    if cur:
        chunks.append(cur)
    header = pack_header(pack.ref)
    return [{"index": i, "spans": [(p[0], p[1], p[2]) for p in c],
             "text": header + "".join(p[3] for p in c) + "FILES_END\n"} for i, c in enumerate(chunks)]


# ---------------------------------------------------------------- prompt

def build_docdrift_prompt(pack_text: str) -> str:
    """RepoAtlas Task A (DocDrift) wording and schema from prompts.build_analysis_user_prompt, Task B dropped."""

    return (
        "Analyse the packed repository below.\n"
        "Task: DocDrift findings where docs contradict code for flags, defaults, signatures, names, env vars, or config keys.\n"
        "Rules:\n"
        "1) Every citation must include path, start_line, end_line, and exact quote text from those lines.\n"
        "2) Proposed fixes must be documentation-only and local patch text.\n"
        "3) If you cannot cite line-level evidence, do not emit that finding.\n"
        "4) Keep each finding concise and factual, but report every drift you can cite; there is no cap on the number of findings.\n"
        "5) Output ONLY one JSON object, no prose, with exactly this shape:\n"
        '{"findings": [{"finding_id": "DD-1", "drift_kind": "flag|default|signature|env_var|config_key|other", '
        '"explanation": "...", "doc_citation": {"path": "...", "start_line": 1, "end_line": 1, "quote": "..."}, '
        '"code_citation": {"path": "...", "start_line": 1, "end_line": 1, "quote": "..."}, "proposed_fix": "..."}], '
        '"atlas_claims": []}\n'
        "Leave atlas_claims empty.\n"
        "Quotes must be copied verbatim from the cited lines, without the '<line>|' prefix.\n"
        "Packed repository context follows:\n\n"
        f"{pack_text}"
    )


# ---------------------------------------------------------------- live calls

BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1")
MODEL = os.environ.get("OLLAMA_MODEL", "beam")
LOCK_PATH = Path(".cache/repoatlas/ollama.lock")  # shared with the RepoAtlas client: one live request at a time
BACKOFFS = (30, 90, 240)


class StopRun(RuntimeError):
    """Raised for quota/payment/rate errors that cannot be backed off."""


class Ledger:
    def __init__(self, path: Path, cap: int) -> None:
        self.path, self.cap = path, cap
        self.data = json.loads(path.read_text()) if path.exists() else {"prompt_tokens": 0, "completion_tokens": 0,
                                                                          "total_tokens": 0, "calls": []}

    @property
    def total(self) -> int:
        return self.data["total_tokens"]

    def check(self, estimate: int, label: str) -> None:
        if self.total + estimate > self.cap:
            raise StopRun(f"budget: {label} estimate {estimate} would take usage {self.total}+{estimate} past cap {self.cap}")

    def add(self, entry: dict) -> None:
        u = entry.get("usage") or {}
        self.data["prompt_tokens"] += int(u.get("prompt_tokens", 0) or 0)
        self.data["completion_tokens"] += int(u.get("completion_tokens", 0) or 0)
        self.data["total_tokens"] = self.data["prompt_tokens"] + self.data["completion_tokens"]
        self.data["calls"].append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))


def call_beam(messages: list[dict], max_tokens: int, reasoning_effort: str, json_schema: dict | None,
              timeout: int = 900, retry_5xx: bool = True) -> tuple[int, dict | str, float, dict]:
    """POST one chat completion. Returns (status, json-or-text, latency, rate headers). 429/5xx backed off."""

    api_key = os.environ["OLLAMA_API_KEY"]
    payload: dict = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "reasoning_effort": reasoning_effort}
    if json_schema is not None:
        payload["response_format"] = {"type": "json_schema",
                                      "json_schema": {"name": "repoatlas_analysis", "schema": json_schema, "strict": True}}
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(len(BACKOFFS) + 1):
        with LOCK_PATH.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                start = time.perf_counter()
                try:
                    r = requests.post(f"{BASE_URL}/chat/completions", json=payload, timeout=timeout,
                                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                except requests.Timeout:
                    return -1, f"timeout after {timeout}s (not retried)", time.perf_counter() - start, {}
                latency = time.perf_counter() - start
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        hdrs = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower() or k.lower() == "retry-after"}
        if r.status_code == 402:
            raise StopRun(f"HTTP 402: {r.text[:500]}")
        if (r.status_code == 429 or (retry_5xx and r.status_code >= 500)) and attempt < len(BACKOFFS):
            wait = BACKOFFS[attempt]
            print(f"  HTTP {r.status_code}; backing off {wait}s: {r.text[:200]}", flush=True)
            time.sleep(wait)
            continue
        if r.status_code == 429:
            raise StopRun(f"HTTP 429 after backoff: {r.text[:500]}")
        if r.status_code >= 400:
            return r.status_code, r.text[:3000], latency, hdrs
        return r.status_code, r.json(), latency, hdrs
    raise StopRun("retry loop exhausted")


# ---------------------------------------------------------------- planting

SYNONYMS: dict[str, list[str]] = {
    "get": ["fetch", "read"], "set": ["assign", "store"], "make": ["build", "create"], "build": ["make", "construct"],
    "create": ["make", "new"], "load": ["read", "fetch"], "parse": ["decode", "read"], "render": ["draw", "format"],
    "format": ["render", "style"], "name": ["label", "ident"], "path": ["location", "filepath"],
    "encoding": ["charset", "codec"], "charset": ["encoding", "codec"], "default": ["fallback", "initial"],
    "callback": ["handler", "hook"], "handler": ["callback", "processor"], "timeout": ["deadline", "wait"],
    "prefix": ["lead", "head"], "suffix": ["tail", "ending"], "limit": ["cap", "maximum"], "max": ["upper", "most"],
    "min": ["lower", "least"], "size": ["length", "extent"], "file": ["document", "stream"], "url": ["uri", "address"],
    "host": ["hostname", "server"], "port": ["portnum", "socket"], "key": ["field", "slot"], "value": ["val", "item"],
    "values": ["items", "entries"], "type": ["kind", "category"], "mode": ["style", "kind"], "level": ["severity", "tier"],
    "error": ["failure", "fault"], "errors": ["failures", "faults"], "message": ["text", "msg"], "context": ["ctx", "scope"],
    "request": ["req", "call"], "response": ["reply", "resp"], "header": ["field", "heading"], "headers": ["fields", "meta"],
    "cookie": ["crumb", "token"], "cookies": ["crumbs", "tokens"], "token": ["marker", "symbol"], "stream": ["flow", "pipe"],
    "buffer": ["buf", "chunk"], "chunk": ["block", "piece"], "data": ["payload", "body"], "body": ["content", "payload"],
    "content": ["body", "payload"], "params": ["args", "options"], "param": ["arg", "option"], "option": ["setting", "flag"],
    "options": ["settings", "flags"], "config": ["settings", "conf"], "command": ["cmd", "action"], "group": ["bundle", "set"],
    "env": ["environ", "environment"], "template": ["layout", "tmpl"], "filter": ["select", "sieve"], "filters": ["selectors", "sieves"],
    "test": ["check", "probe"], "tests": ["checks", "probes"], "loader": ["reader", "source"], "source": ["origin", "input"],
    "cache": ["store", "memo"], "auto": ["implicit", "automatic"], "escape": ["quote", "encode"], "line": ["row", "entry"],
    "lines": ["rows", "entries"], "width": ["columns", "span"], "color": ["colour", "tint"], "style": ["look", "theme"],
    "prompt": ["ask", "query"], "confirm": ["verify", "accept"], "show": ["display", "print"], "hidden": ["secret", "masked"],
    "required": ["mandatory", "needed"], "multiple": ["many", "repeat"], "count": ["tally", "number"], "flag": ["switch", "toggle"],
    "app": ["application", "service"], "server": ["host", "daemon"], "client": ["consumer", "session"], "proxy": ["relay", "gateway"],
    "proxies": ["relays", "gateways"], "transport": ["carrier", "conduit"], "pool": ["reserve", "bank"], "connection": ["link", "conn"],
    "connections": ["links", "conns"], "retries": ["attempts", "tries"], "verify": ["check", "validate"], "cert": ["certificate", "credential"],
    "redirect": ["forward", "reroute"], "redirects": ["forwards", "reroutes"], "follow": ["chase", "track"], "auth": ["credentials", "login"],
    "log": ["record", "journal"], "logger": ["recorder", "journal"], "processor": ["stage", "transform"], "processors": ["stages", "transforms"],
    "event": ["entry", "occurrence"], "bind": ["attach", "link"], "wrap": ["enclose", "decorate"], "wrapper": ["adapter", "shim"],
    "factory": ["maker", "builder"], "rule": ["route", "pattern"], "rules": ["routes", "patterns"], "map": ["table", "mapping"],
    "match": ["resolve", "find"], "route": ["path", "rule"], "endpoint": ["view", "target"], "method": ["verb", "action"],
    "methods": ["verbs", "actions"], "script": ["program", "runner"], "root": ["base", "top"], "base": ["root", "core"],
    "directory": ["folder", "dir"], "dir": ["folder", "directory"], "safe": ["secure", "clean"], "strict": ["exact", "rigid"],
    "char": ["character", "symbol"], "chars": ["characters", "symbols"], "separator": ["delimiter", "divider"], "sep": ["delim", "divider"],
    "join": ["combine", "merge"], "split": ["divide", "separate"], "items": ["entries", "pairs"], "item": ["entry", "element"],
    "start": ["begin", "open"], "stop": ["halt", "end"], "close": ["shutdown", "finish"], "reload": ["refresh", "restart"],
    "workers": ["processes", "procs"], "delay": ["pause", "lag"], "interval": ["period", "spacing"], "date": ["day", "datestamp"],
    "time": ["clock", "moment"], "secret": ["private", "hidden"], "salt": ["seed", "pepper"], "hash": ["digest", "checksum"],
    "method_name": ["func_name", "action_name"], "attribute": ["attr", "field"], "attr": ["attribute", "field"], "undefined": ["missing", "unset"],
    "extension": ["plugin", "addon"], "extensions": ["plugins", "addons"], "block": ["section", "region"], "blocks": ["sections", "regions"],
    "global": ["shared", "common"], "globals": ["shared", "commons"], "sandbox": ["jail", "isolate"], "ascii": ["plain", "basic"],
    "text": ["string", "message"], "string": ["text", "str"], "bytes": ["octets", "raw"], "json": ["payload", "document"],
    "form": ["fields", "inputs"], "files": ["uploads", "attachments"], "upload": ["attach", "submit"], "range": ["span", "interval"],
    "ranges": ["spans", "intervals"], "etag": ["tag", "version"], "cache_control": ["caching", "cache_policy"], "status": ["state", "code"],
    "code": ["status", "number"], "exit": ["quit", "leave"], "abort": ["cancel", "halt"], "input": ["source", "stdin"], "output": ["sink", "target"],
    "echo": ["emit", "print"], "secho": ["semit", "sprint"], "style_": ["look_", "theme_"], "shell": ["terminal", "console"],
    "complete": ["finish", "suggest"], "completion": ["suggestion", "finishing"], "choices": ["options", "alternatives"],
    "choice": ["option", "alternative"], "case": ["casing", "letter"], "sensitive": ["aware", "strict"], "show_default": ["display_default", "print_default"],
}

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _split_ident(name: str) -> list[str]:
    if "_" in name.strip("_"):
        return name.split("_")
    return re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+", name)


def propose_rename(name: str, rng: random.Random, taken: set[str]) -> str | None:
    """Plausible developer-style rename: swap one word for a synonym. Returns None if no plausible rename."""

    camel = "_" not in name.strip("_") and name[:1].isupper()
    words = _split_ident(name)
    idxs = [i for i, w in enumerate(words) if w.lower() in SYNONYMS]
    rng.shuffle(idxs)
    for i in idxs:
        for alt in rng.sample(SYNONYMS[words[i].lower()], len(SYNONYMS[words[i].lower()])):
            new_words = list(words)
            if camel:
                new_words[i] = "".join(part.capitalize() for part in alt.split("_"))
                cand = "".join(new_words)
            else:
                new_words[i] = alt.upper() if words[i].isupper() else alt
                cand = "_".join(new_words)
            if cand != name and cand not in taken and cand.isidentifier():
                return cand
    return None


@dataclass
class DefInfo:
    path: str
    name: str
    kind: str  # function | class
    line: int  # def line (1-based)
    sig_end: int
    end: int
    params: dict[str, int] = field(default_factory=dict)  # param -> line of param in signature
    doc_span: tuple[int, int] | None = None


def scan_python(path: str, lines: list[str]) -> tuple[list[DefInfo], set[int]]:
    """Return defs and the set of docstring line numbers for one .py file."""

    try:
        tree = ast.parse("\n".join(lines) + "\n")
    except SyntaxError:
        return [], set()
    defs: list[DefInfo] = []
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                doc_lines.update(range(body[0].lineno, body[0].end_lineno + 1))
                span = (body[0].lineno, body[0].end_lineno)
            else:
                span = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first_body = node.body[0].lineno if node.body else node.lineno
            sig_end = max(node.lineno, first_body - 1)
            params: dict[str, int] = {}
            if not isinstance(node, ast.ClassDef):
                a = node.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs:
                    if arg.arg not in ("self", "cls"):
                        params[arg.arg] = arg.lineno
            defs.append(DefInfo(path, node.name, "class" if isinstance(node, ast.ClassDef) else "function",
                                node.lineno, sig_end, node.end_lineno or node.lineno, params, span))
    return defs, doc_lines


def _is_doc_file(path: str) -> bool:
    return path.endswith((".md", ".rst"))


def mine_candidates(pack: RepoPack, positions: dict[str, list[int]]) -> tuple[list[dict], set[str]]:
    """Find (doc line, code line) pairs that a realistic rename could break, with their token distance."""

    files = {f.path: f.lines for f in pack.files}
    all_defs: list[DefInfo] = []
    doc_lines_by_file: dict[str, set[int]] = {}
    for path, lines in files.items():
        if path.endswith(".py"):
            defs, docl = scan_python(path, lines)
            all_defs.extend(defs)
            doc_lines_by_file[path] = docl
        elif _is_doc_file(path):
            doc_lines_by_file[path] = set(range(1, len(lines) + 1))
    idents: set[str] = set()
    for lines in files.values():
        for line in lines:
            idents.update(IDENT_RE.findall(line))
    name_count: dict[str, int] = {}
    for d in all_defs:
        name_count[d.name] = name_count.get(d.name, 0) + 1
    unique = {d.name: d for d in all_defs if name_count[d.name] == 1 and len(d.name) >= 6
              and not d.name.startswith("_") and "_" + d.name not in idents}
    # doc mentions of each unique name
    mention_re: dict[str, re.Pattern] = {}
    cands: list[dict] = []
    word_lines: dict[str, list[tuple[str, int]]] = {}
    for path, docl in doc_lines_by_file.items():
        lines = files[path]
        for ln in docl:
            for w in set(IDENT_RE.findall(lines[ln - 1])):
                if w in unique:
                    word_lines.setdefault(w, []).append((path, ln))
    for name, d in unique.items():
        for path, ln in word_lines.get(name, []):
            if path == d.path and d.doc_span and d.doc_span[0] <= ln <= d.doc_span[1]:
                continue  # own docstring mentioning own name: not a useful pair
            dist = abs(positions[path][ln - 1] - positions[d.path][d.line - 1])
            base = {"name": name, "def_path": d.path, "def_line": d.line, "def_kind": d.kind,
                    "doc_path": path, "doc_line": ln, "dist_cl100k": dist}
            cands.append({**base, "kind": "code_rename_" + d.kind})
            cands.append({**base, "kind": "doc_rename_" + d.kind})
        if d.kind != "function":
            continue
        for param, pline in d.params.items():
            if len(param) < 4 or param in ("kwargs", "args"):
                continue
            # (a) own docstring documents the param (short distance)
            if d.doc_span:
                for ln in range(d.doc_span[0], d.doc_span[1] + 1):
                    line = files[d.path][ln - 1]
                    if re.search(rf"(:param\s+(\w+\s+)?{param}:|^\s*{param}\s*(\(|:|-))", line):
                        dist = abs(positions[d.path][ln - 1] - positions[d.path][pline - 1])
                        base = {"name": d.name, "param": param, "def_path": d.path, "def_line": d.line,
                                "param_line": pline, "doc_path": d.path, "doc_line": ln, "dist_cl100k": dist}
                        cands.append({**base, "kind": "code_rename_kwarg"})
                        cands.append({**base, "kind": "doc_rename_kwarg"})
                        break
            # (b) another doc line names the keyword next to (same line or up to 4 lines after) a mention of the function
            seen_doc: set[tuple[str, int]] = set()
            for path, mln in word_lines.get(d.name, []):
                if path == d.path and d.doc_span and d.doc_span[0] <= mln <= d.doc_span[1]:
                    continue
                for ln in range(mln, min(mln + 5, len(files[path]) + 1)):
                    if (path, ln) in seen_doc or ln not in doc_lines_by_file.get(path, set()):
                        continue
                    line = files[path][ln - 1]
                    if not (re.search(rf"\b{d.name}\(.*\b{param}\s*=", line) or
                            re.search(rf"(``|`|\*\*|:param\s+){param}(``|`|\*\*|:|=)", line)):
                        continue
                    seen_doc.add((path, ln))
                    dist = abs(positions[path][ln - 1] - positions[d.path][pline - 1])
                    base = {"name": d.name, "param": param, "def_path": d.path, "def_line": d.line,
                            "param_line": pline, "doc_path": path, "doc_line": ln, "dist_cl100k": dist}
                    cands.append({**base, "kind": "code_rename_kwarg"})
                    cands.append({**base, "kind": "doc_rename_kwarg"})
    return cands, idents


BUCKETS: list[tuple[str, int, int, int]] = [  # label, lo, hi (real tokens), plants per seed
    ("~1k", 0, 3_000, 4), ("~10k", 3_000, 25_000, 4), ("~50k", 25_000, 75_000, 4), ("~100k", 75_000, 150_000, 4),
    ("~200k", 150_000, 300_000, 4), ("~400k", 300_000, 550_000, 4), ("700k+", 700_000, 10**9, 6),
]


def bucket_of(real_dist: int) -> str:
    for label, lo, hi, _ in BUCKETS:
        if lo <= real_dist < hi:
            return label
    return BUCKETS[-1][0]


def _stdlib_names() -> set[str]:
    import importlib
    names: set[str] = set(dir(__builtins__)) if isinstance(__builtins__, dict) is False else set(__builtins__)
    for mod in ("logging", "typing", "collections", "io", "os", "asyncio", "http.client", "http.server",
                "email.message", "urllib.parse", "json", "socket", "ssl", "threading", "unittest", "inspect",
                "functools", "contextlib", "string", "re", "datetime", "pathlib", "shutil", "abc", "enum",
                "dataclasses", "argparse", "textwrap", "codecs", "warnings", "traceback", "types"):
        try:
            m = importlib.import_module(mod)
        except ImportError:
            continue
        for a in dir(m):
            names.add(a)
            obj = getattr(m, a, None)
            if isinstance(obj, type):
                names.update(dir(obj))
    return {n for n in names if not n.startswith("_")}


STDLIB_NAMES = _stdlib_names()

HISTORICAL_RE = re.compile(r"versionchanged|versionadded|deprecated|Deprecated|changelog|renamed|removed", re.I)
KIND_CYCLE = ["code_rename_function", "doc_rename_class", "code_rename_kwarg", "doc_rename_function",
              "code_rename_class", "doc_rename_kwarg"]


def select_plants(cands: list[dict], files: dict[str, list[str]], idents: set[str], calib: float, seed: int,
                  exclude_names: set[str] = frozenset()) -> list[dict]:
    rng = random.Random(seed)
    pool = []
    for c in cands:
        if re.search(r"(changes|changelog|release-notes|history)\.(rst|md)$", c["doc_path"], re.I):
            continue
        if HISTORICAL_RE.search(files[c["doc_path"]][c["doc_line"] - 1]):
            continue
        if c["name"] in exclude_names:
            continue
        pool.append({**c, "dist_real": int(round(c["dist_cl100k"] * calib))})
    rng.shuffle(pool)
    names = {c["name"] for c in pool} | {c["param"] for c in pool if "param" in c}
    word_libs: dict[str, dict[str, int]] = {}
    for path, lines in files.items():
        lib = path.split("/", 1)[0]
        for line in lines:
            for w in IDENT_RE.findall(line):
                if w in names:
                    d = word_libs.setdefault(w, {})
                    d[lib] = d.get(lib, 0) + 1
    chosen: list[dict] = []
    used_names: set[str] = set()
    taken = set(idents)
    for label, lo, hi, n in BUCKETS:
        in_bucket = [c for c in pool if lo <= c["dist_real"] < hi]
        k = 0
        attempts = 0
        while k < n and attempts < 60:
            want = KIND_CYCLE[(attempts + seed) % len(KIND_CYCLE)]
            attempts += 1
            options = [c for c in in_bucket if c["kind"] == want] or in_bucket
            picked = None
            for c in options:
                if c["name"] in used_names or c.get("param") in used_names:
                    continue
                if any(c["doc_path"] == x["doc_path"] and abs(c["doc_line"] - x["doc_line"]) < 25 for x in chosen):
                    continue
                if any(c["def_path"] == x["def_path"] and abs(c["def_line"] - x["def_line"]) < 25 for x in chosen):
                    continue
                doc_text = files[c["doc_path"]][c["doc_line"] - 1]
                if any(x["name"] in doc_text or x.get("param", "\0") in IDENT_RE.findall(doc_text) for x in chosen):
                    continue
                if c["name"] in STDLIB_NAMES or (c["kind"].endswith("kwarg") and c["param"] in STDLIB_NAMES
                                                 and c["kind"].startswith("code")):
                    continue
                if c.get("def_kind") == "function" and re.search(r"[a-z][A-Z]", c["name"]):
                    continue
                sym = c["name"]
                if "_" not in sym and len(re.findall(r"[A-Z]", sym)) < 2:
                    continue  # plain English word (Context, Output, redirect): renames would hit prose
                if c["kind"].endswith("kwarg") and word_libs.get(c["param"], {}).get(c["def_path"].split("/", 1)[0], 0) > 12:
                    continue  # generic concept word (event_dict, request): stale-ness would be ambiguous
                if c["kind"].startswith("code_rename") and not c["kind"].endswith("kwarg"):
                    occ = word_libs.get(sym, {})
                    lib = c["def_path"].split("/", 1)[0]
                    if set(occ) - {lib} or occ.get(lib, 0) > 30:
                        continue  # mentioned in another library, or too many edits
                old = c.get("param") if c["kind"].endswith("kwarg") else c["name"]
                new = propose_rename(old, rng, taken)
                if new is None:
                    continue
                picked = {**c, "old": old, "new": new, "bucket": label}
                break
            if picked is None:
                continue
            taken.add(picked["new"])
            used_names.add(picked["name"])
            if "param" in picked:
                used_names.add(picked["param"])
            chosen.append(picked)
            k += 1
    for i, c in enumerate(chosen):
        c["plant_id"] = f"P{seed}-{i + 1:02d}"
    return chosen


def _sub_word(line: str, old: str, new: str) -> str:
    return re.sub(rf"(?<![\w]){re.escape(old)}(?![\w])", new, line)


def apply_plants(root: Path, plants: list[dict]) -> dict[str, int]:
    """Edit files under root in place. Line counts never change. Returns edited-line counts per plant."""

    py_files = sorted(p for p in root.rglob("*.py"))
    all_files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in KEEP_SUFFIXES)
    cache: dict[Path, list[str]] = {}

    def lines_of(p: Path) -> list[str]:
        if p not in cache:
            cache[p] = read_lines(p)
        return cache[p]

    edits: dict[str, int] = {}
    for pl in plants:
        n = 0
        keep = (pl["doc_path"], pl["doc_line"])
        if pl["kind"].startswith("doc_rename"):
            p = root / pl["doc_path"]
            ls = lines_of(p)
            before = ls[pl["doc_line"] - 1]
            ls[pl["doc_line"] - 1] = _sub_word(before, pl["old"], pl["new"])
            n += before != ls[pl["doc_line"] - 1]
        elif pl["kind"] in ("code_rename_function", "code_rename_class"):
            lib = pl["def_path"].split("/", 1)[0]
            for p in all_files:
                rel = str(p.relative_to(root))
                if rel.split("/", 1)[0] != lib:
                    continue
                ls = lines_of(p)
                for i, line in enumerate(ls):
                    if (rel, i + 1) == keep or pl["old"] not in line:
                        continue
                    new_line = _sub_word(line, pl["old"], pl["new"])
                    if new_line != line:
                        ls[i] = new_line
                        n += 1
        elif pl["kind"] == "code_rename_kwarg":
            n += _rename_param(root, pl, py_files, lines_of)
            for path, ln in pl.get("other_doc_lines", []):
                if (path, ln) == keep:
                    continue
                ls = lines_of(root / path)
                new_line = _sub_word(ls[ln - 1], pl["old"], pl["new"])
                if new_line != ls[ln - 1]:
                    ls[ln - 1] = new_line
                    n += 1
        edits[pl["plant_id"]] = n
    for p, ls in cache.items():
        p.write_text("\n".join(ls) + "\n", encoding="utf-8")
    return edits


def _rename_param(root: Path, pl: dict, py_files: list[Path], lines_of) -> int:
    """AST-precise rename of one parameter: signature, bare-name uses in the body, docstring mentions (except the
    stale doc line), and keyword uses at call sites of the function anywhere in the haystack."""

    old, new, fname = pl["old"], pl["new"], pl["name"]
    edits: list[tuple[Path, int, int, int]] = []  # path, line(1b), col, len  -> replace identifier
    n = 0
    for p in py_files:
        ls = lines_of(p)
        src = "\n".join(ls) + "\n"
        if fname not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = str(p.relative_to(root))
        for node in ast.walk(tree):
            if rel == pl["def_path"] and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == fname and node.lineno == pl["def_line"]:
                a = node.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs:
                    if arg.arg == old:
                        edits.append((p, arg.lineno, arg.col_offset, len(old)))
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Name) and sub.id == old:
                        edits.append((p, sub.lineno, sub.col_offset, len(old)))
                    elif isinstance(sub, (ast.Nonlocal, ast.Global)) and old in sub.names:
                        ls[sub.lineno - 1] = _sub_word(ls[sub.lineno - 1], old, new)
                        n += 1
                body = node.body
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                    for ln in range(body[0].lineno, body[0].end_lineno + 1):
                        if (rel, ln) == (pl["doc_path"], pl["doc_line"]):
                            continue
                        new_line = _sub_word(ls[ln - 1], old, new)
                        if new_line != ls[ln - 1]:
                            ls[ln - 1] = new_line
                            n += 1
            if isinstance(node, ast.Call):
                f = node.func
                called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if called == fname:
                    for kw in node.keywords:
                        if kw.arg == old:
                            # keyword node lineno/col point at the keyword name (py3.9+)
                            edits.append((p, kw.lineno, kw.col_offset, len(old)))
    # apply column edits right-to-left per line
    edits = sorted(set(edits), key=lambda e: (str(e[0]), e[1], -e[2]))
    for p, ln, col, length in edits:
        ls = lines_of(p)
        line = ls[ln - 1]
        col = len(line.encode("utf-8")[:col].decode("utf-8", errors="ignore"))  # ast cols are utf-8 byte offsets
        if line[col:col + length] != old:
            continue
        ls[ln - 1] = line[:col] + new + line[col + length:]
        n += 1
    return n
