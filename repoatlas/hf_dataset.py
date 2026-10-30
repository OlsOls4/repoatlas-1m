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

    hybrid_true = stats["hybrid_true"] if isinstance(stats, dict) else ""
    repro_true = stats["repro_true"] if isinstance(stats, dict) else ""
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
  - config_name: beamv3_findings
    data_files: beamv3_findings.parquet
  - config_name: token_ledger
    data_files: token_ledger.parquet
license: cc-by-4.0
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
| ablation_verdicts | {len(ablation)} | Whole-repo vs local-file triage on the same 56 candidates | `key`, `repo`, `candidate_id`, `label`, `hand_verdict`, `hand_verdict_description`, `cross_file`, `gold_outside_local`, `whole_verdict`, `local_verdict`, `stability_verdict`, citation flags |
| beamv3_findings | {len(beamv3)} | Extra 32k-docstring-chunk and docs-pass findings (unlabelled not counted as true) | `id`, `repo`, `pass`, `doc_path`, `doc_line`, `label`, `drift_id`, `label_by`, `hand_verdict`, `hand_verdict_description`, `new_vs_hybrid`, `strict_confirmed`, `explanation` |
| token_ledger | {len(ledger)} | Hybrid + recall + ablation + extra-pass token ledger | original ledger fields plus `ledger` (`hybrid`, `recall`, `ablation`, `beamv3`) |

`hand_verdict` means {LABEL_SOURCE}. It is not a human annotator.

## Limits

- The 45-drift universe is the union of method output, so it favours those methods.
- 11 of 12 libraries were triaged; structlog failed; cattrs needed 2 calls.
- 2 false + 1 unclear received a strict badge (werkzeug S38, S39 false; S41 unclear).
- End-to-end including repro is 9,302,105 (~9.3M) = 4,424,575 + 4,739,392 + 138,138.
- Ablation ledger (local + stability, not in that 9.3M): 1,948,469 tokens over 60 calls.
- Extra coverage-pass ledger (docs + 32k chunks + stability + repro, not in that 9.3M): 7,713,453 tokens over 168 calls.
- Long context did not change verdict accuracy on these 56 candidates; it changed citation grounding.
- 32k docstring chunks recovered 7 of 11 hybrid misses; the docs pass recovered 1. New-item precision is a lower bound (18.5% for hybrid + 32k chunks). Headline stays 34 of 45.

## Citation

DocDrift bugs: docs-vs-code drifts in 12 Python libraries, found with Beam. Labels by an AI reviewer against source at the pinned commit. Dataset: https://huggingface.co/datasets/ollymcbride4/docdrift-bugs
"""
