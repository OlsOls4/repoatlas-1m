"""Tests for DocDrift v2 hybrid rendering helpers."""

from __future__ import annotations

from repoatlas.hybrid_view import (
    build_comparison_table,
    build_notes_markdown,
    compute_hero_stats,
    headline_sentence,
    load_hybrid_payload,
    merge_hybrid_true_findings,
)


def test_hybrid_headline_and_comparison_are_data_driven() -> None:
    """
    @brief Headline, comparison table, and notes must come from hybrid artifacts.
    """

    payload = load_hybrid_payload()
    assert payload["available"] is True
    stats = compute_hero_stats(payload)
    headline = headline_sentence(stats)
    assert str(stats["hybrid_true"]) in headline
    assert str(stats["repo_count"]) in headline
    assert str(stats["repro_true"]) in headline
    headers, rows = build_comparison_table(payload)
    assert headers == ["Method", "True drifts found", "Findings", "Precision", "Tokens"]
    methods = [str(row[0]).lower() for row in rows]
    assert any("symbol check" in method for method in methods)
    assert any("whole-repo" in method for method in methods)
    assert any("chunked" in method and "32k" in method for method in methods)
    assert any("chunked" in method and "128k" in method for method in methods)
    assert any(method.startswith("hybrid (symbol") for method in methods)
    assert any("repro-confirmed" in method for method in methods)
    notes = build_notes_markdown(payload)
    assert "union of what the methods found" in notes
    assert "rejected **0** hand-true" in notes
    assert "keeping **9** false" in notes
    assert "structlog triage failed" in notes
    assert "11** local docstring" in notes
    assert "after the first repro run" in notes
    assert "No prompt caching" in notes


def test_build_app_constructs_with_hybrid_headline() -> None:
    """
    @brief Building the Space should succeed and include DocDrift v2 copy.
    """

    from repoatlas.app import build_app

    demo = build_app()
    assert demo is not None


def test_hybrid_bug_wall_includes_new_true_drifts() -> None:
    """
    @brief Bug-wall merge should keep earlier true cards and add hybrid-only drifts.
    """

    payload = load_hybrid_payload()
    existing = [
        {
            "finding_key": "starlette-400000/DD-1",
            "finding_id": "DD-1",
            "case_name": "starlette-400000",
            "hand_verdict": "true",
            "is_cross_file": True,
            "token_distance": 122786,
            "repo_url": "https://github.com/Kludex/starlette",
            "breakage_summary": "TypeError when following docs",
        }
    ]
    merged = merge_hybrid_true_findings(existing, payload)
    keys = {str(item.get("finding_key", "")) for item in merged}
    assert "starlette-400000/DD-1" in keys
    assert any(key.startswith("hybrid/") for key in keys)
    assert any(bool(item.get("repro_is_strict_api_error")) for item in merged)
