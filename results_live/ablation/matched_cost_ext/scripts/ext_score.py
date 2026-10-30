"""Score the extension (design: ../design_ext.md): new-items-only and pooled (original 56 + new) analyses.

Primary (pre-registered): POOLED cross-file items, right verdict + gold citation, whole vs matched, exact two-sided
McNemar, alpha 0.05, reported whatever it shows. Everything else is secondary.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

EXT = Path("/workspace/ablation/matched_cost_ext")
MC = Path("/workspace/ablation/matched_cost")
SLACK = 3
ARMS = ("whole", "local", "matched")


def wilson(k, n, z=1.959964):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def mcnemar(a, b):
    n = a + b
    if not n:
        return 1.0
    return round(min(1.0, 2 * sum(math.comb(n, i) for i in range(min(a, b) + 1)) / 2 ** n), 4)


def cite_hit(cc, gold):
    if not cc or not gold:
        return False
    s, e = int(cc.get("start_line") or 0), int(cc.get("end_line") or cc.get("start_line") or 0)
    return any(cc.get("path") == p and s <= b + SLACK and e >= a - SLACK for p, a, b in gold)


def cond(v, gold):
    cc = (v or {}).get("code_citation")
    return {"verdict": (v or {}).get("verdict"), "kept": (v or {}).get("verdict") == "true_drift", "citation": cc,
            "cite_verified": bool(((v or {}).get("code_citation_verification") or {}).get("verified")),
            "cite_correct": cite_hit(cc, gold), "cite_file_correct": bool(cc) and cc.get("path") in {g[0] for g in gold},
            "reason": (v or {}).get("reason")}


def ext_rows():
    data = json.loads((EXT / "items.json").read_text())
    rows = []
    whole = {}
    for it in data["items"]:
        p = EXT / "items" / "whole" / f"{it['unit']}.json"
        if it["unit"] not in whole and p.exists():
            w = json.loads(p.read_text())
            whole[it["unit"]] = ({v["candidate_id"]: v for v in w["verdicts"]}, w)
    for it in data["items"]:
        c = it["candidate"]
        r = {"key": it["key"], "set": "ext", "stratum": it["stratum"], "unit": it["unit"], "label": it["label"],
             "truth": it["label"] == "true", "gold": it["gold"], "cross_file": it["cross_file"]}
        if it["unit"] in whole:
            r["whole"] = cond(whole[it["unit"]][0].get(c["candidate_id"]), it["gold"])
            r["whole_error"] = whole[it["unit"]][1].get("error")
        fn = it["key"].replace(":", "__").replace("/", "_")
        for arm in ("local", "matched"):
            p = EXT / "items" / arm / f"{fn}.json"
            if not p.exists():
                continue
            res = json.loads(p.read_text())
            r[arm] = cond((res["verdicts"] or [None])[0], it["gold"])
            r[f"{arm}_error"] = res.get("error")
            r[f"{arm}_prompt_tokens"] = res["prompt_tokens"]
            if arm == "local":
                r["local_files"] = res["context_files"]
            else:
                r["matched_files"] = res["context_files"]
                r["matched_file_tiers"] = res["file_tiers"]
                r["gold_in_matched_context"] = any(g[0] in res["context_files"] for g in it["gold"])
        r["gold_outside_local"] = "local_files" in r and not any(g[0] in r["local_files"] for g in it["gold"])
        rows.append(r)
    return rows, data


def orig_rows():
    out = []
    for r in json.loads((MC / "results.json").read_text())["rows"]:
        q = {"key": r["key"], "set": "orig", "stratum": "orig", "label": r["label"], "truth": r["truth"], "gold": r["gold"],
             "cross_file": r["cross_file"], "gold_outside_local": r["gold_outside_local"],
             "gold_in_matched_context": r.get("gold_in_matched_context"), "matched_error": r.get("matched_error")}
        for arm in ARMS:
            if arm in r:
                q[arm] = dict(r[arm], cite_file_correct=bool(r[arm]["citation"]) and (r[arm]["citation"] or {}).get("path") in {g[0] for g in r["gold"] or []})
        out.append(q)
    return out


ok = lambda r, a: r[a]["kept"] == r["truth"]  # noqa: E731
vc = lambda r, a: ok(r, a) and r[a]["cite_correct"]  # noqa: E731
vf = lambda r, a: ok(r, a) and r[a]["cite_file_correct"]  # noqa: E731


def paired(items, f, a="whole", b="matched"):
    items = [r for r in items if a in r and b in r]
    ao = sum(1 for r in items if f(r, a) and not f(r, b))
    bo = sum(1 for r in items if f(r, b) and not f(r, a))
    return {"n": len(items), f"{a}_right": sum(1 for r in items if f(r, a)), f"{b}_right": sum(1 for r in items if f(r, b)),
            f"{a}_only": ao, f"{b}_only": bo, "exact_mcnemar_p": mcnemar(ao, bo)}


def grad(rows):
    return [r for r in rows if r["gold"] and r["cross_file"] is not None]


def summary(rows):
    g = grad(rows)
    cross = [r for r in g if r["cross_file"]]
    outside = [r for r in g if r["gold_outside_local"]]
    per = {}
    for a in ARMS:
        rs = [r for r in rows if a in r]
        k = sum(1 for r in cross if a in r and vc(r, a))
        n = sum(1 for r in cross if a in r)
        acc = sum(1 for r in rs if ok(r, a))
        per[a] = {"n": len(rs), "accuracy": [acc, len(rs), wilson(acc, len(rs))],
                  "cross_file_verdict_and_cite": [k, n, wilson(k, n)],
                  "outside_local_verdict_and_cite": [sum(1 for r in outside if a in r and vc(r, a)), sum(1 for r in outside if a in r)],
                  "all_gradable_verdict_and_cite": [sum(1 for r in g if a in r and vc(r, a)), sum(1 for r in g if a in r)],
                  "missing_verdict": sum(1 for r in rs if r[a]["verdict"] is None)}
    return {"n_items": len(rows), "n_cross_file": len(cross), "n_outside_local": len(outside), "per_arm": per,
            "cross_file_verdict_and_cite_whole_vs_matched": paired(cross, vc),
            "outside_local_verdict_and_cite_whole_vs_matched": paired(outside, vc),
            "accuracy_whole_vs_matched": paired(rows, ok),
            "all_gradable_verdict_and_cite_whole_vs_matched": paired(g, vc),
            "cross_file_verdict_and_cite_local_vs_matched": paired(cross, vc, "local", "matched"),
            "cross_file_verdict_and_cite_whole_vs_local": paired(cross, vc, "whole", "local"),
            "lenient_cross_file_verdict_and_cite_file_whole_vs_matched": paired(cross, vf)}


def failure_modes(rows):
    cross = [r for r in grad(rows) if r["cross_file"] and "matched" in r and "whole" in r]
    def mode(r):
        if r["matched"]["verdict"] is None:
            return "matched_parse_failure_or_missing_verdict"
        if not r.get("gold_in_matched_context"):
            return "gold_file_not_retrieved"
        if not ok(r, "matched"):
            return "gold_retrieved_wrong_verdict"
        return "gold_retrieved_right_verdict_citation_misses_gold"
    disc = [r for r in cross if vc(r, "whole") and not vc(r, "matched")]
    allfail = [r for r in cross if not vc(r, "matched")]
    return {"whole_right_matched_wrong": dict(Counter(map(mode, disc))),
            "whole_right_matched_wrong_keys": {r["key"]: mode(r) for r in disc},
            "all_matched_failures_on_cross_file": dict(Counter(map(mode, allfail))),
            "cross_file_gold_retrieved_into_matched_context": [sum(1 for r in cross if r.get("gold_in_matched_context")), len(cross)]}


def tokens():
    led = json.loads((EXT / "beam_usage_ledger.json").read_text())
    by = Counter()
    calls = Counter()
    for e in led["entries"]:
        by[e["kind"]] += e["prompt"] + e["completion"]
        calls[e["kind"]] += 1
    return {"ledger_total": led["total_tokens"], "ledger_calls": led["calls"], "by_arm": dict(by), "calls_by_arm": dict(calls)}


def main():
    er, data = ext_rows()
    orr = orig_rows()
    pooled = orr + er
    res = {"primary": {"test": "POOLED cross-file right verdict + gold citation, whole vs matched, exact two-sided McNemar",
                       **summary(pooled)["cross_file_verdict_and_cite_whole_vs_matched"]},
           "pooled": summary(pooled), "new_only": summary(er),
           "strata": {"planted": summary([r for r in er if r["stratum"] == "planted"]),
                      "real_structlog": summary([r for r in er if r["stratum"] == "real"]),
                      "orig": summary(orr)},
           "failure_modes": {"pooled": failure_modes(pooled), "new_only": failure_modes(er), "orig": failure_modes(orr)},
           "tokens": tokens(), "excluded": data["excluded"],
           "errors": {a: [r["key"] for r in er if r.get(f"{a}_error")] for a in ARMS},
           "rows": er}
    (EXT / "results.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("primary", "failure_modes", "tokens", "errors")}, indent=1))
    for s in ("pooled", "new_only"):
        print(s, json.dumps(res[s]["per_arm"]), json.dumps({k: v for k, v in res[s].items() if k.endswith("matched") or k.endswith("local")}))


if __name__ == "__main__":
    main()
