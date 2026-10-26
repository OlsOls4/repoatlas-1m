"""Benchmark harness for RepoAtlas-1M across repositories and context sizes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from repoatlas.analyser import analyse_repository
from repoatlas.config import RepoAtlasConfig
from repoatlas.models import VerificationResult


@dataclass(slots=True)
class BenchmarkCase:
    """
    @brief One benchmark run configuration.
    @param repo_url Public GitHub repository URL.
    @param ref Branch, tag, or commit.
    @param token_limit Packed context token cap.
    @param case_name Human-readable case identifier.
    """

    repo_url: str
    ref: str
    token_limit: int
    case_name: str


def run_benchmark(
    cases: list[BenchmarkCase],
    base_config: RepoAtlasConfig,
    fixture_path: Path,
    output_directory: Path,
) -> pd.DataFrame:
    """
    @brief Execute benchmark cases and export results, traces, and charts.
    @param cases Benchmark case list.
    @param base_config Baseline runtime configuration.
    @param fixture_path Fixture JSON path used in fixture mode.
    @param output_directory Directory where benchmark artefacts will be saved.
    """

    output_directory.mkdir(parents=True, exist_ok=True)
    traces_directory: Path = output_directory / "traces"
    charts_directory: Path = output_directory / "charts"
    traces_directory.mkdir(parents=True, exist_ok=True)
    charts_directory.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    hand_check_rows: list[dict[str, object]] = []

    for case in cases:
        case_config = RepoAtlasConfig(
            provider=base_config.provider,
            base_url=base_config.base_url,
            model=base_config.model,
            api_key=base_config.api_key,
            token_limit=case.token_limit,
            max_tokens=base_config.max_tokens,
            reasoning_effort=base_config.reasoning_effort,
            cache_dir=base_config.cache_dir,
        )
        bundle = analyse_repository(
            repo_url=case.repo_url,
            ref=case.ref,
            config=case_config,
            fixture_path=fixture_path,
            run_probes=False,
        )
        verified_count: int = sum(1 for result in bundle.verification_results if result.fully_verified)
        total_count: int = max(1, len(bundle.verification_results))
        citation_precision: float = verified_count / total_count
        records.append(
            {
                "case_name": case.case_name,
                "repo_url": case.repo_url,
                "ref": case.ref,
                "token_limit": case.token_limit,
                "context_tokens": bundle.summary.context_tokens,
                "input_tokens": bundle.summary.input_tokens,
                "output_tokens": bundle.summary.output_tokens,
                "cached_input_tokens": bundle.summary.cached_input_tokens,
                "latency_seconds": bundle.summary.latency_seconds,
                "findings_total": bundle.summary.findings_total,
                "findings_fully_verified": verified_count,
                "citation_precision": citation_precision,
                "fixture_run": bundle.summary.fixture_run,
            }
        )
        for finding, verification in zip(bundle.output.findings, bundle.verification_results):
            hand_check_rows.append(
                {
                    "case_name": case.case_name,
                    "repo_url": case.repo_url,
                    "finding_id": finding.finding_id,
                    "drift_kind": finding.drift_kind,
                    "doc_path": finding.doc_citation.path,
                    "doc_line_start": finding.doc_citation.start_line,
                    "doc_line_end": finding.doc_citation.end_line,
                    "code_path": finding.code_citation.path,
                    "code_line_start": finding.code_citation.start_line,
                    "code_line_end": finding.code_citation.end_line,
                    "verified": verification.fully_verified,
                    "human_label_true_positive": "",
                    "human_label_notes": "",
                    "fixture_label": finding.fixture_label or "",
                }
            )
        _write_trace_file(
            traces_directory=traces_directory,
            case_name=case.case_name,
            bundle_data={
                "summary": bundle.summary.model_dump(mode="json"),
                "output": bundle.output.model_dump(mode="json"),
                "verification_results": [result.model_dump(mode="json") for result in bundle.verification_results],
                "pack": bundle.pack.model_dump(mode="json"),
            },
        )

    results_df: pd.DataFrame = pd.DataFrame.from_records(records)
    results_df.sort_values(by=["token_limit", "case_name"], inplace=True)
    results_path: Path = output_directory / "benchmark_results.csv"
    results_df.to_csv(results_path, index=False)
    hand_check_df: pd.DataFrame = pd.DataFrame.from_records(hand_check_rows)
    hand_check_path: Path = output_directory / "hand_check_sheet.csv"
    hand_check_df.to_csv(hand_check_path, index=False)
    _render_charts(results_df=results_df, charts_directory=charts_directory)
    _write_dataset_ready_jsonl(results_df=results_df, output_directory=output_directory)
    return results_df


def _write_trace_file(traces_directory: Path, case_name: str, bundle_data: dict[str, object]) -> None:
    """
    @brief Write one benchmark trace payload for dataset export.
    @param traces_directory Output traces directory.
    @param case_name Case identifier.
    @param bundle_data Serialisable trace payload.
    """

    safe_case_name: str = case_name.replace("/", "_")
    trace_path: Path = traces_directory / f"{safe_case_name}.json"
    trace_path.write_text(json.dumps(bundle_data, indent=2), encoding="utf-8")


def _render_charts(results_df: pd.DataFrame, charts_directory: Path) -> None:
    """
    @brief Generate benchmark charts for precision and latency trends.
    @param results_df Benchmark metrics data frame.
    @param charts_directory Output charts directory.
    """

    if results_df.empty:
        return
    sorted_df: pd.DataFrame = results_df.sort_values(by="context_tokens")
    plt.figure(figsize=(8, 4))
    plt.plot(sorted_df["context_tokens"], sorted_df["citation_precision"], marker="o")
    plt.xlabel("Context tokens")
    plt.ylabel("Citation precision")
    plt.title("Citation precision vs context size")
    plt.tight_layout()
    plt.savefig(charts_directory / "precision_vs_context.png")
    plt.close()

    plt.figure(figsize=(8, 4))
    plt.plot(sorted_df["context_tokens"], sorted_df["latency_seconds"], marker="o", color="tab:orange")
    plt.xlabel("Context tokens")
    plt.ylabel("Latency (seconds)")
    plt.title("Latency vs context size")
    plt.tight_layout()
    plt.savefig(charts_directory / "latency_vs_context.png")
    plt.close()

    plt.figure(figsize=(8, 4))
    plt.plot(sorted_df["context_tokens"], sorted_df["input_tokens"], marker="o", label="Input tokens")
    plt.plot(sorted_df["context_tokens"], sorted_df["output_tokens"], marker="o", label="Output tokens")
    plt.xlabel("Context tokens")
    plt.ylabel("Token count")
    plt.title("Token usage vs context size")
    plt.legend()
    plt.tight_layout()
    plt.savefig(charts_directory / "tokens_vs_context.png")
    plt.close()


def _write_dataset_ready_jsonl(results_df: pd.DataFrame, output_directory: Path) -> None:
    """
    @brief Export benchmark rows as JSONL ready for HF dataset upload.
    @param results_df Benchmark metrics data frame.
    @param output_directory Directory where the JSONL file will be written.
    """

    dataset_path: Path = output_directory / "benchmark_results.jsonl"
    with dataset_path.open("w", encoding="utf-8") as handle:
        for row in results_df.to_dict(orient="records"):
            handle.write(json.dumps(row) + "\n")
