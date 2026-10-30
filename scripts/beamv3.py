"""Beam v3 on the 12 real repos: (a) reuse the hybrid triage output, (b) one whole-repo docs-focused pass
(doc files audited against all code, the recall "focused slice 1" design), (c) 32k chunked passes over
non-test Python files only, aimed at docstring drift. Also: one fresh repeat of the hybrid triage on
httpx, click and cattrs (cache bypassed) to measure run-to-run verdict stability.

All live calls are sequential under the shared ollama lock, back off on 429 (hybrid_triage.post), stop
on any quota/4xx error, and go into results_live/beamv3/beam_usage_ledger.json. Before every call the
worst case (prompt estimate + max_tokens) is checked against --cap (default 8,000,000).

  python scripts/beamv3.py plan                 # token estimates, no calls
  python scripts/beamv3.py docs   [--repos ...]
  python scripts/beamv3.py py     [--repos ...]
  python scripts/beamv3.py repeat [--repos httpx,click,cattrs]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import hybrid_triage as ht  # noqa: E402
from repoatlas.client import _StructuredModelResponse, _extract_message_content  # noqa: E402
from repoatlas.config import load_ollama_api_key  # noqa: E402
from repoatlas.models import DocDriftFinding, RepoPack  # noqa: E402
from repoatlas.recall import build_docdrift_prompt  # noqa: E402
from repoatlas.prompts import SYSTEM_PROMPT  # noqa: E402
from repoatlas.verifier import verify_findings  # noqa: E402

OUT = ROOT / "results_live/beamv3"
# every v3 call (including the triage repeats and repros) is booked in this ledger
ht.LEDGER = OUT / "beam_usage_ledger.json"
CACHE = ROOT / ".cache/repoatlas/beamv3_responses"
REPOS = ht.REPOS
CALIB = 1.20            # real/cl100k (baselines used 1.20; recall measured 1.187)
DOCS_MAX_TOKENS = 32000
PY_MAX_TOKENS = 12000
PY_CHUNK = 32000
DOC_EXT = (".md", ".rst", ".txt")
SKIP_DOC = ("changelog", "changes", "history", "release", "news", "authors", "license", "requirements", "notice")


def load(repo: str) -> tuple[dict, RepoPack]:
    trace = json.loads((ROOT / f"results_live/traces/{repo}-400000.json").read_text())
    return trace, RepoPack.model_validate(trace["pack"])


def doc_files(pack: RepoPack) -> list[str]:
    return [f.path for f in pack.files if f.path.endswith(DOC_EXT) and not any(s in f.path.lower().rsplit("/", 1)[-1] for s in SKIP_DOC)]


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (path.startswith(("tests/", "test/", "testing/")) or "/tests/" in path or "/test/" in path
            or name.startswith("test_") or name == "conftest.py")


def py_files(pack: RepoPack) -> list:
    return [f for f in pack.files if f.path.endswith((".py", ".pyi")) and not is_test(f.path)]


def docs_suffix(paths: list[str]) -> str:
    listing = "\n".join(f"- {p}" for p in paths)
    return (
        "\n\nFOCUSED AUDIT (read this before answering). The packed repository above is complete. Audit ONLY the "
        "documentation files listed below (prose docs: README, guides, API reference pages). Read every listed file "
        "line by line and check each concrete claim - parameter and argument names, defaults, signatures, return "
        "values, exceptions raised, import paths, class/function/attribute names, CLI flags, env vars, config keys, "
        "HTTP status codes, and code examples - against the code ANYWHERE in the pack. Report every contradiction "
        "you can cite; there is no cap. Each finding's doc_citation must be in one of these files and its "
        "code_citation must be the code line that contradicts it. Skip changelog/history entries (they describe the "
        "past) and anything you cannot quote exactly.\n"
        f"Documentation files to audit ({len(paths)}):\n{listing}\n"
    )


PY_SUFFIX = (
    "\n\nFOCUSED AUDIT (read this before answering). This chunk contains only Python source files. Treat docstrings, "
    "comments and help/error strings as the documentation, and audit them against the code in this chunk: "
    ":param:/Args: names that are not real parameters (or are misspelled), wrong or stale defaults, '(optional)' on "
    "required parameters, wrong Returns/Raises, types, renamed or removed functions/classes/attributes, and code examples "
    "in docstrings that would not run against the current signatures. Report every contradiction you can cite: "
    "doc_citation is the docstring/comment line, code_citation is the code line that contradicts it (they may be in "
    "the same file). Skip style nits and anything you cannot quote exactly.\n"
)


def py_chunks(pack: RepoPack) -> list[dict]:
    from baseline_chunked_beam import build_chunks
    sub = pack.model_copy(update={"files": py_files(pack)})
    return build_chunks(sub, PY_CHUNK)


def est_tokens(text: str) -> int:
    from repoatlas.packer import _encode_tokens  # type: ignore
    return int(_encode_tokens(text) * CALIB) + 300


def _cap_check(est_prompt: int, max_tokens: int, cap: int, label: str) -> None:
    used = ht._ledger()["total_tokens"]
    if used + est_prompt + max_tokens > cap:
        raise SystemExit(f"STOP budget: {label}: used {used} + prompt~{est_prompt} + max_tokens {max_tokens} > cap {cap}")


def call(kind: str, label: str, user: str, max_tokens: int, est_prompt: int, cap: int, api_key: str) -> dict:
    schema = _StructuredModelResponse.model_json_schema()
    payload = {"model": ht.MODEL, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
               "response_format": {"type": "json_schema", "json_schema": {"name": "repoatlas_analysis", "schema": schema, "strict": True}},
               "max_tokens": max_tokens, "reasoning_effort": "medium"}
    key = hashlib.sha256(json.dumps([ht.BASE_URL, payload], sort_keys=True).encode()).hexdigest()
    CACHE.mkdir(parents=True, exist_ok=True)
    cfile = CACHE / f"{key}.json"
    if cfile.exists():
        body = json.loads(cfile.read_text())
        return {"body": body, "cached": True}
    _cap_check(est_prompt, max_tokens, cap, label)
    try:
        body, latency = ht.post(payload, api_key)
    except RuntimeError as exc:
        raise SystemExit(f"STOP {label}: {exc}") from exc
    cfile.write_text(json.dumps({**body, "_latency": latency}))
    u = body.get("usage") or {}
    led = ht._ledger_add(kind, label, int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)))
    print(f"  {label}: prompt={u.get('prompt_tokens')} completion={u.get('completion_tokens')} est_prompt={est_prompt} "
          f"finish={(body.get('choices') or [{}])[0].get('finish_reason')} {latency:.0f}s ledger={led['total_tokens']}", flush=True)
    return {"body": body, "cached": False}


def findings_from(body: dict, pack: RepoPack) -> tuple[list[dict], str | None]:
    content = _extract_message_content(body)
    data, err = ht.parse(content)
    if data is None:
        return [], f"parse: {err}; content_len={len(content)}"
    out, objs = [], []
    for f in data.get("findings") or []:
        try:
            objs.append(DocDriftFinding.model_validate(f))
            out.append(dict(f))
        except Exception as exc:  # noqa: BLE001
            out.append({**f, "invalid": str(exc)[:200]})
    res = iter(verify_findings(objs, pack))
    for f in out:
        if "invalid" not in f:
            f["fully_verified"] = next(res).fully_verified
    return out, None


def usage(body: dict) -> dict:
    u = body.get("usage") or {}
    return {"prompt_tokens": int(u.get("prompt_tokens", 0)), "completion_tokens": int(u.get("completion_tokens", 0)),
            "finish_reason": (body.get("choices") or [{}])[0].get("finish_reason")}


def run_docs(repos, cap, api_key) -> None:
    (OUT / "docs").mkdir(parents=True, exist_ok=True)
    for repo in repos:
        trace, pack = load(repo)
        paths = doc_files(pack)
        user = build_docdrift_prompt(pack.pack_text) + docs_suffix(paths)
        est = int(trace["summary"]["input_tokens"]) + est_tokens(docs_suffix(paths)) + 200
        print(f"[docs {repo}] doc files={len(paths)} est_prompt={est}", flush=True)
        r = call("docs", repo, user, DOCS_MAX_TOKENS, est, cap, api_key)
        fs, err = findings_from(r["body"], pack)
        rec = {"repo": repo, "ref": pack.ref, "doc_files": paths, "cached": r["cached"], **usage(r["body"]), "error": err, "findings": fs}
        (OUT / "docs" / f"{repo}.json").write_text(json.dumps(rec, indent=2))
        print(f"  -> {len(fs)} findings ({sum(1 for f in fs if f.get('fully_verified'))} verified) err={err}", flush=True)


def run_py(repos, cap, api_key) -> None:
    (OUT / "py32k").mkdir(parents=True, exist_ok=True)
    for repo in repos:
        trace, pack = load(repo)
        chunks = py_chunks(pack)
        rec_path = OUT / "py32k" / f"{repo}.json"
        rec = json.loads(rec_path.read_text()) if rec_path.exists() else {"repo": repo, "ref": pack.ref, "chunks": {}}
        print(f"[py {repo}] chunks={len(chunks)}", flush=True)
        for ch in chunks:
            label = f"{repo}#{ch['index']}"
            user = build_docdrift_prompt(ch["pack"].pack_text) + PY_SUFFIX
            est = int(ch["pack"].total_tokens * CALIB) + 900
            r = call("py32k", label, user, PY_MAX_TOKENS, est, cap, api_key)
            fs, err = findings_from(r["body"], pack)  # verify against the full pack
            rec["chunks"][str(ch["index"])] = {"paths": ch["paths"], "cached": r["cached"], **usage(r["body"]), "error": err, "findings": fs}
            rec_path.write_text(json.dumps(rec, indent=2))
            print(f"  -> {label}: {len(fs)} findings err={err}", flush=True)


def run_repeat(repos, cap, api_key) -> None:
    """Fresh repeat of the hybrid triage: identical prompt to the scored run, cache bypassed."""
    (OUT / "repeat").mkdir(parents=True, exist_ok=True)
    ht.CACHE = ROOT / ".cache/repoatlas/beamv3_triage_repeat"
    for repo in repos:
        orig = json.loads((ROOT / f"results_live/hybrid/triage/{repo}.json").read_text())
        attempt = int(orig.get("attempt", 1))
        trace, _ = load(repo)
        used = ht._ledger()["total_tokens"]
        est = int(trace["summary"]["input_tokens"]) + 3000
        if used + est + ht.MAX_TOKENS > cap:
            raise SystemExit(f"STOP budget: repeat {repo}: {used}+{est}+{ht.MAX_TOKENS} > {cap}")
        try:
            res = ht.triage_repo(repo, cap, api_key, False, attempt=attempt)
        except RuntimeError as exc:
            raise SystemExit(f"STOP repeat {repo}: {exc}") from exc
        (OUT / "repeat" / f"{repo}.json").write_text(json.dumps(res, indent=2))
        print(f"  -> repeat {repo}: verdicts={len(res.get('verdicts') or [])} adds={len(res.get('additional_findings') or [])} "
              f"err={res.get('error')} ledger={ht._ledger()['total_tokens']}", flush=True)


def plan() -> None:
    tot = {"docs": 0, "py": 0, "repeat": 0}
    for repo in REPOS:
        trace, pack = load(repo)
        d = int(trace["summary"]["input_tokens"]) + est_tokens(docs_suffix(doc_files(pack)))
        chunks = py_chunks(pack)
        p = sum(int(c["pack"].total_tokens * CALIB) + 900 for c in chunks)
        rp = int(trace["summary"]["input_tokens"]) + 3000 if repo in ("httpx", "click", "cattrs") else 0
        tot["docs"] += d; tot["py"] += p; tot["repeat"] += rp
        print(f"{repo:18s} docs_prompt~{d:>8,} docfiles={len(doc_files(pack)):3d} py_chunks={len(chunks):2d} py_prompt~{p:>8,} repeat~{rp:>8,}")
    print({k: f"{v:,}" for k, v in tot.items()}, "prompt total", f"{sum(tot.values()):,}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "docs", "py", "repeat"])
    ap.add_argument("--repos", default="")
    ap.add_argument("--cap", type=int, default=8_000_000)
    a = ap.parse_args()
    if a.cmd == "plan":
        return plan()
    api_key = load_ollama_api_key()
    repos = [r for r in a.repos.split(",") if r] or (["httpx", "click", "cattrs"] if a.cmd == "repeat" else REPOS)
    {"docs": run_docs, "py": run_py, "repeat": run_repeat}[a.cmd](repos, a.cap, api_key)


if __name__ == "__main__":
    main()
