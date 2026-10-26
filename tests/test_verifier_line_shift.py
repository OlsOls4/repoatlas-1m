"""Tests for line-shift-tolerant citation verification, using real off-by-one citations from live runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoatlas.models import Citation
from repoatlas.verifier import LINE_SHIFT_WINDOW, verify_citation

FIXTURE_PATH: Path = Path(__file__).parent / "fixtures" / "line_shift_cases.json"
CASES: list[dict[str, object]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _case(name: str) -> tuple[Citation, dict[str, list[str]]]:
    """
    @brief Load a saved live citation and the real file lines it points into.
    @param name Fixture case name.
    """

    case: dict[str, object] = next(item for item in CASES if item["name"] == name)
    citation: Citation = Citation.model_validate(case["citation"])
    return citation, {citation.path: list(case["lines"])}


@pytest.mark.parametrize(("name", "expected_line"), [("starlette", 74), ("hatch", 87)])
def test_live_off_by_one_citation_passes_as_line_shifted(name: str, expected_line: int) -> None:
    """
    @brief The saved starlette and hatch doc citations cite one line early and must pass as shifted matches.
    """

    citation, lookup = _case(name)
    assert citation.start_line == expected_line - 1
    result = verify_citation(citation, lookup)
    assert result.verified
    assert result.reason == "line-shifted-match"
    assert (result.corrected_start_line, result.corrected_end_line, result.line_offset) == (expected_line, expected_line, 1)


def test_exact_range_keeps_plain_pass() -> None:
    """
    @brief A correctly cited range passes without a shift label or corrections.
    """

    citation, lookup = _case("starlette")
    fixed = citation.model_copy(update={"start_line": 74, "end_line": 74})
    result = verify_citation(fixed, lookup)
    assert result.verified and result.reason is None and result.line_offset is None


def test_fabricated_quote_is_rejected_even_with_shift_window() -> None:
    """
    @brief A quote that does not exist anywhere nearby is still rejected.
    """

    citation, lookup = _case("starlette")
    fabricated = citation.model_copy(update={"quote": 'Use `websocket.receive_json(data, mode="text")` to receive JSON.'})
    result = verify_citation(fabricated, lookup)
    assert not result.verified and result.reason == "quote-not-found-in-range"


def test_non_contiguous_quote_is_rejected() -> None:
    """
    @brief Real lines 71 and 73 stitched together (skipping 72) must not verify at any cited range,
    while the genuinely contiguous lines 73-74 still verify.
    """

    citation, lookup = _case("starlette")
    lines = lookup[citation.path]
    assert lines[70].startswith("May raise") and lines[72].startswith("JSON messages")
    gap_quote = lines[70] + "\n" + lines[72]
    for start, end in ((71, 73), (71, 72), (72, 73), (70, 74)):
        result = verify_citation(citation.model_copy(update={"quote": gap_quote, "start_line": start, "end_line": end}), lookup)
        assert not result.verified, (start, end)
    contiguous_quote = lines[72] + "\n" + lines[73]
    assert verify_citation(citation.model_copy(update={"quote": contiguous_quote, "start_line": 72, "end_line": 73}), lookup).verified


def test_shift_window_is_bounded() -> None:
    """
    @brief A quote exactly LINE_SHIFT_WINDOW lines away passes; one line further is rejected.
    """

    citation, lookup = _case("starlette")
    inside = verify_citation(citation.model_copy(update={"start_line": 74 - LINE_SHIFT_WINDOW, "end_line": 74 - LINE_SHIFT_WINDOW}), lookup)
    assert inside.verified and inside.line_offset == LINE_SHIFT_WINDOW
    outside = verify_citation(citation.model_copy(update={"start_line": 73 - LINE_SHIFT_WINDOW, "end_line": 73 - LINE_SHIFT_WINDOW}), lookup)
    assert not outside.verified and outside.reason == "quote-not-found-in-range"


def test_out_of_bounds_range_can_shift_back_in_but_otherwise_stays_rejected() -> None:
    """
    @brief A range just past the end of file may shift onto the real quote; far out of bounds is rejected.
    """

    lookup = {"a.md": ["alpha", "beta", "gamma"]}
    near = verify_citation(Citation(path="a.md", start_line=4, end_line=4, quote="gamma"), lookup)
    assert near.verified and near.reason == "line-shifted-match" and near.corrected_start_line == 3
    far = verify_citation(Citation(path="a.md", start_line=9, end_line=9, quote="gamma"), lookup)
    assert not far.verified and far.reason == "line-range-out-of-bounds"


def test_whitespace_normalised_quote_can_also_be_shifted() -> None:
    """
    @brief The hatch quote with its indentation stripped still verifies after a shift.
    """

    citation, lookup = _case("hatch")
    result = verify_citation(citation.model_copy(update={"quote": citation.quote.strip()}), lookup)
    assert result.verified and result.reason == "line-shifted-match" and result.line_offset == 1


def test_blank_quote_is_rejected() -> None:
    """
    @brief Whitespace-only quotes never verify, shifted or not.
    """

    lookup = {"a.md": ["", "  ", "x"]}
    assert not verify_citation(Citation(path="a.md", start_line=1, end_line=2, quote="  "), lookup).verified
