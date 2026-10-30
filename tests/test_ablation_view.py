"""Ablation display numbers must come from results_live/ablation/results.json."""

from __future__ import annotations

from pathlib import Path

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
    assert payload["matched_available"] is True
    assert payload["accuracy_matched"] == "0.821"
    assert payload["accuracy_frac_matched"] == "46/56"
    assert payload["accuracy_frac_whole"] == "47/56"
    assert payload["cross_file_cite_matched"] == "19/30"
    assert payload["outside_cite_matched"] == "6/13"
    assert payload["matched_tokens"] == 3_888_241
    assert payload["matched_ledger_tokens"] == 3_957_434
    assert payload["matched_ledger_calls"] == 57
    assert payload["matched_mcnemar_p"] == "0.070"
    assert payload["gold_file_retrieved"] == "8/13"
    assert payload["gold_file_missed"] == 5
    note = payload["why_matched_cost_note"]
    assert "not run yet" not in note.lower()
    assert "46/56" in note and "47/56" in note
    assert "25/30" in note and "19/30" in note
    assert "11/13" in note and "6/13" in note
    assert "not shown at this n" in note
    assert "5 of 13" in note
    assert "importers" in note.lower() or "re-export" in note.lower()
    assert payload["matched_ext_available"] is True
    assert payload["matched_ext_cross_whole"] == "52/78"
    assert payload["matched_ext_cross_matched"] == "38/78"
    assert payload["matched_ext_p"] == "0.0094"
    assert payload["matched_ext_tokens"] == 7_528_878
    assert payload["matched_ext_outside_whole"] == "38/61"
    assert payload["matched_ext_outside_matched"] == "25/61"
    assert payload["matched_ext_outside_p"] == "0.0146"
    assert "Pre-registered extension" in note and "p = 0.096" in note
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


def test_matched_cost_scripts_are_repo_relative() -> None:
    """
    @brief Recorded-run helper scripts must not hardcode a local checkout or secret path.
    """

    for name in ("scripts/matched_cost.py", "scripts/matched_score.py"):
        src = Path(name).read_text(encoding="utf-8")
        assert "/workspace/docdrift_main" not in src
        assert "/workspace/ablation" not in src
        assert "/home/box" not in src
        assert "OLLAMA_API_KEY" in src or name.endswith("matched_score.py")
    replay = (
        "scripts/ablation_triage.py",
        "scripts/baseline_chunked_beam.py",
        "scripts/beamv3.py",
        "scripts/beamv3_repro.py",
        "scripts/hybrid_repro.py",
        "scripts/hybrid_triage.py",
        "scripts/run_recall.py",
    )
    for name in replay:
        src = Path(name).read_text(encoding="utf-8")
        assert "load_ollama_api_key" in src
        assert 'Path("/home/box/.secrets/ollama_api_key").read_text()' not in src
    helper = Path("repoatlas/config.py").read_text(encoding="utf-8")
    env_pos = helper.index('os.environ.get("OLLAMA_API_KEY"')
    fallback_use = helper.index("FALLBACK_OLLAMA_KEY_FILE.is_file()")
    assert env_pos < fallback_use
