"""Build the unpublished v2 Hugging Face dataset folder from results_live."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from repoatlas.hybrid_view import (
    HYBRID_JSON_PATH,
    HYBRID_REPROS_PATH,
    HYBRID_TRIAGE_DIRECTORY,
    LABEL_SOURCE,
    RESULTS_LIVE_DIRECTORY,
    _as_dict,
    _as_dict_list,
    compute_hero_stats,
    load_hybrid_payload,
    strip_local_paths,
)


HF_DATASET_DIRECTORY: Path = Path("hf_dataset")
LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "hybrid" / "beam_usage_ledger.json"
ABLATION_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "results.json"
ABLATION_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "beam_usage_ledger.json"
MATCHED_COST_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "matched_cost" / "results.json"
MATCHED_COST_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "matched_cost" / "beam_usage_ledger.json"
MATCHED_COST_EXT_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "matched_cost_ext" / "beam_usage_ledger.json"
MATCHED_COST_EXT_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "matched_cost_ext" / "results.json"
PUBLIC_SPACE_URL: str = "https://huggingface.co/spaces/ollymcbride4/docdrift"
PUBLIC_CODE_URL: str = "https://github.com/OlsOls4/repoatlas-1m"
PUBLIC_DATASET_URL: str = "https://huggingface.co/datasets/ollymcbride4/docdrift-bugs"
PUBLIC_THREAD_URL: str = "https://huggingface.co/reflection/Beam-1.0-501B-A23B/discussions/5"
PUBLIC_VIDEO_URL: str = "https://huggingface.co/spaces/ollymcbride4/docdrift/resolve/main/assets/docdrift-demo.mp4"
BEAMV3_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "beamv3" / "results.json"
BEAMV3_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "beamv3" / "beam_usage_ledger.json"
FRESH_RUN_FINDINGS_PATH: Path = RESULTS_LIVE_DIRECTORY / "fresh_run" / "findings.json"
GROUND_TRUTH_SEED1: Path = RESULTS_LIVE_DIRECTORY / "recall" / "ground_truth_seed1.json"
GROUND_TRUTH_SEED2: Path = RESULTS_LIVE_DIRECTORY / "recall" / "ground_truth_seed2.json"


def build_hf_dataset(destination: Path | None = None) -> Path:
    """
    @brief Write hf_dataset/ parquet + jsonl + card from recorded results.
    """

    target: Path = destination or HF_DATASET_DIRECTORY
    target.mkdir(parents=True, exist_ok=True)
    payload = load_hybrid_payload()
    if not payload["available"]:
        raise FileNotFoundError(HYBRID_JSON_PATH)
    stats = compute_hero_stats(payload)
    findings = _hybrid_findings(payload)
    verdicts = _triage_verdicts()
    repros = _repro_rows()
    plants = _planted_rows()
    ablation = _ablation_verdicts()
    ext_verdicts = _matched_cost_ext_verdicts()
    beamv3 = _beamv3_findings()
    ledger = _token_ledger()
    _write_table(target, "findings", findings)
    _write_table(target, "triage_verdicts", verdicts)
    _write_table(target, "repros", repros)
    _write_table(target, "planted_drift", plants)
    _write_table(target, "ablation_verdicts", ablation)
    _write_table(target, "matched_cost_ext_verdicts", ext_verdicts)
    _write_table(target, "beamv3_findings", beamv3)
    _write_table(target, "token_ledger", ledger)
    (target / "README.md").write_text(
        _card(stats, findings, verdicts, repros, plants, ablation, ext_verdicts, beamv3, ledger),
        encoding="utf-8",
    )
    return target


def _hybrid_findings(payload: object) -> list[dict[str, object]]:
    """
    @brief The 60 hybrid findings from hybrid.json.
    """

    from repoatlas.hybrid_view import _find_row

    hybrid_row = _find_row(payload["rows"], "hybrid (symbol")  # type: ignore[index]
    rows: list[dict[str, object]] = []
    for item in _as_dict_list(hybrid_row.get("items")):
        rows.append(
            {
                "repo": item.get("repo", ""),
                "id": item.get("id", ""),
                "kind": item.get("kind", ""),
                "verdict": item.get("verdict", ""),
                "drift_id": item.get("drift_id", ""),
                "beam": item.get("beam"),
                "strict_confirmed": bool(item.get("strict_confirmed", False)),
                "repro_status": item.get("repro_status"),
                "evidence": strip_local_paths(str(item.get("evidence") or item.get("recheck") or "")),
                "hand_verdict": item.get("verdict", ""),
                "hand_verdict_description": LABEL_SOURCE,
            }
        )
    return rows


def _triage_verdicts() -> list[dict[str, object]]:
    """
    @brief All Beam triage verdicts except failed/empty attempt files.
    """

    rows: list[dict[str, object]] = []
    if not HYBRID_TRIAGE_DIRECTORY.exists():
        return rows
    for path in sorted(HYBRID_TRIAGE_DIRECTORY.glob("*.json")):
        if path.name.endswith(".attempt1.json"):
            continue
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        repo = str(payload.get("repo", path.stem))
        for verdict in _as_dict_list(payload.get("verdicts")):
            code = _as_dict(verdict.get("code_citation"))
            rows.append(
                {
                    "repo": repo,
                    "candidate_id": verdict.get("candidate_id", ""),
                    "source_id": verdict.get("source_id", ""),
                    "verdict": verdict.get("verdict", ""),
                    "reason": verdict.get("reason", ""),
                    "code_path": code.get("path", ""),
                    "code_line": code.get("start_line", ""),
                    "code_quote": code.get("quote", ""),
                }
            )
    return rows


def _repro_rows() -> list[dict[str, object]]:
    """
    @brief Compact repro index rows (not per-attempt logs).
    """

    if not HYBRID_REPROS_PATH.exists():
        return []
    raw: object = json.loads(HYBRID_REPROS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    rows: list[dict[str, object]] = []
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        rows.append(
            {
                "case_id": value.get("case_id", key),
                "repo": value.get("repo", ""),
                "status": value.get("status", ""),
                "strict_confirmed": bool(value.get("strict_confirmed", False)),
                "exception_type": value.get("exception_type") or "",
                "error_excerpt": strip_local_paths(str(value.get("error_excerpt") or "")),
                "evidence": value.get("evidence") or "",
            }
        )
    return rows


def _planted_rows() -> list[dict[str, object]]:
    """
    @brief Planted-drift ground truth from both seeds.
    """

    rows: list[dict[str, object]] = []
    for seed, path in ((1, GROUND_TRUTH_SEED1), (2, GROUND_TRUTH_SEED2)):
        if not path.exists():
            continue
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        plants: Iterable[object]
        if isinstance(payload, list):
            plants = payload
        elif isinstance(payload, dict):
            plants = payload.get("plants") or payload.get("ground_truth") or []
            if isinstance(plants, dict):
                plants = [{"id": key, **value} for key, value in plants.items() if isinstance(value, dict)]
        else:
            plants = []
        for item in plants:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["seed"] = seed
            rows.append(row)
    return rows


def _ablation_verdicts() -> list[dict[str, object]]:
    """
    @brief One row per judged candidate from the whole-repo vs local-file ablation.
    """

    if not ABLATION_RESULTS_PATH.exists():
        return []
    payload: object = json.loads(ABLATION_RESULTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    matched_by_key: dict[str, dict[str, object]] = {}
    if MATCHED_COST_RESULTS_PATH.exists():
        matched_payload: object = json.loads(MATCHED_COST_RESULTS_PATH.read_text(encoding="utf-8"))
        if isinstance(matched_payload, dict):
            for item in _as_dict_list(matched_payload.get("rows")):
                matched_by_key[str(item.get("key", ""))] = item
    rows: list[dict[str, object]] = []
    for item in _as_dict_list(payload.get("rows")):
        whole = _as_dict(item.get("whole"))
        local = _as_dict(item.get("local"))
        stability = _as_dict(item.get("stability")) if item.get("stability") else {}
        matched_item = matched_by_key.get(str(item.get("key", "")), {})
        matched = _as_dict(matched_item.get("matched")) if matched_item else {}
        rows.append(
            {
                "key": item.get("key", ""),
                "repo": item.get("repo", ""),
                "candidate_id": item.get("candidate_id", ""),
                "source_id": item.get("source_id", ""),
                "label": item.get("label", ""),
                "hand_verdict": item.get("label", ""),
                "hand_verdict_description": LABEL_SOURCE,
                "cross_file": item.get("cross_file"),
                "gold_outside_local": item.get("gold_outside_local"),
                "whole_verdict": whole.get("verdict"),
                "local_verdict": local.get("verdict"),
                "matched_verdict": matched.get("verdict"),
                "stability_verdict": stability.get("verdict"),
                "whole_cite_correct": whole.get("cite_correct"),
                "local_cite_correct": local.get("cite_correct"),
                "matched_cite_correct": matched.get("cite_correct"),
                "whole_cite_verified": whole.get("cite_verified"),
                "local_cite_verified": local.get("cite_verified"),
                "matched_cite_verified": matched.get("cite_verified"),
                "gold_in_matched_context": matched_item.get("gold_in_matched_context"),
            }
        )
    return rows


def _arm_cite_cols(prefix: str, arm: dict[str, object]) -> dict[str, object]:
    """
    @brief Flatten one arm's verdict and citation fields for the extension table.
    """

    citation = _as_dict(arm.get("citation"))
    return {
        f"{prefix}_verdict": arm.get("verdict"),
        f"{prefix}_kept": arm.get("kept"),
        f"{prefix}_cite_correct": arm.get("cite_correct"),
        f"{prefix}_cite_verified": arm.get("cite_verified"),
        f"{prefix}_cite_file_correct": arm.get("cite_file_correct"),
        f"{prefix}_reason": strip_local_paths(str(arm.get("reason") or "")),
        f"{prefix}_cite_path": str(citation.get("path") or ""),
        f"{prefix}_cite_start": citation.get("start_line"),
        f"{prefix}_cite_end": citation.get("end_line"),
        f"{prefix}_cite_quote": strip_local_paths(str(citation.get("quote") or "")),
    }


def _matched_cost_ext_verdicts() -> list[dict[str, object]]:
    """
    @brief Scored extension items from matched_cost_ext/results.json rows (63 recorded items).
    """

    if not MATCHED_COST_EXT_RESULTS_PATH.exists():
        return []
    payload: object = json.loads(MATCHED_COST_EXT_RESULTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, object]] = []
    for item in _as_dict_list(payload.get("rows")):
        whole = _as_dict(item.get("whole"))
        local = _as_dict(item.get("local"))
        matched = _as_dict(item.get("matched"))
        gold = item.get("gold")
        row: dict[str, object] = {
            "key": item.get("key", ""),
            "set": item.get("set", ""),
            "stratum": item.get("stratum", ""),
            "unit": item.get("unit", ""),
            "label": item.get("label", ""),
            "hand_verdict": item.get("label", ""),
            "hand_verdict_description": LABEL_SOURCE,
            "truth": item.get("truth"),
            "cross_file": item.get("cross_file"),
            "gold_outside_local": item.get("gold_outside_local"),
            "gold_in_matched_context": item.get("gold_in_matched_context"),
            "gold": json.dumps(gold, ensure_ascii=False) if gold is not None else "",
            "whole_error": strip_local_paths(str(item.get("whole_error") or "")),
            "local_error": strip_local_paths(str(item.get("local_error") or "")),
            "matched_error": strip_local_paths(str(item.get("matched_error") or "")),
        }
        row.update(_arm_cite_cols("whole", whole))
        row.update(_arm_cite_cols("local", local))
        row.update(_arm_cite_cols("matched", matched))
        rows.append(row)
    return rows


def _beamv3_findings() -> list[dict[str, object]]:
    """
    @brief One row per beam v3 finding, including unlabelled items.
    """

    if not BEAMV3_RESULTS_PATH.exists():
        return []
    payload: object = json.loads(BEAMV3_RESULTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, object]] = []
    for item in _as_dict_list(payload.get("findings")):
        rows.append(
            {
                "id": item.get("id", ""),
                "repo": item.get("repo", ""),
                "pass": item.get("pass", ""),
                "doc_path": item.get("doc_path", ""),
                "doc_line": item.get("doc_line", ""),
                "code": item.get("code", ""),
                "label": item.get("label", "unlabelled"),
                "drift_id": item.get("drift_id", ""),
                "label_by": item.get("label_by", ""),
                "label_evidence": strip_local_paths(str(item.get("label_evidence") or "")),
                "hand_verdict": item.get("label", "unlabelled"),
                "hand_verdict_description": LABEL_SOURCE,
                "new_vs_hybrid": bool(item.get("new_vs_hybrid")),
                "repro_status": item.get("repro_status"),
                "strict_confirmed": bool(item.get("strict_confirmed", False)),
                "explanation": strip_local_paths(str(item.get("explanation") or "")),
            }
        )
    return rows


def _token_ledger() -> list[dict[str, object]]:
    """
    @brief Combined hybrid + recall + ablation + beamv3 + matched-cost + fresh-run token ledger rows.
    """

    rows: list[dict[str, object]] = []
    rows.extend(_first_sweep_ledger_rows())
    for source, path in (
        ("hybrid", LEDGER_PATH),
        ("ablation", ABLATION_LEDGER_PATH),
        ("beamv3", BEAMV3_LEDGER_PATH),
        ("matched_cost", MATCHED_COST_LEDGER_PATH),
        ("matched_cost_ext", MATCHED_COST_EXT_LEDGER_PATH),
    ):
        if not path.exists():
            continue
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        entries: list[dict[str, object]] = []
        if isinstance(payload, dict):
            entries = _as_dict_list(payload.get("entries") or payload.get("rows"))
        elif isinstance(payload, list):
            entries = [row for row in payload if isinstance(row, dict)]
        for entry in entries:
            row = dict(entry)
            row["ledger"] = source
            rows.append(row)
    if FRESH_RUN_FINDINGS_PATH.exists():
        payload = json.loads(FRESH_RUN_FINDINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {}
            rows.append(
                {
                    "kind": "triage",
                    "label": str(payload.get("repo") or "tomlkit"),
                    "prompt": int(tokens.get("triage_prompt") or 0),
                    "completion": int(tokens.get("triage_completion") or 0),
                    "ledger": "fresh_run",
                }
            )
            rows.append(
                {
                    "kind": "repro",
                    "label": str(payload.get("repo") or "tomlkit"),
                    "prompt": int(tokens.get("repro_prompt") or 0),
                    "completion": int(tokens.get("repro_completion") or 0),
                    "ledger": "fresh_run",
                }
            )
    return rows


def _first_sweep_ledger_rows() -> list[dict[str, object]]:
    """
    @brief Per-library first-sweep tokens from results_live/traces/*-400000.json summaries.
    """

    libraries = (
        "starlette",
        "httpx",
        "click",
        "structlog",
        "nox",
        "arrow",
        "cattrs",
        "marshmallow",
        "attrs",
        "jinja",
        "werkzeug",
        "pydantic-settings",
    )
    rows: list[dict[str, object]] = []
    traces = RESULTS_LIVE_DIRECTORY / "traces"
    for library in libraries:
        path = traces / f"{library}-400000.json"
        if not path.exists():
            continue
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        prompt = int(summary.get("input_tokens") or 0)
        completion = int(summary.get("output_tokens") or 0)
        if prompt + completion <= 0:
            continue
        rows.append(
            {
                "kind": "whole_repo",
                "label": library,
                "prompt": prompt,
                "completion": completion,
                "ledger": "first_sweep",
            }
        )
    return rows


def _write_table(target: Path, name: str, rows: list[dict[str, object]]) -> None:
    """
    @brief Write jsonl always and parquet when pyarrow is available.
    """

    jsonl = target / f"{name}.jsonl"
    with jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    try:
        import pandas as pd

        frame = pd.DataFrame(rows)
        frame.to_parquet(target / f"{name}.parquet", index=False)
    except Exception:
        (target / f"{name}.parquet.skipped").write_text(
            "pyarrow/pandas parquet write unavailable; jsonl is the source of truth.\n",
            encoding="utf-8",
        )


def _card(
    stats: object,
    findings: list[dict[str, object]],
    verdicts: list[dict[str, object]],
    repros: list[dict[str, object]],
    plants: list[dict[str, object]],
    ablation: list[dict[str, object]],
    ext_verdicts: list[dict[str, object]],
    beamv3: list[dict[str, object]],
    ledger: list[dict[str, object]],
) -> str:
    """
    @brief sdk-free dataset card with YAML configs.
    """

    hybrid_true = stats["hybrid_true"] if isinstance(stats, dict) else ""
    repro_true = stats["repro_true"] if isinstance(stats, dict) else ""
    ext_cross = sum(1 for row in ext_verdicts if row.get("cross_file"))
    ext_outside = sum(1 for row in ext_verdicts if row.get("gold_outside_local"))
    return f"""---
pretty_name: DocDrift bugs
configs:
  - config_name: findings
    data_files: findings.parquet
  - config_name: triage_verdicts
    data_files: triage_verdicts.parquet
  - config_name: repros
    data_files: repros.parquet
  - config_name: planted_drift
    data_files: planted_drift.parquet
  - config_name: ablation_verdicts
    data_files: ablation_verdicts.parquet
  - config_name: matched_cost_ext_verdicts
    data_files: matched_cost_ext_verdicts.parquet
  - config_name: beamv3_findings
    data_files: beamv3_findings.parquet
  - config_name: token_ledger
    data_files: token_ledger.parquet
license: cc-by-4.0
size_categories:
  - n<1K
task_categories:
  - text-classification
language:
  - en
tags:
  - code
  - documentation
  - long-context
  - beam
  - docdrift
---

# DocDrift bugs: docs-vs-code drifts in 12 Python libraries, found with Beam

DocDrift gives Beam a whole Python library (docs + code, up to ~400k tokens) in one call. A free AST symbol check proposes name and signature mismatches. Beam triages those candidates against the packed repo, can add cross-file or prose drift, and writes a script that runs the documented usage. A finding counts as reproduced only if that script raises TypeError, AttributeError, ImportError, or NameError on a documented-usage line.

This dataset is the recorded output of that pipeline on 12 pinned libraries. {hybrid_true} real docs bugs were found in 11 of the 12 libraries; {repro_true} reproduce. Labels were {LABEL_SOURCE}, not a human annotator. The stored field is still named `hand_verdict`.

**Licence.** DocDrift's own labels, verdicts, and notes are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Quoted documentation and source excerpts remain under each library's own licence (all 12 are permissive OSS).

```python
from datasets import load_dataset
ds = load_dataset("ollymcbride4/docdrift-bugs", "findings")
```

- Space: {PUBLIC_SPACE_URL}
- Demo video: {PUBLIC_VIDEO_URL}
- Code: {PUBLIC_CODE_URL}
- Dataset: {PUBLIC_DATASET_URL}
- HF thread: {PUBLIC_THREAD_URL}

## How it was built

1. Pin each library to a recorded commit.
2. Pack docs + source up to a 400k token cap.
3. Run a free symbol check, then one whole-repo Beam triage call per library (11 of 12 succeeded in one call; structlog failed; cattrs needed 2).
4. Beam-written repro scripts, plus one hand-written starlette script from Beam's verdict.
5. Citation check is quote alignment of cited lines vs packed source (±3-line shift). It is not a verdict that the drift is real.

## Configs

| config | rows | what it is | fields |
|---|---:|---|---|
| findings | {len(findings)} | Hybrid method items (the 60 findings) | `repo`, `id`, `kind`, `verdict`, `drift_id`, `beam`, `strict_confirmed`, `repro_status`, `evidence`, `hand_verdict`, `hand_verdict_description` |
| triage_verdicts | {len(verdicts)} | Beam triage verdicts (56 judged) | `repo`, `candidate_id`, `source_id`, `verdict`, `reason`, `code_path`, `code_line`, `code_quote` |
| repros | {len(repros)} | Executable repro cases | `case_id`, `repo`, `status`, `strict_confirmed`, `exception_type`, `error_excerpt`, `evidence` |
| planted_drift | {len(plants)} | Planted-drift set + ground truth | original probe fields plus `seed` |
| ablation_verdicts | {len(ablation)} | Whole-repo vs local-file vs matched-cost retrieval triage on the same 56 candidates | `key`, `repo`, `candidate_id`, `label`, `hand_verdict`, `hand_verdict_description`, `cross_file`, `gold_outside_local`, `whole_verdict`, `local_verdict`, `matched_verdict`, `stability_verdict`, citation flags |
| matched_cost_ext_verdicts | {len(ext_verdicts)} | Scored pre-registered extension items only ({len(ext_verdicts)} rows in this file; {ext_cross} cross-file, {ext_outside} outside-local). Pooled 52/78 includes the original 56 from `ablation_verdicts`; those original rows are not duplicated here. | `key`, `set`, `stratum`, `label`, `hand_verdict`, `cross_file`, `gold_outside_local`, per-arm `whole_` / `local_` / `matched_` verdicts and citations |
| beamv3_findings | {len(beamv3)} | Extra 32k-docstring-chunk and docs-pass findings (unlabelled not counted as true) | `id`, `repo`, `pass`, `doc_path`, `doc_line`, `label`, `drift_id`, `label_by`, `hand_verdict`, `hand_verdict_description`, `new_vs_hybrid`, `strict_confirmed`, `explanation` |
| token_ledger | {len(ledger)} | Hybrid + first-sweep + ablation + extra-pass token ledger | original ledger fields plus `ledger` (`first_sweep`, `hybrid`, `ablation`, `beamv3`, `matched_cost`, `matched_cost_ext`, `fresh_run`) |

`hand_verdict` means {LABEL_SOURCE}. It is not a human annotator.

## Limits

- The 45-drift universe is the union of method output, so it favours those methods. The 45 true hybrid findings are a different set from those 45 pooled drifts.
- 11 of 12 libraries were triaged; structlog failed; cattrs needed 2 calls.
- 2 false + 1 unclear received a strict badge (werkzeug S38, S39 false; S41 unclear).
- End-to-end including repro is 9,302,105 (~9.3M) = 4,424,575 first sweep + 4,739,392 hybrid triage + 138,138 repro. The first sweep is in `token_ledger` as `ledger=first_sweep` (12 rows from the recorded 400k traces).
- Extra experimental runs, not in the 9.3M: ablation 1,948,469; beam v3 7,713,453; matched-cost control 3,957,434; matched-cost extension 7,528,878; tomlkit CLI run 185,842. Matched-cost controls plus the recording: 11,672,154.
- Long context did not change verdict accuracy on these 56 candidates; it changed citation grounding. A matched-cost retrieval control (96.7% of whole-repo spend) matched accuracy (46/56 vs 47/56) but not grounding (cross-file 19/30 vs 25/30; McNemar p = 0.070, not shown at this n). Retrieval missed the defining file in 5 of 13 outside-local items. A pre-registered extension added 63 items (57 planted renames, 6 real structlog). Pooled, retrieval grounded 38/78 cross-file cases vs 52/78 for the whole repo (McNemar p = 0.0094). Outside-local: 38/61 vs 25/61 (p = 0.0146). Accuracy still did not differ (105/118 vs 108/119). The new items alone give p = 0.096 (not shown at this n), and the pooled p is 0.18 without one pre-registered parse-failure re-send. Pre-registration: design_ext.md sha256 42f6b6fe…c996.
- 32k docstring chunks recovered 7 of 11 hybrid misses; the docs pass recovered 1. New-item precision is a lower bound (18.5% for hybrid + 32k chunks). Headline stays 34 of 45.

## Citation

DocDrift bugs: docs-vs-code drifts in 12 Python libraries, found with Beam. Labels by an AI reviewer against source at the pinned commit. Dataset: {PUBLIC_DATASET_URL}
"""
