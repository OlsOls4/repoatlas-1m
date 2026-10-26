"""Score the Beam v3 experiment against the EXISTING labelled set. Makes no Beam calls.

  (a) docs-focused whole-context pass   results_live/beamv3/docs/<repo>.json
  (b) Python-docstring 32k chunks       results_live/beamv3/py32k/<repo>.json
  (c) triage stability repeat           results_live/beamv3/repeat/{httpx,click,cattrs}.json
  repro of the new (post-dedupe) items  results_live/beamv3/repros/repros.json

Labels: scripts/_beamv3_labels.py. Unlabelled findings never count as true. Writes
results_live/beamv3/results.json and results_live/beamv3/beamv3.md.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "results_live/beamv3"

from beamv3_merge import REPOS, _doc, hybrid_items, merge_distinct, v3_findings  # noqa: E402
from _beamv3_labels import AI_CHECK, AI_REVIEWER, C128_NEW, C32_NEW, RESOLVE  # noqa: E402

NEAR = 3


# ---------------------------------------------------------------- reference (existing labels)
def build_ref() -> list[dict]:
    from _chunked_verdicts import CV
    import hybrid_score as hs
    ref = []
    for it in hybrid_items():
        ref.append(dict(repo=it["repo"], path=it["doc_path"], line=it["doc_line"], end=it["doc_line"],
                        verdict=it["verdict"], drift_id=it.get("drift_id") or "", src=f"hybrid:{it['id']}"))
    for size in (32, 128):
        for p in sorted((ROOT / f"results_live/baselines/chunked-{size}k").glob("*.json")):
            d = json.loads(p.read_text()); repo = d.get("repo") or p.stem
            for i, m in enumerate(d.get("findings") or []):
                f = m.get("finding", m); dc = f.get("doc_citation") or {}
                l = int(dc.get("start_line", 0) or 0); e = int(dc.get("end_line", 0) or l)
                v, lab, _ = CV[(size, repo, i)]
                did = ""
                if v == "true":
                    did = lab if lab.startswith("T") else (C32_NEW if size == 32 else C128_NEW).get(f"{repo}:{i}", "?")
                ref.append(dict(repo=repo, path=dc.get("path", ""), line=l, end=e, verdict=v, drift_id=did, src=f"c{size}:{repo}:{i}"))
    for i, fl in enumerate(hs.sym_flags()):
        v, did = hs.sym_label(i)
        ref.append(dict(repo=fl["repo"], path=fl["path"], line=int(fl["line"]), end=int(fl["line"]), verdict=v,
                        drift_id=did, src=f"sym:S{i}"))
    for f in json.loads((ROOT / "results_live/index.json").read_text())["findings"]:
        dc = f.get("doc_citation") or {}
        l = int(dc.get("start_line", 0) or 0); e = int(dc.get("end_line", 0) or l)
        ref.append(dict(repo=f["case_name"].rsplit("-", 1)[0], path=dc.get("path", ""), line=l, end=e,
                        verdict=f["hand_verdict"], drift_id="", src=f"index:{f['finding_key']}"))
    return ref


def match(ref, repo, path, line):
    return [r for r in ref if r["repo"] == repo and r["path"] == path and r["line"] - NEAR <= line <= max(r["end"], r["line"]) + NEAR]


def label(ref, x) -> dict:
    if x["id"] in RESOLVE:
        v, d, s = RESOLVE[x["id"]]; by = "existing labels (manual pick among +-3 matches)"
    elif (m := match(ref, x["repo"], x["doc_path"], x["doc_line"])):
        labs = {(r["verdict"], r["drift_id"]) for r in m if not (r["src"].startswith("index") and r["verdict"] == "true")}
        labs = labs or {(r["verdict"], r["drift_id"]) for r in m}
        assert len(labs) == 1, (x["id"], m)
        v, d = labs.pop(); s = ", ".join(r["src"] for r in m); by = "existing labels"
    elif x["id"] in AI_CHECK:
        v, d, s = AI_CHECK[x["id"]]; by = AI_REVIEWER
    else:
        v, d, s, by = "unlabelled", "", "", ""
    return {"label": v, "drift_id": d, "label_evidence": s, "label_by": by}


def wilson(k, n, z=1.96):
    if n == 0:
        return [0.0, 0.0]
    p = k / n; den = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / den, 3), round((c + h) / den, 3)]


def main() -> int:
    h = json.loads((ROOT / "results_live/hybrid/hybrid.json").read_text())
    hrow = next(r for r in h["rows"] if r["method"].startswith("Hybrid ("))
    srow = next(r for r in h["rows"] if "strict" in r["method"])
    universe = set(h["universe"]); hyb_ids = set(hrow["distinct_true_ids"])
    missed = sorted(universe - hyb_ids)
    ledger = json.loads((OUT / "beam_usage_ledger.json").read_text())
    kinds = {}
    for c in ledger["entries"]:
        k = kinds.setdefault(c["kind"], {"calls": 0, "prompt": 0, "completion": 0})
        k["calls"] += 1; k["prompt"] += c["prompt"]; k["completion"] += c["completion"]
    for k in kinds.values():
        k["total"] = k["prompt"] + k["completion"]
    tok = {k: v["total"] for k, v in kinds.items()}
    total_tokens = sum(tok.values())

    ref = build_ref()
    F = v3_findings()
    for x in F:
        x.update(label(ref, x))
    new, dups = merge_distinct(hybrid_items(), F)
    new_ids = {x["id"] for x in new}
    for x in F:
        x["new_vs_hybrid"] = x["id"] in new_ids
    repros = json.loads((OUT / "repros/repros.json").read_text())
    for x in F:
        r = repros.get(x["id"])
        x["repro_status"] = r and r["status"]; x["strict_confirmed"] = bool(r and r["strict_confirmed"])

    # sensitivity: also accept the interrupted run's own (AI, unreviewed) labels for the remaining unlabelled ones
    from _beamv3_verdicts import V as PRIOR
    for x in F:
        p = PRIOR.get(x["id"])
        x["prior_run_label"] = p[0] if p else None
        x["prior_run_drift_id"] = p[1] if p else None

    def known(xs):
        return {x["drift_id"] for x in xs if x["label"] == "true" and x["drift_id"] in universe}

    def ai_new(xs):
        return {x["drift_id"] for x in xs if x["label"] == "true" and x["drift_id"].startswith("N3:")}

    def stats(name, xs, tokens, base_known=frozenset(), base_tokens=0, prior=False):
        c = Counter(x["label"] for x in xs); n = len(xs)
        t = sum(1 for x in xs if x["label"] == "true")
        labelled = c["true"] + c["false"] + c["unclear"]
        kn = known(xs) | set(base_known); nw = ai_new(xs)
        row = dict(mode=name, findings=n, true=t, false=c["false"], unclear=c["unclear"], unlabelled=c["unlabelled"],
                   ai_checked=sum(1 for x in xs if x["label_by"] == AI_REVIEWER),
                   precision_lower_bound=round(t / n, 3) if n else None,
                   precision_among_labelled=round(t / labelled, 3) if labelled else None,
                   distinct_of_45=len(kn), extra_of_45_vs_hybrid=sorted(kn - hyb_ids),
                   distinct_new_ai_verified=sorted(nw), tokens=tokens + base_tokens)
        dt = len(kn) + len(nw)
        row["tokens_per_distinct_true"] = round(row["tokens"] / dt) if dt else None
        extra = len(kn - hyb_ids) + len(nw)
        row["marginal_tokens_per_extra_drift"] = round(tokens / extra) if (base_tokens and extra) else None
        if prior:
            pt = [x for x in xs if x["label"] == "true" or (x["label"] == "unlabelled" and x["prior_run_label"] == "true")]
            row["prior_run_true"] = len(pt)
            row["prior_run_precision"] = round(len(pt) / n, 3) if n else None
            row["prior_run_distinct_new"] = len({(x["drift_id"] if x["label"] == "true" else x["prior_run_drift_id"]) or "" for x in pt} - universe - {""})
        return row

    docs = [x for x in F if x["pass"] == "docs"]; py = [x for x in F if x["pass"] == "py32k"]
    nd = [x for x in new if x["pass"] == "docs"]; npy = [x for x in new if x["pass"] == "py32k"]
    rows = [
        dict(mode="Hybrid (existing, for reference)", findings=hrow["findings"], true=hrow["true_findings"],
             precision_lower_bound=hrow["precision"], distinct_of_45=len(hyb_ids), tokens=hrow["beam_tokens"],
             tokens_per_distinct_true=round(hrow["beam_tokens"] / len(hyb_ids))),
        dict(mode="Hybrid + repro strict (existing)", findings=srow["findings"], true=srow["true_findings"],
             precision_lower_bound=srow["precision"], distinct_of_45=srow["distinct_true"], tokens=srow["beam_tokens"]),
        stats("(a) docs-focused pass alone", docs, tok["docs"], prior=True),
        stats("(b) py32k docstring chunks alone", py, tok["py32k"], prior=True),
        stats("Hybrid + (a): new items only", nd, tok["docs"], hyb_ids, hrow["beam_tokens"]),
        stats("Hybrid + (b): new items only", npy, tok["py32k"], hyb_ids, hrow["beam_tokens"]),
        stats("Hybrid + (a) + (b): new items only", new, tok["docs"] + tok["py32k"], hyb_ids, hrow["beam_tokens"], prior=True),
        stats("Hybrid + v3 new items strict-confirmed by repro", [x for x in new if x["strict_confirmed"]],
              tok["docs"] + tok["py32k"] + tok["repro"], hyb_ids, hrow["beam_tokens"]),
    ]
    # AI-check sample rate -> rough estimate of true rate among the still-unlabelled
    for r, xs in ((rows[2], docs), (rows[3], py)):
        s = [x for x in xs if x["label_by"] == AI_REVIEWER]; k = sum(x["label"] == "true" for x in s)
        r["ai_sample_true"] = f"{k}/{len(s)}"; r["ai_sample_true_wilson95"] = wilson(k, len(s))
        u = r["unlabelled"]; p = k / len(s)
        r["precision_estimate_using_sample_rate"] = round((r["true"] + u * p) / r["findings"], 3)

    # agreement of AI check with the interrupted run's own labels (true vs not-true)
    agree = [(x["id"], x["label"], x["prior_run_label"]) for x in F if x["label_by"] == AI_REVIEWER]
    agree_tv = sum((a == "true") == (b == "true") for _, a, b in agree)
    agree_exact = sum(a == b for _, a, b in agree)

    # recovery of hybrid's 11 misses
    rec = {}
    for d in missed:
        hit = [x["id"] for x in F if x["drift_id"] == d and x["label"] == "true"]
        rec[d] = {"recovered": bool(hit), "by": hit}

    # stability
    stab = {}
    for repo in ("httpx", "click", "cattrs"):
        a = json.loads((ROOT / f"results_live/hybrid/triage/{repo}.json").read_text())
        b = json.loads((OUT / f"repeat/{repo}.json").read_text())
        va = {v["candidate_id"]: v for v in a["verdicts"]}; vb = {v["candidate_id"]: v for v in b["verdicts"]}
        both = sorted(set(va) & set(vb))
        flips = [dict(candidate=c, source_id=va[c].get("source_id"), original=va[c]["verdict"], repeat=vb[c]["verdict"])
                 for c in both if va[c]["verdict"] != vb[c]["verdict"]]
        def adds(t):
            out = []
            for f in t.get("additional_findings") or []:
                p, l = _doc(f); out.append({"path": p, "line": l, **label(ref, {"id": "", "repo": repo, "doc_path": p, "doc_line": l})})
            return out
        aa, ab = adds(a), adds(b)
        same = [x for x in aa if any(x["path"] == y["path"] and abs(x["line"] - y["line"]) <= NEAR for y in ab)]
        union = len(aa) + len(ab) - len(same)
        stab[repo] = dict(candidates=len(both), agree=len(both) - len(flips), flips=flips,
                          additions_original=aa, additions_repeat=ab, additions_overlap=len(same),
                          additions_jaccard=f"{len(same)}/{union}" if union else "n/a",
                          tokens=b["prompt_tokens"] + b["completion_tokens"],
                          missing_verdicts=b.get("missing_verdicts"))
    tc = sum(s["candidates"] for s in stab.values()); ta = sum(s["agree"] for s in stab.values())

    res = dict(
        generated_by="scripts/beamv3_analyze.py (no Beam calls)",
        labels_note=("Ground truth = existing labelled set (45-true union in hybrid.json; hybrid/chunked/symbol/index "
                     "labels). Unlabelled findings are not counted as true. 15 findings labelled by " + AI_REVIEWER +
                     " (marked label_by). Unclear counts as not-true."),
        ledger=dict(calls=len(ledger["entries"]), total_tokens=total_tokens, by_kind=kinds),
        end_to_end_tokens_hybrid_plus_v3=hrow["beam_tokens"] + total_tokens,
        hybrid_missed_11=rec, recovered=sum(v["recovered"] for v in rec.values()),
        rows=rows,
        ai_check_vs_prior_run_labels=dict(n=len(agree), agree_true_vs_not=agree_tv, agree_exact=agree_exact, items=agree),
        stability=dict(repos=stab, candidates=tc, agree=ta, agreement=round(ta / tc, 3)),
        repro=dict(attempted=len(repros), status=Counter(r["status"] for r in repros.values()),
                   strict_confirmed=sum(r["strict_confirmed"] for r in repros.values()),
                   strict_by_label=Counter(x["label"] for x in new if x["strict_confirmed"]),
                   all_new_by_label=Counter(x["label"] for x in new)),
        raw_findings=len(F), new_after_dedupe=len(new), duplicates_of_hybrid_or_each_other=len(dups),
        findings=[{k: v for k, v in x.items() if k != "finding"} | {
            "code": "{}:{}".format((x["finding"].get("code_citation") or {}).get("path"), (x["finding"].get("code_citation") or {}).get("start_line")),
            "explanation": x["finding"].get("explanation", "")} for x in F],
    )
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=dict))
    (OUT / "beamv3.md").write_text(render(res))
    print(json.dumps({k: res[k] for k in ("ledger", "recovered", "rows", "stability", "repro", "ai_check_vs_prior_run_labels")}, indent=1, default=dict)[:20000])
    return 0


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.1%}" if v <= 1 else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, list):
        return str(len(v))
    return str(v)


def render(r) -> str:
    L = []
    w = L.append
    k = r["ledger"]["by_kind"]
    w("# Beam v3: docs-focused pass + Python-docstring 32k chunks + stability repeat\n")
    w("Scored by `scripts/beamv3_analyze.py` with no new Beam calls. " + r["labels_note"] + "\n")
    w("## Did it recover hybrid's 11 missed drifts?\n")
    w(f"**{r['recovered']} of 11 recovered.**\n")
    w("| drift | recovered | by |\n|---|---|---|")
    for d, v in r["hybrid_missed_11"].items():
        w(f"| {d} | {'yes' if v['recovered'] else 'no'} | {', '.join(v['by']) or '-'} |")
    w("\npy32k recovered the docstring drifts. The docs pass recovered only C:attrs-force_kw_only. The 3 that were still missed are all prose-doc drifts "
      "(httpx CONTRIBUTING sslcontext, marshmallow quotes_api example, attrs api.rst py2 reprs).\n")
    w("## Modes\n")
    w("Precision LB = labelled-true / all findings. Unlabelled findings count as not-true, so this is a lower bound. "
      "'Among labelled' is biased upward, because the labelled findings are the ones that hit known items. "
      "'Of 45' = distinct drifts from the existing 45-true union. 'New (AI)' = distinct new trues from the 15-item AI check.\n")
    w("| mode | findings | true | false | unclear | unlabelled | precision LB | among labelled | of 45 | extra of 45 vs hybrid | new (AI) | tokens | tokens / distinct true | marginal tokens / extra drift |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for x in r["rows"]:
        w("| " + " | ".join(fmt(x.get(c)) for c in ("mode", "findings", "true", "false", "unclear", "unlabelled", "precision_lower_bound",
                                                     "precision_among_labelled", "distinct_of_45", "extra_of_45_vs_hybrid",
                                                     "distinct_new_ai_verified", "tokens", "tokens_per_distinct_true",
                                                     "marginal_tokens_per_extra_drift")) + " |")
    w("\nIn the 'Hybrid + ...' rows, findings, true, false, unclear and unlabelled count only the v3 items that are new after dedupe against hybrid's 60 (repo, path, line ±3). "
      "Tokens are hybrid's plus the pass's. 'Marginal' = the pass's own tokens / extra distinct true drifts it added.\n")
    for x in r["rows"]:
        if "ai_sample_true" in x:
            w(f"- {x['mode']}: AI-check sample {x['ai_sample_true']} true (Wilson 95% {x['ai_sample_true_wilson95']}). "
              f"Applying that rate to the unlabelled gives estimated precision ≈ {x['precision_estimate_using_sample_rate']:.0%}. "
              f"This is rough because the sample is small.")
    for x in r["rows"]:
        if "prior_run_true" in x:
            w(f"- Sensitivity (NOT ground truth) for {x['mode']}: if the interrupted run's own unreviewed AI labels are accepted for the unlabelled, "
              f"true={x['prior_run_true']}, precision={x['prior_run_precision']:.0%}, distinct new drifts={x['prior_run_distinct_new']}.")
    a = r["ai_check_vs_prior_run_labels"]
    w(f"- The AI source check agreed with those prior-run labels on true/not-true for {a['agree_true_vs_not']}/{a['n']} "
      f"({a['agree_exact']}/{a['n']} exact; the 2 differences were false→unclear).\n")
    w("Extra true drifts beyond hybrid's 34:")
    last = r["rows"][6]
    w(f"- From the 45 union: {', '.join(last['extra_of_45_vs_hybrid'])}.")
    w(f"- New, AI-verified (not in any labelled set): {', '.join(last['distinct_new_ai_verified'])}.\n")
    s = r["stability"]
    w("## Stability repeat (triage re-run on httpx, click, cattrs)\n")
    w(f"Candidate verdict agreement: **{s['agree']}/{s['candidates']} ({s['agreement']:.1%})**.\n")
    w("| repo | candidates | agree | flips | additions orig / repeat | overlap (Jaccard) | repeat tokens |\n|---|---|---|---|---|---|---|")
    for repo, v in s["repos"].items():
        fl = "; ".join(f"{f['source_id']} {f['original']}→{f['repeat']}" for f in v["flips"]) or "-"
        w(f"| {repo} | {v['candidates']} | {v['agree']} | {fl} | {len(v['additions_original'])} / {len(v['additions_repeat'])} | {v['additions_jaccard']} | {v['tokens']:,} |")
    w("\nThe one flip is cattrs S25 (labelled true, T8), which the repeat rejected. The httpx additional findings only partly reproduce (3 of 7 distinct in both runs).\n")
    p = r["repro"]
    w("## Repro on the new items\n")
    w(f"{p['attempted']} attempted; status {dict(p['status'])}. Strict-confirmed (reproduced + interface_error): {p['strict_confirmed']}, "
      f"by label {dict(p['strict_by_label'])}. All new items by label: {dict(p['all_new_by_label'])}.\n")
    w("## Tokens (ledger)\n")
    w("| kind | calls | prompt | completion | total |\n|---|---|---|---|---|")
    for kk, v in k.items():
        w(f"| {kk} | {v['calls']} | {v['prompt']:,} | {v['completion']:,} | {v['total']:,} |")
    w(f"| **total** | {r['ledger']['calls']} | | | **{r['ledger']['total_tokens']:,}** |")
    w(f"\nDetection cost of the v3 passes = docs + py32k = {k['docs']['total'] + k['py32k']['total']:,}; repro adds {k['repro']['total']:,}; the stability repeat ({k['triage']['total']:,}) is measurement only. "
      f"Hybrid's own Beam tokens {r['rows'][0]['tokens']:,} + all v3 = {r['end_to_end_tokens_hybrid_plus_v3']:,}. This excludes the earlier sweep, which brings hybrid end-to-end to ~9.2M.\n")
    w("## What this means for the Space\n")
    w("This belongs in a Benchmark-tab section; the headline should stay as it is. Adding py32k to hybrid is the cheap win: "
      "about 1.7M tokens bring in 7 of the 11 missed labelled drifts plus 5 AI-verified new ones (~140k tokens per extra drift). "
      "But the v3 findings that are new after dedupe have a measured precision of only 18-53%; most are unlabelled. "
      "The docs-focused pass costs 4.5M tokens for 1 recovered labelled drift and 2 AI-verified new ones. Three prose drifts are still missed. "
      "No new number here is hand-labelled at the level of the existing 45-true union.\n")
    w("## Notes\n")
    w("- The AI check used /workspace/sweep/<repo> at the pack refs (starlette at /workspace/repro_src/starlette 8aa828c). The .cache/repoatlas/packs directory holds pack JSONs, not git clones.")
    w("- This supersedes the preliminary beamv3.json/csv written by the interrupted run. That file counted its own unreviewed labels as true and mislabelled docs:marshmallow:DD-4 as a new drift; it is the known T11.")
    w("- Per-finding labels, evidence and label_by are in results.json under `findings`.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
