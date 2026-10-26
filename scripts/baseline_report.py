"""Build results_live/baselines/{baselines.json,baselines.csv,baselines.md} from the baseline artefacts."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baseline_common import TRUE_DRIFTS, match_true_drifts  # noqa: E402
from _symbol_verdicts import SAMPLE, SAMPLE_SEED, V  # noqa: E402

try:
    from _chunked_verdicts import CV  # (size_k, repo, finding_index) -> (verdict, true_id_or_known_id, evidence)
except ImportError:
    CV = {}

REPOS9 = ["starlette", "httpx", "click", "structlog", "nox", "arrow", "cattrs", "marshmallow", "attrs"]
OUT = Path("results_live/baselines")
ALL_TRUE = {d["id"] for d in TRUE_DRIFTS}


def whole_repo() -> dict:
    rows, recovered, verified_rec = [], set(), set()
    calls = prompt = compl = findings = 0
    wall = 0.0
    for r in REPOS9:
        t = json.loads(Path(f"results_live/traces/{r}-400000.json").read_text())
        s = t["summary"]
        calls += 1
        prompt += s["input_tokens"]
        compl += s["output_tokens"]
        wall += s["latency_seconds"]
        for f, v in zip(t["output"]["findings"], t["verification_results"]):
            findings += 1
            cites = [(f["doc_citation"]["path"], f["doc_citation"]["start_line"], f["doc_citation"]["end_line"]),
                     (f["code_citation"]["path"], f["code_citation"]["start_line"], f["code_citation"]["end_line"])]
            text = " ".join([f["explanation"], f["doc_citation"]["quote"], f["code_citation"]["quote"], f["proposed_fix"]])
            m = match_true_drifts(r, cites, text)
            recovered.update(m)
            if v.get("fully_verified"):
                verified_rec.update(m)
    return {"method": "Whole-repo Beam (one call per repo, 400k)", "calls": calls, "prompt_tokens": prompt,
            "completion_tokens": compl, "wall_seconds": round(wall, 1), "total_findings": findings,
            "true_recovered": sorted(recovered, key=lambda x: int(x[1:])),
            "true_recovered_verified": sorted(verified_rec, key=lambda x: int(x[1:])),
            "true_findings": len(recovered), "precision_note": "11 true / 16 findings on these 9 repos (handcheck.md)",
            "precision": round(11 / 16, 3)}


def symbol() -> dict:
    d = json.loads((OUT / "symbol_check_flags.json").read_text())
    flags = d["flags"]
    rec = sorted({V[i][1] for i in V if V[i][1]}, key=lambda x: int(x[1:]))
    in9 = [i for i, f in enumerate(flags) if f["repo"] in REPOS9]
    s_true = sum(V[i][0] == "true" for i in SAMPLE)
    all_true = sum(v[0] == "true" for v in V.values())
    in9_true = sum(V[i][0] == "true" for i in in9)
    return {"method": "Non-AI symbol check (ast)", "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "total_findings": len(flags), "total_findings_9repos": len(in9), "true_recovered": rec,
            "precision_sample20": round(s_true / 20, 3), "sample_true": s_true, "sample_seed": SAMPLE_SEED, "sample": SAMPLE,
            "precision_all_handchecked": round(all_true / len(flags), 3), "all_true": all_true,
            "all_unclear": sum(v[0] == "unclear" for v in V.values()),
            "precision_9repos": round(in9_true / len(in9), 3), "true_9repos": in9_true,
            "new_true_not_in_known_21": sum(1 for v in V.values() if v[0] == "true" and not v[1]),
            "verdicts": {i: {"flag": flags[i], "verdict": V[i][0], "true_drift": V[i][1], "evidence": V[i][2]} for i in V}}


def chunked(size_k: int) -> dict | None:
    d = OUT / f"chunked-{size_k}k"
    if not d.exists():
        return None
    per_repo, rec, rec_ver = [], set(), set()
    calls = prompt = compl = nf = 0
    wall = 0.0
    errors, verdicts = [], []
    for r in REPOS9:
        p = d / f"{r}.json"
        if not p.exists():
            per_repo.append({"repo": r, "status": "not run"})
            continue
        res = json.loads(p.read_text())
        if res.get("stopped", "") and str(res["stopped"]).startswith("skipped"):
            per_repo.append({"repo": r, "status": res["stopped"]})
            continue
        calls += res.get("calls_ok", 0)
        prompt += res.get("prompt_tokens", 0)
        compl += res.get("completion_tokens", 0)
        wall += res.get("wall_seconds", 0.0)
        errors += [{"repo": r, **e} for e in res.get("errors", [])]
        fl = res.get("findings", [])
        nf += len(fl)
        for i, m in enumerate(fl):
            v = CV.get((size_k, r, i))
            ids = set(m["true_drift_match"]) | ({v[1]} if v and v[1].startswith("T") else set())
            rec.update(ids)
            if m["fully_verified"]:
                rec_ver.update(ids)
            verdicts.append({"repo": r, "index": i, "chunk": m["chunk"], "doc": f"{m['finding']['doc_citation']['path']}:{m['finding']['doc_citation']['start_line']}",
                             "code": f"{m['finding']['code_citation']['path']}:{m['finding']['code_citation']['start_line']}",
                             "fully_verified": m["fully_verified"], "auto_true_match": m["true_drift_match"],
                             "explanation": m["finding"]["explanation"][:300],
                             "verdict": v[0] if v else ("true" if m["true_drift_match"] else "UNCHECKED"),
                             "label": v[1] if v else ",".join(m["true_drift_match"]), "evidence": v[2] if v else ""})
        per_repo.append({"repo": r, "status": res.get("stopped") or "ok", "calls": res.get("calls_ok"), "chunks": res.get("chunks_planned"),
                         "prompt_tokens": res.get("prompt_tokens"), "completion_tokens": res.get("completion_tokens"),
                         "wall_seconds": round(res.get("wall_seconds", 0), 1), "raw_findings": res.get("raw_findings"),
                         "merged_findings": len(fl), "true": res.get("true_drifts_recovered")})
    ntrue = sum(1 for v in verdicts if v["verdict"] == "true")
    return {"method": f"Chunked Beam (~{size_k}k chunks)", "calls": calls, "prompt_tokens": prompt, "completion_tokens": compl,
            "wall_seconds": round(wall, 1), "total_findings": nf, "true_recovered": sorted(rec, key=lambda x: int(x[1:])),
            "true_recovered_verified": sorted(rec_ver, key=lambda x: int(x[1:])), "true_findings": ntrue,
            "precision": round(ntrue / nf, 3) if nf else None, "per_repo": per_repo, "errors": errors, "findings": verdicts}


def main() -> None:
    rows = [whole_repo(), symbol()]
    for k in (32, 128):
        c = chunked(k)
        if c:
            rows.append(c)
    ledger = json.loads((OUT / "beam_usage_ledger.json").read_text()) if (OUT / "beam_usage_ledger.json").exists() else {}
    ledger_summary = {k: ledger.get(k) for k in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")}
    (OUT / "baselines.json").write_text(json.dumps({"rows": rows, "beam_usage_this_work": ledger_summary,
                                                    "true_drifts": TRUE_DRIFTS}, indent=2, default=str))
    with (OUT / "baselines.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["method", "calls", "prompt_tokens", "completion_tokens", "true_recovered_of_11", "missed", "total_findings", "precision"])
        for r in rows:
            prec = r.get("precision", r.get("precision_sample20"))
            w.writerow([r["method"], r["calls"], r["prompt_tokens"], r["completion_tokens"], len(r["true_recovered"]),
                        " ".join(sorted(ALL_TRUE - set(r["true_recovered"]), key=lambda x: int(x[1:]))), r["total_findings"], prec])
    print(json.dumps([{k: v for k, v in r.items() if k not in ("verdicts", "findings", "per_repo")} for r in rows], indent=1))
    print(ledger_summary)


if __name__ == "__main__":
    main()
