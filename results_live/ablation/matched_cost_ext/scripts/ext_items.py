"""Build the extension item set for the matched-cost control (pre-registered in ../design_ext.md).

Sources (no new labels by guesswork):
  E1 planted drifts: results_live/recall/ground_truth_seed{1,2}.json (58 plants; truth and code location recorded at
     planting time). Repo context = that library's files from the planted haystack pack (/workspace/recall_work/
     pack_seed{s}.json), which already carries the plant edits. Exclusion rule (mechanical): drop a plant whose stale doc
     line itself defines the stale name (`def NAME` / `class NAME`), because then the doc is a user-defined example,
     not a reference to the package.
  E2 structlog real candidates: the 6 DocDrift v2 candidates of structlog (never judged in the 56 because the hybrid
     whole-repo call failed to parse). Labels: scripts/_symbol_verdicts.py + results_live/repros/hand_labels.json.
     Gold = file:line evidence recorded in results_live/handcheck.md / _symbol_verdicts.py, checked at 19c4f21.
Writes ../items.json and ../packs/<unit>.json (derived per-library packs).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path("/workspace/docdrift_main")
EXT = Path("/workspace/ablation/matched_cost_ext")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from repoatlas.models import RepoPack  # noqa: E402
import hybrid_triage as H  # noqa: E402

UPSTREAM = {"click": ("https://github.com/pallets/click", "2247b35"), "jinja": ("https://github.com/pallets/jinja", "5ef7011"),
            "werkzeug": ("https://github.com/pallets/werkzeug", "b73dce5"), "httpx": ("https://github.com/encode/httpx", "b5addb6"),
            "httpcore": ("https://github.com/encode/httpcore", "10a6582"), "structlog": ("https://github.com/hynek/structlog", "19c4f21"),
            "uvicorn": ("https://github.com/encode/uvicorn", "9d81c12")}
CLAIM = "name-check: the documentation refers to `{name}`; this name may not match the code."


def lib_pack(seed: int, lib: str) -> RepoPack:
    full = RepoPack.model_validate_json((Path("/workspace/recall_work") / f"pack_seed{seed}.json").read_text())
    url, ref = UPSTREAM[lib]
    head = (f"# REPOATLAS PACK FORMAT 1\nREPO_URL: {url}\nREF: {ref}\nFILTER_SIGNATURE: v4\nLINE_FORMAT: <line>|<text>\n"
            "FILES_BEGIN\n")
    t = full.pack_text
    parts, files = [], []
    for f in full.files:
        if not f.path.startswith(lib + "/"):
            continue
        a = t.index(f"--- FILE: {f.path} ---\n")
        endm = f"--- END FILE: {f.path} ---\n"
        parts.append(t[a: t.index(endm, a) + len(endm)])
        files.append(f.model_dump())
    text = head + "".join(parts) + "FILES_END\n"
    data = full.model_dump()
    data.update(repo_url=url, ref=ref, files=files, pack_text=text, total_tokens=sum(f["token_count"] for f in files),
                prefix_hash=hashlib.sha256(text.encode()).hexdigest()[:16], truncated=False)
    return RepoPack.model_validate(data)


def main() -> None:
    (EXT / "packs").mkdir(parents=True, exist_ok=True)
    items, excluded, units = [], [], {}
    for seed in (1, 2):
        truth = json.loads((ROOT / f"results_live/recall/ground_truth_seed{seed}.json").read_text())
        bylib: dict[str, list[dict]] = {}
        for p in truth:
            name = p["doc_says"]
            if re.search(rf"\b(?:def|class)\s+{re.escape(name)}\b", p["doc_text"]):
                excluded.append({"plant_id": p["plant_id"], "why": "stale doc line defines the name itself (user-defined example)",
                                 "doc_text": p["doc_text"].strip()})
                continue
            if not p["stale_line_check"]:
                excluded.append({"plant_id": p["plant_id"], "why": "stale_line_check false"})
                continue
            bylib.setdefault(p["doc_path"].split("/")[0], []).append(p)
        for lib, ps in sorted(bylib.items()):
            unit = f"planted{seed}-{lib}"
            pack = lib_pack(seed, lib)
            (EXT / "packs" / f"{unit}.json").write_text(pack.model_dump_json())
            units[unit] = {"pack": f"packs/{unit}.json", "pack_cl100k": pack.total_tokens, "files": len(pack.files),
                           "pack_sha256": hashlib.sha256(pack.pack_text.encode()).hexdigest()}
            for i, p in enumerate(sorted(ps, key=lambda q: q["plant_id"]), 1):
                c = {"source": "planted", "source_id": p["plant_id"], "doc_path": p["doc_path"], "doc_line": p["doc_line"],
                     "doc_end": p["doc_line"], "doc_text": p["doc_text"].strip(), "claim": CLAIM.format(name=p["doc_says"]),
                     "code_hint": "", "candidate_id": f"C{i:02d}"}
                gold = sorted({(p["code_path"], p["code_line"], p["code_line"]), (p["code_path"], p["def_line"], p["def_line"])})
                items.append({"key": f"{unit}:{p['plant_id']}", "unit": unit, "stratum": "planted", "candidate": c, "label": "true",
                              "gold": [list(g) for g in gold], "cross_file": p["doc_path"] != p["code_path"],
                              "code_says": p["code_says"], "doc_says": p["doc_says"], "kind": p["kind"], "bucket": p["bucket"],
                              "provenance": f"results_live/recall/ground_truth_seed{seed}.json {p['plant_id']}"})
    # E2 structlog real candidates
    trace = json.loads((ROOT / "results_live/traces/structlog-400000.json").read_text())
    pack = RepoPack.model_validate(trace["pack"])
    cands = H.load_candidates("structlog", pack, trace)
    units["real-structlog"] = {"pack": "results_live/traces/structlog-400000.json (pack)", "pack_cl100k": pack.total_tokens,
                               "files": len(pack.files), "pack_sha256": hashlib.sha256(pack.pack_text.encode()).hexdigest()}
    LL = "src/structlog/_log_levels.py"
    S = {  # source_id: (label, gold, cross_file, evidence note)
        "structlog-400000:DD-2": ("true", [[LL, 27, 27]], True, "handcheck.md: mapping is structlog._log_levels.NAME_TO_LEVEL (_log_levels.py:27)"),
        "S13": ("true", [[LL, 27, 27]], True, "_symbol_verdicts 13 (T5, same claim as DD-2); _log_levels.py:27"),
        "structlog-400000:DD-1": ("false", [[LL, 27, 36], ["src/structlog/_native.py", 132, 133]], True,
                                  "handcheck.md: doc lists a subset, code accepts a superset (NAME_TO_LEVEL _log_levels.py:27-36, "
                                  "looked up at _native.py:132-133)"),
        "S16": ("false", [["src/structlog/dev.py", 999, 1008]], False, "_symbol_verdicts 16: property docstring documents the setter value (dev.py:999-1008)"),
        "S14": ("true", [[LL, 27, 27]], True, "_symbol_verdicts 14 (T5 second site, stdlib.py:862); _log_levels.py:27"),
        "S15": ("true", [["src/structlog/twisted.py", 202, 202]], False, "_symbol_verdicts 15: class is PlainFileLogObserver (twisted.py:202)"),
    }
    for c in cands:
        lab, gold, cross, note = S[c["source_id"]]
        items.append({"key": f"real-structlog:{c['source_id']}", "unit": "real-structlog", "stratum": "real", "candidate": c,
                      "label": lab, "gold": gold, "cross_file": cross, "provenance": note})
    (EXT / "items.json").write_text(json.dumps({"items": items, "excluded": excluded, "units": units}, indent=1))
    print(len(items), "items;", sum(1 for i in items if i["cross_file"]), "cross-file;", "excluded:", excluded)
    for u, d in units.items():
        print(u, d["pack_cl100k"], d["files"], sum(1 for i in items if i["unit"] == u))


if __name__ == "__main__":
    main()
