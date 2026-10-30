"""DocDrift v2 hybrid, step 2: one whole-repo Beam triage call per repo.

Candidates are the 43 symbol-check flags (results_live/baselines/symbol_check_flags.json) and the whole-repo
Beam findings (results_live/traces/<repo>-400000.json) for the 12 symbol-check repos. Candidates get neutral
ids (C01..) and are sorted by doc location, so the model is not told which source produced them.
Each repo gets ONE call holding the same ~400k pack that the whole-repo run used. The model returns a verdict
per candidate, with a cited code location (checked by the RepoAtlas citation verifier) and a doc fix. It also
returns any extra drifts it finds, in the RepoAtlas findings format, and those are verified the same way.

Safety: calls are sequential and use the shared .cache/repoatlas/ollama.lock. On HTTP 429 the script backs off
60/120/240 s. A 402, quota message or other 4xx stops the run. A timeout is never resent. A ledger
(results_live/hybrid/beam_usage_ledger.json) stops a call before it could pass the cap. The API key is read
from a file and only ever goes in the Authorization header.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import requests  # noqa: E402

from repoatlas.client import _close_truncated_json, _exclusive_lock, _extract_message_content  # noqa: E402
from repoatlas.config import load_ollama_api_key  # noqa: E402
from repoatlas.models import Citation, DocDriftFinding, RepoPack  # noqa: E402
from repoatlas.verifier import _build_file_lookup, verify_citation, verify_findings  # noqa: E402

TRACE_DIR = ROOT / "results_live/traces"
SYMBOL_FLAGS = ROOT / "results_live/baselines/symbol_check_flags.json"
OUT = ROOT / "results_live/hybrid"
LEDGER = OUT / "beam_usage_ledger.json"
CACHE = ROOT / ".cache/repoatlas/hybrid_responses"
LOCK = ROOT / ".cache/repoatlas/ollama.lock"
REPOS = ["starlette", "httpx", "click", "structlog", "nox", "arrow", "cattrs", "marshmallow", "attrs",
         "jinja", "werkzeug", "pydantic-settings"]
BASE_URL = "https://ollama.com/v1"
MODEL = "beam"
MAX_TOKENS = 32000
EST_OUTPUT = 15000
STOP_MARKERS = ("402", "quota", "Quota", "insufficient", "payment", "Payment")

SYSTEM = (
    "You are RepoAtlas-1M, triaging documentation-drift reports against a whole software repository. "
    "Return strict JSON that matches the requested schema. Never invent citations. Quotes must be verbatim."
)

CIT = {"type": "object", "additionalProperties": False, "required": ["path", "start_line", "end_line", "quote"],
       "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"},
                      "quote": {"type": "string"}}}
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["verdicts", "additional_findings"],
    "properties": {
        "verdicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["candidate_id", "verdict", "reason", "code_citation", "suggested_doc_fix"],
            "properties": {"candidate_id": {"type": "string"},
                           "verdict": {"type": "string", "enum": ["true_drift", "false", "unclear"]},
                           "reason": {"type": "string"}, "code_citation": CIT, "suggested_doc_fix": {"type": "string"}}}},
        "additional_findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["finding_id", "drift_kind", "explanation", "doc_citation", "code_citation", "proposed_fix"],
            "properties": {"finding_id": {"type": "string"},
                           "drift_kind": {"type": "string", "enum": ["flag", "default", "signature", "env_var", "config_key", "other"]},
                           "explanation": {"type": "string"}, "doc_citation": CIT, "code_citation": CIT,
                           "proposed_fix": {"type": "string"}}}},
    },
}


def _line(lookup: dict[str, list[str]], path: str, n: int) -> str:
    lines = lookup.get(path.lstrip("./")) or []
    return lines[n - 1].strip() if 1 <= n <= len(lines) else ""


def load_candidates(repo: str, pack: RepoPack, trace: dict) -> list[dict]:
    lookup = _build_file_lookup(pack)
    cands: list[dict] = []
    flags = json.loads(SYMBOL_FLAGS.read_text())["flags"]
    for idx, f in enumerate(flags):
        if f["repo"] != repo:
            continue
        cands.append({"source": "symbol", "source_id": f"S{idx}", "doc_path": f["path"], "doc_line": f["line"],
                      "doc_end": f["line"], "doc_text": _line(lookup, f["path"], f["line"]),
                      "claim": f"{f['check']}: `{f['reference']}`: {f['detail']}", "code_hint": ""})
    for f in (trace.get("output") or {}).get("findings") or []:
        d, c = f["doc_citation"], f["code_citation"]
        cands.append({"source": "whole_repo", "source_id": f"{repo}-400000:{f['finding_id']}", "doc_path": d["path"],
                      "doc_line": d["start_line"], "doc_end": d["end_line"], "doc_text": d["quote"],
                      "claim": f["explanation"], "code_hint": f"{c['path']}:{c['start_line']}-{c['end_line']} {c['quote']!r}"})
    cands.sort(key=lambda x: (x["doc_path"], x["doc_line"], x["source_id"]))
    for i, c in enumerate(cands, 1):
        c["candidate_id"] = f"C{i:02d}"
    return cands


def candidate_block(cands: list[dict]) -> str:
    out = []
    for c in cands:
        s = f"- {c['candidate_id']}: docs {c['doc_path']}:{c['doc_line']}"
        if c["doc_end"] != c["doc_line"]:
            s += f"-{c['doc_end']}"
        s += f" | doc text: {c['doc_text'][:300]!r} | report: {c['claim'][:600]}"
        if c["code_hint"]:
            s += f" | code cited by the report: {c['code_hint'][:300]}"
        out.append(s)
    return "\n".join(out)


def build_user_prompt(pack: RepoPack, cands: list[dict]) -> str:
    block = candidate_block(cands)
    return (
        "Below is a list of candidate documentation-drift reports for this repository, then the packed repository.\n"
        "The reports come from automated tools and many are false positives: for example an example that uses "
        "another library's object, a user-defined name in an example, a name that does exist via re-export, "
        "subclassing or __getattr__, a deliberately historical note, or a misread of the docs.\n"
        "Task 1: for EVERY candidate, use the whole repository to decide:\n"
        "  true_drift = the documentation as written is wrong for this code (a user following it would hit an error "
        "or wrong behaviour, or a reference/name/parameter/default it states does not match the code);\n"
        "  false = the documentation is correct, or the report misreads it;\n"
        "  unclear = you cannot decide from the repository.\n"
        "  Give a one-line reason, the single code location you relied on (path, start_line, end_line and a "
        "verbatim quote from those lines), and a documentation-only suggested fix (empty string unless true_drift).\n"
        "Task 2: list any OTHER documentation drifts the candidates missed, especially cross-file ones (a doc in one "
        "file names an API, parameter, option, default, import path or error type defined in another file) and "
        "drifts stated in prose. Each needs a doc citation and a code citation with verbatim quotes. Do not repeat "
        "candidates. When unsure, omit.\n"
        "Rules: citations use the <line> numbers shown in the pack; quotes are copied without the '<line>|' prefix.\n"
        "Output ONLY one JSON object of this shape:\n"
        '{"verdicts": [{"candidate_id": "C01", "verdict": "true_drift|false|unclear", "reason": "...", '
        '"code_citation": {"path": "...", "start_line": 1, "end_line": 1, "quote": "..."}, "suggested_doc_fix": "..."}], '
        '"additional_findings": [{"finding_id": "AD-1", "drift_kind": "flag|default|signature|env_var|config_key|other", '
        '"explanation": "...", "doc_citation": {"path": "...", "start_line": 1, "end_line": 1, "quote": "..."}, '
        '"code_citation": {"path": "...", "start_line": 1, "end_line": 1, "quote": "..."}, "proposed_fix": "..."}]}\n\n'
        f"CANDIDATES ({len(cands)}):\n{block}\n\n"
        "Packed repository context follows:\n\n"
        f"{pack.pack_text}\n\n"
        f"END OF REPOSITORY. Reminder: return one verdict for each of these {len(cands)} candidates "
        f"({', '.join(c['candidate_id'] for c in cands)}) plus any additional findings, as one JSON object.\n"
    )


def _ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "entries": []}


def _ledger_add(kind: str, label: str, prompt: int, completion: int) -> dict:
    led = _ledger()
    led["calls"] += 1
    led["prompt_tokens"] += prompt
    led["completion_tokens"] += completion
    led["total_tokens"] += prompt + completion
    led["entries"].append({"kind": kind, "label": label, "prompt": prompt, "completion": completion,
                           "at": datetime.now(UTC).isoformat()})
    LEDGER.write_text(json.dumps(led, indent=2))
    return led


def post(payload: dict, api_key: str) -> tuple[dict, float]:
    backoffs = [60, 120, 240]
    for attempt in range(len(backoffs) + 1):
        t0 = time.perf_counter()
        with _exclusive_lock(LOCK):
            try:
                r = requests.post(f"{BASE_URL}/chat/completions", json=payload, timeout=900,
                                  headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
            except requests.Timeout as exc:
                raise RuntimeError(f"TIMEOUT (not resent; may be billed): {type(exc).__name__}") from exc
        latency = time.perf_counter() - t0
        if r.status_code == 200:
            return r.json(), latency
        text = f"HTTP {r.status_code}: {r.text[:400]}"
        if r.status_code == 429 and attempt < len(backoffs):
            print(f"  429, backing off {backoffs[attempt]}s", flush=True)
            time.sleep(backoffs[attempt])
            continue
        if r.status_code >= 500 and attempt < 1:
            time.sleep(30)
            continue
        raise RuntimeError(text)
    raise RuntimeError("retry loop exhausted")


def parse(content: str) -> tuple[dict | None, str | None]:
    start = content.find("{")
    if start < 0:
        return None, "no JSON object in content"
    text = content[start:]
    end = text.rfind("}")
    for candidate in (text[: end + 1] if end >= 0 else text, _close_truncated_json(text)):
        if not candidate:
            continue
        try:
            return json.loads(candidate), None
        except json.JSONDecodeError:
            continue
    return None, "unparseable JSON"


RETRY_NOTE = ("\n\nRetry note: a previous attempt returned no JSON. The message content must be ONLY the JSON object "
              "matching the schema, with no analysis, reasoning or prose before or after it.")


def triage_repo(repo: str, cap: int, api_key: str | None, dry_run: bool, attempt: int = 1) -> dict:
    trace = json.loads((TRACE_DIR / f"{repo}-400000.json").read_text())
    pack = RepoPack.model_validate(trace["pack"])
    cands = load_candidates(repo, pack, trace)
    user = build_user_prompt(pack, cands)
    est_prompt = int(trace["summary"]["input_tokens"]) + len(candidate_block(cands)) // 3 + 600
    est = est_prompt + EST_OUTPUT
    res: dict = {"repo": repo, "ref": pack.ref, "attempt": attempt, "candidates": cands, "estimate_tokens": est, "error": None}
    led = _ledger()
    print(f"[{repo}] candidates={len(cands)} est={est} ledger={led['total_tokens']}", flush=True)
    if dry_run:
        res["error"] = "dry-run"
        return res
    system = SYSTEM + (RETRY_NOTE if attempt > 1 else "")
    payload = {"model": MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "response_format": {"type": "json_schema", "json_schema": {"name": "docdrift_triage", "schema": SCHEMA, "strict": True}},
               "max_tokens": MAX_TOKENS, "reasoning_effort": "medium"}
    import hashlib
    key = hashlib.sha256(json.dumps([BASE_URL, payload], sort_keys=True).encode()).hexdigest()
    CACHE.mkdir(parents=True, exist_ok=True)
    cfile = CACHE / f"{key}.json"
    if cfile.exists():
        body = json.loads(cfile.read_text())
        latency = body.pop("_latency", 0.0)
        res["cached"] = True
    else:
        if led["total_tokens"] + est > cap:
            res["error"] = f"skipped: ledger {led['total_tokens']} + est {est} > cap {cap}"
            return res
        body, latency = post(payload, api_key)
        cfile.write_text(json.dumps({**body, "_latency": latency}))
        res["cached"] = False
        u = body.get("usage") or {}
        _ledger_add("triage", repo, int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)))
    u = body.get("usage") or {}
    res.update(prompt_tokens=int(u.get("prompt_tokens", 0)), completion_tokens=int(u.get("completion_tokens", 0)),
               latency_seconds=latency, finish_reason=(body.get("choices") or [{}])[0].get("finish_reason"))
    content = _extract_message_content(body)
    data, err = parse(content)
    if data is None:
        res["error"] = f"parse: {err}; content_len={len(content)}"
        return res
    lookup = _build_file_lookup(pack)
    by_id = {c["candidate_id"]: c for c in cands}
    verdicts = []
    for v in data.get("verdicts") or []:
        cid = v.get("candidate_id")
        cc = v.get("code_citation") or {}
        try:
            cv = verify_citation(Citation(path=cc.get("path", ""), start_line=max(1, int(cc.get("start_line", 1))),
                                          end_line=max(1, int(cc.get("end_line", 1))), quote=cc.get("quote", "")), lookup)
            ver = {"verified": cv.verified, "reason": cv.reason}
        except Exception as exc:  # noqa: BLE001
            ver = {"verified": False, "reason": f"invalid citation: {exc}"[:200]}
        verdicts.append({**v, "code_citation_verification": ver, "source_id": by_id.get(cid, {}).get("source_id")})
    res["verdicts"] = verdicts
    res["missing_verdicts"] = sorted(set(by_id) - {v.get("candidate_id") for v in verdicts})
    adds = []
    objs = []
    for a in data.get("additional_findings") or []:
        try:
            objs.append(DocDriftFinding.model_validate(a))
            adds.append(a)
        except Exception as exc:  # noqa: BLE001
            adds.append({**a, "invalid": str(exc)[:200]})
    vres = iter(verify_findings(objs, pack))
    for a in adds:
        if "invalid" not in a:
            a["fully_verified"] = next(vres).fully_verified
    res["additional_findings"] = adds
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default=",".join(REPOS))
    ap.add_argument("--cap", type=int, default=4_600_000, help="cap for triage calls (leaves room for repros)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--attempt", type=int, default=1, help=">1 adds a JSON-only retry note (new cache key); keeps earlier output")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    api_key = None
    if not args.dry_run:
        api_key = load_ollama_api_key()
    for repo in args.repos.split(","):
        out_file = OUT / "triage" / f"{repo}.json"
        try:
            if args.attempt > 1 and out_file.exists() and not args.dry_run:
                prev = out_file.parent / f"{repo}.attempt{args.attempt - 1}.json"
                if not prev.exists():
                    prev.write_text(out_file.read_text())
            res = triage_repo(repo, args.cap, api_key, args.dry_run, args.attempt)
        except RuntimeError as exc:
            msg = str(exc)
            print(f"[{repo}] ERROR {msg[:300]}", flush=True)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps({"repo": repo, "error": msg[:1000]}, indent=2))
            if any(m in msg for m in STOP_MARKERS) or "429" in msg or "TIMEOUT" in msg:
                print("STOPPING RUN", flush=True)
                break
            continue
        if args.dry_run:
            continue
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(res, indent=2))
        nt = sum(1 for v in res.get("verdicts", []) if v.get("verdict") == "true_drift")
        print(f"[{repo}] prompt={res.get('prompt_tokens')} compl={res.get('completion_tokens')} "
              f"lat={res.get('latency_seconds', 0):.0f}s finish={res.get('finish_reason')} verdicts={len(res.get('verdicts', []))} "
              f"true={nt} adds={len(res.get('additional_findings', []))} missing={res.get('missing_verdicts')} "
              f"err={res.get('error')} ledger={_ledger()['total_tokens']}", flush=True)


if __name__ == "__main__":
    main()
