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
RECALL_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "recall" / "usage_ledger.json"
ABLATION_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "results.json"
ABLATION_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "beam_usage_ledger.json"
BEAMV3_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "beamv3" / "results.json"
BEAMV3_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "beamv3" / "beam_usage_ledger.json"
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
    beamv3 = _beamv3_findings()
    ledger = _token_ledger()
    _write_table(target, "findings", findings)
    _write_table(target, "triage_verdicts", verdicts)
    _write_table(target, "repros", repros)
    _write_table(target, "planted_drift", plants)
    _write_table(target, "ablation_verdicts", ablation)
    _write_table(target, "beamv3_findings", beamv3)
    _write_table(target, "token_ledger", ledger)
    (target / "README.md").write_text(
        _card(stats, findings, verdicts, repros, plants, ablation, beamv3, ledger), encoding="utf-8"
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
    rows: list[dict[str, object]] = []
    for item in _as_dict_list(payload.get("rows")):
        whole = _as_dict(item.get("whole"))
        local = _as_dict(item.get("local"))
        stability = _as_dict(item.get("stability")) if item.get("stability") else {}
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
                "stability_verdict": stability.get("verdict"),
                "whole_cite_correct": whole.get("cite_correct"),
                "local_cite_correct": local.get("cite_correct"),
                "whole_cite_verified": whole.get("cite_verified"),
                "local_cite_verified": local.get("cite_verified"),
            }
        )
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
    @brief Combined hybrid + recall + ablation + beamv3 token ledger rows.
    """

    rows: list[dict[str, object]] = []
    for source, path in (
        ("hybrid", LEDGER_PATH),
        ("recall", RECALL_LEDGER_PATH),
        ("ablation", ABLATION_LEDGER_PATH),
        ("beamv3", BEAMV3_LEDGER_PATH),
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
    beamv3: list[dict[str, object]],
    ledger: list[dict[str, object]],
) -> str:
    """
    @brief sdk-free dataset card with YAML configs.
    """

    return f"""---
pretty_name: DocDrift v2
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
  - config_name: beamv3_findings
    data_files: beamv3_findings.parquet
  - config_name: token_ledger
    data_files: token_ledger.parquet
license: other
task_categories:
  - text-classification
language:
  - en
tags:
  - docdrift
  - beam
  - long-context
  - docs
  - code
---

# DocDrift v2

Unpublished companion dataset for RepoAtlas-1M. Numbers come from `results_live/`. This card is sdk-free.

## Splits

| file | rows | meaning |
|---|---|---|
| findings.jsonl / .parquet | {len(findings)} | Hybrid method items (the 60 findings) |
| triage_verdicts.jsonl / .parquet | {len(verdicts)} | Beam triage verdicts (56 judged) |
| repros.jsonl / .parquet | {len(repros)} | Executable repro cases (54) |
| planted_drift.jsonl / .parquet | {len(plants)} | Planted-drift set + ground truth |
| ablation_verdicts.jsonl / .parquet | {len(ablation)} | Whole-repo vs local-file triage on the same 56 candidates |
| beamv3_findings.jsonl / .parquet | {len(beamv3)} | Docs-pass + py32k findings with labels (unlabelled not counted as true) |
| token_ledger.jsonl / .parquet | {len(ledger)} | Hybrid + recall + ablation + beamv3 token ledger |

## Fields

- `hand_verdict`: stored field name. **Description:** {LABEL_SOURCE}. Not a human annotator.
- `verdict` / `strict_confirmed` / `repro_status`: from `hybrid.json` and `repros.json`.
- `label` on beamv3_findings: existing labelled set, AI source-check, or unlabelled. Unlabelled is not true.
- Citation fields are quote alignment only, including line-shifted matches (±3 lines).

## Limits

- The 45-drift universe is the union of method output.
- 11 of 12 libraries were triaged; structlog failed; cattrs needed 2 calls.
- 2 false + 1 unclear received a strict badge (werkzeug S38, S39 false; S41 unclear).
- End-to-end including repro is 9,302,105 (~9.3M) = 4,424,575 + 4,739,392 + 138,138.
- Ablation ledger (local + stability, not in that 9.3M): 1,948,469 tokens over 60 calls.
- Beam v3 ledger (docs + py32k + stability + repro, not in that 9.3M): 7,713,453 tokens over 168 calls.
- Long context did not change verdict accuracy on these 56 candidates; it changed citation grounding.
- Adding py32k recovered 7 of 11 hybrid misses; the docs pass recovered 1. New-item precision is a lower bound (18.5% for hybrid+py32k). Headline stays 34 of 45.

"""
