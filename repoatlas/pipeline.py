"""DocDrift v2 pipeline: symbol check, token preflight, whole-repo Beam triage, executable repro."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable, Protocol
from urllib.parse import urlparse

from repoatlas.config import DEFAULT_TOKEN_CALIBRATION_FACTOR
from repoatlas.hybrid_view import strip_local_paths
from repoatlas.packer import build_pack_from_directory, estimate_prompt_tokens


SCRIPTS_DIRECTORY: Path = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import baseline_symbol_check  # noqa: E402
import hybrid_triage  # noqa: E402

from repoatlas.models import Citation, DocDriftFinding  # noqa: E402
from repoatlas.verifier import _build_file_lookup, verify_citation, verify_findings  # noqa: E402


DEFAULT_BASE_URL: str = "https://ollama.com/v1"
DEFAULT_MODEL: str = "beam"
TRIAGE_MAX_TOKENS: int = 32_000
"""Output budget for the triage call. Beam's thinking tokens count toward it, so 4k is not enough."""


class TokenGuardError(RuntimeError):
    """
    @brief Raised when the projected prompt exceeds --max-tokens.
    """


class BeamClient(Protocol):
    """
    @brief OpenAI-compatible chat client used for triage.
    """

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int) -> dict[str, object]:
        """
        @brief Return a parsed JSON object from the model.
        """


@dataclass
class PipelineResult:
    """
    @brief Structured output of one DocDrift run.
    """

    repo: str
    repo_url: str
    ref: str
    pack_tokens: int
    projected_prompt_tokens: int
    truncated: bool
    symbol_flags: list[dict[str, object]] = field(default_factory=list)
    triage: dict[str, object] = field(default_factory=dict)
    repros: list[dict[str, object]] = field(default_factory=list)
    skipped_reason: str = ""
    full_ref: str = ""
    candidates: list[dict[str, object]] = field(default_factory=list)


def resolve_target(target: str, workspace: Path | None = None) -> tuple[Path, str, str]:
    """
    @brief Resolve a local path or git URL to (root, repo_url, ref).
    @param target Path or https git URL.
    @param workspace Scratch directory for clones.
    """

    path = Path(target).expanduser()
    if path.exists():
        root = path.resolve()
        return root, f"file://{root}", _git_ref(root)
    parsed = urlparse(target)
    if parsed.scheme not in {"https", "http"} or parsed.netloc != "github.com":
        raise ValueError(f"unsupported target: {target}")
    dest = (workspace or Path(tempfile.mkdtemp(prefix="docdrift-"))) / Path(parsed.path).stem
    subprocess.run(["git", "clone", "--depth", "1", target, str(dest)], check=True, capture_output=True)
    return dest, target.rstrip("/"), _git_ref(dest)


def run_docdrift(
    target: str,
    *,
    max_tokens: int,
    run_repro: bool = True,
    client: BeamClient | None = None,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    token_calibration_factor: float = DEFAULT_TOKEN_CALIBRATION_FACTOR,
    pack_token_limit: int = 400_000,
    log: Callable[[str], None] | None = None,
    repro_runner: Callable[[Path, str, str, list[dict[str, object]], dict[str, object]], list[dict[str, object]]] | None = None,
) -> PipelineResult:
    """
    @brief Run symbol check, token preflight, optional Beam triage and repro.
    @param target Local path or GitHub URL.
    @param max_tokens Guard; abort before any network call if the estimate exceeds this.
    @param run_repro When True and a client is provided, request a repro script.
    @param client Injected Beam client. Tests pass a fake; live runs pass HttpBeamClient.
    @param base_url OpenAI-compatible base URL.
    @param model Model name.
    @param token_calibration_factor Packer calibration.
    @param pack_token_limit Packer budget.
    @param log Optional progress printer.
    @param repro_runner Optional executor for true_drift verdicts (the CLI passes the isolated-venv runner).
        Without it the old "planned" repro request is made through ``client``.
    """

    del base_url, model
    say: Callable[[str], None] = log or (lambda _msg: None)
    root, repo_url, ref = resolve_target(target)
    repo_name: str = root.name
    say(f"[1/4] symbol check: {repo_name} @ {ref}")
    flags, _stats = baseline_symbol_check.run_repo(repo_name, root)
    symbol_flags: list[dict[str, object]] = [
        {
            "path": item.path,
            "line": item.line,
            "check": item.check,
            "reference": item.reference,
            "detail": item.detail,
        }
        for item in flags
    ]
    say(f"      {len(symbol_flags)} symbol flags")
    say("[2/4] packing the whole repository (RepoAtlas packer)")
    pack = build_pack_from_directory(
        repo_url=repo_url,
        ref=ref,
        repo_root=root,
        token_limit=pack_token_limit,
        token_calibration_factor=token_calibration_factor,
    )
    projected: int = estimate_prompt_tokens(pack.total_tokens, token_calibration_factor)
    preflight: PipelineResult = PipelineResult(
        repo=repo_name,
        repo_url=repo_url,
        ref=ref,
        pack_tokens=pack.total_tokens,
        projected_prompt_tokens=projected,
        truncated=pack.truncated,
        symbol_flags=symbol_flags,
        full_ref=_git_ref(root, short=False),
    )
    say(f"      pack {pack.total_tokens:,} tokens, {len(pack.files)} files, truncated={pack.truncated}; "
        f"projected prompt {projected:,} (guard {max_tokens:,})")
    if projected > max_tokens:
        raise TokenGuardError(
            f"projected prompt {projected:,} tokens exceeds --max-tokens {max_tokens:,} "
            f"(pack {pack.total_tokens:,}, truncated={pack.truncated})"
        )
    if client is None:
        preflight.skipped_reason = "no Beam client; preflight only"
        return preflight
    candidates = _candidates(pack, symbol_flags)
    preflight.candidates = candidates
    messages = _triage_messages(pack, candidates)
    say(f"[3/4] Beam whole-repo triage: 1 call, {len(candidates)} candidates + open search for cross-file drift")
    triage = client.complete(messages, max_tokens=TRIAGE_MAX_TOKENS)
    triage = _verify_triage(triage, pack, candidates)
    preflight.triage = triage
    if run_repro:
        if repro_runner is not None:
            say("[4/4] executable repro: doc-literal script per true_drift / extra finding, isolated venv, no network")
            preflight.repros = repro_runner(root, repo_url, preflight.full_ref or ref, candidates, triage)
        else:
            repro_messages = _repro_messages(triage)
            repro = client.complete(repro_messages, max_tokens=2048)
            preflight.repros = [_as_repro_row(repro)]
    return preflight


def format_preflight(result: PipelineResult) -> str:
    """
    @brief Human preflight block printed before any Beam call.
    """

    return (
        f"repo={result.repo} ref={result.ref}\n"
        f"symbol flags={len(result.symbol_flags)}\n"
        f"pack tokens={result.pack_tokens:,} truncated={result.truncated}\n"
        f"projected prompt tokens={result.projected_prompt_tokens:,}"
    )


def _git_ref(root: Path, short: bool = True) -> str:
    """
    @brief Best-effort HEAD ref, or 'local'.
    """

    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", *(["--short"] if short else []), "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip() or "local"
    except (OSError, subprocess.CalledProcessError):
        return "local"


def _candidates(pack: object, flags: list[dict[str, object]]) -> list[dict[str, object]]:
    """
    @brief Turn symbol-check flags into neutral, doc-sorted triage candidates (same shape as the hybrid run).
    """

    lookup = _build_file_lookup(pack)  # type: ignore[arg-type]
    cands: list[dict[str, object]] = []
    for idx, f in enumerate(flags):
        line = int(f["line"])  # type: ignore[arg-type]
        lines = lookup.get(str(f["path"]).lstrip("./")) or []
        cands.append({"source": "symbol", "source_id": f"S{idx}", "doc_path": f["path"], "doc_line": line,
                      "doc_end": line, "doc_text": lines[line - 1].strip() if 1 <= line <= len(lines) else "",
                      "claim": f"{f['check']}: `{f['reference']}`: {f['detail']}", "code_hint": ""})
    cands.sort(key=lambda x: (str(x["doc_path"]), int(x["doc_line"]), str(x["source_id"])))  # type: ignore[arg-type]
    for i, c in enumerate(cands, 1):
        c["candidate_id"] = f"C{i:02d}"
    return cands


def _triage_messages(pack: object, candidates: list[dict[str, object]]) -> list[dict[str, str]]:
    """
    @brief Build the whole-repo triage prompt: the hybrid-run prompt with the FULL pack (no truncation).
    """

    return [
        {"role": "system", "content": hybrid_triage.SYSTEM},
        {"role": "user", "content": hybrid_triage.build_user_prompt(pack, candidates)},  # type: ignore[arg-type]
    ]


def _verify_triage(triage: dict[str, object], pack: object, candidates: list[dict[str, object]]) -> dict[str, object]:
    """
    @brief Check every cited code location and every extra finding against the packed snapshot.
    """

    lookup = _build_file_lookup(pack)  # type: ignore[arg-type]
    known = {str(c["candidate_id"]) for c in candidates}
    verdicts: list[dict[str, object]] = []
    for v in triage.get("verdicts") or []:  # type: ignore[union-attr]
        if not isinstance(v, dict):
            continue
        cc = v.get("code_citation") or {}
        try:
            cv = verify_citation(Citation(path=str(cc.get("path", "")), start_line=max(1, int(cc.get("start_line", 1))),
                                          end_line=max(1, int(cc.get("end_line", 1))), quote=str(cc.get("quote", ""))), lookup)
            ver = {"verified": cv.verified, "reason": cv.reason}
        except Exception as exc:  # noqa: BLE001
            ver = {"verified": False, "reason": f"invalid citation: {exc}"[:200]}
        verdicts.append({**v, "code_citation_verification": ver})
    adds: list[dict[str, object]] = []
    objs: list[DocDriftFinding] = []
    for a in triage.get("additional_findings") or []:  # type: ignore[union-attr]
        if not isinstance(a, dict):
            continue
        try:
            objs.append(DocDriftFinding.model_validate(a))
            adds.append(dict(a))
        except Exception as exc:  # noqa: BLE001
            adds.append({**a, "invalid": str(exc)[:200]})
    if objs:
        results = iter(verify_findings(objs, pack))  # type: ignore[arg-type]
        for a in adds:
            if "invalid" not in a:
                a["fully_verified"] = next(results).fully_verified
    out: dict[str, object] = {**triage, "verdicts": verdicts, "additional_findings": adds}
    out["missing_verdicts"] = sorted(known - {str(v.get("candidate_id")) for v in verdicts})
    return out


def _repro_messages(triage: dict[str, object]) -> list[dict[str, str]]:
    """
    @brief Ask for a doc-literal repro script for true_drift verdicts.
    """

    return [
        {
            "role": "system",
            "content": "Write a short Python repro using the documented call. Return JSON only.",
        },
        {"role": "user", "content": json.dumps(triage, ensure_ascii=False)[:8000]},
    ]


def _as_repro_row(payload: dict[str, object]) -> dict[str, object]:
    """
    @brief Normalise a repro payload and strip local paths.
    """

    excerpt = strip_local_paths(str(payload.get("error_excerpt") or payload.get("traceback") or ""))
    return {
        "status": str(payload.get("status", "planned")),
        "script": str(payload.get("script", "")),
        "error_excerpt": excerpt,
    }
