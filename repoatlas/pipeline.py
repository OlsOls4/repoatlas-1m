"""DocDrift v2 pipeline: symbol check, token preflight, Beam triage, optional repro."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Protocol
from urllib.parse import urlparse

from repoatlas.config import DEFAULT_TOKEN_CALIBRATION_FACTOR
from repoatlas.hybrid_view import strip_local_paths
from repoatlas.packer import build_pack_from_directory, estimate_prompt_tokens


SCRIPTS_DIRECTORY: Path = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import baseline_symbol_check  # noqa: E402


DEFAULT_BASE_URL: str = "https://ollama.com/v1"
DEFAULT_MODEL: str = "beam"


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
    """

    del base_url, model
    root, repo_url, ref = resolve_target(target)
    repo_name: str = root.name
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
    )
    if projected > max_tokens:
        raise TokenGuardError(
            f"projected prompt {projected:,} tokens exceeds --max-tokens {max_tokens:,} "
            f"(pack {pack.total_tokens:,}, truncated={pack.truncated})"
        )
    if client is None:
        preflight.skipped_reason = "no Beam client; preflight only"
        return preflight
    messages = _triage_messages(pack.pack_text, symbol_flags)
    triage = client.complete(messages, max_tokens=4096)
    preflight.triage = triage
    if run_repro:
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


def _git_ref(root: Path) -> str:
    """
    @brief Best-effort HEAD ref, or 'local'.
    """

    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip() or "local"
    except (OSError, subprocess.CalledProcessError):
        return "local"


def _triage_messages(pack_text: str, flags: list[dict[str, object]]) -> list[dict[str, str]]:
    """
    @brief Build the triage prompt from the packed repo and symbol flags.
    """

    candidates = json.dumps(flags, ensure_ascii=False)
    return [
        {
            "role": "system",
            "content": "You are DocDrift, triaging documentation-drift reports. Return JSON only.",
        },
        {
            "role": "user",
            "content": f"CANDIDATES:\n{candidates}\n\nPACK:\n{pack_text[:20000]}",
        },
    ]


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
