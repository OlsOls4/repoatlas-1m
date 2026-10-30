"""Ablation display numbers must come from results_live/ablation/results.json."""

from __future__ import annotations

from repoatlas.ablation_view import (
    CLAIM,
    ablation_long_context_blurb,
    ablation_markdown_table,
    load_ablation_payload,
)


def test_ablation_payload_matches_recorded_results() -> None:
    """
    @brief Same 56-candidate keep/reject split; grounding is the difference.
    """

    payload = load_ablation_payload()
    assert payload["available"] is True
    assert payload["n"] == 56
    assert payload["disagreements"] == 6
    assert payload["stability_agree"] == 26
    assert payload["stability_n"] == 27
    assert payload["whole_tokens"] == 4_022_532
    assert payload["local_tokens"] == 830_527
    assert payload["token_multiplier"] == 4.8
    assert payload["ablation_ledger_tokens"] == 1_948_469
    assert payload["cross_file_cite_whole"] == "25/30"
    assert payload["cross_file_cite_local"] == "14/30"
    assert payload["outside_cite_whole"] == "11/13"
    assert payload["outside_cite_local"] == "0/13"
    assert payload["accuracy_whole"] == payload["accuracy_local"] == "0.839"
    assert payload["accuracy_whole_subset"] == "0.815"
    assert payload["accuracy_local_subset"] == "0.926"
    assert "0.926 vs 0.815" in payload["subset_note"]
    assert "4/4 vs 0/4" in payload["subset_note"]
    kept = next(row for row in payload["rows"] if row[0] == "True candidates kept")
    rejected = next(row for row in payload["rows"] if row[0] == "False/unclear candidates rejected")
    assert kept[1] == kept[2] == "32/32"
    assert rejected[1] == rejected[2] == "15/24"


def test_ablation_claim_is_grounding_not_accuracy() -> None:
    """
    @brief Public copy must not claim a verdict-accuracy lift.
    """

    blurb = ablation_long_context_blurb()
    table = ablation_markdown_table()
    assert CLAIM in blurb
    assert "didn't make verdicts more accurate" in blurb
    assert "25/30" in blurb and "14/30" in blurb
    assert "improves accuracy" not in blurb.lower()
    assert "improves precision" not in table.lower()
    assert "32/32" in table and "11/13" in table
