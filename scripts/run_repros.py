"""Tutorial runner CLI: generate and run doc-literal repro scripts for DocDrift findings.

Example (live, sequential Beam calls):
    OLLAMA_API_KEY=... python scripts/run_repros.py \
        --traces 'results_live/traces/*-400000.json' \
        --sources results_live/repros/sources.json \
        --labels results_live/repros/hand_labels.json \
        --out results_live/repros

Use --dry-run to list cases and prompt sizes without calling Beam or installing anything.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import sys

ROOT: Path = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repoatlas.config import DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_MODEL  # noqa: E402
from repoatlas.repro import (  # noqa: E402
    ALL_STATUSES,
    BeamReproClient,
    TokenBudgetExceeded,
    VenvManager,
    build_repro_messages,
    ensure_checkout,
    load_cases_from_traces,
    network_isolation_prefix,
    run_case,
    summarise,
)


def _parse_args() -> argparse.Namespace:
    """
    @brief Parse CLI arguments.
    """

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--traces", default="results_live/traces/*-400000.json", help="Glob of analyser trace JSONs.")
    parser.add_argument("--sources", default="results_live/repros/sources.json", help="repo -> {path, ref, repo_url}.")
    parser.add_argument("--labels", default="results_live/repros/hand_labels.json", help="Optional hand labels JSON.")
    parser.add_argument("--out", default="results_live/repros", help="Output directory.")
    parser.add_argument("--venv-root", default=".cache/repoatlas/repro_venvs")
    parser.add_argument("--checkout-root", default=".cache/repoatlas/checkouts")
    parser.add_argument("--only", nargs="*", default=None, help="Case ids to run (e.g. cattrs-400000:DD-2).")
    parser.add_argument("--timeout", type=int, default=60, help="Per-script timeout (s).")
    parser.add_argument("--token-budget", type=int, default=2_000_000)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--api-key-file", default=None, help="Read the key from this file instead of OLLAMA_API_KEY.")
    parser.add_argument("--base-url", default=os.environ.get("REPRO_BASE_URL", DEFAULT_OLLAMA_BASE_URL))
    parser.add_argument("--model", default=os.environ.get("REPRO_MODEL", DEFAULT_OLLAMA_MODEL))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _write_summary_md(path: Path, results: dict, labels: dict, summary: dict, usage: dict) -> None:
    """
    @brief Human-readable summary table.
    """

    lines: list[str] = [
        "# DocDrift tutorial runner: repro results",
        "",
        "| Finding | Hand label | Repro status | Reason | Observed | Predicted | Model verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for case_id in sorted(results):
        rec = results[case_id]
        lines.append(
            f"| {case_id} | {labels.get(case_id, '-')} | {rec['status']} | {rec['reason']} | "
            f"{rec.get('exception_type') or '-'} | {rec.get('expected_exception_type') or '-'} | {rec.get('model_verdict') or '-'} |"
        )
    lines += ["", "## Summary", "", "```json", json.dumps(summary, indent=2), "```", "", "## Beam usage (this run)", "", "```json", json.dumps(usage, indent=2), "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """
    @brief Entry point.
    """

    args = _parse_args()
    out_dir: Path = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sources: dict = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    for repo, src in sources.items():
        if not src.get("path") or not Path(src["path"]).exists():
            src["path"] = str(ensure_checkout(src["repo_url"], src["ref"], Path(args.checkout_root)))
    labels: dict = {}
    if args.labels and Path(args.labels).is_file():
        raw = json.loads(Path(args.labels).read_text(encoding="utf-8"))
        labels = raw.get("labels", raw)
    traces: list[Path] = [Path(p) for p in sorted(glob.glob(args.traces))]
    cases = load_cases_from_traces(traces, sources)
    if args.only:
        cases = [case for case in cases if case.case_id in set(args.only)]
    print(f"{len(cases)} findings from {len(traces)} traces")

    if args.dry_run:
        for case in cases:
            chars = sum(len(m["content"]) for m in build_repro_messages(case))
            print(f"{case.case_id}: {case.repo}@{case.ref[:7]} prompt ~{chars // 4} tok label={labels.get(case.case_id, '-')}")
        return 0

    api_key: str | None = Path(args.api_key_file).read_text(encoding="utf-8").strip() if args.api_key_file else os.environ.get("OLLAMA_API_KEY")
    if not api_key:
        print("OLLAMA_API_KEY is not set (or pass --api-key-file).", file=sys.stderr)
        return 2
    client = BeamReproClient(
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        cache_dir=Path(".cache/repoatlas/repro_responses"),
        lock_path=Path(".cache/repoatlas/ollama.lock"),
        max_tokens=args.max_tokens,
        token_budget=args.token_budget,
    )
    venvs = VenvManager(Path(args.venv_root))
    isolation = network_isolation_prefix()
    print(f"network isolation: {isolation[1]}")

    results_path: Path = out_dir / "repros.json"
    results: dict = json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else {}
    errors: list[str] = []
    for case in cases:
        try:
            results[case.case_id] = run_case(case, client, venvs, out_dir, isolation, timeout=args.timeout)
        except TokenBudgetExceeded as exc:
            errors.append(f"{case.case_id}: {exc}")
            print(f"stopping: {exc}", file=sys.stderr)
            break
        results_path.write_text(json.dumps(dict(sorted(results.items())), indent=2), encoding="utf-8")
        print(f"  -> {case.case_id}: {results[case.case_id]['status']} (live tokens so far {client.total_tokens})")

    results_path.write_text(json.dumps(dict(sorted(results.items())), indent=2), encoding="utf-8")
    summary = summarise(results, labels) if labels else {}
    usage = {**client.usage, "total_live_tokens": client.total_tokens, "errors": errors}
    (out_dir / "summary.json").write_text(json.dumps({"summary": summary, "beam_usage_this_run": usage}, indent=2), encoding="utf-8")
    _write_summary_md(out_dir / "summary.md", results, labels, summary, usage)
    print(json.dumps(summary, indent=2))
    print(json.dumps(usage, indent=2))
    counts = {status: sum(1 for rec in results.values() if rec["status"] == status) for status in ALL_STATUSES}
    print(counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
