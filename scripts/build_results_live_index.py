"""Build compact live-result indexes and dataset exports for RepoAtlas-1M."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil

import pandas as pd


RESULTS_LIVE_DIRECTORY: Path = Path("results_live")
DATASET_DIRECTORY: Path = Path("dataset")
INDEX_PATH: Path = RESULTS_LIVE_DIRECTORY / "index.json"
BENCHMARK_COMBINED_PATH: Path = RESULTS_LIVE_DIRECTORY / "benchmark_results_combined.csv"
HANDCHECK_PATH: Path = RESULTS_LIVE_DIRECTORY / "handcheck.md"
TRACES_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "traces"


@dataclass(slots=True)
class HandVerdict:
    """
    @brief Hand-checked verdict for one finding.
    @param verdict One of true, false, or unclear.
    @param notes Short human-verification note.
    @param upstream_status Optional upstream filing status note.
    """

    verdict: str
    notes: str
    upstream_status: str = ""


HAND_VERDICTS: dict[str, HandVerdict] = {
    "flask-120000-replay/DD-1": HandVerdict(
        verdict="false",
        notes="False positive: implicit secure behaviour is implemented in Werkzeug.",
    ),
    "starlette-400000/DD-1": HandVerdict(
        verdict="true",
        notes="True drift: docs show receive_json(data, mode=...) but code takes no data argument.",
        upstream_status="fixed upstream in starlette PR #3746",
    ),
    "hatch-400000/DD-1": HandVerdict(
        verdict="unclear",
        notes="Unclear: documentation is correct for pip default, but incomplete for uv installer mode.",
    ),
    "poetry-400000/DD-1": HandVerdict(
        verdict="false",
        notes="False positive: example requires-python value is illustrative and still valid.",
    ),
    "httpx-400000/DD-1": HandVerdict(
        verdict="true",
        notes="True drift: docs use non-existent httpx.Mounts; correct API is Client(mounts=...).",
        upstream_status="independently confirmed by an open upstream PR",
    ),
    "httpx-400000/DD-2": HandVerdict(
        verdict="true",
        notes="True drift: docstring still shows removed Client(app=...) shortcut.",
    ),
    "click-400000/DD-1": HandVerdict(
        verdict="true",
        notes="True drift: docs reference non-existent FileType class.",
    ),
    "pydantic-settings-400000/DD-1": HandVerdict(
        verdict="false",
        notes="False positive: docs describe behaviour of cli_kebab_case=True, not the default value.",
    ),
    "structlog-400000/DD-1": HandVerdict(
        verdict="false",
        notes="False positive: docs provide a subset of accepted names, not a contradiction.",
    ),
    "structlog-400000/DD-2": HandVerdict(
        verdict="true",
        notes="True drift: docs point to non-existent stdlib mapping paths.",
    ),
    "jinja-400000/DD-1": HandVerdict(
        verdict="unclear",
        notes="Unclear: effective default remains false through fallback despite signature difference.",
    ),
    "nox-400000/DD-1": HandVerdict(
        verdict="true",
        notes="True drift: docs use reuse_venvs, but option name is reuse_venv.",
    ),
    "arrow-400000/DD-1": HandVerdict(
        verdict="true",
        notes="True drift: docstring uses timestring but parameter is input_string.",
        upstream_status="independently confirmed by an open upstream PR",
    ),
    "arrow-400000/DD-2": HandVerdict(
        verdict="false",
        notes="False positive: locale aliases en-us and en_us are normalised.",
    ),
    "arrow-400000/DD-3": HandVerdict(
        verdict="false",
        notes="False positive: parsing token behaviour aligns with parser implementation.",
    ),
    "arrow-400000/DD-4": HandVerdict(
        verdict="false",
        notes="False positive: parsing token behaviour aligns with parser implementation.",
    ),
    "cattrs-400000/DD-1": HandVerdict(
        verdict="true",
        notes="True drift: docs use ForbiddenExtraKeyError instead of ForbiddenExtraKeysError.",
    ),
    "cattrs-400000/DD-2": HandVerdict(
        verdict="true",
        notes="True drift: docs mention cache parameter, implementation uses cache_result.",
    ),
    "cattrs-400000/DD-3": HandVerdict(
        verdict="true",
        notes="True drift: docs mention cache parameter, implementation uses cache_result.",
    ),
    "marshmallow-400000/DD-1": HandVerdict(
        verdict="false",
        notes="False positive: kwargs forwarding in documentation remains reachable and valid.",
    ),
    "marshmallow-400000/DD-2": HandVerdict(
        verdict="true",
        notes="True drift: docs mention removed default parameter, should be load_default.",
    ),
    "werkzeug-400000/DD-1": HandVerdict(
        verdict="false",
        notes="False positive: historical note does not contradict current restored behaviour.",
    ),
}


def main() -> None:
    """
    @brief Build index.json and dataset/ export files from results_live artefacts.
    """

    benchmark_df: pd.DataFrame = pd.read_csv(BENCHMARK_COMBINED_PATH)
    findings: list[dict[str, object]] = _build_findings_index()
    sweep_case_names: set[str] = set(
        str(case_name)
        for case_name in benchmark_df[benchmark_df.get("batch", "") == "sweep 2026-10-26"]["case_name"].tolist()
    )
    summary: dict[str, object] = _build_summary(findings, sweep_case_names)
    runs: list[dict[str, object]] = _clean_records(benchmark_df.to_dict(orient="records"))
    index_payload: dict[str, object] = {
        "summary": summary,
        "runs": runs,
        "findings": findings,
        "handcheck_markdown_path": str(HANDCHECK_PATH),
    }
    INDEX_PATH.write_text(json.dumps(index_payload, indent=2), encoding="utf-8")
    _build_dataset_export(index_payload=index_payload, findings=findings, runs=runs)
    print(f"Wrote {INDEX_PATH} and dataset export in {DATASET_DIRECTORY}")


def _build_findings_index() -> list[dict[str, object]]:
    """
    @brief Extract finding metadata from live traces and the flask replay payload.
    """

    trace_cases: list[tuple[str, Path]] = sorted(
        [(trace_path.stem, trace_path) for trace_path in TRACES_DIRECTORY.glob("*.json")]
    )
    findings: list[dict[str, object]] = []
    for case_name, trace_path in trace_cases:
        findings.extend(_extract_findings_from_trace(case_name=case_name, trace_path=trace_path))
    ordered_findings: list[dict[str, object]] = sorted(
        findings,
        key=lambda item: (str(item.get("case_name", "")), str(item.get("finding_id", ""))),
    )
    return ordered_findings


def _extract_findings_from_trace(case_name: str, trace_path: Path) -> list[dict[str, object]]:
    """
    @brief Extract finding cards from one trace JSON file.
    @param case_name Benchmark case name.
    @param trace_path Path to one trace JSON file.
    """

    payload: dict[str, object] = json.loads(trace_path.read_text(encoding="utf-8"))
    summary: dict[str, object] = _as_dict(payload.get("summary"))
    output: dict[str, object] = _as_dict(payload.get("output"))
    verification_results: list[dict[str, object]] = _as_dict_list(payload.get("verification_results"))
    verification_map: dict[str, dict[str, object]] = {
        str(item.get("finding_id", "")): item for item in verification_results
    }
    findings: list[dict[str, object]] = []
    for finding in _as_dict_list(output.get("findings")):
        finding_id: str = str(finding.get("finding_id", ""))
        key: str = f"{case_name}/{finding_id}"
        hand: HandVerdict | None = HAND_VERDICTS.get(key)
        verifier: dict[str, object] = verification_map.get(finding_id, {})
        doc_citation: dict[str, object] = _as_dict(finding.get("doc_citation"))
        code_citation: dict[str, object] = _as_dict(finding.get("code_citation"))
        findings.append(
            {
                "finding_key": key,
                "case_name": case_name,
                "repo_url": summary.get("repo_url", ""),
                "ref": summary.get("ref", ""),
                "finding_id": finding_id,
                "drift_kind": finding.get("drift_kind", ""),
                "explanation": finding.get("explanation", ""),
                "doc_citation": doc_citation,
                "code_citation": code_citation,
                "doc_quote": doc_citation.get("quote", ""),
                "code_quote": code_citation.get("quote", ""),
                "verifier_fully_verified": bool(verifier.get("fully_verified", False)),
                "verifier_doc_reason": _as_dict(verifier.get("doc_check")).get("reason", ""),
                "verifier_code_reason": _as_dict(verifier.get("code_check")).get("reason", ""),
                "hand_verdict": hand.verdict if hand else "unknown",
                "hand_notes": hand.notes if hand else "No hand verdict recorded in results_live/handcheck.md.",
                "upstream_status": hand.upstream_status if hand else "",
                "input_tokens": summary.get("input_tokens", 0),
                "latency_seconds": summary.get("latency_seconds", 0.0),
                "atlas_claims_total": summary.get("atlas_claims_total", 0),
                "atlas_citations_verified": summary.get("atlas_citations_verified", 0),
            }
        )
    return findings


def _build_summary(findings: list[dict[str, object]], sweep_case_names: set[str]) -> dict[str, object]:
    """
    @brief Compute accuracy and verifier summary metrics from finding rows.
    @param findings Finding rows.
    """

    true_count: int = sum(1 for finding in findings if finding.get("hand_verdict") == "true")
    false_count: int = sum(1 for finding in findings if finding.get("hand_verdict") == "false")
    unclear_count: int = sum(1 for finding in findings if finding.get("hand_verdict") == "unclear")
    judged_count: int = true_count + false_count + unclear_count
    sweep_findings: list[dict[str, object]] = [
        finding for finding in findings if str(finding.get("case_name", "")) in sweep_case_names
    ]
    verifier_caught_false_count: int = sum(
        1
        for finding in sweep_findings
        if finding.get("hand_verdict") == "false" and not bool(finding.get("verifier_fully_verified", False))
    )
    verifier_false_total_count: int = sum(
        1 for finding in sweep_findings if finding.get("hand_verdict") == "false"
    )
    verifier_rejected_true_count: int = sum(
        1
        for finding in sweep_findings
        if finding.get("hand_verdict") == "true" and not bool(finding.get("verifier_fully_verified", False))
    )
    precision: float = (true_count / judged_count) if judged_count else 0.0
    return {
        "true_count": true_count,
        "false_count": false_count,
        "unclear_count": unclear_count,
        "judged_count": judged_count,
        "precision": precision,
        "verifier_caught_false_count": verifier_caught_false_count,
        "verifier_false_total_count": verifier_false_total_count,
        "verifier_rejected_true_count": verifier_rejected_true_count,
    }


def _build_dataset_export(
    index_payload: dict[str, object], findings: list[dict[str, object]], runs: list[dict[str, object]]
) -> None:
    """
    @brief Write dataset README and JSONL exports, including full traces.
    @param index_payload Top-level index payload.
    @param findings Findings list.
    @param runs Run list.
    """

    DATASET_DIRECTORY.mkdir(parents=True, exist_ok=True)
    _write_dataset_readme(index_payload=index_payload)
    _write_jsonl(DATASET_DIRECTORY / "findings.jsonl", findings)
    _write_jsonl(DATASET_DIRECTORY / "runs.jsonl", runs)
    handcheck_text: str = HANDCHECK_PATH.read_text(encoding="utf-8")
    (DATASET_DIRECTORY / "handcheck.md").write_text(handcheck_text, encoding="utf-8")
    shutil.copy2(BENCHMARK_COMBINED_PATH, DATASET_DIRECTORY / "benchmark_results_combined.csv")
    shutil.copy2(RESULTS_LIVE_DIRECTORY / "benchmark_results.csv", DATASET_DIRECTORY / "benchmark_results.csv")
    shutil.copy2(RESULTS_LIVE_DIRECTORY / "benchmark_results.jsonl", DATASET_DIRECTORY / "benchmark_results.jsonl")
    shutil.copy2(RESULTS_LIVE_DIRECTORY / "hand_check_sheet.csv", DATASET_DIRECTORY / "hand_check_sheet.csv")
    traces_target: Path = DATASET_DIRECTORY / "traces"
    if traces_target.exists():
        shutil.rmtree(traces_target)
    shutil.copytree(TRACES_DIRECTORY, traces_target)
    drafts_target: Path = DATASET_DIRECTORY / "upstream_drafts"
    if drafts_target.exists():
        shutil.rmtree(drafts_target)
    shutil.copytree(RESULTS_LIVE_DIRECTORY / "upstream_drafts", drafts_target)


def _write_dataset_readme(index_payload: dict[str, object]) -> None:
    """
    @brief Write the dataset card README in HF-ready markdown format.
    @param index_payload Top-level index payload.
    """

    summary: dict[str, object] = _as_dict(index_payload.get("summary"))
    true_count: int = int(summary.get("true_count", 0))
    judged_count: int = int(summary.get("judged_count", 0))
    false_count: int = int(summary.get("false_count", 0))
    unclear_count: int = int(summary.get("unclear_count", 0))
    precision: float = float(summary.get("precision", 0.0))
    readme_text: str = (
        "---\n"
        "pretty_name: RepoAtlas-1M Live DocDrift Results (Oct 2026)\n"
        "task_categories:\n"
        "  - text-classification\n"
        "  - summarization\n"
        "language:\n"
        "  - en\n"
        "tags:\n"
        "  - beam\n"
        "  - long-context\n"
        "  - docs\n"
        "  - code\n"
        "---\n\n"
        "# RepoAtlas-1M live results dataset export\n\n"
        "This folder is prepared for a companion Hugging Face dataset publication.\n\n"
        f"- Hand-checked precision across all live findings: **{true_count}/{judged_count} = {precision * 100:.1f}%**\n"
        f"- Breakdown: true={true_count}, false={false_count}, unclear={unclear_count}\n"
        "- Full run narrative and caveats are in `handcheck.md`.\n\n"
        "## Files\n\n"
        "- `runs.jsonl`: one row per run from `results_live/benchmark_results_combined.csv`\n"
        "- `findings.jsonl`: one row per finding with verifier and hand verdict labels\n"
        "- `traces/`: full raw trace JSON payloads (large; include pack text)\n"
        "- `upstream_drafts/`: unfiled upstream issue/PR draft notes\n\n"
        "## Notes\n\n"
        "- `verifier_fully_verified=true` means cited snippets matched pack text; it does not prove a finding is correct.\n"
        "- `hand_verdict` is the source of truth for precision reporting.\n"
    )
    (DATASET_DIRECTORY / "README.md").write_text(readme_text, encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """
    @brief Write records to JSONL.
    @param path Output file path.
    @param rows Record list.
    """

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_clean_value(row)) + "\n")


def _clean_records(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """
    @brief Replace non-JSON NaN values in row dictionaries with null.
    @param rows Input records.
    """

    return [_clean_value(row) for row in rows]


def _clean_value(value: object) -> object:
    """
    @brief Recursively replace non-JSON values such as NaN with serialisable values.
    @param value Input object.
    """

    if isinstance(value, dict):
        return {key: _clean_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    if isinstance(value, float) and value != value:
        return None
    return value


def _as_dict(value: object) -> dict[str, object]:
    """
    @brief Convert an unknown value to dictionary.
    @param value Input value.
    """

    if isinstance(value, dict):
        return value
    return {}


def _as_dict_list(value: object) -> list[dict[str, object]]:
    """
    @brief Convert an unknown value to list of dictionaries.
    @param value Input value.
    """

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


if __name__ == "__main__":
    main()
