"""Beam v3, repro step: run the unchanged repro runner (repoatlas/repro.py, as in hybrid_repro.py) on every v3
finding that is NEW after dedupe against the hybrid items (no triage gate, so all of them are tried).
Strict confirmation = status reproduced with an interface error on a doc-literal line (same rule as the hybrid).
Tokens go into the v3 ledger; the run stops before the v3 total could pass --total-cap (8M)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from repoatlas.repro import (  # noqa: E402
    BeamReproClient, ReproCase, TokenBudgetExceeded, VenvManager, network_isolation_prefix, run_case)
import hybrid_triage as ht  # noqa: E402
from beamv3_merge import OUT, hybrid_items, v3_findings, merge_distinct  # noqa: E402

ht.LEDGER = OUT / "beam_usage_ledger.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--total-cap", type=int, default=8_000_000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sources = json.loads((ROOT / "results_live/hybrid/sources.json").read_text())
    new, _ = merge_distinct(hybrid_items(), v3_findings())
    cases = [ReproCase(case_id=n["id"], repo=n["repo"], repo_url=sources[n["repo"]]["repo_url"], ref=sources[n["repo"]]["ref"],
                       source_dir=Path(sources[n["repo"]]["path"]), finding=n["finding"]) for n in new]
    print(f"{len(cases)} cases")
    if args.dry_run:
        return 0
    used = ht._ledger()["total_tokens"]
    client = BeamReproClient(base_url="https://ollama.com/v1", model="beam",
                             api_key=Path("/home/box/.secrets/ollama_api_key").read_text().strip(),
                             cache_dir=ROOT / ".cache/repoatlas/repro_responses", lock_path=ROOT / ".cache/repoatlas/ollama.lock",
                             max_tokens=8000, token_budget=max(0, args.total_cap - used))
    venvs = VenvManager(ROOT / ".cache/repoatlas/repro_venvs")
    isolation = network_isolation_prefix()
    out_dir = OUT / "repros"
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "repros.json"
    results: dict = json.loads(results_path.read_text()) if results_path.exists() else {}
    errors: list[str] = []
    for case in cases:
        if case.case_id in results:
            continue
        before = dict(client.usage)
        try:
            rec = run_case(case, client, venvs, out_dir, isolation, timeout=60)
        except TokenBudgetExceeded as exc:
            errors.append(f"{case.case_id}: {exc}")
            print("stopping:", exc)
            break
        dp = client.usage["prompt_tokens"] - before["prompt_tokens"]
        dc = client.usage["completion_tokens"] - before["completion_tokens"]
        if dp or dc:
            ht._ledger_add("repro", case.case_id, dp, dc)
        rec["strict_confirmed"] = rec["status"] == "reproduced" and rec.get("evidence") == "interface_error"
        rec["live_tokens"] = dp + dc
        results[case.case_id] = rec
        results_path.write_text(json.dumps(dict(sorted(results.items())), indent=2))
        print(f"  -> {case.case_id}: {rec['status']} {rec.get('evidence')} {rec.get('exception_type')} "
              f"strict={rec['strict_confirmed']} tokens={dp + dc} ledger={ht._ledger()['total_tokens']}", flush=True)
        ex = str(rec.get("error_excerpt"))
        if "HTTP 402" in ex or "quota" in ex.lower():
            errors.append(f"{case.case_id}: quota error")
            break
    (out_dir / "usage.json").write_text(json.dumps({**client.usage, "errors": errors}, indent=2))
    print(json.dumps(client.usage))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
