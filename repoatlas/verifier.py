"""Deterministic verification for citations and runnable checks."""

from __future__ import annotations

from pathlib import Path
import subprocess

from repoatlas.models import (
    AtlasClaim,
    Citation,
    CitationVerification,
    DocDriftFinding,
    ProbeVerification,
    RepoPack,
    RunnableProbe,
    VerificationResult,
)


LINE_SHIFT_WINDOW: int = 3

# Private function prototypes:
# - _match_quote(quote: str, lines: list[str], start_line: int, end_line: int) -> str | None
# - _shift_offsets(window: int) -> list[int]
# - _build_file_lookup(pack: RepoPack) -> dict[str, list[str]]
# - _normalise_path(path: str) -> str
# - _verify_probe(probe: RunnableProbe, repo_root: Path) -> ProbeVerification


def verify_citation(citation: Citation, file_lookup: dict[str, list[str]]) -> CitationVerification:
    """
    @brief Verify that a citation points to valid lines and contains the quoted text.
    @param citation Citation to verify.
    @param file_lookup Mapping of repository paths to file line lists.
    """

    normalised_path: str = _normalise_path(citation.path)
    if normalised_path not in file_lookup:
        return CitationVerification(citation=citation, verified=False, reason="file-not-found")
    lines: list[str] = file_lookup[normalised_path]
    if citation.start_line > citation.end_line:
        return CitationVerification(citation=citation, verified=False, reason="invalid-line-range")
    in_bounds: bool = citation.start_line >= 1 and citation.end_line <= len(lines)
    if in_bounds:
        match_label: str | None = _match_quote(citation.quote, lines, citation.start_line, citation.end_line)
        if match_label is not None:
            return CitationVerification(
                citation=citation,
                verified=True,
                reason=None if match_label == "exact" else match_label,
            )
    # Models often cite a range one or two lines away from the real quote. Search the same-length range
    # shifted by up to LINE_SHIFT_WINDOW lines (nearest first) and accept only a contiguous exact or
    # whitespace-normalised match there, recording where it really is.
    for offset in _shift_offsets(LINE_SHIFT_WINDOW):
        shifted_start: int = citation.start_line + offset
        shifted_end: int = citation.end_line + offset
        if shifted_start < 1 or shifted_end > len(lines):
            continue
        if _match_quote(citation.quote, lines, shifted_start, shifted_end) is not None:
            return CitationVerification(
                citation=citation,
                verified=True,
                reason="line-shifted-match",
                corrected_start_line=shifted_start,
                corrected_end_line=shifted_end,
                line_offset=offset,
            )
    if not in_bounds:
        return CitationVerification(citation=citation, verified=False, reason="line-range-out-of-bounds")
    return CitationVerification(citation=citation, verified=False, reason="quote-not-found-in-range")


def _match_quote(quote: str, lines: list[str], start_line: int, end_line: int) -> str | None:
    """
    @brief Match a quote against a contiguous 1-based inclusive line range.
    @param quote Quoted text from the citation.
    @param lines File lines.
    @param start_line First line of the range.
    @param end_line Last line of the range.
    @return "exact", "whitespace-normalised-match", or None when the quote is absent.
    """

    selected_text: str = "\n".join(lines[start_line - 1 : end_line])
    if quote.strip() and quote in selected_text:
        return "exact"
    # Models often drop leading indentation on continuation lines of a multi-line quote.
    # Accept a match that differs only in per-line leading/trailing whitespace, and say so.
    stripped_quote: str = _strip_lines(quote)
    if stripped_quote.strip() and stripped_quote in _strip_lines(selected_text):
        return "whitespace-normalised-match"
    return None


def _shift_offsets(window: int) -> list[int]:
    """
    @brief Return non-zero line offsets ordered nearest first, earlier before later: -1, 1, -2, 2, ...
    @param window Maximum absolute offset.
    """

    offsets: list[int] = []
    for distance in range(1, window + 1):
        offsets.extend((-distance, distance))
    return offsets


def _strip_lines(text: str) -> str:
    """
    @brief Strip leading and trailing whitespace from each line for lenient quote matching.
    @param text Multi-line text.
    """

    return "\n".join(line.strip() for line in text.split("\n"))


def verify_finding(
    finding: DocDriftFinding,
    pack: RepoPack,
    repo_root: Path | None = None,
    run_probes: bool = False,
) -> VerificationResult:
    """
    @brief Verify a DocDrift finding using citation checks and optional runnable probes.
    @param finding DocDrift finding to verify.
    @param pack Packed repository used for citation source lines.
    @param repo_root Optional local repository root for runnable probes.
    @param run_probes Whether runnable probes should be executed.
    """

    file_lookup: dict[str, list[str]] = _build_file_lookup(pack)
    doc_check: CitationVerification = verify_citation(finding.doc_citation, file_lookup)
    code_check: CitationVerification = verify_citation(finding.code_citation, file_lookup)
    probe_check: ProbeVerification | None = None
    if run_probes and finding.runnable_probe and repo_root is not None:
        probe_check = _verify_probe(finding.runnable_probe, repo_root)
    fully_verified: bool = doc_check.verified and code_check.verified and (probe_check.passed if probe_check else True)
    return VerificationResult(
        finding_id=finding.finding_id,
        doc_check=doc_check,
        code_check=code_check,
        probe_check=probe_check,
        fully_verified=fully_verified,
    )


def verify_findings(
    findings: list[DocDriftFinding],
    pack: RepoPack,
    repo_root: Path | None = None,
    run_probes: bool = False,
) -> list[VerificationResult]:
    """
    @brief Verify a list of DocDrift findings.
    @param findings DocDrift findings to verify.
    @param pack Packed repository used for citation source lines.
    @param repo_root Optional local repository root for runnable probes.
    @param run_probes Whether runnable probes should be executed.
    """

    return [
        verify_finding(finding=finding, pack=pack, repo_root=repo_root, run_probes=run_probes)
        for finding in findings
    ]


def verify_atlas_claims(claims: list[AtlasClaim], pack: RepoPack) -> tuple[int, int]:
    """
    @brief Verify citations inside atlas claims and return verified versus total counts.
    @param claims Atlas claims to verify.
    @param pack Packed repository used for citation source lines.
    """

    file_lookup: dict[str, list[str]] = _build_file_lookup(pack)
    verified: int = 0
    total: int = 0
    for claim in claims:
        for citation in claim.citations:
            total += 1
            if verify_citation(citation, file_lookup).verified:
                verified += 1
    return verified, total


def _build_file_lookup(pack: RepoPack) -> dict[str, list[str]]:
    """
    @brief Build a normalised lookup map from a packed repository snapshot.
    @param pack Packed repository payload.
    """

    return {_normalise_path(file_snapshot.path): file_snapshot.lines for file_snapshot in pack.files}


def _normalise_path(path: str) -> str:
    """
    @brief Normalise repository-relative path strings.
    @param path Original path value.
    """

    return path.replace("\\", "/").lstrip("./")


def _verify_probe(probe: RunnableProbe, repo_root: Path) -> ProbeVerification:
    """
    @brief Execute a runnable probe in a subprocess with timeout safeguards.
    @param probe Runnable probe specification.
    @param repo_root Local repository root.
    """

    if not probe.command:
        return ProbeVerification(
            kind=probe.kind,
            command=[],
            passed=False,
            stdout="",
            stderr="",
            reason="empty-command",
        )
    try:
        completed = subprocess.run(
            probe.command,
            cwd=repo_root,
            timeout=15,
            check=False,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        return ProbeVerification(
            kind=probe.kind,
            command=probe.command,
            passed=False,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            reason="timeout",
        )
    combined_output: str = f"{completed.stdout}\n{completed.stderr}"
    passed: bool = completed.returncode == 0 and probe.expected_substring in combined_output
    reason: str | None = None if passed else "expected-substring-missing-or-nonzero-exit"
    return ProbeVerification(
        kind=probe.kind,
        command=probe.command,
        passed=passed,
        stdout=completed.stdout,
        stderr=completed.stderr,
        reason=reason,
    )
