"""Tests for deterministic citation verification."""

from __future__ import annotations

from repoatlas.models import Citation, RepoFileSnapshot, RepoPack
from repoatlas.verifier import verify_citation


def _build_pack() -> RepoPack:
    """
    @brief Build a small in-memory pack for verifier unit tests.
    """

    return RepoPack(
        repo_url="https://github.com/example/repo",
        ref="main",
        prefix_hash="unit-test",
        total_tokens=10,
        token_limit=10,
        truncated=False,
        packed_at="2026-10-26T00:00:00Z",
        files=[
            RepoFileSnapshot(
                path="README.md",
                lines=["Usage: run --limit 400000", "Set BEAM_PROVIDER=ollama"],
                token_count=10,
            )
        ],
        skipped_paths=[],
        pack_text="fixture",
    )


def test_verify_citation_passes_for_matching_quote() -> None:
    """
    @brief Ensure a citation verifies when quote and line range match.
    """

    pack = _build_pack()
    lookup: dict[str, list[str]] = {file_snapshot.path: file_snapshot.lines for file_snapshot in pack.files}
    citation = Citation(path="README.md", start_line=1, end_line=1, quote="--limit 400000")
    result = verify_citation(citation, lookup)
    assert result.verified is True


def test_verify_citation_fails_when_quote_missing() -> None:
    """
    @brief Ensure a citation fails when quote text is absent from cited lines.
    """

    pack = _build_pack()
    lookup: dict[str, list[str]] = {file_snapshot.path: file_snapshot.lines for file_snapshot in pack.files}
    citation = Citation(path="README.md", start_line=1, end_line=1, quote="--limit 900000")
    result = verify_citation(citation, lookup)
    assert result.verified is False
    assert result.reason == "quote-not-found-in-range"


def test_verify_citation_fails_for_missing_file() -> None:
    """
    @brief Ensure a citation fails for a non-existent file path.
    """

    pack = _build_pack()
    lookup: dict[str, list[str]] = {file_snapshot.path: file_snapshot.lines for file_snapshot in pack.files}
    citation = Citation(path="docs/guide.md", start_line=1, end_line=1, quote="guide")
    result = verify_citation(citation, lookup)
    assert result.verified is False
    assert result.reason == "file-not-found"
