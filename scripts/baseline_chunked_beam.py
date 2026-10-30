"""Chunked Beam baseline for DocDrift.

Takes the exact pack sent in the whole-repo 400k run (results_live/traces/<repo>-400000.json), splits it into
~N-token chunks in the same file order (whole files where possible, oversized files split at line boundaries
with their original line numbers), runs the unchanged RepoAtlas prompt on each chunk, merges and dedupes the
findings, and runs the unchanged citation verifier against the full pack.

Safety: requests are sequential; retries are disabled (REPOATLAS_MAX_RETRIES=1) so a 429 is never resent;
any 402/429/quota error stops the run; a usage ledger stops the run before cumulative new usage passes the cap.
The API key is read from a file into the environment and never printed or written out.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("REPOATLAS_MAX_RETRIES", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import json
import time
from datetime import UTC, datetime

from repoatlas.client import OpenAICompatibleAnalysisClient, _StructuredModelResponse, _cache_key
from repoatlas.config import RepoAtlasConfig, load_ollama_api_key
from repoatlas.models import RepoPack
from repoatlas.packer import FILTER_SIGNATURE, PACK_FORMAT_VERSION, _encode_tokens
from repoatlas.prompts import SYSTEM_PROMPT, build_analysis_user_prompt
from repoatlas.verifier import verify_findings

from baseline_common import match_true_drifts

TRACE_DIR = Path("results_live/traces")
OUT_ROOT = Path("results_live/baselines")
LEDGER = OUT_ROOT / "beam_usage_ledger.json"
CALIBRATION = 1.20  # observed real/cl100k ratio on these packs (sweep: 3.97M real / ~3.3M est)
PROMPT_OVERHEAD_EST = 700  # system prompt + instructions + pack header, cl100k estimate
EST_OUTPUT_PER_CALL = 6000
STOP_MARKERS = ("HTTP 402", "HTTP 429", "quota", "Quota", "rate limit", "Rate limit", "insufficient", "payment")


def _file_block(path: str, lines: list[str], first_line: int, total_lines: int) -> str:
    numbered = "\n".join(f"{first_line + i}|{line}" for i, line in enumerate(lines))
    if first_line == 1 and len(lines) == total_lines:
        return f"--- FILE: {path} ---\n{numbered}\n--- END FILE: {path} ---\n"
    last = first_line + len(lines) - 1
    return f"--- FILE: {path} (lines {first_line}-{last} of {total_lines}) ---\n{numbered}\n--- END FILE: {path} ---\n"


def build_chunks(pack: RepoPack, chunk_real_tokens: int) -> list[dict]:
    budget = int(chunk_real_tokens / CALIBRATION) - PROMPT_OVERHEAD_EST
    header = (
        f"# REPOATLAS PACK FORMAT {PACK_FORMAT_VERSION}\nREPO_URL: {pack.repo_url}\nREF: {pack.ref}\n"
        f"FILTER_SIGNATURE: {FILTER_SIGNATURE}\nLINE_FORMAT: <line>|<text>\nFILES_BEGIN\n"
    )
    pieces: list[tuple[str, str, int]] = []  # (path, block, tokens)
    for f in pack.files:
        block = _file_block(f.path, f.lines, 1, len(f.lines))
        tok = _encode_tokens(block)
        if tok <= budget:
            pieces.append((f.path, block, tok))
            continue
        # split oversized file at line boundaries, keeping original numbering
        start = 0
        while start < len(f.lines):
            lo, hi = start + 1, len(f.lines)
            best = start + 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if _encode_tokens(_file_block(f.path, f.lines[start:mid], start + 1, len(f.lines))) <= budget:
                    best, lo = mid, mid + 1
                else:
                    hi = mid - 1
            block = _file_block(f.path, f.lines[start:best], start + 1, len(f.lines))
            pieces.append((f.path, block, _encode_tokens(block)))
            start = best
    chunks: list[dict] = []
    cur: list[tuple[str, str, int]] = []
    cur_tok = 0
    for piece in pieces:
        if cur and cur_tok + piece[2] > budget:
            chunks.append({"pieces": cur})
            cur, cur_tok = [], 0
        cur.append(piece)
        cur_tok += piece[2]
    if cur:
        chunks.append({"pieces": cur})
    out = []
    for i, c in enumerate(chunks):
        text = header + "".join(p[1] for p in c["pieces"]) + "FILES_END\n"
        out.append({
            "index": i,
            "paths": [p[0] for p in c["pieces"]],
            "pack": RepoPack(repo_url=pack.repo_url, ref=pack.ref, prefix_hash="chunk", total_tokens=_encode_tokens(text),
                             token_limit=chunk_real_tokens, truncated=pack.truncated, packed_at=pack.packed_at, files=[],
                             skipped_paths=[], pack_text=text),
        })
    return out


def _load_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "entries": []}


def _save_ledger(ledger: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, indent=2))


def _dedupe(findings: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for f in findings:
        d, c = f["finding"]["doc_citation"], f["finding"]["code_citation"]
        dup = False
        for k in kept:
            kd, kc = k["finding"]["doc_citation"], k["finding"]["code_citation"]
            if (kd["path"] == d["path"] and abs(kd["start_line"] - d["start_line"]) <= 3
                    and kc["path"] == c["path"] and abs(kc["start_line"] - c["start_line"]) <= 3):
                dup = True
                k.setdefault("duplicates", []).append({"chunk": f["chunk"], "finding_id": f["finding"]["finding_id"]})
                break
        if not dup:
            kept.append(f)
    return kept


def run_repo(repo: str, chunk_size: int, cap: int, dry_run: bool) -> dict:
    trace = json.loads((TRACE_DIR / f"{repo}-400000.json").read_text())
    full_pack = RepoPack.model_validate(trace["pack"])
    chunks = build_chunks(full_pack, chunk_size)
    est_prompt = sum(int(c["pack"].total_tokens * CALIBRATION) + 600 for c in chunks)
    est_total = est_prompt + EST_OUTPUT_PER_CALL * len(chunks)
    ledger = _load_ledger()
    print(f"[{repo} @ {chunk_size}] chunks={len(chunks)} est_prompt={est_prompt} est_total={est_total} "
          f"ledger_total={ledger['total_tokens']}", flush=True)
    result = {"repo": repo, "chunk_size": chunk_size, "ref": full_pack.ref, "full_pack_tokens_est": full_pack.total_tokens,
              "chunks_planned": len(chunks), "estimate_prompt_tokens": est_prompt, "estimate_total_tokens": est_total,
              "calls": [], "errors": [], "stopped": None}
    if dry_run:
        result["stopped"] = "dry-run"
        return result
    if ledger["total_tokens"] + est_total > cap:
        result["stopped"] = f"skipped: ledger {ledger['total_tokens']} + estimate {est_total} would pass cap {cap}"
        print(result["stopped"], flush=True)
        return result

    os.environ["OLLAMA_API_KEY"] = load_ollama_api_key()
    config = RepoAtlasConfig.from_environment(provider="ollama", token_limit=chunk_size)
    client = OpenAICompatibleAnalysisClient(config)
    schema = _StructuredModelResponse.model_json_schema()
    all_findings: list[dict] = []
    wall_start = time.perf_counter()
    for c in chunks:
        payload = {
            "model": config.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": build_analysis_user_prompt(c["pack"])}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "repoatlas_analysis", "schema": schema, "strict": True}},
            "max_tokens": config.max_tokens,
            "reasoning_effort": config.reasoning_effort,
        }
        key = _cache_key(config.base_url, config.model, payload)
        call_est = int(c["pack"].total_tokens * CALIBRATION) + 600 + EST_OUTPUT_PER_CALL
        if _load_ledger()["total_tokens"] + call_est > cap:
            result["stopped"] = f"pre-call cap check: next call (~{call_est}) would pass cap {cap}"
            print("  " + result["stopped"], flush=True)
            break
        cached = client._read_cached_response(key)
        call = {"chunk": c["index"], "paths": len(c["paths"]), "est_tokens": c["pack"].total_tokens, "cached": cached is not None}
        try:
            if cached is not None:
                resp, headers, latency = cached["response_payload"], cached.get("response_headers", {}), float(cached.get("latency_seconds", 0.0))
            else:
                t0 = time.perf_counter()
                resp, headers = client._post_with_retries(payload)
                latency = time.perf_counter() - t0
                client._write_cached_response(key, response_payload=resp, response_headers=headers, latency_seconds=latency)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)[:1500]
            call["error"] = msg
            result["calls"].append(call)
            result["errors"].append({"chunk": c["index"], "error": msg})
            print(f"  chunk {c['index']}: ERROR {msg[:300]}", flush=True)
            if any(m in msg for m in STOP_MARKERS):
                result["stopped"] = f"quota/rate error at chunk {c['index']}"
                break
            continue
        usage = resp.get("usage", {}) if isinstance(resp, dict) else {}
        call.update(prompt_tokens=int(usage.get("prompt_tokens", 0)), completion_tokens=int(usage.get("completion_tokens", 0)),
                    latency_seconds=latency, finish_reason=(resp.get("choices") or [{}])[0].get("finish_reason"))
        if not call["cached"]:
            ledger = _load_ledger()
            ledger["calls"] += 1
            ledger["prompt_tokens"] += call["prompt_tokens"]
            ledger["completion_tokens"] += call["completion_tokens"]
            ledger["total_tokens"] += call["prompt_tokens"] + call["completion_tokens"]
            ledger["entries"].append({"repo": repo, "chunk_size": chunk_size, "chunk": c["index"], "prompt": call["prompt_tokens"],
                                      "completion": call["completion_tokens"], "at": datetime.now(UTC).isoformat()})
            _save_ledger(ledger)
        try:
            output, _ = client._build_output_and_metrics(resp, headers, full_pack.repo_url, full_pack.ref, latency)
            call["findings"] = len(output.findings)
            for f in output.findings:
                all_findings.append({"chunk": c["index"], "finding": f.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001
            call["parse_error"] = str(exc)[:500]
            result["errors"].append({"chunk": c["index"], "parse_error": str(exc)[:500]})
        result["calls"].append(call)
        print(f"  chunk {c['index']}: prompt={call['prompt_tokens']} compl={call['completion_tokens']} "
              f"{latency:.1f}s findings={call.get('findings', 'ERR')} cached={call['cached']} ledger={ledger['total_tokens']}", flush=True)
        if ledger["total_tokens"] > cap:
            result["stopped"] = f"cap passed: ledger {ledger['total_tokens']} > {cap}"
            break
    result["wall_seconds"] = time.perf_counter() - wall_start
    result["raw_findings"] = len(all_findings)
    merged = _dedupe(all_findings)
    from repoatlas.models import DocDriftFinding
    objs = [DocDriftFinding.model_validate(m["finding"]) for m in merged]
    verification = verify_findings(objs, full_pack)
    for m, v in zip(merged, verification):
        f = m["finding"]
        cites = [(f["doc_citation"]["path"], f["doc_citation"]["start_line"], f["doc_citation"]["end_line"]),
                 (f["code_citation"]["path"], f["code_citation"]["start_line"], f["code_citation"]["end_line"])]
        text = " ".join([f["explanation"], f["doc_citation"]["quote"], f["code_citation"]["quote"], f["proposed_fix"]])
        m["verification"] = v.model_dump(mode="json")
        m["fully_verified"] = v.fully_verified
        m["true_drift_match"] = match_true_drifts(repo, cites, text)
    result["findings"] = merged
    result["prompt_tokens"] = sum(c.get("prompt_tokens", 0) for c in result["calls"])
    result["completion_tokens"] = sum(c.get("completion_tokens", 0) for c in result["calls"])
    result["calls_ok"] = sum(1 for c in result["calls"] if "prompt_tokens" in c)
    result["sum_call_latency_seconds"] = sum(c.get("latency_seconds", 0.0) for c in result["calls"])
    result["true_drifts_recovered"] = sorted({t for m in merged for t in m["true_drift_match"]})
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default="starlette,httpx,click,structlog,nox,arrow,cattrs,marshmallow,attrs")
    ap.add_argument("--chunk-size", type=int, default=32000)
    ap.add_argument("--cap", type=int, default=8_000_000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out_dir = OUT_ROOT / f"chunked-{args.chunk_size // 1000}k"
    out_dir.mkdir(parents=True, exist_ok=True)
    for repo in args.repos.split(","):
        res = run_repo(repo, args.chunk_size, args.cap, args.dry_run)
        if not args.dry_run:
            (out_dir / f"{repo}.json").write_text(json.dumps(res, indent=2))
            print(f"[{repo}] calls_ok={res.get('calls_ok')} prompt={res.get('prompt_tokens')} compl={res.get('completion_tokens')} "
                  f"findings={len(res.get('findings', []))} true={res.get('true_drifts_recovered')} stopped={res['stopped']}", flush=True)
        if res["stopped"] and res["stopped"] != "dry-run" and not res["stopped"].startswith("skipped"):
            print("STOPPING RUN:", res["stopped"], flush=True)
            break


if __name__ == "__main__":
    main()
