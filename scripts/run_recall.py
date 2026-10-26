"""Planted-drift recall benchmark CLI: probe | plant | run | score | chart. See results_live/recall/recall.md."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime

from repoatlas import recall as R

WORK = Path("/workspace/recall_work")
OUT = Path("results_live/recall")
CAP = 10_000_000
CALIB = float(os.environ.get("RECALL_CALIB", "1.21"))


def _load_key() -> None:
    if not os.environ.get("OLLAMA_API_KEY"):
        os.environ["OLLAMA_API_KEY"] = Path("/home/box/.secrets/ollama_api_key").read_text().strip()


def cmd_probe(args) -> None:
    _load_key()
    manifest = json.loads((WORK / "manifest.json").read_text())
    ledger = R.Ledger(OUT / "usage_ledger.json", CAP)
    results_path = OUT / "context_probe.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else []
    for real in args.sizes:
        if any(r["target_real_tokens"] == real for r in results):
            print("skip (done)", real)
            continue
        pack = R.build_ordered_pack(WORK / "clean", manifest["order"], int(real / CALIB), "probe")
        first, last = pack.files[0].path, pack.files[-1].path
        task = ("\n\nTiny task: reply with ONLY a JSON object {\"first_file\": \"...\", \"last_file\": \"...\"} giving the "
                "path of the FIRST and the LAST '--- FILE:' block in the packed context above.")
        est = int(pack.total_tokens * CALIB) + args.max_tokens
        ledger.check(est, f"probe {real}")
        print(f"probe target={real} est_cl100k={pack.total_tokens} est_real~{int(pack.total_tokens*CALIB)}", flush=True)
        status, body, latency, hdrs = R.call_beam(
            [{"role": "system", "content": "You answer tersely."},
             {"role": "user", "content": pack.pack_text + task}],
            max_tokens=args.max_tokens, reasoning_effort="low", json_schema=None, retry_5xx=False)
        rec = {"target_real_tokens": real, "pack_cl100k_tokens": pack.total_tokens, "status": status,
               "latency_s": round(latency, 1), "rate_headers": hdrs, "expected_first": first, "expected_last": last,
               "at": datetime.now(UTC).isoformat()}
        if isinstance(body, dict):
            usage = body.get("usage") or {}
            msg = (body.get("choices") or [{}])[0].get("message") or {}
            rec.update(usage=usage, content=(msg.get("content") or "")[:500],
                       finish_reason=(body.get("choices") or [{}])[0].get("finish_reason"))
            ledger.add({"label": f"probe-{real}", "usage": usage, "latency_s": rec["latency_s"]})
            rec["ratio_real_over_cl100k"] = round(int(usage.get("prompt_tokens", 0)) / max(1, pack.total_tokens), 4)
        else:
            rec["error"] = str(body)[:2000]
            ledger.add({"label": f"probe-{real}", "usage": {}, "error": rec["error"][:300]})
        results.append(rec)
        results_path.write_text(json.dumps(results, indent=2))
        print(json.dumps({k: v for k, v in rec.items() if k != "rate_headers"}, indent=1), flush=True)
        if status != 200:
            print("hard failure -> stop probing")
            break


HAYSTACK_REAL = 940_000


def haystack_dir(seed: int) -> Path:
    return WORK / f"seed{seed}"


def cmd_plant(args) -> None:
    import py_compile
    import shutil
    manifest = json.loads((WORK / "manifest.json").read_text())
    order = manifest["order"]
    budget = int(HAYSTACK_REAL / CALIB)
    clean = R.build_ordered_pack(WORK / "clean", order, budget, "clean")
    pos = R.line_positions(clean)
    cands, idents = R.mine_candidates(clean, pos)
    files = {f.path: f.lines for f in clean.files}
    exclude: set[str] = set()
    for seed in args.seeds:
        plants = R.select_plants(cands, files, idents, CALIB, seed, exclude_names=exclude if args.disjoint else set())
        exclude |= {p["name"] for p in plants}
        for p in plants:
            if p["kind"] == "code_rename_kwarg":
                p["other_doc_lines"] = sorted({(c["doc_path"], c["doc_line"]) for c in cands
                                               if c.get("param") == p["param"] and c["name"] == p["name"]})
        d = haystack_dir(seed)
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(WORK / "clean", d)
        edits = R.apply_plants(d, plants)
        bad = []
        for rel in {p["def_path"] for p in plants} | {p["doc_path"] for p in plants if p["doc_path"].endswith(".py")}:
            try:
                py_compile.compile(str(d / rel), doraise=True, cfile="/tmp/recall_pyc")
            except py_compile.PyCompileError as exc:
                bad.append((rel, str(exc)[:200]))
        pack = R.build_ordered_pack(d, [f.path for f in clean.files], 10**9, f"planted-seed{seed}")
        assert [f.path for f in pack.files] == [f.path for f in clean.files], "file set changed after planting"
        ppos = R.line_positions(pack)
        pfiles = {f.path: f.lines for f in pack.files}
        truth = []
        for p in plants:
            code_line = p.get("param_line", p["def_line"])
            dist = abs(ppos[p["doc_path"]][p["doc_line"] - 1] - ppos[p["def_path"]][code_line - 1])
            doc_text = pfiles[p["doc_path"]][p["doc_line"] - 1]
            code_text = pfiles[p["def_path"]][code_line - 1]
            stale_word = p["old"] if p["kind"].startswith("code_") else p["new"]
            ok = re.search(rf"(?<!\w){re.escape(stale_word)}(?!\w)", doc_text) is not None
            truth.append({
                "plant_id": p["plant_id"], "kind": p["kind"], "bucket": R.bucket_of(int(dist * CALIB)),
                "distance_real_tokens_est": int(round(dist * CALIB)), "distance_cl100k": dist,
                "doc_path": p["doc_path"], "doc_line": p["doc_line"], "doc_text": doc_text,
                "code_path": p["def_path"], "code_line": code_line, "def_line": p["def_line"], "code_text": code_text,
                "symbol": p["name"], "old": p["old"], "new": p["new"],
                "doc_says": stale_word, "code_says": p["new"] if p["kind"].startswith("code_") else p["old"],
                "doc_pos_real_est": int(ppos[p["doc_path"]][p["doc_line"] - 1] * CALIB),
                "code_pos_real_est": int(ppos[p["def_path"]][code_line - 1] * CALIB),
                "lines_edited": edits[p["plant_id"]], "stale_line_check": ok,
            })
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"ground_truth_seed{seed}.json").write_text(json.dumps(truth, indent=2))
        (WORK / f"pack_seed{seed}.json").write_text(pack.model_dump_json())
        diff = subprocess.run(["diff", "-ru", str(WORK / "clean"), str(d)], capture_output=True, text=True).stdout
        (OUT / f"plants_seed{seed}.diff").write_text(diff.replace(str(WORK) + "/", ""))
        print(f"seed {seed}: {len(truth)} plants, pack cl100k={pack.total_tokens}, compile errors={bad}")
        for t in truth:
            print(f"  {t['plant_id']} {t['kind']:22} {t['bucket']:6} d={t['distance_real_tokens_est']:>7} "
                  f"{t['old']}->{t['new']} edits={t['lines_edited']} ok={t['stale_line_check']} {t['doc_path']}:{t['doc_line']}")


METHODS = {  # name: (chunk budget in real tokens or None, max_tokens)
    "whole": (None, 40_000),
    "chunk128k": (128_000, 24_000),
    "chunk32k": (32_000, 12_000),
}


def _units(method: str, seed: int):
    from repoatlas.models import RepoPack
    pack = RepoPack.model_validate_json((WORK / f"pack_seed{seed}.json").read_text())
    chunk_real, _ = METHODS[method]
    if chunk_real is None:
        return [{"index": 0, "spans": [(f.path, 1, len(f.lines)) for f in pack.files], "text": pack.pack_text}]
    overhead = R.tok(R.build_docdrift_prompt("")) + 200
    return R.build_chunks(pack, int(chunk_real / CALIB) - overhead)


def cmd_run(args) -> None:
    from repoatlas.client import _StructuredModelResponse
    from repoatlas.prompts import SYSTEM_PROMPT
    _load_key()
    schema = _StructuredModelResponse.model_json_schema()
    ledger = R.Ledger(OUT / "usage_ledger.json", CAP)
    units = _units(args.method, args.seed)
    _, max_tokens = METHODS[args.method]
    run_dir = OUT / "raw" / f"{args.method}_seed{args.seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "chunks.json").write_text(json.dumps([{"index": u["index"], "spans": u["spans"],
                                                      "cl100k": R.tok(u["text"])} for u in units], indent=1))
    todo = [u for u in units if not (run_dir / f"unit{u['index']:03d}.json").exists()]
    est = sum(int(R.tok(R.build_docdrift_prompt(u["text"])) * CALIB) + max_tokens for u in todo)
    print(f"{args.method} seed{args.seed}: {len(units)} units ({len(todo)} todo), estimate <= {est:,} tokens; "
          f"ledger so far {ledger.total:,}", flush=True)
    ledger.check(est, f"{args.method} seed{args.seed}")
    for u in todo:
        prompt = R.build_docdrift_prompt(u["text"])
        print(f"  unit {u['index']} cl100k={R.tok(prompt):,} ...", flush=True)
        status, body, latency, hdrs = R.call_beam(
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            max_tokens=max_tokens, reasoning_effort=args.reasoning, json_schema=schema)
        rec = {"method": args.method, "seed": args.seed, "unit": u["index"], "status": status,
               "latency_s": round(latency, 1), "rate_headers": hdrs, "max_tokens": max_tokens,
               "reasoning_effort": args.reasoning, "at": datetime.now(UTC).isoformat()}
        if isinstance(body, dict):
            ch = (body.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            rec.update(usage=body.get("usage") or {}, finish_reason=ch.get("finish_reason"),
                       content=msg.get("content") or "", reasoning_chars=len(msg.get("reasoning") or msg.get("reasoning_content") or ""))
            ledger.add({"label": f"{args.method}-seed{args.seed}-u{u['index']}", "usage": rec["usage"],
                        "latency_s": rec["latency_s"]})
        else:
            rec["error"] = body
            ledger.add({"label": f"{args.method}-seed{args.seed}-u{u['index']}-error", "usage": {},
                        "latency_s": rec["latency_s"], "status": status})
        (run_dir / f"unit{u['index']:03d}.json").write_text(json.dumps(rec, indent=1))
        print(f"    status={status} {latency:.0f}s usage={rec.get('usage')} finish={rec.get('finish_reason')}; "
              f"ledger {ledger.total:,}", flush=True)


KNOWN_REAL = [  # pre-existing drifts at these SHAs, from earlier manual review (sweep_notes.md); matched by path + token
    ("httpx/docs", "Mounts"), ("httpx/httpx/_transports/wsgi.py", "app=app"), ("click/docs/exceptions.md", "FileType"),
    ("structlog/docs/standard-library.md", "_NAME_TO_LEVEL"), ("structlog/src/structlog/stdlib.py", "_NAME_TO_LEVEL"),
    ("jinja/docs/extensions.rst", "newstyle"), ("structlog/src/structlog/_native.py", ""),
]
WORD = lambda w: re.compile(rf"(?<![\w]){re.escape(w)}(?![\w])")


def _cite_lines(chk) -> tuple[int, int]:
    c = chk.citation
    if chk.corrected_start_line is not None:
        return chk.corrected_start_line, chk.corrected_end_line
    return c.start_line, c.end_line


def _near(a: tuple[int, int], line: int, tol: int) -> bool:
    return a[0] - tol <= line <= a[1] + tol


def score_run(method: str, seed: int) -> tuple[list[dict], dict]:
    from repoatlas.client import parse_structured_content
    from repoatlas.models import RepoPack
    from repoatlas.verifier import _build_file_lookup, _normalise_path, verify_citation
    pack = RepoPack.model_validate_json((WORK / f"pack_seed{seed}.json").read_text())
    lookup = _build_file_lookup(pack)
    truth = json.loads((OUT / f"ground_truth_seed{seed}.json").read_text())
    run_dir = OUT / "raw" / f"{method}_seed{seed}"
    findings, meta = [], {"units": 0, "errors": [], "parse_failures": 0, "truncated": 0, "usage": 0}
    for f in sorted(run_dir.glob("unit*.json")):
        rec = json.loads(f.read_text())
        meta["units"] += 1
        meta["usage"] += int((rec.get("usage") or {}).get("total_tokens", 0) or 0)
        if rec.get("error") is not None or rec.get("status") != 200:
            meta["errors"].append(f"unit {rec['unit']}: status {rec.get('status')} {str(rec.get('error'))[:200]}")
            continue
        if rec.get("finish_reason") == "length":
            meta["truncated"] += 1
        try:
            parsed, _ = parse_structured_content(rec.get("content") or "")
        except Exception as exc:  # noqa: BLE001
            meta["parse_failures"] += 1
            meta["errors"].append(f"unit {rec['unit']}: parse failure {type(exc).__name__}: {str(exc)[:160]}")
            continue
        for fd in parsed.findings:
            findings.append((rec["unit"], fd))
    checked = []
    for unit, fd in findings:
        dchk, cchk = verify_citation(fd.doc_citation, lookup), verify_citation(fd.code_citation, lookup)
        checked.append({"unit": unit, "f": fd, "d": dchk, "c": cchk,
                        "dpath": _normalise_path(fd.doc_citation.path), "cpath": _normalise_path(fd.code_citation.path),
                        "text": " ".join([fd.explanation or "", fd.doc_citation.quote, fd.code_citation.quote,
                                          getattr(fd, "proposed_fix", "") or ""]),
                        "matched": None})
    rows = []
    for t in truth:
        strict = loose = None
        for i, ch in enumerate(checked):
            same_doc = ch["dpath"] == t["doc_path"]
            if not same_doc:
                continue
            dl = _cite_lines(ch["d"])
            code_lines = lookup.get(ch["cpath"], [])
            cl = _cite_lines(ch["c"])
            code_text = " ".join(code_lines[max(cl[0] - 1, 0):cl[1]]) + " " + ch["f"].code_citation.quote
            if (strict is None and ch["d"].verified and ch["c"].verified and _near(dl, t["doc_line"], 3)
                    and WORD(t["code_says"]).search(code_text)):
                strict = i
            if loose is None and (_near((ch["f"].doc_citation.start_line, ch["f"].doc_citation.end_line), t["doc_line"], 5)
                                  or _near(dl, t["doc_line"], 5)
                                  or (WORD(t["doc_says"]).search(ch["text"]) and WORD(t["code_says"]).search(ch["text"]))):
                loose = i
        for i in (strict, loose):
            if i is not None:
                checked[i]["matched"] = t["plant_id"]
        rows.append({"method": method, "seed": seed, "plant_id": t["plant_id"], "kind": t["kind"], "bucket": t["bucket"],
                     "distance_real_tokens_est": t["distance_real_tokens_est"],
                     "nearest_evidence_real_tokens_est": t.get("nearest_evidence_real_tokens_est"),
                     "same_unit": t.get(f"same_unit_{method}"), "strict_hit": int(strict is not None),
                     "loose_hit": int(loose is not None), "old": t["old"], "new": t["new"],
                     "doc": f"{t['doc_path']}:{t['doc_line']}"})
    unplanted = [c for c in checked if c["matched"] is None]
    known = []
    for c in unplanted:
        for path, token in KNOWN_REAL:
            if (c["dpath"].startswith(path) or c["cpath"].startswith(path)) and token in c["text"]:
                known.append(c)
                break
    meta.update(findings=len(checked), fully_verified=sum(c["d"].verified and c["c"].verified for c in checked),
                matched_findings=len(checked) - len(unplanted), unplanted=len(unplanted),
                unplanted_verified=sum(c["d"].verified and c["c"].verified for c in unplanted),
                unplanted_known_real=len(known))
    (run_dir / "unplanted_findings.json").write_text(json.dumps([
        {"unit": c["unit"], "known_real": c in known, "doc_verified": c["d"].verified, "code_verified": c["c"].verified,
         **c["f"].model_dump(include={"finding_id", "drift_kind", "explanation", "doc_citation", "code_citation"})}
        for c in unplanted], indent=1))
    return rows, meta


def _augment_truth(seed: int) -> None:
    """Add nearest-evidence distance and same-chunk flags to the ground truth (idempotent)."""
    from repoatlas.models import RepoPack
    path = OUT / f"ground_truth_seed{seed}.json"
    truth = json.loads(path.read_text())
    pack = RepoPack.model_validate_json((WORK / f"pack_seed{seed}.json").read_text())
    pos = R.line_positions(pack)
    for t in truth:
        w = WORD(t["code_says"])
        dpos = pos[t["doc_path"]][t["doc_line"] - 1]
        best = None
        for f in pack.files:
            for i, line in enumerate(f.lines):
                if (f.path, i + 1) != (t["doc_path"], t["doc_line"]) and w.search(line):
                    d = abs(pos[f.path][i] - dpos)
                    best = d if best is None or d < best else best
        t["nearest_evidence_real_tokens_est"] = int(best * CALIB) if best is not None else None
        for method in ("chunk128k", "chunk32k"):
            cfile = OUT / "raw" / f"{method}_seed{seed}" / "chunks.json"
            if not cfile.exists():
                continue
            chunks = json.loads(cfile.read_text())

            def unit_of(p, ln):
                return next(c["index"] for c in chunks for (sp, a, b) in c["spans"] if sp == p and a <= ln <= b)
            t[f"same_unit_{method}"] = unit_of(t["doc_path"], t["doc_line"]) == unit_of(t["code_path"], t["code_line"])
    path.write_text(json.dumps(truth, indent=2))


def cmd_score(args) -> None:
    import csv
    all_rows, summary = [], []
    for seed in (1, 2):
        _augment_truth(seed)
    for run_dir in sorted((OUT / "raw").glob("*_seed*")):
        method, seed = run_dir.name.rsplit("_seed", 1)
        if not list(run_dir.glob("unit*.json")):
            continue
        rows, meta = score_run(method, int(seed))
        all_rows += rows
        summary.append({"run": run_dir.name, **meta})
    with (OUT / "scores.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows(all_rows)
    labels = [b[0] for b in R.BUCKETS]
    table = []
    for run in sorted({(r["method"], r["seed"]) for r in all_rows}):
        rs = [r for r in all_rows if (r["method"], r["seed"]) == run]
        row = {"run": f"{run[0]}_seed{run[1]}"}
        for b in labels:
            br = [r for r in rs if r["bucket"] == b]
            row[f"{b} strict"] = f"{sum(r['strict_hit'] for r in br)}/{len(br)}"
            row[f"{b} loose"] = f"{sum(r['loose_hit'] for r in br)}/{len(br)}"
        row["all strict"] = f"{sum(r['strict_hit'] for r in rs)}/{len(rs)}"
        row["all loose"] = f"{sum(r['loose_hit'] for r in rs)}/{len(rs)}"
        table.append(row)
    with (OUT / "recall_by_bucket.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    (OUT / "run_summary.json").write_text(json.dumps(summary, indent=2))
    for row in table:
        print(row)
    for s_ in summary:
        print(s_)
    _chart(all_rows, labels)


def _chart(rows, labels) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5))
    runs = sorted({(r["method"], r["seed"]) for r in rows})
    colors = {"whole": ["#1f4e9c", "#6a8fd8"], "chunk128k": ["#c0392b"], "chunk32k": ["#27ae60"]}
    for method, seed in runs:
        rs = [r for r in rows if (r["method"], r["seed"]) == (method, seed)]
        ys, yl = [], []
        for b in labels:
            br = [r for r in rs if r["bucket"] == b]
            ys.append(sum(r["strict_hit"] for r in br) / len(br) if br else float("nan"))
            yl.append(sum(r["loose_hit"] for r in br) / len(br) if br else float("nan"))
        col = colors.get(method, ["#555"])[min(seed - 1, len(colors.get(method, ["#555"])) - 1)]
        name = {"whole": "whole prompt (~940k)", "chunk128k": "chunked 128k", "chunk32k": "chunked 32k"}[method]
        ax.plot(labels, ys, marker="o", color=col, label=f"{name}, seed {seed} (strict)")
        ax.plot(labels, yl, marker="x", ls="--", color=col, alpha=0.45, label=f"{name}, seed {seed} (loose)")
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("doc-line to code-definition distance (estimated real tokens)")
    ax.set_ylabel("recall of planted drifts")
    ax.set_title("DocDrift planted-drift recall vs distance (Beam, 4-6 plants per bucket)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    fig.savefig(OUT / "recall_vs_distance.png", dpi=150)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--sizes", type=int, nargs="+", default=[200_000, 400_000, 600_000, 800_000, 950_000])
    p.add_argument("--max-tokens", type=int, default=2048)
    p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("plant")
    p.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    p.add_argument("--disjoint", action="store_true")
    p.set_defaults(fn=cmd_plant)
    p = sub.add_parser("run")
    p.add_argument("method", choices=sorted(METHODS))
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--reasoning", default="medium")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("score")
    p.set_defaults(fn=cmd_score)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    args.fn(args)


if __name__ == "__main__":
    main()
