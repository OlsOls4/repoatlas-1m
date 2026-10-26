"""Rerun the starlette receive_json strict repro with a fixed script (no Beam call)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hybrid_repro import build_cases  # noqa: E402
from repoatlas.repro import (  # noqa: E402
    VenvManager,
    network_isolation_prefix,
    run_fixed_plan,
    starlette_receive_json_plan,
)

STARLETTE_IDS = {"starlette:S1", "starlette:starlette-400000:DD-1"}


def main() -> int:
    """
    @brief Install starlette extras, run the fixed script, update repros.json.
    """

    sources = json.loads((ROOT / "results_live/hybrid/sources.json").read_text(encoding="utf-8"))
    cases = [case for case in build_cases(sources) if case.case_id in STARLETTE_IDS]
    if len(cases) != 2:
        raise SystemExit(f"expected 2 starlette cases, got {[c.case_id for c in cases]}")
    out_dir = ROOT / "results_live/hybrid/repros"
    results_path = out_dir / "repros.json"
    results: dict = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}
    venvs = VenvManager(ROOT / ".cache/repoatlas/repro_venvs")
    isolation = network_isolation_prefix()
    plan = starlette_receive_json_plan()
    for case in cases:
        rec = run_fixed_plan(case, plan, venvs, out_dir, isolation)
        results[case.case_id] = rec
        print(json.dumps({k: rec[k] for k in ("case_id", "status", "evidence", "exception_type", "strict_confirmed", "script_origin")}))
    results_path.write_text(json.dumps(dict(sorted(results.items())), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
