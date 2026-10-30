"""DocDrift v2 hybrid, step 3: executable confirmation for every candidate the Beam triage marks true_drift,
and for every extra finding it adds. This uses the unchanged tutorial runner (repoatlas/repro.py).

"Confirmed" follows the strict rule: status reproduced with an interface error (TypeError, AttributeError,
ImportError or NameError) raised on a DOC-LITERAL line.
Whole-repo findings are rerun with the same finding dicts, so their repro prompts usually replay from
the cache. Symbol flags become a finding made of the flagged doc line plus the code citation and reason
from the triage.
Repro Beam tokens go into the hybrid ledger, and the run stops before the total could pass --total-cap.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from repoatlas.config import load_ollama_api_key  # noqa: E402
from repoatlas.repro import (  # noqa: E402
    BeamReproClient, ReproCase, TokenBudgetExceeded, VenvManager, network_isolation_prefix, run_case)
from hybrid_triage import OUT, _ledger, _ledger_add  # noqa: E402

CHECK_KIND = {"call-signature": "signature", "method-call-signature": "signature", "docstring-param": "signature"}


def build_cases(sources: dict) -> list[ReproCase]:
    traces = {p.stem.rsplit("-", 1)[0]: json.loads(p.read_text()) for p in (ROOT / "results_live/traces").glob("*-400000.json")}
    cases: list[ReproCase] = []
    for tf in sorted((OUT / "triage").glob("*.json")):
        res = json.loads(tf.read_text())
        repo = res["repo"]
        if not res.get("verdicts") and not res.get("additional_findings"):
            continue
        src = sources[repo]
        cands = {c["candidate_id"]: c for c in res["candidates"]}
        wr = {f"{repo}-400000:{f['finding_id']}": f for f in (traces[repo].get("output") or {}).get("findings") or []}
        for v in res.get("verdicts") or []:
            if v.get("verdict") != "true_drift" or v.get("candidate_id") not in cands:
                continue
            c = cands[v["candidate_id"]]
            if c["source"] == "whole_repo":
                finding = wr[c["source_id"]]
            else:
                cc = dict(v["code_citation"])
                ver = v.get("code_citation_verification") or {}
                finding = {
                    "finding_id": c["source_id"],
                    "drift_kind": CHECK_KIND.get(c["claim"].split(":")[0], "other"),
                    "explanation": f"{c['claim']}. Triage reason: {v.get('reason', '')}",
                    "doc_citation": {"path": c["doc_path"], "start_line": c["doc_line"], "end_line": c["doc_end"], "quote": c["doc_text"]},
                    "code_citation": {"path": cc.get("path", ""), "start_line": max(1, int(cc.get("start_line", 1))),
                                      "end_line": max(1, int(cc.get("end_line", 1))), "quote": cc.get("quote", ""),
                                      **({} if ver.get("verified") else {})},
                    "proposed_fix": v.get("suggested_doc_fix", ""),
                }
            cases.append(ReproCase(case_id=f"{repo}:{c['source_id']}", repo=repo, repo_url=src["repo_url"], ref=src["ref"],
                                   source_dir=Path(src["path"]), finding=finding))
        for a in res.get("additional_findings") or []:
            if a.get("invalid"):
                continue
            cases.append(ReproCase(case_id=f"{repo}:ADD-{a['finding_id']}", repo=repo, repo_url=src["repo_url"], ref=src["ref"],
                                   source_dir=Path(src["path"]), finding=a))
    return cases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--total-cap", type=int, default=4_950_000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sources = json.loads((ROOT / "results_live/repros/sources.json").read_text())
    attrs_ref = json.loads((ROOT / "results_live/traces/attrs-400000.json").read_text())["summary"]["ref"]
    sources.setdefault("attrs", {"repo_url": "https://github.com/python-attrs/attrs", "ref": attrs_ref, "path": "/workspace/sweep/attrs"})
    (OUT / "sources.json").write_text(json.dumps(sources, indent=2))
    cases = build_cases(sources)
    print(f"{len(cases)} cases")
    if args.dry_run:
        for c in cases:
            print(c.case_id, c.finding["doc_citation"]["path"], c.finding["doc_citation"]["start_line"])
        return 0
    used = _ledger()["total_tokens"]
    client = BeamReproClient(base_url="https://ollama.com/v1", model="beam",
                             api_key=load_ollama_api_key(),
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
            _ledger_add("repro", case.case_id, dp, dc)
        rec["strict_confirmed"] = rec["status"] == "reproduced" and rec.get("evidence") == "interface_error"
        rec["live_tokens"] = dp + dc
        results[case.case_id] = rec
        results_path.write_text(json.dumps(dict(sorted(results.items())), indent=2))
        print(f"  -> {case.case_id}: {rec['status']} {rec.get('evidence')} {rec.get('exception_type')} strict={rec['strict_confirmed']} "
              f"tokens={dp + dc} ledger={_ledger()['total_tokens']}", flush=True)
        if any("HTTP 402" in str(rec.get("error_excerpt")) or "quota" in str(rec.get("error_excerpt")).lower() for _ in [0]):
            errors.append(f"{case.case_id}: quota error")
            break
    (out_dir / "usage.json").write_text(json.dumps({**client.usage, "errors": errors}, indent=2))
    print(json.dumps(client.usage))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
