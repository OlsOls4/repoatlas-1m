"""Score the long-context ablation (local-file vs whole-repo Beam triage) against the existing labels.

Conditions: whole (reused hybrid verdicts, results_live/hybrid/triage), local (results_live/ablation/local),
stability (whole-repo rerun on a subset, results_live/ablation/stability). Labels: scripts/_symbol_verdicts.py and
results_live/repros/hand_labels.json via hybrid_score.item (unclear counts as not-true). Gold evidence locations:
scripts/_ablation_gold.py. Writes results.json and table.md into the ablation output directory.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(sys.argv[sys.argv.index("--repo-root") + 1]) if "--repo-root" in sys.argv else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else REPO_ROOT / "results_live/ablation"
from _ablation_gold import G  # noqa: E402
from hybrid_score import item, whole_labels  # noqa: E402

JUDGED = ["starlette", "httpx", "click", "nox", "arrow", "cattrs", "marshmallow", "attrs", "jinja", "werkzeug", "pydantic-settings"]
SLACK = 3


def cite_hit(cc: dict | None, gold: list) -> bool:
    if not cc or not gold:
        return False
    s, e = int(cc.get("start_line") or 0), int(cc.get("end_line") or cc.get("start_line") or 0)
    return any(cc.get("path") == p and s <= b + SLACK and e >= a - SLACK for p, a, b in gold)


def load() -> tuple[list[dict], dict]:
    wl = whole_labels()
    rows, tokens = [], {"whole": 0, "local": 0, "stability": 0}
    hl = json.loads((REPO_ROOT / "results_live/hybrid/beam_usage_ledger.json").read_text())
    tokens["whole"] = sum(e["prompt"] + e["completion"] for e in hl["entries"] if e["kind"] == "triage" and e["label"] in JUDGED)
    tokens["whole_calls"] = sum(1 for e in hl["entries"] if e["kind"] == "triage" and e["label"] in JUDGED)
    last = {e["label"]: e["prompt"] + e["completion"] for e in hl["entries"] if e["kind"] == "triage" and e["label"] in JUDGED}
    tokens["whole_final_call_per_repo"] = sum(last.values())  # cattrs triage was sent twice; this counts only the call used
    al = json.loads((OUT / "beam_usage_ledger.json").read_text())
    tokens["ablation_ledger_total"] = al["total_tokens"]
    tokens["ablation_ledger_calls"] = al["calls"]
    tokens["local_as_spent"] = sum(e["prompt"] + e["completion"] for e in al["entries"] if e["kind"] == "local")
    tokens["local_calls_as_spent"] = sum(1 for e in al["entries"] if e["kind"] == "local")
    stab = {}
    for repo in JUDGED:
        p = OUT / "stability" / f"{repo}.json"
        if p.exists():
            stab[repo] = json.loads(p.read_text())
            tokens["stability"] += stab[repo]["prompt_tokens"] + stab[repo]["completion_tokens"]
    for repo in JUDGED:
        tri = json.loads((REPO_ROOT / "results_live/hybrid/triage" / f"{repo}.json").read_text())
        wv = {v["candidate_id"]: v for v in tri["verdicts"]}
        sv = {v["candidate_id"]: v for v in stab[repo]["verdicts"]} if repo in stab else None
        for c in tri["candidates"]:
            key = f"{repo}:{c['source_id']}"
            label, _ = item(repo, c["source_id"], wl)
            gold, cross = G[key]
            lp = OUT / "local" / f"{repo}__{c['candidate_id']}.json"
            loc = json.loads(lp.read_text()) if lp.exists() else None
            if loc:
                tokens["local"] += loc["prompt_tokens"] + loc["completion_tokens"]
            lv = ((loc or {}).get("verdicts") or [None])[0] if loc else None
            local_files = (loc or {}).get("local_files") or []
            r = {"key": key, "repo": repo, "candidate_id": c["candidate_id"], "source_id": c["source_id"], "label": label,
                 "truth": label == "true", "gold": gold, "cross_file": cross, "local_files": local_files,
                 "gold_outside_local": bool(gold) and cross is not None and not any(p in local_files for p, _, _ in gold),
                 "local_prompt_tokens": (loc or {}).get("prompt_tokens"), "local_finish": (loc or {}).get("finish_reason"),
                 "local_error": (loc or {}).get("error") if loc else "not run"}
            for name, v in (("whole", wv.get(c["candidate_id"])), ("local", lv),
                            ("stability", sv.get(c["candidate_id"]) if sv is not None else "n/a")):
                if v == "n/a":
                    continue
                cc = (v or {}).get("code_citation")
                r[name] = {"verdict": (v or {}).get("verdict"), "kept": (v or {}).get("verdict") == "true_drift",
                           "citation": cc, "cite_verified": bool(((v or {}).get("code_citation_verification") or {}).get("verified")),
                           "cite_correct": cite_hit(cc, gold), "reason": (v or {}).get("reason")}
            rows.append(r)
    return rows, tokens


def metrics(rows: list[dict], cond: str) -> dict:
    rs = [r for r in rows if cond in r]
    kept = [r for r in rs if r[cond]["kept"]]
    t = [r for r in rs if r["truth"]]
    f = [r for r in rs if not r["truth"]]
    ok = lambda r: r[cond]["kept"] == r["truth"]  # noqa: E731
    gradable = [r for r in rs if r["gold"] and r["cross_file"] is not None]
    cross = [r for r in gradable if r["cross_file"]]
    outside = [r for r in gradable if r["gold_outside_local"]]
    tk = [r for r in kept if r["truth"]]
    return {"n": len(rs), "n_true": len(t), "n_false_or_unclear": len(f),
            "kept_true": len(tk), "rejected_false": sum(1 for r in f if not r[cond]["kept"]),
            "kept": len(kept), "precision": round(len(tk) / len(kept), 3) if kept else None,
            "recall": round(len(tk) / len(t), 3) if t else None, "accuracy": round(sum(map(ok, rs)) / len(rs), 3) if rs else None,
            "missing_verdict": sum(1 for r in rs if r[cond]["verdict"] is None),
            "gradable_for_citation": len(gradable),
            "cite_correct": sum(1 for r in gradable if r[cond]["cite_correct"]),
            "verdict_and_cite_correct": sum(1 for r in gradable if ok(r) and r[cond]["cite_correct"]),
            "true_kept_with_correct_cite": sum(1 for r in tk if r[cond]["cite_correct"]),
            "cite_verified": sum(1 for r in rs if r[cond]["cite_verified"]),
            "cross_file_cases": len(cross), "cross_file_verdict_right": sum(map(ok, cross)),
            "cross_file_verdict_and_cite_right": sum(1 for r in cross if ok(r) and r[cond]["cite_correct"]),
            "gold_outside_local_cases": len(outside), "outside_local_verdict_right": sum(map(ok, outside)),
            "outside_local_verdict_and_cite_right": sum(1 for r in outside if ok(r) and r[cond]["cite_correct"])}


def main() -> None:
    rows, tokens = load()
    m = {c: metrics(rows, c) for c in ("whole", "local", "stability")}
    stab_keys = [r for r in rows if "stability" in r]
    m["whole_on_stability_subset"] = metrics(stab_keys, "whole") if stab_keys else None
    m["local_on_stability_subset"] = metrics(stab_keys, "local") if stab_keys else None
    agree = {"stability_vs_whole_verdict_agreement": sum(1 for r in stab_keys if r["stability"]["kept"] == r["whole"]["kept"]),
             "n": len(stab_keys),
             "flips": [{"key": r["key"], "whole": r["whole"]["verdict"], "rerun": r["stability"]["verdict"], "label": r["label"]}
                       for r in stab_keys if r["stability"]["kept"] != r["whole"]["kept"]]}
    disagree = [{"key": r["key"], "label": r["label"], "cross_file": r["cross_file"], "gold_outside_local": r["gold_outside_local"],
                 "whole": r["whole"]["verdict"], "local": r["local"]["verdict"],
                 "whole_reason": r["whole"]["reason"], "local_reason": r["local"]["reason"]}
                for r in rows if "local" in r and r["local"]["kept"] != r["whole"]["kept"]]
    res = {"metrics": m, "tokens": tokens, "stability": agree, "local_vs_whole_disagreements": disagree, "rows": rows,
           "notes": ["labels from an AI reviewer checking against pinned source; unclear counts as not-true",
                     "whole = reused hybrid triage verdicts (one batched call per repo, ~290k-405k prompt tokens)",
                     "local = one call per candidate, pack restricted to the doc file + code files named in the candidate",
                     f"citation correct = path match and line overlap with gold +/-{SLACK} lines"]}
    (OUT / "results.json").write_text(json.dumps(res, indent=2))
    def fmt(x): return "—" if x is None else str(x)  # noqa: E301,E704
    cols = [("whole", "Whole-repo (reused hybrid)"), ("local", "Local-file only")]
    if m["stability"]["n"]:
        cols += [("whole_on_stability_subset", f"Whole-repo, subset ({m['stability']['n']})"),
                 ("local_on_stability_subset", f"Local, subset ({m['stability']['n']})"),
                 ("stability", f"Whole-repo rerun, subset ({m['stability']['n']})")]
    lines = ["| Metric | " + " | ".join(n for _, n in cols) + " |", "|---|" + "---|" * len(cols)]
    spec = [("True candidates kept", lambda d: f"{d['kept_true']}/{d['n_true']}"),
            ("False/unclear candidates rejected", lambda d: f"{d['rejected_false']}/{d['n_false_or_unclear']}"),
            ("Precision (kept that are true)", lambda d: f"{fmt(d['precision'])} ({d['kept_true']}/{d['kept']})"),
            ("Verdict accuracy", lambda d: fmt(d["accuracy"])),
            ("Citation hits gold file:line (gradable)", lambda d: f"{d['cite_correct']}/{d['gradable_for_citation']}"),
            ("Right verdict + gold citation", lambda d: f"{d['verdict_and_cite_correct']}/{d['gradable_for_citation']}"),
            ("Citation verified (quote matches source)", lambda d: f"{d['cite_verified']}/{d['n']}"),
            ("Cross-file cases: right verdict", lambda d: f"{d['cross_file_verdict_right']}/{d['cross_file_cases']}"),
            ("Cross-file cases: right verdict + citation", lambda d: f"{d['cross_file_verdict_and_cite_right']}/{d['cross_file_cases']}"),
            ("Evidence outside local context: right verdict", lambda d: f"{d['outside_local_verdict_right']}/{d['gold_outside_local_cases']}"),
            ("Evidence outside local context: right verdict + citation",
             lambda d: f"{d['outside_local_verdict_and_cite_right']}/{d['gold_outside_local_cases']}")]
    for name, fn in spec:
        lines.append(f"| {name} | " + " | ".join(fn(m[c]) for c, _ in cols) + " |")
    tok = {"whole": f"{tokens['whole_final_call_per_repo']:,} (11 calls; {tokens['whole']:,} as spent incl. a cattrs re-send)",
           "local": f"{tokens['local']:,} (56 calls; {tokens['local_as_spent']:,} as spent incl. 1 re-send)"}
    if m["stability"]["n"]:
        tok |= {"whole_on_stability_subset": "—", "local_on_stability_subset": "—",
                "stability": f"{tokens['stability']:,}"}
    lines.append("| Beam tokens | " + " | ".join(tok[c] for c, _ in cols) + " |")
    (OUT / "table.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(json.dumps({"disagreements": [(d["key"], d["label"], d["whole"], d["local"]) for d in disagree], "stability": agree}, indent=1))


if __name__ == "__main__":
    main()
