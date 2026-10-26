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


def test_parse_structured_content_handles_aliases_and_special_tokens() -> None:
    """
    @brief Beam via Ollama ignored json_schema and leaked <|im_end|>; parser must recover.
    """

    from repoatlas.client import parse_structured_content

    raw = (
        '{"doc_drift": [{"summary": "s", "doc": {"path": "a.rst", "start_line": 1, "end_line": 1, "quote": "q"}, '
        '"code": {"path": "b.py", "start_line": 2, "end_line": 2, "quote": "r"}, "proposed_fix": "f"}], '
        '"onboarding": [{"claim": "c", "doc": {"path": "a.rst", "start_line": 1, "end_line": 1, "quote": "q"}}]}<|im_end|>'
    )
    parsed, normalised = parse_structured_content(raw)
    assert normalised is True
    assert parsed.findings[0].doc_citation.path == "a.rst"
    assert parsed.findings[0].finding_id == "DD-1"
    assert parsed.atlas_claims[0].text == "c"
    assert len(parsed.atlas_claims[0].citations) == 1


def test_verify_citation_tolerates_dropped_indentation_only() -> None:
    """
    @brief A quote that only loses continuation-line indentation verifies, flagged as normalised.
    """

    from repoatlas.models import Citation
    from repoatlas.verifier import verify_citation

    lookup = {"docs/config.rst": ["    Enabling this implicitly enables X as well, as", "    it is only valid over HTTPS."]}
    ok = verify_citation(
        Citation(path="docs/config.rst", start_line=1, end_line=2, quote="Enabling this implicitly enables X as well, as\nit is only valid over HTTPS."),
        lookup,
    )
    assert ok.verified and ok.reason == "whitespace-normalised-match"
    bad = verify_citation(
        Citation(path="docs/config.rst", start_line=1, end_line=2, quote="Enabling this disables X"),
        lookup,
    )
    assert not bad.verified


def test_parse_structured_content_repairs_truncated_json() -> None:
    from repoatlas.client import parse_structured_content

    truncated = (
        '{"findings": [], "atlas_claims": [{"claim_id": "AC-1", "section": "s", "text": "t", '
        '"citations": [{"path": "a.py", "start_line": 1, "end_line": 1, "quote": "x"}]}'
    )
    parsed, _ = parse_structured_content(truncated)
    assert parsed.findings == []
    assert parsed.atlas_claims[0].claim_id == "AC-1"
