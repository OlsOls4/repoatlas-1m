"""Score DocDrift v2 (symbol candidates + whole-repo Beam triage + repro badge) against the hand labels.

Rows: symbol check alone | whole-repo Beam alone | hybrid (symbol + Beam triage) | hybrid + repro-confirmed (strict).
Writes results_live/hybrid/hybrid.{json,csv,md}. Unclear counts as not-true for precision.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _hybrid_verdicts import ADD, RECHECK  # noqa: E402
from _symbol_verdicts import V  # noqa: E402
from hybrid_triage import REPOS  # noqa: E402

OUT = ROOT / "results_live/hybrid"
NINE = ["starlette", "httpx", "click", "structlog", "nox", "arrow", "cattrs", "marshmallow", "attrs"]
WHOLE_T = {"starlette-400000:DD-1": "T1", "httpx-400000:DD-1": "T2", "httpx-400000:DD-2": "T3", "click-400000:DD-1": "T4",
           "structlog-400000:DD-2": "T5", "nox-400000:DD-1": "T6", "arrow-400000:DD-1": "T7", "cattrs-400000:DD-1": "T8",
           "cattrs-400000:DD-2": "T9", "cattrs-400000:DD-3": "T10", "marshmallow-400000:DD-2": "T11"}
# Known-true universe before this work: T1-T11, symbol-check new trues (S<idx>), chunked-Beam new trues (C:...).
CHUNKED_NEW = {  # id -> repo (from scripts/_chunked_verdicts.py, deduped across 32k/128k and against symbol flags)
 "C:httpx-handle_request": "httpx", "C:httpx-sslcontext": "httpx", "C:structlog-output-args": "structlog",
 "C:nox-tasks-returns": "nox", "C:arrow-interval-end": "arrow", "C:arrow-span_range-end": "arrow",
 "C:cattrs-td59": "cattrs", "C:cattrs-td251": "cattrs", "C:cattrs-ujson-b85": "cattrs", "C:mm-url-default": "marshmallow",
 "C:mm-quotes-400": "marshmallow", "C:attrs-py2-reprs": "attrs", "C:attrs-force_kw_only": "attrs"}


def sym_flags() -> list[dict]:
    d = json.loads((ROOT / "results_live/baselines/symbol_check_flags.json").read_text())
    return d if isinstance(d, list) else d["flags"]


def sym_label(idx: int) -> tuple[str, str]:
    verdict, tid, _ = V[idx]
    return verdict, (tid or f"S{idx}") if verdict == "true" else ""


def known_universe() -> dict[str, str]:
    u = {f"T{i}": r for i, r in enumerate(["starlette", "httpx", "httpx", "click", "structlog", "nox", "arrow", "cattrs",
                                             "cattrs", "cattrs", "marshmallow"], start=1)}
    for i, f in enumerate(sym_flags()):
        v, did = sym_label(i)
        if v == "true" and did.startswith("S"):
            u[did] = f["repo"]
    u.update(CHUNKED_NEW)
    return u


def whole_labels() -> dict[str, str]:
    return json.loads((ROOT / "results_live/repros/hand_labels.json").read_text())["labels"]


def item(repo: str, source_id: str, wl: dict) -> tuple[str, str]:
    """(verdict, drift_id) for a symbol flag or whole-repo finding."""
    if source_id.startswith("S"):
        return sym_label(int(source_id[1:]))
    v = wl.get(source_id, "unclear")
    return v, WHOLE_T.get(source_id, "") if v == "true" else ""


def row(name: str, items: list[dict], tokens: int, universe: dict) -> dict:
    true_items = [i for i in items if i["verdict"] == "true"]
    found = sorted({i["drift_id"] for i in true_items})
    found9 = [d for d in found if d in universe and universe[d] in NINE and not d.startswith("N:")]
    return {"method": name, "findings": len(items), "true_findings": len(true_items),
            "unclear_findings": sum(1 for i in items if i["verdict"] == "unclear"),
            "precision": round(len(true_items) / len(items), 3) if items else None,
            "distinct_true": len(found), "distinct_true_ids": found,
            "of_33_prior_9repo_union": len(found9),
            "beam_tokens": tokens, "items": items}


def main() -> None:
    wl = whole_labels()
    universe = known_universe()
    for k, (v, did, _ev) in ADD.items():
        if v == "true" and did.startswith("N:"):
            universe[did] = k.split(":")[0]
    flags = sym_flags()
    # 1. symbol alone (12 repos)
    s_items = []
    for i, f in enumerate(flags):
        v, did = sym_label(i)
        s_items.append({"repo": f["repo"], "id": f"S{i}", "verdict": v, "drift_id": did})
    # 2. whole-repo alone (12 repos)
    w_items, w_tokens = [], 0
    for repo in REPOS:
        t = json.loads((ROOT / f"results_live/traces/{repo}-400000.json").read_text())
        w_tokens += int(t["summary"]["input_tokens"]) + int(t["summary"].get("output_tokens") or 0)
        for f in t["output"]["findings"]:
            sid = f"{repo}-400000:{f['finding_id']}"
            v, did = item(repo, sid, wl)
            w_items.append({"repo": repo, "id": sid, "verdict": v, "drift_id": did})
    # 3./4. hybrid
    ledger = json.loads((OUT / "beam_usage_ledger.json").read_text())
    tri_tokens = sum(e["prompt"] + e["completion"] for e in ledger["entries"] if e["kind"] == "triage")
    rep_tokens = sum(e["prompt"] + e["completion"] for e in ledger["entries"] if e["kind"] == "repro")
    repros = json.loads((OUT / "repros/repros.json").read_text())
    h_items, triage_notes = [], {}
    for repo in REPOS:
        r = json.loads((OUT / "triage" / f"{repo}.json").read_text())
        if r.get("error"):  # triage failed: fall back to the untriaged candidates (disclosed)
            triage_notes[repo] = f"triage failed ({r['error']}); hybrid keeps all {len(r['candidates'])} candidates untriaged, no repros"
            for c in r["candidates"]:
                v, did = item(repo, c["source_id"], wl)
                h_items.append({"repo": repo, "id": c["source_id"], "kind": "untriaged-fallback", "verdict": v, "drift_id": did,
                                "beam": None, "strict_confirmed": False, "repro_status": None})
            continue
        for bv in r["verdicts"]:
            if bv["verdict"] != "true_drift":
                continue
            v, did = item(repo, bv["source_id"], wl)
            rec = repros.get(f"{repo}:{bv['source_id']}", {})
            h_items.append({"repo": repo, "id": bv["source_id"], "kind": "candidate", "verdict": v, "drift_id": did,
                            "beam": "true_drift", "citation_verified": bv["code_citation_verification"]["verified"],
                            "strict_confirmed": bool(rec.get("strict_confirmed")), "repro_status": rec.get("status"),
                            "repro_evidence": rec.get("evidence"), "recheck": RECHECK.get(f"{repo}:{bv['source_id']}")})
        for a in r.get("additional_findings") or []:
            if a.get("invalid"):
                continue
            v, did, ev = ADD[f"{repo}:{a['finding_id']}"]
            rec = repros.get(f"{repo}:ADD-{a['finding_id']}", {})
            h_items.append({"repo": repo, "id": f"ADD-{a['finding_id']}", "kind": "addition", "verdict": v,
                            "drift_id": did if v == "true" else "", "evidence": ev, "fully_verified": a.get("fully_verified"),
                            "strict_confirmed": bool(rec.get("strict_confirmed")), "repro_status": rec.get("status"),
                            "repro_evidence": rec.get("evidence")})
    conf = [i for i in h_items if i["strict_confirmed"]]
    rows = [row("Symbol check alone", s_items, 0, universe),
            row("Whole-repo Beam alone", w_items, w_tokens, universe),
            row("Hybrid (symbol + whole-repo Beam triage)", h_items, tri_tokens, universe),
            row("Hybrid + repro-confirmed (strict)", conf, tri_tokens + rep_tokens, universe)]
    for r in rows:
        r["missed_known"] = sorted(set(universe) - set(r["distinct_true_ids"]))
    # Beam triage as a filter on the candidates it judged
    judged = []
    for repo in REPOS:
        r = json.loads((OUT / "triage" / f"{repo}.json").read_text())
        for bv in r.get("verdicts") or []:
            v, _ = item(repo, bv["source_id"], wl)
            judged.append((bv["verdict"], v))
    filt = {"judged": len(judged),
            "beam_true__hand_true": sum(1 for b, h in judged if b == "true_drift" and h == "true"),
            "beam_true__hand_not_true": sum(1 for b, h in judged if b == "true_drift" and h != "true"),
            "beam_not_true__hand_true": sum(1 for b, h in judged if b != "true_drift" and h == "true"),
            "beam_not_true__hand_not_true": sum(1 for b, h in judged if b != "true_drift" and h != "true")}
    res = {"rows": rows, "universe_size": len(universe), "universe": universe, "triage_notes": triage_notes,
           "triage_filter_confusion": filt,
           "beam_tokens": {"triage": tri_tokens, "repro_live": rep_tokens, "total_new": ledger["total_tokens"]}}
    (OUT / "hybrid.json").write_text(json.dumps(res, indent=2))
    with (OUT / "hybrid.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["method", "distinct_true_drifts", "of_33_prior_union", "findings", "true_findings", "precision", "beam_tokens"])
        for r in rows:
            w.writerow([r["method"], r["distinct_true"], r["of_33_prior_9repo_union"], r["findings"], r["true_findings"],
                        r["precision"], r["beam_tokens"]])
    print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "universe")}, indent=1))
    for r in rows:
        print(f"{r['method']:45s} distinct={r['distinct_true']}/{len(universe)} of33={r['of_33_prior_9repo_union']} "
              f"findings={r['findings']} true={r['true_findings']} prec={r['precision']} tokens={r['beam_tokens']}")
        print("   missed:", " ".join(r["missed_known"]))


if __name__ == "__main__":
    main()
