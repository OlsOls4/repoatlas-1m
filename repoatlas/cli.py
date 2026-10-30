"""Command-line entry for DocDrift: `docdrift run <repo>`."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import hashlib
import sys
import time
from typing import Callable, Sequence

import requests

from repoatlas.client import _extract_message_content
from repoatlas.hybrid_view import strip_local_paths

from repoatlas.pipeline import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    BeamClient,
    PipelineResult,
    TokenGuardError,
    format_preflight,
    run_docdrift,
)
import hybrid_triage  # noqa: E402  (scripts/ is put on sys.path by repoatlas.pipeline)


STOP_MARKERS: tuple[str, ...] = ("402", "quota", "insufficient", "payment", "billing")


class QuotaStop(RuntimeError):
    """
    @brief Raised on HTTP 402 or any quota/billing message: the run stops, nothing is resent.
    """


class HttpBeamClient:
    """
    @brief OpenAI-compatible chat completions client for the whole-repo triage call.
    """

    def __init__(self, base_url: str, model: str, api_key: str, cache_dir: Path | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cached_calls": 0}
        self.last_latency: float = 0.0
        self.last_finish_reason: str = ""

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int) -> dict[str, object]:
        """
        @brief POST /chat/completions with the strict triage schema and parse the JSON content.
        """

        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": {"name": "docdrift_triage", "schema": hybrid_triage.SCHEMA, "strict": True}},
            "max_tokens": max_tokens,
            "reasoning_effort": "medium",
        }
        key = hashlib.sha256(json.dumps([self.base_url, payload], sort_keys=True).encode()).hexdigest()
        cache_file = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if cache_file is not None and cache_file.is_file():
            body: dict[str, object] = json.loads(cache_file.read_text(encoding="utf-8"))
            self.usage["cached_calls"] += 1
        else:
            body = self._post(payload)
            if cache_file is not None:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(body), encoding="utf-8")
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            self.usage["prompt_tokens"] += int(usage.get("prompt_tokens", 0))  # type: ignore[union-attr]
            self.usage["completion_tokens"] += int(usage.get("completion_tokens", 0))  # type: ignore[union-attr]
            self.usage["calls"] += 1
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Beam response had no choices")
        self.last_finish_reason = str(choices[0].get("finish_reason", "")) if isinstance(choices[0], dict) else ""
        content = _extract_message_content(body)
        parsed, err = hybrid_triage.parse(content)
        if parsed is None:
            raise RuntimeError(f"Beam did not return JSON ({err}; finish_reason={self.last_finish_reason})")
        return parsed if isinstance(parsed, dict) else {"raw": parsed}

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        """
        @brief One request with 429 backoff; 402/quota stops; a timeout is never resent.
        """

        for attempt, wait in enumerate([60, 120, 240, None]):
            started = time.perf_counter()
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=900,
                )
            except requests.Timeout as exc:
                raise RuntimeError("Beam request timed out (not resent)") from exc
            self.last_latency = time.perf_counter() - started
            text = response.text[:400]
            if response.status_code == 200:
                out: object = response.json()
                if not isinstance(out, dict):
                    raise RuntimeError("Beam response was not an object")
                return out
            if response.status_code == 402 or any(m in text.lower() for m in STOP_MARKERS[1:]):
                raise QuotaStop(f"HTTP {response.status_code}: stopping (quota/billing)")
            if response.status_code == 429 and wait is not None:
                print(f"  429 from Beam, backing off {wait}s", file=sys.stderr, flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {response.status_code}: {text}")
        raise RuntimeError("retry loop exhausted")


def make_repro_runner(api_key: str, base_url: str, model: str, cache_root: Path, token_budget: int,
                      usage_sink: dict[str, int], log: Callable[[str], None]) -> Callable[..., list[dict[str, object]]]:
    """
    @brief Build the executable-repro step: Beam writes a doc-literal script, it runs in an isolated venv
        with the library installed at the pinned commit, and the status comes from what actually happened.
    """

    from repoatlas.repro import (BeamReproClient, ReproCase, TokenBudgetExceeded, VenvManager,
                                 network_isolation_prefix, run_case)

    def runner(root: Path, repo_url: str, ref: str, candidates: list[dict[str, object]],
               triage: dict[str, object]) -> list[dict[str, object]]:
        client = BeamReproClient(base_url=base_url, model=model, api_key=api_key,
                                 cache_dir=cache_root / "repro_responses", lock_path=cache_root / "ollama.lock",
                                 max_tokens=8000, token_budget=token_budget)
        venvs = VenvManager(cache_root / "repro_venvs", log=log)
        isolation = network_isolation_prefix()
        by_id = {str(c["candidate_id"]): c for c in candidates}
        cases: list[ReproCase] = []
        for v in triage.get("verdicts") or []:  # type: ignore[union-attr]
            if v.get("verdict") != "true_drift" or v.get("candidate_id") not in by_id:
                continue
            c = by_id[str(v["candidate_id"])]
            cc = dict(v.get("code_citation") or {})
            finding = {
                "finding_id": c["candidate_id"], "drift_kind": "other",
                "explanation": f"{c['claim']}. Triage reason: {v.get('reason', '')}",
                "doc_citation": {"path": c["doc_path"], "start_line": c["doc_line"], "end_line": c["doc_end"], "quote": c["doc_text"]},
                "code_citation": {"path": cc.get("path", ""), "start_line": max(1, int(cc.get("start_line", 1))),
                                  "end_line": max(1, int(cc.get("end_line", 1))), "quote": cc.get("quote", "")},
                "proposed_fix": v.get("suggested_doc_fix", ""),
            }
            cases.append(ReproCase(case_id=f"{root.name}:{c['candidate_id']}", repo=root.name, repo_url=repo_url,
                                   ref=ref, source_dir=root, finding=finding))
        for a in triage.get("additional_findings") or []:  # type: ignore[union-attr]
            if a.get("invalid"):
                continue
            cases.append(ReproCase(case_id=f"{root.name}:{a['finding_id']}", repo=root.name, repo_url=repo_url,
                                   ref=ref, source_dir=root, finding=a))
        rows: list[dict[str, object]] = []
        out_dir = cache_root / "repro_runs" / f"{root.name}-{ref[:12]}"
        for case in cases:
            try:
                rec = run_case(case, client, venvs, out_dir, isolation, timeout=60, log=log)
            except TokenBudgetExceeded as exc:
                log(f"      stopping repro: {exc}")
                break
            rec["strict_confirmed"] = rec["status"] == "reproduced" and rec.get("evidence") == "interface_error"
            rec["error_excerpt"] = strip_local_paths(str(rec.get("error_excerpt") or ""))
            rec["script"] = Path(str(rec["script_path"])).read_text(encoding="utf-8") if rec.get("script_path") else ""
            rec.pop("script_path", None)
            rows.append(rec)
            if "402" in str(rec.get("error_excerpt")) or "quota" in str(rec.get("error_excerpt")).lower():
                log("      stopping repro: quota/billing message")
                break
        usage_sink["prompt_tokens"] = client.usage["prompt_tokens"]
        usage_sink["completion_tokens"] = client.usage["completion_tokens"]
        usage_sink["calls"] = client.usage["calls"]
        return rows

    return runner


def build_parser() -> argparse.ArgumentParser:
    """
    @brief Build the `docdrift` argument parser.
    """

    parser = argparse.ArgumentParser(
        prog="docdrift",
        description=(
            "DocDrift v2: free symbol check, whole-repo Beam triage (full pack, 32k output "
            "tokens, citation verify), then executable repro in an isolated venv."
        ),
        epilog=(
            "The shipped command is the real pipeline: pack the whole repository (no char cap), "
            "one Beam triage call with the hybrid schema (32k max_tokens, medium reasoning, "
            "citation verify), then Beam-written doc-literal scripts run in an isolated venv "
            "with no network (skip with --no-repro). Stops on HTTP 402/quota (exit 4). "
            "Key from OLLAMA_API_KEY or OLLAMA_API_KEY_FILE. "
            "Recommended extra coverage: 32k docstring chunks via scripts/beamv3.py "
            "(not a --docstring-chunks flag)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the v2 pipeline on a local path or GitHub URL.")
    run.add_argument("target", help="Local repo path or https://github.com/OWNER/REPO")
    run.add_argument("--max-tokens", type=int, default=400_000, help="Refuse the Beam call if the projected prompt exceeds this.")
    run.add_argument("--no-repro", action="store_true", help="Skip the executable-repro step.")
    run.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible endpoint.")
    run.add_argument("--model", default=DEFAULT_MODEL, help="Model name (default: beam).")
    run.add_argument("--preflight-only", action="store_true", help="Print the token estimate and exit without calling Beam.")
    run.add_argument("--json", action="store_true", dest="as_json", help="Print machine-readable output.")
    run.add_argument("--out", default="", help="Write findings.json (triage, citations, repros, tokens) to this directory.")
    run.add_argument("--repro-budget", type=int, default=200_000, help="Token cap for the repro step.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """
    @brief CLI entry. Returns a process exit code.
    """

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command != "run":
        parser.error("unknown command")
    started = time.perf_counter()
    client: HttpBeamClient | None = None
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    if not api_key and os.environ.get("OLLAMA_API_KEY_FILE"):
        api_key = Path(os.environ["OLLAMA_API_KEY_FILE"]).read_text(encoding="utf-8").strip()
    cache_root = Path(os.environ.get("DOCDRIFT_CACHE", ".cache/docdrift"))
    repro_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    say: Callable[[str], None] = (lambda m: print(m, file=sys.stderr, flush=True)) if args.as_json else (lambda m: print(m, flush=True))
    runner = None
    if not args.preflight_only:
        if not api_key:
            print("OLLAMA_API_KEY is not set. Use --preflight-only or export a free Ollama Cloud key.", file=sys.stderr)
            return 2
        client = HttpBeamClient(args.base_url, args.model, api_key, cache_dir=cache_root / "triage_responses")
        runner = make_repro_runner(api_key, args.base_url, args.model, cache_root, args.repro_budget, repro_usage, say)
    try:
        result: PipelineResult = run_docdrift(
            args.target,
            max_tokens=args.max_tokens,
            run_repro=not args.no_repro,
            client=None if args.preflight_only else client,
            base_url=args.base_url,
            model=args.model,
            log=say,
            repro_runner=runner,
        )
    except TokenGuardError as exc:
        print(f"token guard: {exc}", file=sys.stderr)
        return 3
    except QuotaStop as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 4
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    wall = time.perf_counter() - started
    tokens = {
        "triage_prompt": client.usage["prompt_tokens"] if client else 0,
        "triage_completion": client.usage["completion_tokens"] if client else 0,
        "repro_prompt": repro_usage["prompt_tokens"],
        "repro_completion": repro_usage["completion_tokens"],
        "repro_calls": repro_usage["calls"],
    }
    tokens["total"] = sum(v for k, v in tokens.items() if k != "repro_calls")
    if args.as_json:
        print(format_preflight(result), file=sys.stderr)
    else:
        if result.skipped_reason:
            print(format_preflight(result))
            print(result.skipped_reason)
        else:
            print(render_report(result, tokens, wall, client))
    record = {
        "repo": result.repo, "repo_url": result.repo_url, "ref": result.full_ref or result.ref,
        "pack_tokens": result.pack_tokens, "projected_prompt_tokens": result.projected_prompt_tokens,
        "truncated": result.truncated, "symbol_flags": result.symbol_flags, "candidates": result.candidates,
        "triage": result.triage, "repros": result.repros, "tokens": tokens,
        "triage_latency_seconds": round(client.last_latency, 1) if client else 0.0,
        "triage_finish_reason": client.last_finish_reason if client else "",
        "wall_seconds": round(wall, 1), "skipped_reason": result.skipped_reason, "model": args.model,
        "base_url": args.base_url,
    }
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "findings.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    if args.as_json:
        print(json.dumps(record, indent=2))
    return 0


def render_report(result: PipelineResult, tokens: dict[str, int], wall: float, client: HttpBeamClient | None) -> str:
    """
    @brief Human-readable summary for the terminal.
    """

    lines: list[str] = ["", f"DocDrift report: {result.repo} @ {result.full_ref[:12] or result.ref}", "=" * 60]
    verdicts = result.triage.get("verdicts") or []
    counts: dict[str, int] = {}
    for v in verdicts:  # type: ignore[union-attr]
        counts[str(v.get("verdict"))] = counts.get(str(v.get("verdict")), 0) + 1
    lines.append(f"candidates triaged: {len(verdicts)}  " + "  ".join(f"{k}={n}" for k, n in sorted(counts.items())))
    for v in verdicts:  # type: ignore[union-attr]
        cc = v.get("code_citation") or {}
        ok = "verified" if (v.get("code_citation_verification") or {}).get("verified") else "UNVERIFIED"
        lines.append(f"  {v.get('candidate_id')} {v.get('verdict'):<10} {str(v.get('reason'))[:70]}")
        lines.append(f"      cites {cc.get('path')}:{cc.get('start_line')} ({ok})")
    adds = result.triage.get("additional_findings") or []
    lines.append(f"extra findings from the whole-repo pass: {len(adds)}")
    for a in adds:  # type: ignore[union-attr]
        d, c = a.get("doc_citation") or {}, a.get("code_citation") or {}
        ok = "verified" if a.get("fully_verified") else "UNVERIFIED"
        lines.append(f"  {a.get('finding_id')} [{a.get('drift_kind')}] {str(a.get('explanation'))[:80]}")
        lines.append(f"      docs {d.get('path')}:{d.get('start_line')}  code {c.get('path')}:{c.get('start_line')}  ({ok})")
    if result.repros:
        lines.append("executable repro (isolated venv, no network):")
        for r in result.repros:
            lines.append(f"  {r.get('case_id')}: {r.get('status')} {r.get('exception_type') or ''}"
                         f"{'  STRICT-CONFIRMED' if r.get('strict_confirmed') else ''}")
    lines.append("-" * 60)
    lines.append(f"Beam tokens: triage {tokens['triage_prompt']:,} in + {tokens['triage_completion']:,} out; "
                 f"repro {tokens['repro_prompt'] + tokens['repro_completion']:,} ({tokens['repro_calls']} calls); "
                 f"total {tokens['total']:,}")
    lines.append(f"wall time {wall:,.0f}s (triage call {client.last_latency:,.0f}s)" if client else f"wall time {wall:,.0f}s")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
