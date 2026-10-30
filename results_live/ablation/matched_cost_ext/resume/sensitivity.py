"""Sensitivity checks (NOT pre-registered; descriptive only). Reuses scripts/ext_score.py functions unchanged."""
import json, sys, copy
sys.path.insert(0, "/workspace/ablation/matched_cost_ext/scripts")
import ext_score as S
from pathlib import Path
R = Path("/workspace/ablation/matched_cost_ext/resume/first_attempt")
er, _ = S.ext_rows(); orr = S.orig_rows()
def prim(rows):
    cross=[r for r in S.grad(rows) if r["cross_file"]]
    return S.paired(cross, S.vc)
out = {"as_scored": prim(orr+er)}
# (a) no nonce re-sends: first attempts of the 3 parse failures
na = copy.deepcopy(er)
w1 = json.loads((R/"planted1-structlog.json").read_text())
for r in na:
    if r["unit"] == "planted1-structlog":
        r["whole"] = S.cond({v["candidate_id"]: v for v in w1["verdicts"]}.get(r["key"].split(":",1)[1]), r["gold"])
for key, f in (("planted1-jinja:P1-18","planted1-jinja__P1-18.json"),("real-structlog:S16","real-structlog__S16.json")):
    m = json.loads((R/f).read_text())
    for r in na:
        if r["key"] == key: r["matched"] = S.cond((m["verdicts"] or [None])[0], r["gold"])
out["no_resends_first_attempt_only"] = prim(orr+na)
# (b) as stopped by the timeout (drop the 3 items run after the stop: S16, S14, S15)
out["as_stopped_without_resumed_S14_S15_S16"] = prim(orr+[r for r in er if r["key"] not in ("real-structlog:S14","real-structlog:S15","real-structlog:S16")])
out["as_stopped_and_no_resends"] = prim(orr+[r for r in na if r["key"] not in ("real-structlog:S14","real-structlog:S15","real-structlog:S16")])
# (c) DD-1 matched (timed out, not resent): bound by counting it as matched-wrong / matched-right
dd = [r for r in er if r["key"]=="real-structlog:structlog-400000:DD-1"][0]
out["DD1"] = {"cross_file": dd["cross_file"], "whole_verdict": dd["whole"]["verdict"], "whole_right_and_cite": S.vc(dd,"whole")}
for lab, val in (("DD1_matched_counted_wrong", False), ("DD1_matched_counted_right", True)):
    p = prim(orr+[r for r in er if r is not dd])
    wo, mo = p["whole_only"], p["matched_only"]
    w = S.vc(dd,"whole")
    if w and not val: wo += 1
    if val and not w: mo += 1
    out[lab] = {"n": p["n"]+1, "whole_only": wo, "matched_only": mo, "exact_mcnemar_p": S.mcnemar(wo, mo)}
print(json.dumps(out, indent=1))
