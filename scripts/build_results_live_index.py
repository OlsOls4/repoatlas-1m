"""Build compact live-result indexes and dataset exports for RepoAtlas-1M."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
from statistics import median
from typing import TypedDict

import pandas as pd
import tiktoken


RESULTS_LIVE_DIRECTORY: Path = Path("results_live")
DATASET_DIRECTORY: Path = Path("dataset")
INDEX_PATH: Path = RESULTS_LIVE_DIRECTORY / "index.json"
BENCHMARK_COMBINED_PATH: Path = RESULTS_LIVE_DIRECTORY / "benchmark_results_combined.csv"
HANDCHECK_PATH: Path = RESULTS_LIVE_DIRECTORY / "handcheck.md"
TRACES_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "traces"
UPSTREAM_STATUS_PATH: Path = RESULTS_LIVE_DIRECTORY / "upstream_status.json"
REVERIFY_LINE_SHIFT_PATH: Path = RESULTS_LIVE_DIRECTORY / "reverify_line_shift.json"
UPSTREAM_DRAFTS_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "upstream_drafts"
FILTER_SIGNATURE: str = "v4"
SHA_PATTERN: re.Pattern[str] = re.compile(r"^[0-9a-f]{7,40}$")


class UpstreamStatus(TypedDict):
    """
    @brief Typed upstream status payload for one finding.
    @param repo Canonical repository URL.
    @param finding Finding key in the form case/finding_id.
    @param status Human-readable status string.
    @param url Upstream PR or issue URL.
    @param checked_at Timestamp when status was checked.
    """

    repo: str
    finding: str
    status: str
    url: str
    checked_at: str


class TraceRecord(TypedDict):
    """
    @brief Parsed trace payload and source path.
    @param path Trace JSON path.
    @param payload Parsed trace payload.
    """

    path: str
    payload: dict[str, object]


@dataclass(slots=True)
class HandVerdict:
    """
    @brief Hand-checked verdict for one finding.
    @param verdict One of true, false, or unclear.
    @param notes Short human-verification note.
    """

    verdict: str
    notes: str


HAND_VERDICTS: dict[str, HandVerdict] = {
    "starlette-400000/DD-1": HandVerdict(
        verdict="true",
        notes="True drift: docs show receive_json(data, mode=...) but code takes no data argument.",
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


BREAKAGE_SUMMARIES: dict[str, str] = {
    "starlette-400000/DD-1": "Following the docs can raise TypeError for multiple values of mode.",
    "httpx-400000/DD-1": "Following the docs raises AttributeError: module 'httpx' has no attribute 'Mounts'.",
    "httpx-400000/DD-2": "Following the docstring raises TypeError: unexpected keyword argument 'app'.",
    "click-400000/DD-1": "Docs reference a non-existent FileType symbol, breaking class links and examples.",
    "structlog-400000/DD-2": "Documented symbol path does not exist, so direct lookup fails.",
    "nox-400000/DD-1": "Using the documented option name raises AttributeError in Noxfile configuration.",
    "arrow-400000/DD-1": "Using timestring= as documented raises TypeError for unexpected keyword argument.",
    "cattrs-400000/DD-1": "Catching the documented exception name fails because the class does not exist.",
    "cattrs-400000/DD-2": "Using cache= as documented raises TypeError; parameter is cache_result.",
    "cattrs-400000/DD-3": "Using cache= as documented raises TypeError; parameter is cache_result.",
    "marshmallow-400000/DD-2": "Using default= as documented raises TypeError in marshmallow 4.x.",
}

FINDING_DRAFT_FILE_BY_KEY: dict[str, str] = {
    "starlette-400000/DD-1": "starlette-receive_json.md",
    "httpx-400000/DD-1": "httpx-transports-mounts.md",
    "httpx-400000/DD-2": "httpx-wsgitransport-app-arg.md",
    "click-400000/DD-1": "click-fileerror-filetype.md",
    "structlog-400000/DD-2": "structlog-name-to-level-path.md",
    "nox-400000/DD-1": "nox-reuse-venvs-typo.md",
    "arrow-400000/DD-1": "arrow-dehumanize-param.md",
    "cattrs-400000/DD-1": "cattrs-forbidden-extra-key-error.md",
    "cattrs-400000/DD-2": "cattrs-get-hook-cache-param.md",
    "cattrs-400000/DD-3": "cattrs-get-hook-cache-param.md",
    "marshmallow-400000/DD-2": "marshmallow-missing-load-default.md",
}

CASE_REF_OVERRIDES: dict[str, str] = {
    "starlette-400000": "8aa828c",
}


# Private function prototypes:
# - _load_trace_records() -> dict[str, TraceRecord]
# - _load_reverify_map() -> dict[str, dict[str, object]]
# - _enrich_runs_with_trace_data(runs: list[dict[str, object]], trace_records: dict[str, TraceRecord], reverify_map: dict[str, dict[str, object]]) -> list[dict[str, object]]
# - _build_findings_index(upstream_by_finding: dict[str, UpstreamStatus], trace_records: dict[str, TraceRecord], reverify_map: dict[str, dict[str, object]]) -> list[dict[str, object]]
# - _extract_findings_from_trace(case_name: str, trace_payload: dict[str, object], trace_path: Path, upstream_by_finding: dict[str, UpstreamStatus], reverify_payload: dict[str, object] | None) -> list[dict[str, object]]
# - _build_finding_permalink(repo_url: str, ref_value: str, citation: dict[str, object], case_name: str) -> str
# - _normalise_ref(case_name: str, ref_value: str) -> str
# - _build_issue_draft(finding_key: str) -> tuple[str, str]
# - _verifier_label(verifier_payload: dict[str, object]) -> str
# - _verified_line(verification_check: dict[str, object], fallback: int) -> int
# - _coerce_int(value: object, fallback: int = 0) -> int
# - _as_str_list(value: object) -> list[str]
# - _describe_dropped_paths(skipped_paths: list[str], truncated: bool) -> str
# - _compute_token_distance(pack_payload: dict[str, object], doc_citation: dict[str, object], code_citation: dict[str, object]) -> int | None
# - _citation_token_offset(pack_payload: dict[str, object], citation: dict[str, object]) -> int | None
# - _make_file_block(path: str, lines: list[str]) -> str
# - _encode_tokens(text: str) -> int
# - _load_upstream_status_map() -> dict[str, UpstreamStatus]
# - _build_summary(findings: list[dict[str, object]], sweep_case_names: set[str], runs: list[dict[str, object]]) -> dict[str, object]
# - _build_dataset_export(index_payload: dict[str, object], findings: list[dict[str, object]], runs: list[dict[str, object]]) -> None
# - _write_dataset_readme(index_payload: dict[str, object]) -> None
# - _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None
# - _clean_records(rows: list[dict[str, object]]) -> list[dict[str, object]]
# - _clean_value(value: object) -> object
# - _as_dict(value: object) -> dict[str, object]
# - _as_dict_list(value: object) -> list[dict[str, object]]


def main() -> None:
    """
    @brief Build index.json and dataset/ export files from results_live artefacts.
    """

    benchmark_df: pd.DataFrame = pd.read_csv(BENCHMARK_COMBINED_PATH)
    runs: list[dict[str, object]] = _clean_records(benchmark_df.to_dict(orient="records"))
    trace_records: dict[str, TraceRecord] = _load_trace_records()
    reverify_map: dict[str, dict[str, object]] = _load_reverify_map()
    runs = _enrich_runs_with_trace_data(runs=runs, trace_records=trace_records, reverify_map=reverify_map)
    upstream_by_finding: dict[str, UpstreamStatus] = _load_upstream_status_map()
    findings: list[dict[str, object]] = _build_findings_index(
        upstream_by_finding=upstream_by_finding,
        trace_records=trace_records,
        reverify_map=reverify_map,
    )
    sweep_case_names: set[str] = set(
        str(case_name)
        for case_name in benchmark_df[benchmark_df.get("batch", "") == "sweep 2026-10-26"]["case_name"].tolist()
    )
    summary: dict[str, object] = _build_summary(findings=findings, sweep_case_names=sweep_case_names, runs=runs)
    index_payload: dict[str, object] = {
        "summary": summary,
        "runs": runs,
        "findings": findings,
        "handcheck_markdown_path": str(HANDCHECK_PATH),
        "upstream_status_path": str(UPSTREAM_STATUS_PATH),
        "reverify_line_shift_path": str(REVERIFY_LINE_SHIFT_PATH) if REVERIFY_LINE_SHIFT_PATH.exists() else "",
    }
    INDEX_PATH.write_text(json.dumps(index_payload, indent=2), encoding="utf-8")
    _build_dataset_export(index_payload=index_payload, findings=findings, runs=runs)
    print(f"Wrote {INDEX_PATH} and dataset export in {DATASET_DIRECTORY}")


def _load_trace_records() -> dict[str, TraceRecord]:
    """
    @brief Load all trace payloads keyed by case name.
    """

    records: dict[str, TraceRecord] = {}
    for trace_path in sorted(TRACES_DIRECTORY.glob("*.json")):
        payload: dict[str, object] = json.loads(trace_path.read_text(encoding="utf-8"))
        records[trace_path.stem] = TraceRecord(path=str(trace_path), payload=payload)
    return records


def _load_reverify_map() -> dict[str, dict[str, object]]:
    """
    @brief Load optional ±3 line-shift verifier output keyed by case name.
    """

    if not REVERIFY_LINE_SHIFT_PATH.exists():
        return {}
    payload: object = json.loads(REVERIFY_LINE_SHIFT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return {}
    reverify_map: dict[str, dict[str, object]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        trace_value: str = str(row.get("trace", "")).strip()
        case_name: str = Path(trace_value).stem
        if not case_name:
            continue
        reverify_map[case_name] = row
    return reverify_map


def _enrich_runs_with_trace_data(
    runs: list[dict[str, object]],
    trace_records: dict[str, TraceRecord],
    reverify_map: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """
    @brief Enrich benchmark run rows with trace-derived atlas and packing metadata.
    @param runs Run records from benchmark_results_combined.csv.
    @param trace_records Parsed trace map.
    @param reverify_map Optional reverify payload map.
    """

    enriched_runs: list[dict[str, object]] = []
    for run in runs:
        run_copy: dict[str, object] = dict(run)
        case_name: str = str(run_copy.get("case_name", ""))
        trace_record: TraceRecord | None = trace_records.get(case_name)
        if trace_record is None:
            enriched_runs.append(run_copy)
            continue
        trace_payload: dict[str, object] = trace_record["payload"]
        output_payload: dict[str, object] = _as_dict(trace_payload.get("output"))
        summary_payload: dict[str, object] = _as_dict(trace_payload.get("summary"))
        pack_payload: dict[str, object] = _as_dict(trace_payload.get("pack"))
        claims: list[dict[str, object]] = _as_dict_list(output_payload.get("atlas_claims"))
        citations_total: int = sum(len(_as_dict_list(claim.get("citations"))) for claim in claims)
        reverify_payload: dict[str, object] | None = reverify_map.get(case_name)
        atlas_citations_verified: int = _coerce_int(summary_payload.get("atlas_citations_verified"), 0)
        findings_fully_verified: int = _coerce_int(summary_payload.get("findings_fully_verified"), 0)
        if reverify_payload is not None:
            atlas_citations_verified = _coerce_int(
                reverify_payload.get("atlas_citations_verified"),
                atlas_citations_verified,
            )
            findings_fully_verified = _coerce_int(reverify_payload.get("new_fully_verified"), findings_fully_verified)
        skipped_paths: list[str] = _as_str_list(pack_payload.get("skipped_paths"))
        truncated: bool = bool(pack_payload.get("truncated", False))
        run_copy["trace_path"] = trace_record["path"]
        run_copy["pack_truncated"] = truncated
        run_copy["pack_skipped_paths"] = skipped_paths
        run_copy["pack_dropped_summary"] = _describe_dropped_paths(skipped_paths=skipped_paths, truncated=truncated)
        run_copy["atlas_claims_total"] = len(claims)
        run_copy["atlas_citations_total"] = citations_total
        run_copy["atlas_citations_verified"] = atlas_citations_verified
        run_copy["findings_fully_verified"] = findings_fully_verified
        enriched_runs.append(run_copy)
    return enriched_runs


def _build_findings_index(
    upstream_by_finding: dict[str, UpstreamStatus],
    trace_records: dict[str, TraceRecord],
    reverify_map: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """
    @brief Extract finding metadata from live traces.
    @param upstream_by_finding Mapping of finding keys to upstream status rows.
    @param trace_records Parsed trace payload map.
    @param reverify_map Optional reverify payload map.
    """

    findings: list[dict[str, object]] = []
    for case_name in sorted(trace_records.keys()):
        trace_record: TraceRecord = trace_records[case_name]
        trace_path: Path = Path(trace_record["path"])
        findings.extend(
            _extract_findings_from_trace(
                case_name=case_name,
                trace_payload=trace_record["payload"],
                trace_path=trace_path,
                upstream_by_finding=upstream_by_finding,
                reverify_payload=reverify_map.get(case_name),
            )
        )
    ordered_findings: list[dict[str, object]] = sorted(
        findings,
        key=lambda item: (str(item.get("case_name", "")), str(item.get("finding_id", ""))),
    )
    return ordered_findings


def _extract_findings_from_trace(
    case_name: str,
    trace_payload: dict[str, object],
    trace_path: Path,
    upstream_by_finding: dict[str, UpstreamStatus],
    reverify_payload: dict[str, object] | None,
) -> list[dict[str, object]]:
    """
    @brief Extract finding cards from one trace payload.
    @param case_name Benchmark case name.
    @param trace_payload Parsed trace JSON payload.
    @param trace_path Source trace file path.
    @param upstream_by_finding Mapping of finding keys to upstream status rows.
    @param reverify_payload Optional ±3-line reverify payload.
    """

    summary: dict[str, object] = _as_dict(trace_payload.get("summary"))
    output: dict[str, object] = _as_dict(trace_payload.get("output"))
    pack_payload: dict[str, object] = _as_dict(trace_payload.get("pack"))
    verification_results: list[dict[str, object]] = _as_dict_list(trace_payload.get("verification_results"))
    if reverify_payload is not None:
        verification_results = _as_dict_list(reverify_payload.get("verification_results"))
    verification_map: dict[str, dict[str, object]] = {
        str(item.get("finding_id", "")): item for item in verification_results
    }
    findings: list[dict[str, object]] = []
    for finding in _as_dict_list(output.get("findings")):
        finding_id: str = str(finding.get("finding_id", ""))
        key: str = f"{case_name}/{finding_id}"
        hand: HandVerdict | None = HAND_VERDICTS.get(key)
        upstream: UpstreamStatus | None = upstream_by_finding.get(key)
        verifier: dict[str, object] = verification_map.get(finding_id, {})
        doc_check: dict[str, object] = _as_dict(verifier.get("doc_check"))
        code_check: dict[str, object] = _as_dict(verifier.get("code_check"))
        doc_citation: dict[str, object] = _as_dict(finding.get("doc_citation"))
        code_citation: dict[str, object] = _as_dict(finding.get("code_citation"))
        doc_model_line: int = _coerce_int(doc_citation.get("start_line"), 0)
        code_model_line: int = _coerce_int(code_citation.get("start_line"), 0)
        doc_verified_line: int = _verified_line(verification_check=doc_check, fallback=doc_model_line)
        code_verified_line: int = _verified_line(verification_check=code_check, fallback=code_model_line)
        doc_line_offset: int = doc_verified_line - doc_model_line
        code_line_offset: int = code_verified_line - code_model_line
        doc_citation_for_distance: dict[str, object] = dict(doc_citation)
        code_citation_for_distance: dict[str, object] = dict(code_citation)
        if doc_verified_line > 0:
            doc_citation_for_distance["start_line"] = doc_verified_line
            doc_citation_for_distance["end_line"] = max(
                doc_verified_line,
                _coerce_int(doc_citation.get("end_line"), doc_verified_line) + doc_line_offset,
            )
        if code_verified_line > 0:
            code_citation_for_distance["start_line"] = code_verified_line
            code_citation_for_distance["end_line"] = max(
                code_verified_line,
                _coerce_int(code_citation.get("end_line"), code_verified_line) + code_line_offset,
            )
        upstream_status_text: str = upstream["status"] if upstream else "draft prepared, unfiled"
        issue_draft_path, issue_draft_text = _build_issue_draft(finding_key=key)
        repo_url_for_finding: str = upstream["repo"] if upstream else str(summary.get("repo_url", ""))
        source_ref: str = str(summary.get("ref", ""))
        findings.append(
            {
                "finding_key": key,
                "case_name": case_name,
                "trace_path": str(trace_path),
                "repo_url": repo_url_for_finding,
                "source_repo_url": summary.get("repo_url", ""),
                "ref": source_ref,
                "finding_id": finding_id,
                "drift_kind": finding.get("drift_kind", ""),
                "explanation": finding.get("explanation", ""),
                "doc_citation": doc_citation,
                "code_citation": code_citation,
                "doc_quote": doc_citation.get("quote", ""),
                "code_quote": code_citation.get("quote", ""),
                "verifier_fully_verified": bool(verifier.get("fully_verified", False)),
                "verifier_label": _verifier_label(verifier),
                "verifier_doc_reason": doc_check.get("reason", ""),
                "verifier_code_reason": code_check.get("reason", ""),
                "doc_model_line": doc_model_line,
                "doc_verified_line": doc_verified_line,
                "doc_line_offset": doc_line_offset,
                "code_model_line": code_model_line,
                "code_verified_line": code_verified_line,
                "code_line_offset": code_line_offset,
                "hand_verdict": hand.verdict if hand else "unknown",
                "hand_notes": hand.notes if hand else "No hand verdict recorded in results_live/handcheck.md.",
                "upstream_status": upstream_status_text,
                "upstream_url": upstream["url"] if upstream else "",
                "upstream_checked_at": upstream["checked_at"] if upstream else "",
                "upstream_prior_reported": "already reported upstream by others"
                in upstream_status_text.lower(),
                "breakage_summary": BREAKAGE_SUMMARIES.get(key, ""),
                "token_distance": _compute_token_distance(
                    pack_payload=pack_payload,
                    doc_citation=doc_citation_for_distance,
                    code_citation=code_citation_for_distance,
                ),
                "is_cross_file": str(doc_citation.get("path", "")) != str(code_citation.get("path", "")),
                "input_tokens": summary.get("input_tokens", 0),
                "latency_seconds": summary.get("latency_seconds", 0.0),
                "atlas_claims_total": summary.get("atlas_claims_total", 0),
                "atlas_citations_verified": summary.get("atlas_citations_verified", 0),
                "doc_permalink": _build_finding_permalink(
                    repo_url=repo_url_for_finding,
                    ref_value=source_ref,
                    citation=doc_citation_for_distance,
                    case_name=case_name,
                ),
                "code_permalink": _build_finding_permalink(
                    repo_url=repo_url_for_finding,
                    ref_value=source_ref,
                    citation=code_citation_for_distance,
                    case_name=case_name,
                ),
                "issue_draft_path": issue_draft_path,
                "issue_draft_text": issue_draft_text,
            }
        )
    return findings


def _build_finding_permalink(
    repo_url: str,
    ref_value: str,
    citation: dict[str, object],
    case_name: str,
) -> str:
    """
    @brief Build a SHA-pinned GitHub permalink for one citation when possible.
    @param repo_url Repository URL.
    @param ref_value Trace reference value.
    @param citation Citation payload.
    @param case_name Benchmark case name.
    """

    path_value: str = str(citation.get("path", "")).strip().lstrip("./")
    start_line: int = _coerce_int(citation.get("start_line"), 0)
    end_line: int = _coerce_int(citation.get("end_line"), start_line)
    if not repo_url.startswith("https://github.com/") or not path_value:
        return ""
    normalised_ref: str = _normalise_ref(case_name=case_name, ref_value=ref_value)
    if not normalised_ref:
        return ""
    if start_line > 0:
        fragment: str = f"#L{start_line}" if end_line <= start_line else f"#L{start_line}-L{end_line}"
    else:
        fragment = ""
    return f"{repo_url}/blob/{normalised_ref}/{path_value}{fragment}"


def _normalise_ref(case_name: str, ref_value: str) -> str:
    """
    @brief Resolve reference value for permalink generation.
    @param case_name Benchmark case name.
    @param ref_value Raw trace ref.
    """

    stripped_ref: str = ref_value.strip()
    if stripped_ref and SHA_PATTERN.match(stripped_ref):
        return stripped_ref
    override_ref: str = CASE_REF_OVERRIDES.get(case_name, "")
    if override_ref:
        return override_ref
    return ""


def _build_issue_draft(finding_key: str) -> tuple[str, str]:
    """
    @brief Resolve issue draft markdown path and body text for one finding.
    @param finding_key Finding key in case/finding_id format.
    """

    draft_filename: str = FINDING_DRAFT_FILE_BY_KEY.get(finding_key, "")
    if not draft_filename:
        return "", ""
    draft_path: Path = UPSTREAM_DRAFTS_DIRECTORY / draft_filename
    if not draft_path.exists():
        return str(draft_path), ""
    return str(draft_path), draft_path.read_text(encoding="utf-8")


def _verifier_label(verifier_payload: dict[str, object]) -> str:
    """
    @brief Build a human label for verifier status.
    @param verifier_payload Verifier payload for one finding.
    """

    if not bool(verifier_payload.get("fully_verified", False)):
        return "reject"
    doc_check: dict[str, object] = _as_dict(verifier_payload.get("doc_check"))
    code_check: dict[str, object] = _as_dict(verifier_payload.get("code_check"))
    shifted: bool = str(doc_check.get("reason", "")) == "line-shifted-match" or str(
        code_check.get("reason", "")
    ) == "line-shifted-match"
    if shifted:
        return "verified (line-shifted)"
    return "verified"


def _verified_line(verification_check: dict[str, object], fallback: int) -> int:
    """
    @brief Resolve corrected citation start line from verifier payload.
    @param verification_check Verifier check payload.
    @param fallback Original citation line.
    """

    corrected: int = _coerce_int(verification_check.get("corrected_start_line"), 0)
    if corrected > 0:
        return corrected
    return fallback


def _coerce_int(value: object, fallback: int = 0) -> int:
    """
    @brief Coerce unknown values to integer with fallback.
    @param value Input value.
    @param fallback Fallback integer.
    """

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return fallback
    return fallback


def _as_str_list(value: object) -> list[str]:
    """
    @brief Convert unknown value to list of non-empty strings.
    @param value Input value.
    """

    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _describe_dropped_paths(skipped_paths: list[str], truncated: bool) -> str:
    """
    @brief Describe dropped paths from pack metadata.
    @param skipped_paths Explicit skipped path list.
    @param truncated Whether the pack was trimmed by token cap.
    """

    if skipped_paths:
        preview: str = ", ".join(skipped_paths[:3])
        if len(skipped_paths) > 3:
            preview += f", +{len(skipped_paths) - 3} more"
        return f"explicitly skipped paths: {preview}"
    if truncated:
        return "trimmed to token cap; exact dropped paths were not recorded in this trace."
    return "no trimming recorded"


def _compute_token_distance(
    pack_payload: dict[str, object],
    doc_citation: dict[str, object],
    code_citation: dict[str, object],
) -> int | None:
    """
    @brief Compute citation token distance within a packed prompt when derivable.
    @param pack_payload Packed repository payload from one trace.
    @param doc_citation Doc citation payload.
    @param code_citation Code citation payload.
    """

    doc_offset: int | None = _citation_token_offset(pack_payload=pack_payload, citation=doc_citation)
    code_offset: int | None = _citation_token_offset(pack_payload=pack_payload, citation=code_citation)
    if doc_offset is None or code_offset is None:
        return None
    return abs(doc_offset - code_offset)


def _citation_token_offset(pack_payload: dict[str, object], citation: dict[str, object]) -> int | None:
    """
    @brief Approximate the citation start-line token offset in one packed prompt.
    @param pack_payload Packed payload map.
    @param citation Citation payload map.
    """

    files: list[dict[str, object]] = _as_dict_list(pack_payload.get("files"))
    repo_url: str = str(pack_payload.get("repo_url", ""))
    ref: str = str(pack_payload.get("ref", ""))
    citation_path: str = str(citation.get("path", "")).replace("\\", "/").lstrip("./")
    citation_start_line: int = _coerce_int(citation.get("start_line"), 0)
    if citation_start_line <= 0 or not citation_path:
        return None
    running_text: str = (
        "# REPOATLAS PACK FORMAT 1\n"
        f"REPO_URL: {repo_url}\n"
        f"REF: {ref}\n"
        f"FILTER_SIGNATURE: {FILTER_SIGNATURE}\n"
        "LINE_FORMAT: <line>|<text>\n"
        "FILES_BEGIN\n"
    )
    running_tokens: int = _encode_tokens(running_text)
    for file_payload in files:
        file_path: str = str(file_payload.get("path", "")).replace("\\", "/").lstrip("./")
        file_lines: list[str] = [
            str(line)
            for line in file_payload.get("lines", [])
            if isinstance(line, str)
        ]
        file_block: str = _make_file_block(file_path, file_lines)
        if file_path != citation_path:
            running_tokens += _encode_tokens(file_block)
            continue
        if citation_start_line > len(file_lines):
            return None
        file_header: str = f"--- FILE: {file_path} ---\n"
        leading_lines: list[str] = [
            f"{line_number + 1}|{line}"
            for line_number, line in enumerate(file_lines[: citation_start_line - 1])
        ]
        prefix_within_file: str = file_header
        if leading_lines:
            prefix_within_file += "\n".join(leading_lines) + "\n"
        return running_tokens + _encode_tokens(prefix_within_file)
    return None


def _make_file_block(path: str, lines: list[str]) -> str:
    """
    @brief Render one file block in pack format.
    @param path Repository-relative file path.
    @param lines File lines.
    """

    numbered_lines: list[str] = [f"{index + 1}|{line}" for index, line in enumerate(lines)]
    body: str = "\n".join(numbered_lines)
    return f"--- FILE: {path} ---\n{body}\n--- END FILE: {path} ---\n"


def _encode_tokens(text: str) -> int:
    """
    @brief Count tokens with cl100k_base, with a safe fallback.
    @param text Input text.
    """

    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text.split()))


def _load_upstream_status_map() -> dict[str, UpstreamStatus]:
    """
    @brief Load upstream status rows keyed by finding identifier.
    """

    payload: object = json.loads(UPSTREAM_STATUS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("results_live/upstream_status.json must be a JSON array.")
    by_finding: dict[str, UpstreamStatus] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        repo: str = str(row.get("repo", "")).strip()
        finding: str = str(row.get("finding", "")).strip()
        status: str = str(row.get("status", "")).strip()
        url: str = str(row.get("url", "")).strip()
        checked_at: str = str(row.get("checked_at", "")).strip()
        if not repo or not finding or not status:
            continue
        by_finding[finding] = UpstreamStatus(
            repo=repo,
            finding=finding,
            status=status,
            url=url,
            checked_at=checked_at,
        )
    return by_finding


def _build_summary(
    findings: list[dict[str, object]],
    sweep_case_names: set[str],
    runs: list[dict[str, object]],
) -> dict[str, object]:
    """
    @brief Compute accuracy, verifier, and hero metrics from index records.
    @param findings Finding rows.
    @param sweep_case_names Case names included in the 2026-10-26 sweep.
    @param runs Run rows.
    """

    true_findings: list[dict[str, object]] = [
        finding for finding in findings if finding.get("hand_verdict") == "true"
    ]
    false_findings: list[dict[str, object]] = [
        finding for finding in findings if finding.get("hand_verdict") == "false"
    ]
    unclear_findings: list[dict[str, object]] = [
        finding for finding in findings if finding.get("hand_verdict") == "unclear"
    ]
    true_count: int = len(true_findings)
    false_count: int = len(false_findings)
    unclear_count: int = len(unclear_findings)
    judged_count: int = true_count + false_count + unclear_count
    precision: float = (true_count / judged_count) if judged_count else 0.0
    sweep_findings: list[dict[str, object]] = [
        finding for finding in findings if str(finding.get("case_name", "")) in sweep_case_names
    ]
    sweep_false_findings: list[dict[str, object]] = [
        finding for finding in sweep_findings if finding.get("hand_verdict") == "false"
    ]
    sweep_true_findings: list[dict[str, object]] = [
        finding for finding in sweep_findings if finding.get("hand_verdict") == "true"
    ]
    verifier_caught_false_count_sweep: int = sum(
        1 for finding in sweep_false_findings if not bool(finding.get("verifier_fully_verified", False))
    )
    verifier_false_total_count_sweep: int = len(sweep_false_findings)
    verifier_rejected_true_count_sweep: int = sum(
        1 for finding in sweep_true_findings if not bool(finding.get("verifier_fully_verified", False))
    )
    verifier_caught_false_count_all: int = sum(
        1 for finding in false_findings if not bool(finding.get("verifier_fully_verified", False))
    )
    verifier_false_total_count_all: int = len(false_findings)
    verifier_rejected_true_count_all: int = sum(
        1 for finding in true_findings if not bool(finding.get("verifier_fully_verified", False))
    )
    repos_300k_to_400k: set[str] = {
        str(run.get("repo_url", ""))
        for run in runs
        if 300_000 <= _as_float(run.get("input_tokens"), 0.0) <= 401_000
    }
    unique_repos: set[str] = {str(run.get("repo_url", "")) for run in runs}
    run_count: int = len(runs)
    repo_count: int = len(unique_repos)
    call_ratio: float = run_count / max(1, repo_count)
    pack_total_count: int = run_count
    pack_trimmed_count: int = sum(1 for run in runs if bool(run.get("pack_truncated", False)))
    true_cross_file_findings: list[dict[str, object]] = [
        finding for finding in true_findings if bool(finding.get("is_cross_file", False))
    ]
    true_cross_file_distances: list[int] = [
        int(finding.get("token_distance"))
        for finding in true_cross_file_findings
        if isinstance(finding.get("token_distance"), int)
    ]
    true_cross_file_median_distance: int = (
        int(median(true_cross_file_distances)) if true_cross_file_distances else 0
    )
    true_cross_file_max_distance: int = max(true_cross_file_distances) if true_cross_file_distances else 0
    prior_reported_true_count: int = sum(
        1 for finding in true_findings if bool(finding.get("upstream_prior_reported", False))
    )
    no_prior_report_true_count: int = true_count - prior_reported_true_count
    total_input_tokens: int = int(sum(_as_float(run.get("input_tokens"), 0.0) for run in runs))
    total_output_tokens: int = int(sum(_as_float(run.get("output_tokens"), 0.0) for run in runs))
    input_token_values: list[float] = [_as_float(run.get("input_tokens"), 0.0) for run in runs]
    prompt_tokens_min: int = int(min(input_token_values)) if input_token_values else 0
    prompt_tokens_max: int = int(max(input_token_values)) if input_token_values else 0
    return {
        "run_count": run_count,
        "repo_count": repo_count,
        "true_count": true_count,
        "false_count": false_count,
        "unclear_count": unclear_count,
        "judged_count": judged_count,
        "precision": precision,
        "verifier_caught_false_count_all": verifier_caught_false_count_all,
        "verifier_false_total_count_all": verifier_false_total_count_all,
        "verifier_rejected_true_count_all": verifier_rejected_true_count_all,
        "verifier_caught_false_count_sweep": verifier_caught_false_count_sweep,
        "verifier_false_total_count_sweep": verifier_false_total_count_sweep,
        "verifier_rejected_true_count_sweep": verifier_rejected_true_count_sweep,
        "hero_repos_300k_to_400k_count": len(repos_300k_to_400k),
        "hero_calls_per_repo": call_ratio,
        "pack_trimmed_count": pack_trimmed_count,
        "pack_total_count": pack_total_count,
        "true_cross_file_count": len(true_cross_file_findings),
        "true_cross_file_median_token_distance": true_cross_file_median_distance,
        "true_cross_file_max_token_distance": true_cross_file_max_distance,
        "true_prior_reported_count": prior_reported_true_count,
        "true_no_prior_report_count": no_prior_report_true_count,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "prompt_tokens_min": prompt_tokens_min,
        "prompt_tokens_max": prompt_tokens_max,
    }


def _build_dataset_export(
    index_payload: dict[str, object],
    findings: list[dict[str, object]],
    runs: list[dict[str, object]],
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
    shutil.copy2(UPSTREAM_STATUS_PATH, DATASET_DIRECTORY / "upstream_status.json")
    if REVERIFY_LINE_SHIFT_PATH.exists():
        shutil.copy2(REVERIFY_LINE_SHIFT_PATH, DATASET_DIRECTORY / "reverify_line_shift.json")
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
    shutil.copytree(UPSTREAM_DRAFTS_DIRECTORY, drafts_target)


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
        "pretty_name: DocDrift v2 results (RepoAtlas-1M, Oct 2026)\n"
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
        "# DocDrift dataset card\n\n"
        "This folder is the earlier v1 live-results export. The v2 publication folder is `hf_dataset/`.\n\n"
        f"- Labels were checked against the source by an AI reviewer. v1 precision: **{true_count}/{judged_count} = {precision * 100:.1f}%**\n"
        f"- Breakdown: true={true_count}, false={false_count}, unclear={unclear_count}\n"
        "- The stored field is still `hand_verdict`.\n"
        "- Full run narrative and caveats are in `handcheck.md`.\n\n"
        "## Files\n\n"
        "- `runs.jsonl`: one row per run from `results_live/benchmark_results_combined.csv`\n"
        "- `findings.jsonl`: one row per finding with verifier and hand verdict labels\n"
        "- `upstream_status.json`: source of truth for external status labels and links\n"
        "- `reverify_line_shift.json`: ±3 line-shift verifier output used for corrected citation checks\n"
        "- `traces/`: full raw trace JSON payloads (large; include pack text)\n"
        "- `upstream_drafts/`: unfiled upstream issue/PR draft notes\n\n"
        "## Notes\n\n"
        "- `verifier_fully_verified=true` means cited snippets matched pack text; it does not prove a finding is correct.\n"
        "- `hand_verdict` means checked against the source by an AI reviewer, not a human annotator.\n"
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


def _as_float(value: object, fallback: float) -> float:
    """
    @brief Convert an unknown value to float.
    @param value Input value.
    @param fallback Fallback value when parsing fails.
    """

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return fallback
    return fallback


if __name__ == "__main__":
    main()
