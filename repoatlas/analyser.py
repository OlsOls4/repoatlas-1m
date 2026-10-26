"""High-level orchestration for RepoAtlas analysis runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from repoatlas.client import AnalysisClient, AnalysisCallMetrics, make_analysis_client
from repoatlas.config import RepoAtlasConfig
from repoatlas.models import AnalysisOutput, AnalysisRunSummary, RepoPack, VerificationResult
from repoatlas.packer import pack_repository
from repoatlas.verifier import verify_atlas_claims, verify_findings


@dataclass(slots=True)
class AnalysisBundle:
    """
    @brief In-memory bundle containing full outputs from one analysis run.
    @param pack Packed repository payload.
    @param output Structured analysis output.
    @param verification_results Per-finding verification results.
    @param summary Run summary metrics.
    """

    pack: RepoPack
    output: AnalysisOutput
    verification_results: list[VerificationResult]
    summary: AnalysisRunSummary


def analyse_repository(
    repo_url: str,
    ref: str,
    config: RepoAtlasConfig,
    fixture_path: Path,
    run_probes: bool = False,
) -> AnalysisBundle:
    """
    @brief Pack a repository, run analysis, verify results, and return a complete bundle.
    @param repo_url Public GitHub repository URL.
    @param ref Branch, tag, or commit to analyse.
    @param config Runtime configuration.
    @param fixture_path Fixture file path used in fixture mode.
    @param run_probes Whether runnable probes should execute.
    """

    pack: RepoPack = pack_repository(
        repo_url=repo_url,
        ref=ref,
        token_limit=config.token_limit,
        cache_dir=config.cache_dir,
    )
    client: AnalysisClient = make_analysis_client(config=config, fixture_path=fixture_path)
    output: AnalysisOutput
    metrics: AnalysisCallMetrics
    output, metrics = client.analyse(pack=pack, repo_url=repo_url, ref=ref)
    verification_results: list[VerificationResult] = verify_findings(
        findings=output.findings,
        pack=pack,
        repo_root=None,
        run_probes=run_probes,
    )
    atlas_verified, atlas_total = verify_atlas_claims(output.atlas_claims, pack)
    summary = AnalysisRunSummary(
        repo_url=repo_url,
        ref=ref,
        context_tokens=pack.total_tokens,
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
        cached_input_tokens=metrics.cached_input_tokens,
        latency_seconds=metrics.latency_seconds,
        findings_total=len(output.findings),
        findings_fully_verified=sum(1 for result in verification_results if result.fully_verified),
        atlas_claims_total=len(output.atlas_claims),
        atlas_citations_verified=atlas_verified if atlas_total else 0,
        fixture_run=output.fixture_run,
        rate_limit_headers=metrics.rate_limit_headers,
    )
    return AnalysisBundle(pack=pack, output=output, verification_results=verification_results, summary=summary)


def save_analysis_bundle(bundle: AnalysisBundle, output_directory: Path) -> None:
    """
    @brief Persist one analysis bundle as JSON artefacts.
    @param bundle Analysis bundle to persist.
    @param output_directory Target directory for JSON artefacts.
    """

    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp: str = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary_path: Path = output_directory / f"summary-{timestamp}.json"
    details_path: Path = output_directory / f"analysis-{timestamp}.json"
    verification_path: Path = output_directory / f"verification-{timestamp}.json"
    summary_path.write_text(bundle.summary.model_dump_json(indent=2), encoding="utf-8")
    details_path.write_text(bundle.output.model_dump_json(indent=2), encoding="utf-8")
    verification_path.write_text(
        json.dumps([result.model_dump(mode="json") for result in bundle.verification_results], indent=2),
        encoding="utf-8",
    )
    _write_local_patch_file(bundle, output_directory=output_directory, timestamp=timestamp)


def _write_local_patch_file(bundle: AnalysisBundle, output_directory: Path, timestamp: str) -> None:
    """
    @brief Persist proposed documentation patches locally without any remote publication.
    @param bundle Analysis bundle that may contain suggested patches.
    @param output_directory Target directory for local patch artefacts.
    @param timestamp Timestamp suffix for deterministic file grouping.
    """

    patches: list[dict[str, str]] = []
    for finding in bundle.output.findings:
        if finding.suggested_patch is None:
            continue
        patches.append(
            {
                "finding_id": finding.finding_id,
                "target_path": finding.suggested_patch.target_path,
                "patch": finding.suggested_patch.patch,
                "fixture_label": finding.fixture_label or "",
            }
        )
    if not patches:
        return
    patch_path: Path = output_directory / f"proposed-doc-patches-{timestamp}.json"
    patch_path.write_text(json.dumps(patches, indent=2), encoding="utf-8")
