"""Beam v3 display numbers must come from results_live/beamv3/results.json."""

from __future__ import annotations

from repoatlas.beamv3_view import (
    RECIPE,
    SECTION_TITLE,
    beamv3_markdown_table,
    load_beamv3_payload,
)


def test_beamv3_payload_matches_recorded_results() -> None:
    """
    @brief py32k recovered 7 of 11; docs 1; union 34 -> 42; precision is a lower bound.
    """

    payload = load_beamv3_payload()
    assert payload["available"] is True
    assert payload["title"] == SECTION_TITLE
    assert payload["recipe"] == RECIPE
    assert payload["recovered"] == 8
    assert payload["py32k_extra_of_45"] == 7
    assert payload["docs_extra_of_45"] == 1
    assert payload["hybrid_of_45"] == 34
    assert payload["union_of_45"] == 42
    assert payload["new_ai_verified"] == 7
    assert payload["py32k_precision_lb"] == "18.5%"
    assert payload["py32k_precision_labelled"] == "60.0%"
    assert payload["py32k_marginal"] == 140_047
    assert payload["docs_marginal"] == 1_495_308
    assert payload["stability_agree"] == 18
    assert payload["stability_n"] == 19
    assert payload["ledger_tokens"] == 7_713_453
    assert payload["ledger_calls"] == 168
    assert payload["still_missed"] == ["C:attrs-py2-reprs", "C:httpx-sslcontext", "C:mm-quotes-400"]


def test_beamv3_table_and_claim_are_honest() -> None:
    """
    @brief Unlabelled findings are not counted as true; headline stays 34 of 45.
    """

    payload = load_beamv3_payload()
    table = beamv3_markdown_table(payload)
    assert "18.5%" in table
    assert "60.0%" in table
    assert "7,713,453" not in table
    assert any(row[0] == "Hybrid + (b): new items only" and row[8] == "41" and row[9] == "7" for row in payload["rows"])
    assert any(row[0] == "Hybrid + (a) + (b): new items only" and row[8] == "42" for row in payload["rows"])
    assert "lower bound" in payload["claim"]
    assert "not counted as true" in payload["claim"]
    assert "Headline coverage stays 34 of 45" in " ".join(payload["caveats"])
    assert "unlabelled" in " ".join(payload["caveats"]).lower()
    assert "--docstring-chunks" in " ".join(payload["caveats"])
    assert "improves accuracy" not in payload["claim"].lower()
    assert "improves precision" not in table.lower()
