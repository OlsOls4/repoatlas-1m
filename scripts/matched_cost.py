"""Matched-cost control for the long-context ablation (round-4 fix 11).

Condition "matched": one Beam call per candidate (same 56 candidates, same SYSTEM / build_user_prompt / strict schema /
max_tokens=32000 / reasoning_effort=medium as the hybrid and local runs). The packed context is the ablation's local
files PLUS deterministic retrieval, filled up to a fixed per-candidate prompt budget so that the total spend matches
the whole-repo condition (4,022,532 tokens / 56 candidates = 71,831 tokens per candidate).

Retrieval tiers (no model involved; ties broken by pack order):
  T0 local files (doc file + files named in the claim / code hint), exactly as in the local condition;
  T1 symbol/grep: files that DEFINE an identifier mentioned in the candidate (def/class/assignment at any indent);
  T2 import neighbourhood: in-repo modules imported by, or importing, any T0/T1 Python file;
  T3 BM25 top-k over the remaining files with the candidate's identifiers + words as the query.
Files are added greedily tier by tier; a file that would overflow the budget is skipped and the next one tried.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = (
    Path(sys.argv[sys.argv.index("--repo-root") + 1])
    if "--repo-root" in sys.argv
    else Path(__file__).resolve().parents[1]
)
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import ablation_triage as A  # noqa: E402  (shares H, ledger, call(), judge(), sub_pack(), local_files())
import tiktoken  # noqa: E402

OUTDIR = (
    Path(sys.argv[sys.argv.index("--out") + 1])
    if "--out" in sys.argv
    else REPO_ROOT / "results_live" / "ablation" / "matched_cost"
)
A.LEDGER = OUTDIR / "beam_usage_ledger.json"

ENC = tiktoken.get_encoding("cl100k_base")  # the packer's tokenizer
_BLOCK_CACHE: dict[tuple[str, str], int] = {}

WHOLE_TOTAL = 4_022_532
N_CANDIDATES = 56
PER_ITEM_TOTAL = WHOLE_TOTAL // N_CANDIDATES          # 71,831 API tokens (prompt + completion)
RESERVED_OUTPUT = 3_000                               # mean local completion was ~1.9k; round up
CALIBRATION = 1.22                                    # API prompt tokens / tiktoken estimate (RepoAtlas calibration)
PROMPT_BUDGET_EST = int((PER_ITEM_TOTAL - RESERVED_OUTPUT) / CALIBRATION)  # 56,416 estimated (tiktoken) tokens
STOP = {"the", "and", "for", "not", "with", "that", "this", "from", "are", "was", "but", "has", "have", "into", "its",
        "found", "documented", "param", "signature", "reference", "missing", "does", "exist", "def", "class", "none",
        "true", "false", "self", "return", "import", "docs", "doc", "code", "should", "would", "when", "which", "line"}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def identifiers(c: dict) -> list[str]:
    text = " ".join([c["claim"], c["doc_text"], c["code_hint"]])
    out: list[str] = []
    for tok in IDENT.findall(text):
        for part in [tok, tok.split(".")[-1]]:
            if len(part) >= 3 and part.lower() not in STOP and part not in out:
                out.append(part)
    return out


def file_text(pack, path: str) -> str:
    for f in pack.files:
        if f.path == path:
            return "\n".join(f.lines) if hasattr(f, "lines") else f.content
    return ""


def defining_files(pack, names: list[str]) -> list[str]:
    simple = [n for n in names if "." not in n]
    scores: Counter = Counter()
    for f in pack.files:
        txt = file_text(pack, f.path)
        for n in simple:
            if re.search(rf"^\s*(?:async\s+def|def|class)\s+{re.escape(n)}\b|^\s*{re.escape(n)}\s*(?::[^=\n]*)?=", txt, re.M):
                scores[f.path] += 1
    order = {f.path: i for i, f in enumerate(pack.files)}
    return sorted(scores, key=lambda p: (-scores[p], order[p]))


def module_of(path: str) -> str | None:
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    if parts[0] in ("src",):
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def import_neighbours(pack, seeds: list[str]) -> list[str]:
    mods = {module_of(f.path): f.path for f in pack.files if module_of(f.path)}
    def imports(path: str) -> set[str]:
        txt = file_text(pack, path)
        pkg = (module_of(path) or "").rsplit(".", 1)[0]
        found: set[str] = set()
        for m in re.finditer(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+([\w, ()*]+)|^\s*import\s+([\w.]+)", txt, re.M):
            if m.group(4):
                base = m.group(4)
            else:
                dots, name = m.group(1), m.group(2)
                if dots:
                    up = pkg.split(".")
                    up = up[: len(up) - (len(dots) - 1)] if len(dots) > 1 else up
                    base = ".".join([*up, name]) if name else ".".join(up)
                else:
                    base = name
                for sub in re.split(r"[,()\s]+", m.group(3)):
                    if sub and f"{base}.{sub}" in mods:
                        found.add(mods[f"{base}.{sub}"])
            if base in mods:
                found.add(mods[base])
        return found
    out: list[str] = []
    seedset = [s for s in seeds if s.endswith(".py")]
    for s in seedset:
        for p in sorted(imports(s)):
            if p not in out:
                out.append(p)
    for f in pack.files:
        if f.path.endswith(".py") and f.path not in out and any(s in imports(f.path) for s in seedset):
            out.append(f.path)
    return out


def bm25(pack, query: list[str]) -> list[str]:
    docs = {f.path: Counter(t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", file_text(pack, f.path))) for f in pack.files}
    n = len(docs)
    avg = sum(sum(c.values()) for c in docs.values()) / max(n, 1)
    q = [t.lower() for t in query]
    df = {t: sum(1 for c in docs.values() if t in c) for t in set(q)}
    def score(c: Counter) -> float:
        L = sum(c.values())
        s = 0.0
        for t in q:
            if c[t]:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * c[t] * 2.2 / (c[t] + 1.2 * (0.25 + 0.75 * L / avg))
        return s
    sc = {p: score(c) for p, c in docs.items()}
    return [p for p in sorted(sc, key=lambda p: -sc[p]) if sc[p] > 0]


def est_tokens(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


def block_tokens(pack, path: str) -> int:
    key = (pack.prefix_hash, path)
    if key not in _BLOCK_CACHE:
        t = pack.pack_text
        a = t.index(f"--- FILE: {path} ---\n")
        endm = f"--- END FILE: {path} ---\n"
        _BLOCK_CACHE[key] = est_tokens(t[a: t.index(endm, a) + len(endm)])
    return _BLOCK_CACHE[key]


def select(pack, c: dict) -> tuple[list[str], dict[str, str], int]:
    names = identifiers(c)
    tiers: list[tuple[str, list[str]]] = [("T0_local", A.local_files(c, pack))]
    tiers.append(("T1_symbol", defining_files(pack, names)))
    tiers.append(("T2_imports", import_neighbours(pack, tiers[0][1] + tiers[1][1])))
    words = names + [w for w in re.findall(r"[A-Za-z]{4,}", c["claim"] + " " + c["doc_text"]) if w.lower() not in STOP]
    tiers.append(("T3_bm25", bm25(pack, words)))
    chosen: list[str] = []
    why: dict[str, str] = {}
    base = est_tokens(A.H.SYSTEM + A.H.build_user_prompt(A.sub_pack(pack, []), [c]))
    est = base
    for tier, paths in tiers:
        for p in paths:
            if p in chosen:
                continue
            e = est + block_tokens(pack, p)
            if e <= PROMPT_BUDGET_EST or tier == "T0_local":
                chosen.append(p)
                est = e
                why[p] = tier
    ordered = [f.path for f in pack.files if f.path in chosen]
    exact = est_tokens(A.H.SYSTEM + A.H.build_user_prompt(A.sub_pack(pack, ordered), [c]))
    return ordered, why, exact


def run(repos: list[str], cap: int, api_key: str | None, only: set[str] | None, nonce: str) -> None:
    for repo in repos:
        pack, cands = A.load_repo(repo)
        for c in cands:
            if only and f"{repo}:{c['candidate_id']}" not in only:
                continue
            keep, why, est = select(pack, c)
            sp = A.sub_pack(pack, keep)
            user = A.H.build_user_prompt(sp, [c])
            label = f"{repo}:{c['candidate_id']}:{c['source_id']}"
            raw = OUTDIR / "raw" / (f"{repo}__{c['candidate_id']}" + (f"__{nonce}" if nonce else "") + ".json")
            rec = A.call("matched", label + (f":{nonce}" if nonce else ""), A.payload_for(user), int(est * CALIBRATION) + 15000, cap, api_key, raw, nonce=nonce)
            if rec is None:
                print(json.dumps({"label": label, "files": len(keep), "est": est, "tiers": Counter(why.values())}), flush=True)
                continue
            res = A.judge(rec, [c], pack)
            res.update(repo=repo, candidate=c, context_files=keep, file_tiers=why, local_files=A.local_files(c, pack),
                       prompt_chars=len(user), est_prompt_tokens=est)
            if nonce:
                prev = json.loads((OUTDIR / "items" / f"{repo}__{c['candidate_id']}.json").read_text())
                res["resend"] = {"nonce": nonce, "first_attempt": {k: prev.get(k) for k in ("prompt_tokens", "completion_tokens", "finish_reason", "error")}}
            (OUTDIR / "items").mkdir(parents=True, exist_ok=True)
            (OUTDIR / "items" / f"{repo}__{c['candidate_id']}.json").write_text(json.dumps(res, indent=2))
            v = (res["verdicts"] or [{}])[0]
            print(f"[matched] {label} files={len(keep)} p={res['prompt_tokens']} c={res['completion_tokens']} "
                  f"verdict={v.get('verdict')} err={res['error']} ledger={A.ledger()['total_tokens']}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default=",".join(A.JUDGED))
    ap.add_argument("--cap", type=int, default=4_600_000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--nonce", default="")
    ap.add_argument("--repo-root")
    ap.add_argument("--out")
    a = ap.parse_args()
    key_file = Path(os.environ["OLLAMA_API_KEY_FILE"]) if os.environ.get("OLLAMA_API_KEY_FILE") else None
    key = None if a.dry_run else (
        Path(key_file).read_text(encoding="utf-8").strip()
        if key_file
        else os.environ.get("OLLAMA_API_KEY", "") or None
    )
    if not a.dry_run and not key:
        raise SystemExit("OLLAMA_API_KEY or OLLAMA_API_KEY_FILE is required unless --dry-run")
    try:
        run(a.repos.split(","), a.cap, key, set(a.only.split(",")) if a.only else None, a.nonce)
    except RuntimeError as exc:
        print(f"STOPPING: {str(exc)[:400]}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
