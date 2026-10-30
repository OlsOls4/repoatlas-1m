"""Run the three arms (whole / local / matched) on the extension items (design: ../design_ext.md).

Same SYSTEM, build_user_prompt, strict json_schema, max_tokens=32000, reasoning_effort=medium, model "beam" as the
original 56 (via ablation_triage.payload_for). Matched context = matched_cost.select() with the SAME constant prompt
budget (56,416 cl100k est). Whole = one call per unit (library pack x seed, or structlog real) with all of that unit's
candidates, exactly like the hybrid whole-repo triage. Local = one call per item, doc file + files named in claim/hint.
Stops on ANY non-200 response (no 429 backoff), any quota/billing wording, or the ledger cap.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

EXT = Path("/workspace/ablation/matched_cost_ext")
sys.argv += ["--repo-root", "/workspace/docdrift_main", "--out", str(EXT)]
sys.path.insert(0, "/workspace/docdrift_main")
sys.path.insert(0, "/workspace/ablation/matched_cost/scripts")
import matched_cost as M  # noqa: E402  (select(), CALIBRATION, PROMPT_BUDGET_EST)
A = M.A
import requests  # noqa: E402
from repoatlas.models import RepoPack  # noqa: E402

assert A.OUT == EXT, A.OUT
BILLING = re.compile(r"quota|billing|payment|credit|insufficient|subscription|upgrade your plan|rate.?limit", re.I)


def strict_post(payload: dict, api_key: str):
    t0 = time.perf_counter()
    with A.H._exclusive_lock(A.H.LOCK):
        try:
            r = requests.post(f"{A.H.BASE_URL}/chat/completions", json=payload, timeout=900,
                              headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        except requests.Timeout as exc:
            raise RuntimeError(f"TIMEOUT (not resent; may be billed): {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    if body.get("error") or (not body.get("choices") and BILLING.search(json.dumps(body)[:2000])):
        raise RuntimeError(f"error body: {json.dumps(body)[:300]}")
    return body, time.perf_counter() - t0


A.H.post = strict_post


def load_pack(unit: str) -> RepoPack:
    if unit == "real-structlog":
        return RepoPack.model_validate(json.loads(Path("/workspace/docdrift_main/results_live/traces/structlog-400000.json").read_text())["pack"])
    return RepoPack.model_validate_json((EXT / "packs" / f"{unit}.json").read_text())


def fname(key: str) -> str:
    return key.replace(":", "__").replace("/", "_")


def run(arms: list[str], units: list[str] | None, cap: int, api_key: str | None, only: set[str] | None, nonce: str) -> dict:
    items = json.loads((EXT / "items.json").read_text())["items"]
    est_total = {"whole": 0, "local": 0, "matched": 0}
    order = list(dict.fromkeys(i["unit"] for i in items))
    for unit in order:
        if units and unit not in units:
            continue
        pack = load_pack(unit)
        its = [i for i in items if i["unit"] == unit]
        cands = [i["candidate"] for i in its]
        sfx = f"__{nonce}" if nonce else ""
        if "whole" in arms and (not only or unit in only):
            user = A.H.build_user_prompt(pack, cands)
            est = int(M.est_tokens(A.H.SYSTEM + user) * M.CALIBRATION) + 15000
            est_total["whole"] += est
            rec = A.call("whole", f"{unit}{':' + nonce if nonce else ''}", A.payload_for(user), est, cap, api_key,
                         EXT / "raw" / "whole" / f"{unit}{sfx}.json", nonce=nonce)
            if rec is not None:
                res = A.judge(rec, cands, pack)
                res.update(unit=unit, candidates=cands)
                _save("whole", unit, res, nonce)
                print(f"[whole] {unit} n={len(cands)} p={res['prompt_tokens']} c={res['completion_tokens']} err={res['error']} "
                      f"missing={res.get('missing_verdicts')} ledger={A.ledger()['total_tokens']}", flush=True)
        for it in its:
            c = it["candidate"]
            for arm in ("local", "matched"):
                if arm not in arms or (only and it["key"] not in only):
                    continue
                if arm == "local":
                    keep, why = A.local_files(c, pack), {}
                    est_p = M.est_tokens(A.H.SYSTEM + A.H.build_user_prompt(A.sub_pack(pack, keep), [c]))
                else:
                    keep, why, est_p = M.select(pack, c)
                user = A.H.build_user_prompt(A.sub_pack(pack, keep), [c])
                est = int(est_p * M.CALIBRATION) + 15000
                est_total[arm] += est
                rec = A.call(arm, it["key"] + (f":{nonce}" if nonce else ""), A.payload_for(user), est, cap, api_key,
                             EXT / "raw" / arm / f"{fname(it['key'])}{sfx}.json", nonce=nonce)
                if rec is None:
                    continue
                res = A.judge(rec, [c], pack)
                res.update(key=it["key"], candidate=c, context_files=keep, file_tiers=why, local_files=A.local_files(c, pack),
                           est_prompt_tokens=est_p)
                _save(arm, fname(it["key"]), res, nonce)
                v = (res["verdicts"] or [{}])[0]
                print(f"[{arm}] {it['key']} files={len(keep)} p={res['prompt_tokens']} c={res['completion_tokens']} "
                      f"verdict={v.get('verdict')} err={res['error']} ledger={A.ledger()['total_tokens']}", flush=True)
    return est_total


def _save(arm: str, name: str, res: dict, nonce: str) -> None:
    d = EXT / "items" / arm
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    if nonce and p.exists():
        prev = json.loads(p.read_text())
        res["resend"] = {"nonce": nonce, "first_attempt": {k: prev.get(k) for k in ("prompt_tokens", "completion_tokens", "finish_reason", "error")}}
    p.write_text(json.dumps(res, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="whole,local,matched")
    ap.add_argument("--units")
    ap.add_argument("--cap", type=int, default=11_500_000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--nonce", default="")
    ap.add_argument("--repo-root")
    ap.add_argument("--out")
    a = ap.parse_args()
    key = None if a.dry_run else Path("/home/box/.secrets/ollama_api_key").read_text().strip()
    try:
        est = run(a.arms.split(","), a.units.split(",") if a.units else None, a.cap, key,
                  set(a.only.split(",")) if a.only else None, a.nonce)
        if a.dry_run:
            print("DRY-RUN estimates (API tokens incl. 15k output reserve):", est, "total", sum(est.values()))
    except RuntimeError as exc:
        print(f"STOPPING: {str(exc)[:400]}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
