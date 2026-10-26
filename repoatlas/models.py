"""Typed data models used by RepoAtlas-1M."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RepoFileSnapshot(BaseModel):
    """
    @brief Snapshot of one packed repository file.
    @param path Repository-relative path.
    @param lines File content split by line.
    @param token_count Approximate file token count.
    """

    path: str
    lines: list[str]
    token_count: int


class RepoPack(BaseModel):
    """
    @brief Deterministically packed repository payload for Beam.
    @param repo_url Source repository URL.
    @param ref Branch, tag, or commit used to pack content.
    @param prefix_hash Stable hash of the packed prefix content.
    @param total_tokens Total token count of pack_text.
    @param token_limit Applied token limit.
    @param truncated Whether truncation occurred to satisfy token_limit.
    @param packed_at ISO timestamp for pack generation.
    @param files Included text files with line content.
    @param skipped_paths Paths skipped by filters.
    @param pack_text Prompt prefix sent to Beam.
    """

    repo_url: str
    ref: str
    prefix_hash: str
    total_tokens: int
    token_limit: int
    truncated: bool
    packed_at: str
    files: list[RepoFileSnapshot]
    skipped_paths: list[str]
    pack_text: str


class Citation(BaseModel):
    """
    @brief Citation reference to a repository file and line range.
    @param path Repository-relative file path.
    @param start_line Inclusive first line.
    @param end_line Inclusive last line.
    @param quote Exact quoted text expected in the cited range.
    """

    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str


class SuggestedPatch(BaseModel):
    """
    @brief Proposed local documentation patch for a finding.
    @param target_path Documentation file to patch.
    @param patch Unified diff patch text.
    """

    target_path: str
    patch: str


class RunnableProbe(BaseModel):
    """
    @brief Optional runnable probe specification for deterministic checks.
    @param kind Probe kind, such as cli_help.
    @param command Command argv to execute.
    @param expected_substring Required substring in stdout or stderr.
    """

    kind: str
    command: list[str]
    expected_substring: str


class DocDriftFinding(BaseModel):
    """
    @brief One detected contradiction between documentation and code.
    @param finding_id Stable identifier for the finding.
    @param drift_kind Drift category label.
    @param explanation Human-readable explanation.
    @param doc_citation Citation into README/docs/docstring/help text.
    @param code_citation Citation into source code.
    @param proposed_fix Natural-language fix summary.
    @param suggested_patch Local patch representation.
    @param runnable_probe Optional executable verification probe.
    @param fixture_label Marks fixture-generated findings.
    """

    finding_id: str
    drift_kind: str
    explanation: str
    doc_citation: Citation
    code_citation: Citation
    proposed_fix: str
    suggested_patch: SuggestedPatch | None = None
    runnable_probe: RunnableProbe | None = None
    fixture_label: str | None = None


class AtlasClaim(BaseModel):
    """
    @brief One onboarding claim with supporting citations.
    @param claim_id Stable claim identifier.
    @param section Section heading.
    @param text Claim statement.
    @param citations Supporting citations.
    @param fixture_label Marks fixture-generated claims.
    """

    claim_id: str
    section: str
    text: str
    citations: list[Citation]
    fixture_label: str | None = None


class AnalysisOutput(BaseModel):
    """
    @brief Structured analysis output returned by Beam or fixtures.
    @param repo_url Analysed repository URL.
    @param ref Analysed reference.
    @param findings DocDrift findings.
    @param atlas_claims Onboarding atlas claims.
    @param model Model identifier used for the run.
    @param provider Provider identifier used for the run.
    @param fixture_run True when generated from local fixtures.
    @param raw_response Raw model response payload for trace export.
    """

    repo_url: str
    ref: str
    findings: list[DocDriftFinding]
    atlas_claims: list[AtlasClaim]
    model: str
    provider: str
    fixture_run: bool
    raw_response: str


class CitationVerification(BaseModel):
    """
    @brief Deterministic verification result for one citation.
    @param citation Original citation.
    @param verified Whether the citation passed.
    @param reason Failure reason when unverified.
    """

    citation: Citation
    verified: bool
    reason: str | None = None


class ProbeVerification(BaseModel):
    """
    @brief Deterministic verification result for one runnable probe.
    @param kind Probe kind.
    @param command Command argv executed.
    @param passed Whether the probe passed.
    @param stdout Captured standard output.
    @param stderr Captured standard error.
    @param reason Failure reason for unsuccessful probes.
    """

    kind: str
    command: list[str]
    passed: bool
    stdout: str
    stderr: str
    reason: str | None = None


class VerificationResult(BaseModel):
    """
    @brief Verification state for one DocDrift finding.
    @param finding_id Related finding identifier.
    @param doc_check Documentation citation verification result.
    @param code_check Code citation verification result.
    @param probe_check Optional runnable probe verification result.
    @param fully_verified True only when all available checks pass.
    """

    finding_id: str
    doc_check: CitationVerification
    code_check: CitationVerification
    probe_check: ProbeVerification | None
    fully_verified: bool


class AnalysisRunSummary(BaseModel):
    """
    @brief Summary metrics for one analysis run.
    @param repo_url Analysed repository URL.
    @param ref Analysed reference.
    @param context_tokens Packed context tokens.
    @param input_tokens Billed input token count.
    @param output_tokens Billed output token count.
    @param cached_input_tokens Cached input token count.
    @param latency_seconds End-to-end latency.
    @param findings_total Number of findings produced.
    @param findings_fully_verified Number of fully verified findings.
    @param atlas_claims_total Number of atlas claims produced.
    @param atlas_citations_verified Number of verified atlas citations.
    @param fixture_run True when generated from fixture data.
    @param rate_limit_headers Captured x-ratelimit-* headers.
    """

    repo_url: str
    ref: str
    context_tokens: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    latency_seconds: float
    findings_total: int
    findings_fully_verified: int
    atlas_claims_total: int
    atlas_citations_verified: int
    fixture_run: bool
    rate_limit_headers: dict[str, str]
