"""Score the matched-cost condition against the same labels/gold as the ablation; compare with whole-repo and local."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO_ROOT = (
    Path(sys.argv[sys.argv.index("--repo-root") + 1])
    if "--repo-root" in sys.argv
    else Path(__file__).resolve().parents[1]
)
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import ablation_score as S  # noqa: E402

MC = REPO_ROOT / "results_live" / "ablation" / "matched_cost"


def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def mcnemar(a_only: int, b_only: int) -> float:
    n = a_only + b_only
    if n == 0:
        return 1.0
    k = min(a_only, b_only)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return round(min(1.0, 2 * p), 4)


def main() -> None:
    rows, tokens = S.load()
    led = json.loads((MC / "beam_usage_ledger.json").read_text())
    mt = {"prompt": 0, "completion": 0, "items": 0}
    for r in rows:
        p = MC / "items" / f"{r['repo']}__{r['candidate_id']}.json"
        if not p.exists():
            continue
        it = json.loads(p.read_text())
        mt["prompt"] += it["prompt_tokens"]
        mt["completion"] += it["completion_tokens"]
        mt["items"] += 1
        v = (it.get("verdicts") or [None])[0]
        cc = (v or {}).get("code_citation")
        r["matched_files"] = it["context_files"]
        r["matched_file_tiers"] = it["file_tiers"]
        r["matched_prompt_tokens"] = it["prompt_tokens"]
        r["matched_error"] = it.get("error")
        r["gold_in_matched_context"] = bool(r["gold"]) and any(g[0] in it["context_files"] for g in r["gold"])
        r["matched"] = {"verdict": (v or {}).get("verdict"), "kept": (v or {}).get("verdict") == "true_drift", "citation": cc,
                        "cite_verified": bool(((v or {}).get("code_citation_verification") or {}).get("verified")),
                        "cite_correct": S.cite_hit(cc, r["gold"]), "reason": (v or {}).get("reason")}
    conds = ["whole", "local", "matched"]
    m = {c: S.metrics(rows, c) for c in conds}
    for c in conds:
        d = m[c]
        d["ci95"] = {
            "accuracy": wilson(round(d["accuracy"] * d["n"]), d["n"]),
            "cite_correct": wilson(d["cite_correct"], d["gradable_for_citation"]),
            "cross_file_verdict_and_cite_right": wilson(d["cross_file_verdict_and_cite_right"], d["cross_file_cases"]),
            "outside_local_verdict_and_cite_right": wilson(d["outside_local_verdict_and_cite_right"], d["gold_outside_local_cases"]),
        }
        rs = [r for r in rows if c in r]
        d["accuracy_count"] = sum(1 for r in rs if r[c]["kept"] == r["truth"])
        gr = [r for r in rs if r["gold"] and r["cross_file"] is not None]
        cross = [r for r in gr if r["cross_file"]]
        d["cross_file_cite_correct"] = sum(1 for r in cross if r[c]["cite_correct"])
        # citation points outside the candidate's local files (doc file + named files)
        d["citation_outside_local_files"] = sum(1 for r in rs if (r[c]["citation"] or {}).get("path") and
                                                (r[c]["citation"] or {}).get("path") not in r["local_files"])
        d["citation_outside_doc_file"] = sum(1 for r in rs if (r[c]["citation"] or {}).get("path") and
                                             (r[c]["citation"] or {}).get("path") != r["key"] and
                                             (r[c]["citation"] or {}).get("path") != (r["local_files"] or [None])[0])
    rs = [r for r in rows if "matched" in r]
    ok = lambda r, c: r[c]["kept"] == r["truth"]  # noqa: E731
    vc = lambda r, c: ok(r, c) and r[c]["cite_correct"]  # noqa: E731
    gr = [r for r in rs if r["gold"] and r["cross_file"] is not None]
    cross = [r for r in gr if r["cross_file"]]
    outside = [r for r in gr if r["gold_outside_local"]]
    def paired(items, f, a="whole", b="matched"):
        ao = sum(1 for r in items if f(r, a) and not f(r, b))
        bo = sum(1 for r in items if f(r, b) and not f(r, a))
        return {"n": len(items), f"{a}_only": ao, f"{b}_only": bo, "exact_mcnemar_p": mcnemar(ao, bo)}
    comp = {
        "accuracy_whole_vs_matched": paired(rs, ok),
        "cross_file_verdict_and_cite_whole_vs_matched": paired(cross, vc),
        "outside_local_verdict_and_cite_whole_vs_matched": paired(outside, vc),
        "all_gradable_verdict_and_cite_whole_vs_matched": paired(gr, vc),
        "cross_file_verdict_and_cite_local_vs_matched": paired(cross, vc, "local", "matched"),
        "accuracy_local_vs_matched": paired(rs, ok, "local", "matched"),
    }
    coverage = {"outside_local_items": len(outside),
                "gold_file_retrieved_into_matched_context": sum(1 for r in outside if r["gold_in_matched_context"]),
                "cross_file_items_gold_in_matched_context": sum(1 for r in cross if r["gold_in_matched_context"]),
                "cross_file_items": len(cross)}
    disagree = [{"key": r["key"], "label": r["label"], "cross_file": r["cross_file"], "gold_outside_local": r["gold_outside_local"],
                 "whole": r["whole"]["verdict"], "matched": r["matched"]["verdict"], "local": r["local"]["verdict"],
                 "whole_cite_correct": r["whole"]["cite_correct"], "matched_cite_correct": r["matched"]["cite_correct"],
                 "matched_reason": r["matched"]["reason"]}
                for r in rs if r["matched"]["kept"] != r["whole"]["kept"] or r["matched"]["cite_correct"] != r["whole"]["cite_correct"]]
    tok = {"whole": tokens["whole_final_call_per_repo"], "local": tokens["local"],
           "matched": mt["prompt"] + mt["completion"], "matched_prompt": mt["prompt"], "matched_completion": mt["completion"],
           "matched_items": mt["items"], "matched_ledger_as_spent": led["total_tokens"], "matched_ledger_calls": led["calls"]}
    res = {"metrics": m, "paired_comparisons": comp, "retrieval_coverage": coverage, "tokens": tok, "disagreements_with_whole": disagree,
           "rows": [{k: v for k, v in r.items() if k != "stability"} for r in rows],
           "notes": ["labels from an AI reviewer against pinned source; unclear = not-true",
                     "whole and local are the ablation's existing results (not rerun); matched is new",
                     "citation correct = path match and line overlap with gold +/-3",
                     "95% intervals are Wilson score intervals; paired tests are exact two-sided McNemar (binomial on discordant pairs)"]}
    (MC / "results.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({k: res[k] for k in ("paired_comparisons", "retrieval_coverage", "tokens")}, indent=1))
    for c in conds:
        d = m[c]
        print(c, {k: d[k] for k in ("n", "accuracy_count", "accuracy", "precision", "kept_true", "kept", "cite_correct", "gradable_for_citation",
                                    "verdict_and_cite_correct", "cross_file_verdict_right", "cross_file_verdict_and_cite_right", "cross_file_cite_correct",
                                    "outside_local_verdict_right", "outside_local_verdict_and_cite_right", "cite_verified",
                                    "citation_outside_local_files", "missing_verdict")}, d["ci95"])


if __name__ == "__main__":
    main()
