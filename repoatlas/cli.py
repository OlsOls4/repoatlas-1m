"""Command-line entry for DocDrift: `docdrift run <repo>`."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

import requests

from repoatlas.pipeline import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    BeamClient,
    PipelineResult,
    TokenGuardError,
    format_preflight,
    run_docdrift,
)


class HttpBeamClient:
    """
    @brief OpenAI-compatible chat completions client.
    """

    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int) -> dict[str, object]:
        """
        @brief POST /chat/completions and parse JSON content.
        """

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0},
            timeout=120,
        )
        response.raise_for_status()
        payload: object = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Beam response was not an object")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Beam response had no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        content = str(message.get("content", "") if isinstance(message, dict) else "")
        try:
            parsed: object = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Beam did not return JSON") from exc
        return parsed if isinstance(parsed, dict) else {"raw": parsed}


def build_parser() -> argparse.ArgumentParser:
    """
    @brief Build the `docdrift` argument parser.
    """

    parser = argparse.ArgumentParser(
        prog="docdrift",
        description="DocDrift v2: symbol check + Beam triage + optional repro.",
        epilog=(
            "Recommended: symbol check + whole-repo Beam triage, plus 32k docstring chunks "
            "if you want more coverage at lower precision. The shipped command is the first "
            "two steps. 32k docstring chunks are an experimental extra pass "
            "(scripts/beamv3.py), not a --docstring-chunks flag."
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """
    @brief CLI entry. Returns a process exit code.
    """

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command != "run":
        parser.error("unknown command")
    client: BeamClient | None = None
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    if not args.preflight_only:
        if not api_key:
            print("OLLAMA_API_KEY is not set. Use --preflight-only or export a free Ollama Cloud key.", file=sys.stderr)
            return 2
        client = HttpBeamClient(args.base_url, args.model, api_key)
    try:
        result: PipelineResult = run_docdrift(
            args.target,
            max_tokens=args.max_tokens,
            run_repro=not args.no_repro,
            client=None if args.preflight_only else client,
            base_url=args.base_url,
            model=args.model,
        )
    except TokenGuardError as exc:
        print(f"token guard: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(format_preflight(result))
    if args.as_json:
        print(
            json.dumps(
                {
                    "repo": result.repo,
                    "pack_tokens": result.pack_tokens,
                    "projected_prompt_tokens": result.projected_prompt_tokens,
                    "symbol_flags": len(result.symbol_flags),
                    "triage": result.triage,
                    "repros": result.repros,
                    "skipped_reason": result.skipped_reason,
                },
                indent=2,
            )
        )
    elif result.skipped_reason:
        print(result.skipped_reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
