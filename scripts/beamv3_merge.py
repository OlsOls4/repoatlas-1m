"""Beam v3 merge: hybrid items (a) + docs-focused pass (b) + Python-only 32k chunks (c), deduped by
(repo, doc path, doc line +-3). Writes results_live/beamv3/merged.json; labels come from _beamv3_verdicts.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "results_live/beamv3"
REPOS = ["starlette", "httpx", "click", "structlog", "nox", "arrow", "cattrs", "marshmallow", "attrs",
         "jinja", "werkzeug", "pydantic-settings"]
NEAR = 3


def _doc(f: dict) -> tuple[str, int]:
    d = f.get("doc_citation") or {}
    return d.get("path", ""), int(d.get("start_line", 0) or 0)


def hybrid_items() -> list[dict]:
    """The 60 scored hybrid items with a doc location each."""
    h = json.loads((ROOT / "results_live/hybrid/hybrid.json").read_text())
    row = next(r for r in h["rows"] if r["method"].startswith("Hybrid ("))
    flags = json.loads((ROOT / "results_live/baselines/symbol_check_flags.json").read_text())["flags"]
    traces = {r: json.loads((ROOT / f"results_live/traces/{r}-400000.json").read_text()) for r in REPOS}
    triage = {r: json.loads((ROOT / f"results_live/hybrid/triage/{r}.json").read_text()) for r in REPOS}
    out = []
    for it in row["items"]:
        repo, iid = it["repo"], it["id"]
        if iid.startswith("ADD-"):
            fid = iid[4:]
            f = next(a for a in triage[repo].get("additional_findings") or [] if a.get("finding_id") == fid)
            loc = _doc(f)
        elif iid.startswith("S") and iid[1:].isdigit():
            fl = flags[int(iid[1:])]
            loc = (fl["path"], int(fl["line"]))
        else:
            fid = iid.split(":", 1)[1]
            f = next(x for x in traces[repo]["output"]["findings"] if x["finding_id"] == fid)
            loc = _doc(f)
        out.append({**it, "doc_path": loc[0], "doc_line": loc[1]})
    return out


def v3_findings() -> list[dict]:
    out = []
    for repo in REPOS:
        p = OUT / "docs" / f"{repo}.json"
        if p.exists():
            for f in json.loads(p.read_text())["findings"]:
                out.append({"repo": repo, "id": f"docs:{repo}:{f.get('finding_id')}", "pass": "docs", "finding": f})
        p = OUT / "py32k" / f"{repo}.json"
        if p.exists():
            for k, c in json.loads(p.read_text())["chunks"].items():
                for f in c["findings"]:
                    out.append({"repo": repo, "id": f"py:{repo}#{k}:{f.get('finding_id')}", "pass": "py32k", "finding": f})
    for x in out:
        x["doc_path"], x["doc_line"] = _doc(x["finding"])
        x["fully_verified"] = bool(x["finding"].get("fully_verified"))
    return out


def chunked32k_findings() -> list[dict]:
    """Existing chunked-32k baseline merged findings (9 repos), for the 'hybrid + chunked 32k' row."""
    out = []
    for p in sorted((ROOT / "results_live/baselines/chunked-32k").glob("*.json")):
        d = json.loads(p.read_text())
        repo = d.get("repo") or p.stem
        for i, m in enumerate(d.get("findings") or []):
            f = m.get("finding", m)
            path, line = _doc(f)
            out.append({"repo": repo, "id": f"c32:{repo}:{i}", "idx": i, "doc_path": path, "doc_line": line,
                        "fully_verified": bool(m.get("fully_verified"))})
    return out


def near(a: dict, b: dict) -> bool:
    return a["repo"] == b["repo"] and a["doc_path"] == b["doc_path"] and abs(a["doc_line"] - b["doc_line"]) <= NEAR


def merge(base: list[dict], extra: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (new unique extras, duplicates) after dedupe against base and among themselves."""
    new, dups = [], []
    for x in extra:
        hit = next((b for b in base if near(b, x)), None) or next((n for n in new if near(n, x)), None)
        if hit is not None:
            dups.append({**x, "dup_of": hit["id"]})
        else:
            new.append(x)
    return new, dups


def merge_distinct(base: list[dict], extra: list[dict]) -> tuple[list[dict], list[dict]]:
    """merge() with the hand DISTINCT overrides from _beamv3_verdicts (different claims that sit within +-3 lines)."""
    from _beamv3_verdicts import DISTINCT
    new, dups = merge(base, [x for x in extra if x["id"] not in DISTINCT])
    order = {x["id"]: i for i, x in enumerate(extra)}
    new = sorted(new + [x for x in extra if x["id"] in DISTINCT], key=lambda x: order[x["id"]])
    return new, dups


if __name__ == "__main__":
    hy = hybrid_items()
    v3 = v3_findings()
    new, dups = merge_distinct(hy, v3)
    print(f"hybrid items {len(hy)}; v3 raw {len(v3)}; new unique {len(new)}; dups {len(dups)}")
    for d in dups:
        print("DUP", d["id"], d["doc_path"], d["doc_line"], "->", d["dup_of"])
    for n in new:
        f = n["finding"]
        print(f"NEW {n['id']} v={n['fully_verified']} {n['doc_path']}:{n['doc_line']} C={f['code_citation'].get('path')}:{f['code_citation'].get('start_line')}\n    {f.get('explanation','')[:300]}")
