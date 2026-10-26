"""Tests for DocDrift v2 hybrid rendering helpers."""

from __future__ import annotations

from repoatlas.app import _render_bug_wall_html, _rewrite_finding_display_fields
from repoatlas.hybrid_view import (
    build_beam_did_markdown,
    build_comparison_table,
    build_long_context_markdown,
    build_notes_markdown,
    build_v2_replay_rows,
    compute_hero_stats,
    headline_sentence,
    load_hybrid_payload,
    merge_hybrid_true_findings,
    render_hero_html,
)


def test_hybrid_headline_and_comparison_are_data_driven() -> None:
    """
    @brief Headline, comparison table, and notes must come from hybrid artifacts.
    """

    payload = load_hybrid_payload()
    assert payload["available"] is True
    stats = compute_hero_stats(payload)
    headline = headline_sentence(stats)
    assert headline == (
        "34 real docs bugs in 12 Python libraries. "
        "3 in 4 flagged findings were real (45 of 60); "
        "29 bugs reproduce a real API error when you run the docs"
    )
    assert stats["rejected_true"] == 0
    assert stats["true_candidates_judged"] == 32
    assert stats["false_repro_badges"] == 3
    headers, rows = build_comparison_table(payload)
    assert headers == ["Method", "True drifts found", "Findings", "Precision", "Tokens"]
    methods = [str(row[0]).lower() for row in rows]
    assert any("symbol check" in method for method in methods)
    assert any("whole-repo" in method for method in methods)
    assert any("chunked" in method and "32k" in method for method in methods)
    assert any("chunked" in method and "128k" in method for method in methods)
    assert any(method.startswith("hybrid (symbol") for method in methods)
    assert any("repro-confirmed" in method for method in methods)
    found_cells = [str(row[1]) for row in rows]
    token_cells = [str(row[4]) for row in rows]
    assert any("15 of 33" in cell for cell in found_cells)
    assert any("9 of 33" in cell for cell in found_cells)
    assert any("4,739,392" in cell and "~9.2M triage-only" in cell for cell in token_cells)
    assert any("9,302,105" in cell and "~9.3M" in cell for cell in token_cells)
    notes = build_notes_markdown(payload)
    assert "union of what the methods found" in notes
    assert "rejected **0** of 32 true candidates" in notes
    assert "removing **15** of 24" in notes
    assert "S38, S39 false; S41 unclear" in notes
    assert "structlog: Beam's triage reply had no JSON" in notes
    assert "11** local docstring" in notes
    assert "after the first repro run" in notes
    assert "No prompt caching" in notes
    assert "9.2M" in notes
    assert "9,302,105" in notes
    assert "11 of 12 libraries" in notes
    assert "hand-checked" not in notes.lower()
    assert "hand-verified" not in notes.lower()
    assert "hand-true" not in notes


def test_hero_units_and_wording() -> None:
    """
    @brief Hero tiles must keep distinct-bug counts separate from finding-level rates.
    """

    payload = load_hybrid_payload()
    stats = compute_hero_stats(payload)
    hero = render_hero_html(stats)
    assert "0 of 32" in hero
    assert "Real bugs Beam's triage threw away" in hero
    assert "45 / 60" in hero
    assert "checked against the source by an AI reviewer" in hero
    assert "hand-checked" not in hero.lower()
    assert "hand-verified" not in hero.lower()
    beam_did = build_beam_did_markdown(stats, 947446, (5, 6), (0, 6))
    assert "rejected 0 of 32" in beam_did
    assert "947,446" in beam_did
    assert "5/6" in beam_did
    assert "0/6" in beam_did
    assert "seed 1" in beam_did
    assert "4,755,853" in beam_did
    assert "tail-of-prompt" not in beam_did
    long_context = build_long_context_markdown(stats, 947446, (5, 6), (0, 6))
    assert "not** a better detector" in long_context or "not a better detector" in long_context


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
            "doc_citation": {"path": "docs/websockets.md", "start_line": 73, "end_line": 73},
            "code_citation": {"path": "starlette/websockets.py", "start_line": 136, "end_line": 136},
        }
    ]
    merged = merge_hybrid_true_findings(existing, payload)
    keys = {str(item.get("finding_key", "")) for item in merged}
    assert "starlette-400000/DD-1" in keys
    assert any(key.startswith("hybrid/") for key in keys)
    assert any(bool(item.get("repro_is_strict_api_error")) for item in merged)
    starlette = next(item for item in merged if str(item.get("finding_key", "")) == "starlette-400000/DD-1")
    assert starlette.get("repro_is_strict_api_error") is False
    assert "isn't counted in the 29" in str(starlette.get("repro_badge_override", ""))
    jinja = next(
        item
        for item in merged
        if str(item.get("hybrid_drift_id", "")) == "N:jinja-install_translations"
        or str(item.get("finding_id", "")) == "ADD-AD-1"
        and "jinja" in str(item.get("finding_key", ""))
    )
    jinja_doc = jinja.get("doc_citation") if isinstance(jinja.get("doc_citation"), dict) else {}
    assert int(jinja_doc.get("start_line", 0)) == 157
    assert int(jinja_doc.get("end_line", 0)) == 158
    wall = _render_bug_wall_html(merged)
    assert "Code: :" not in wall
    assert "Verifier: hybrid" not in wall
    assert "distance not derivable" not in wall
    assert "draft prepared, unfiled" not in wall
    assert "independently confirmed" not in wall
    httpx_s4 = next(item for item in merged if str(item.get("hybrid_drift_id", item.get("finding_id", ""))) == "S4")
    assert bool(httpx_s4.get("is_cross_file")) is True
    replay = build_v2_replay_rows(payload, compute_hero_stats(payload), 394577)
    replay_text = " ".join(str(cell) for row in replay for cell in row)
    assert "Symbol check" in replay_text
    assert "Beam triage" in replay_text
    assert "394,577" in replay_text


def test_upstream_badges_use_also_reported_wording() -> None:
    """
    @brief Arrow and httpx prior-art badges must name the other reporter's PR.
    """

    arrow = _rewrite_finding_display_fields(
        {
            "finding_key": "arrow-400000/DD-1",
            "case_name": "arrow-400000",
            "hand_verdict": "true",
            "upstream_status": "independently confirmed by an open upstream PR",
            "upstream_url": "https://github.com/arrow-py/arrow/pull/1355",
            "upstream_prior_reported": True,
            "repo_url": "https://github.com/arrow-py/arrow",
        }
    )
    httpx = _rewrite_finding_display_fields(
        {
            "finding_key": "httpx-400000/DD-1",
            "case_name": "httpx-400000",
            "hand_verdict": "true",
            "upstream_status": "independently confirmed by an open upstream PR",
            "upstream_url": "https://github.com/encode/httpx/pull/3774",
            "upstream_prior_reported": True,
            "repo_url": "https://github.com/encode/httpx",
        }
    )
    assert arrow["upstream_status"] == "Already reported upstream by others: open PR #1355"
    assert httpx["upstream_status"] == "Already reported upstream by others: open PR #3774"
    starlette = _rewrite_finding_display_fields(
        {
            "finding_key": "starlette-400000/DD-1",
            "case_name": "starlette-400000",
            "hand_verdict": "true",
            "repo_url": "https://github.com/encode/starlette",
            "repro_is_strict_api_error": True,
        }
    )
    assert starlette["repo_url"] == "https://github.com/Kludex/starlette"
    assert starlette["repro_is_strict_api_error"] is False
    assert "isn't counted in the 29" in str(starlette["repro_badge_override"])
