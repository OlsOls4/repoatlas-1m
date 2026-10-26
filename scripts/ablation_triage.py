"""Long-context ablation for DocDrift v2 triage: does whole-repo context help Beam judge drift candidates?

Conditions (same 56 candidates, same prompt template as scripts/hybrid_triage.py):
  local   : one call per candidate; the "packed repository" holds ONLY the candidate's doc file plus any code
            file whose path is named in the candidate text (claim or code hint). Same SYSTEM, same user template,
            same schema, max_tokens and reasoning_effort as the hybrid run. Line numbers are the same snapshot.
  whole   : the existing hybrid verdicts (results_live/hybrid/triage/<repo>.json), not rerun.
  stability: optional exact rerun of the whole-repo hybrid payload for a few repos (bypasses the hybrid cache).

Safety: sequential, shared ollama.lock, own ledger with a hard cap, 402/quota/4xx stop, 429 backoff (via hybrid post()).
The API key is read from a file and only placed in the Authorization header.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(sys.argv[sys.argv.index("--repo-root") + 1]) if "--repo-root" in sys.argv else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import hybrid_triage as H  # noqa: E402
from repoatlas.client import _extract_message_content  # noqa: E402
from repoatlas.models import Citation, RepoPack  # noqa: E402
from repoatlas.verifier import _build_file_lookup, verify_citation  # noqa: E402

OUT = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else REPO_ROOT / "results_live/ablation"
LEDGER = OUT / "beam_usage_ledger.json"
JUDGED = ["starlette", "httpx", "click", "nox", "arrow", "cattrs", "marshmallow", "attrs", "jinja", "werkzeug",
          "pydantic-settings"]  # structlog's hybrid triage failed to parse, so its 6 candidates were never judged


def ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "entries": []}


def ledger_add(kind: str, label: str, p: int, c: int) -> dict:
    led = ledger()
    led["calls"] += 1
    led["prompt_tokens"] += p
    led["completion_tokens"] += c
    led["total_tokens"] += p + c
    led["entries"].append({"kind": kind, "label": label, "prompt": p, "completion": c, "at": datetime.now(UTC).isoformat()})
    LEDGER.write_text(json.dumps(led, indent=2))
    return led


def sub_pack(pack: RepoPack, keep: list[str]) -> RepoPack:
    text = pack.pack_text
    head = text[: text.index("FILES_BEGIN\n") + len("FILES_BEGIN\n")]
    parts = []
    for f in pack.files:
        if f.path in keep:
            a = text.index(f"--- FILE: {f.path} ---\n")
            endm = f"--- END FILE: {f.path} ---\n"
            b = text.index(endm, a) + len(endm)
            parts.append(text[a:b])
    data = pack.model_dump()
    data["files"] = [f for f in data["files"] if f["path"] in keep]
    data["pack_text"] = head + "".join(parts) + "FILES_END\n"
    data["total_tokens"] = sum(f.get("token_count", 0) for f in data["files"])
    return RepoPack.model_validate(data)


def local_files(c: dict, pack: RepoPack) -> list[str]:
    txt = c["claim"] + " " + c["code_hint"]
    named = {c["doc_path"]} | {f.path for f in pack.files if f.path in txt}
    return [f.path for f in pack.files if f.path in named]


def payload_for(user: str) -> dict:
    return {"model": H.MODEL, "messages": [{"role": "system", "content": H.SYSTEM}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "docdrift_triage", "schema": H.SCHEMA, "strict": True}},
            "max_tokens": H.MAX_TOKENS, "reasoning_effort": "medium"}


def call(kind: str, label: str, payload: dict, est: int, cap: int, api_key: str | None, raw_file: Path, nonce: str = "") -> dict | None:
    key = hashlib.sha256(json.dumps([H.BASE_URL, payload, nonce], sort_keys=True).encode()).hexdigest()
    if raw_file.exists():
        rec = json.loads(raw_file.read_text())
        if rec.get("payload_sha256") == key and rec.get("body"):
            return rec
    led = ledger()
    if led["total_tokens"] + est > cap:
        raise RuntimeError(f"CAP: ledger {led['total_tokens']} + est {est} > cap {cap}")
    if api_key is None:
        return None
    body, latency = H.post(payload, api_key)
    u = body.get("usage") or {}
    ledger_add(kind, label, int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)))
    rec = {"label": label, "payload_sha256": key, "latency_seconds": latency, "body": body,
           "at": datetime.now(UTC).isoformat()}
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(json.dumps(rec, indent=2))
    return rec


def judge(rec: dict, cands: list[dict], full_pack: RepoPack) -> dict:
    body = rec["body"]
    u = body.get("usage") or {}
    res = {"prompt_tokens": int(u.get("prompt_tokens", 0)), "completion_tokens": int(u.get("completion_tokens", 0)),
           "finish_reason": (body.get("choices") or [{}])[0].get("finish_reason"), "latency_seconds": rec.get("latency_seconds"),
           "error": None}
    data, err = H.parse(_extract_message_content(body))
    if data is None:
        res["error"] = f"parse: {err}"
        res["verdicts"] = []
        return res
    lookup = _build_file_lookup(full_pack)
    by_id = {c["candidate_id"]: c for c in cands}
    out = []
    for v in data.get("verdicts") or []:
        cc = v.get("code_citation") or {}
        try:
            cv = verify_citation(Citation(path=cc.get("path", ""), start_line=max(1, int(cc.get("start_line", 1))),
                                          end_line=max(1, int(cc.get("end_line", 1))), quote=cc.get("quote", "")), lookup)
            ver = {"verified": cv.verified, "reason": cv.reason}
        except Exception as exc:  # noqa: BLE001
            ver = {"verified": False, "reason": f"invalid citation: {exc}"[:200]}
        out.append({**v, "code_citation_verification": ver, "source_id": by_id.get(v.get("candidate_id"), {}).get("source_id")})
    res["verdicts"] = out
    res["additional_findings_count"] = len(data.get("additional_findings") or [])
    res["missing_verdicts"] = sorted(set(by_id) - {v.get("candidate_id") for v in out})
    return res


def load_repo(repo: str) -> tuple[RepoPack, list[dict]]:
    trace = json.loads((H.TRACE_DIR / f"{repo}-400000.json").read_text())
    pack = RepoPack.model_validate(trace["pack"])
    cands = H.load_candidates(repo, pack, trace)
    hyb = json.loads((H.OUT / "triage" / f"{repo}.json").read_text())
    assert [c["source_id"] for c in cands] == [c["source_id"] for c in hyb["candidates"]], repo
    return pack, cands


def run_local(repos: list[str], cap: int, api_key: str | None, only: set[str] | None = None, nonce: str = "") -> None:
    """only/nonce: re-send selected candidates (e.g. after a JSON parse failure) without touching the first raw response."""
    for repo in repos:
        pack, cands = load_repo(repo)
        for c in cands:
            if only and f"{repo}:{c['candidate_id']}" not in only:
                continue
            keep = local_files(c, pack)
            sp = sub_pack(pack, keep)
            user = H.build_user_prompt(sp, [c])
            est = len(user) // 3 + H.EST_OUTPUT
            label = f"{repo}:{c['candidate_id']}:{c['source_id']}"
            raw = OUT / "raw/local" / (f"{repo}__{c['candidate_id']}" + (f"__{nonce}" if nonce else "") + ".json")
            rec = call("local", label + (f":{nonce}" if nonce else ""), payload_for(user), est, cap, api_key, raw, nonce=nonce)
            if rec is None:
                print(f"[dry] {label} files={keep} est={est}", flush=True)
                continue
            rec.setdefault("local_files", keep)
            res = judge(rec, [c], pack)
            res.update(repo=repo, candidate=c, local_files=keep, prompt_chars=len(user))
            if nonce:
                prev = json.loads((OUT / "local" / f"{repo}__{c['candidate_id']}.json").read_text())
                res["resend"] = {"nonce": nonce, "first_attempt": {k: prev.get(k) for k in
                                 ("prompt_tokens", "completion_tokens", "finish_reason", "error")}}
            (OUT / "local").mkdir(parents=True, exist_ok=True)
            (OUT / "local" / f"{repo}__{c['candidate_id']}.json").write_text(json.dumps(res, indent=2))
            v = (res["verdicts"] or [{}])[0]
            print(f"[local] {label} files={len(keep)} p={res['prompt_tokens']} c={res['completion_tokens']} "
                  f"verdict={v.get('verdict')} err={res['error']} ledger={ledger()['total_tokens']}", flush=True)


def run_stability(repos: list[str], cap: int, api_key: str | None) -> None:
    for repo in repos:
        pack, cands = load_repo(repo)
        user = H.build_user_prompt(pack, cands)
        payload = payload_for(user)
        est = len(user) // 3 + H.EST_OUTPUT
        raw = OUT / "raw/stability" / f"{repo}.json"
        rec = call("stability", repo, payload, est, cap, api_key, raw, nonce="stability-rerun-1")
        if rec is None:
            print(f"[dry] stability {repo} est={est}", flush=True)
            continue
        res = judge(rec, cands, pack)
        res.update(repo=repo, candidates=cands)
        (OUT / "stability").mkdir(parents=True, exist_ok=True)
        (OUT / "stability" / f"{repo}.json").write_text(json.dumps(res, indent=2))
        print(f"[stability] {repo} p={res['prompt_tokens']} c={res['completion_tokens']} verdicts={len(res['verdicts'])} "
              f"err={res['error']} ledger={ledger()['total_tokens']}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["local", "stability"], required=True)
    ap.add_argument("--repos", default=",".join(JUDGED))
    ap.add_argument("--cap", type=int, default=4_500_000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--repo-root")
    ap.add_argument("--out")
    ap.add_argument("--only", help="comma list of repo:candidate_id to re-send (local mode)")
    ap.add_argument("--nonce", default="")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    key = None if a.dry_run else Path("/home/box/.secrets/ollama_api_key").read_text().strip()
    try:
        if a.mode == "local":
            run_local(a.repos.split(","), a.cap, key, set(a.only.split(",")) if a.only else None, a.nonce)
        else:
            run_stability(a.repos.split(","), a.cap, key)
    except RuntimeError as exc:
        print(f"STOPPING: {str(exc)[:400]}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
