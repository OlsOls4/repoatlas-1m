"""Tests that the static Space JSON is generated from recorded results files."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from repoatlas.hybrid_view import compute_hero_stats, headline_sentence, load_hybrid_payload
from repoatlas.static_build import (
    HF_SHORT_DESCRIPTION_MAX,
    HF_SPACE_COLORS,
    build_static_payload,
    write_static_space,
)


def test_static_json_numbers_match_hybrid_results(tmp_path: Path) -> None:
    """
    @brief Generated hero and comparison numbers must equal hybrid.json / csv.
    """

    payload = load_hybrid_payload()
    stats = compute_hero_stats(payload)
    documents = build_static_payload()
    hero = documents["hero"]
    assert hero["headline"] == headline_sentence(stats)
    assert hero["hybrid_true"] == stats["hybrid_true"]
    assert hero["hybrid_findings"] == stats["hybrid_findings"]
    assert hero["hybrid_true_findings"] == stats["hybrid_true_findings"]
    assert hero["repro_true"] == stats["repro_true"]
    assert hero["rejected_true"] == stats["rejected_true"]
    assert hero["true_candidates_judged"] == stats["true_candidates_judged"]
    assert hero["removed_false"] == stats["removed_false"]
    hybrid = json.loads(Path("results_live/hybrid/hybrid.json").read_text(encoding="utf-8"))
    confusion = hybrid["triage_filter_confusion"]
    assert hero["judged"] == confusion["judged"]
    assert hero["rejected_true"] == confusion["beam_not_true__hand_true"]
    assert hero["triage_tokens"] == hybrid["beam_tokens"]["triage"]
    assert hero["repro_tokens"] == hybrid["beam_tokens"]["repro_live"]
    probe = json.loads(Path("results_live/recall/context_probe.json").read_text(encoding="utf-8"))
    max_probe = max(int(row["usage"]["prompt_tokens"]) for row in probe)
    assert hero["max_probe_tokens"] == max_probe
    compare_rows = documents["benchmark"]["rows"]
    found = {str(row[0]): row for row in compare_rows}
    assert any("15 of 33" in str(row[1]) for row in compare_rows)
    assert any("9 of 33" in str(row[1]) for row in compare_rows)
    hybrid_tokens = str(next(row[4] for row in compare_rows if "hybrid (symbol" in str(row[0]).lower()))
    assert "4,739,392" in hybrid_tokens
    assert "~9.2M triage-only" in hybrid_tokens
    assert any("9,302,105" in str(row[4]) or "~9.3M" in str(row[4]) for row in compare_rows)
    ablation = documents["benchmark"]["ablation"]
    assert ablation["available"] is True
    assert ablation["claim"].startswith("Long context didn't make verdicts more accurate")
    assert any(row[0] == "Cross-file cases: right verdict + citation" and row[1] == "25/30" and row[2] == "14/30" for row in ablation["rows"])
    beamv3 = documents["benchmark"]["beamv3"]
    assert beamv3["available"] is True
    assert beamv3["title"] == "Catching what one whole-repo call misses"
    assert beamv3["py32k_extra_of_45"] == 7
    assert beamv3["docs_extra_of_45"] == 1
    assert beamv3["union_of_45"] == 42
    assert beamv3["hybrid_of_45"] == 34
    assert beamv3["py32k_precision_lb"] == "18.5%"
    assert "lower bound" in beamv3["claim"]
    assert beamv3["recipe"].startswith("Recommended: symbol check + whole-repo Beam triage")
    assert hero["hybrid_true"] == 34
    assert hero["repro_true"] == 30
    dumped = json.dumps(documents).lower()
    assert "improves accuracy" not in dumped
    assert "improves precision" not in dumped
    assert found


def test_static_upstream_and_replay_are_honest(tmp_path: Path) -> None:
    """
    @brief Filed PRs are only starlette #3746 and nox #1216; replay tokens come from the trace.
    """

    documents = build_static_payload()
    filed = [bug for bug in documents["bugs"] if bug.get("upstream") and bug["upstream"]["kind"] == "filed_open"]
    filed_labels = {bug["upstream"]["label"] for bug in filed}
    assert any("3746" in label for label in filed_labels)
    assert any("1216" in label for label in filed_labels)
    for bug in filed:
        assert bug["library"] not in {"cattrs", "click"}
        assert "cattrs" not in str(bug["upstream"]).lower()
        assert "click" not in str(bug["upstream"]).lower()
    for bug in documents["bugs"]:
        if bug["library"] in {"cattrs", "click"}:
            assert bug.get("upstream") is None
    trace = json.loads(Path("results_live/traces/starlette-400000.json").read_text(encoding="utf-8"))
    replay = documents["replay"]
    assert replay["is_recording"] is True
    assert replay["prompt_tokens"] == trace["summary"]["input_tokens"]
    assert replay["completion_tokens"] == trace["summary"]["output_tokens"]
    assert replay["pack_tokens"] == trace["pack"]["total_tokens"]
    assert replay["recorded_at"] == trace["pack"]["packed_at"]
    assert replay["candidate_count"] == 3
    assert replay["symbol_candidates"] == 2
    assert replay["whole_candidates"] == 1
    assert replay["kept"] == 2
    assert replay["rejected"] == 1
    assert replay["pr"]["url"].endswith("/3746")
    assert replay["tracebacks"]
    assert any(str(row.get("status")) == "reproduced" and str(row.get("exception_type")) == "TypeError" for row in replay["tracebacks"])
    assert "written by hand from Beam's verdict" in replay["repro_note"]
    assert "could not run" not in replay["repro_note"]
    dumped = json.dumps(documents)
    assert "file only lists starlette" not in dumped
    assert "after results_live/upstream_status.json was written" not in dumped
    assert "hand-checked" not in dumped.lower()
    assert "hand-verified" not in json.dumps(documents).lower()
    assert "/workspace/" not in json.dumps(documents)
    false_cards = [bug for bug in documents["bugs"] if bug["badge"] == "false"]
    assert false_cards
    httpx_s7 = next(bug for bug in false_cards if bug["id"] == "httpx/S7")
    assert httpx_s7["doc_path"]
    assert httpx_s7["doc_url"].startswith("https://github.com/")
    assert "cattrs" not in httpx_s7["doc_url"]
    arrow_ad1 = next(bug for bug in false_cards if bug["id"] == "arrow/ADD-AD-1")
    assert arrow_ad1["doc_path"] == "docs/guide.rst"
    assert arrow_ad1["doc_line"] == 398


def test_write_static_space_emits_hf_yaml(tmp_path: Path) -> None:
    """
    @brief The generated Space folder has static YAML and fetchable JSON.
    """

    target = write_static_space(tmp_path / "static_space")
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "sdk: static" in readme
    assert "app_file: index.html" in readme
    assert (target / "index.html").exists()
    assert (target / "assets" / "app.js").exists()
    assert (target / "assets" / "app.css").exists()
    index_html = (target / "index.html").read_text(encoding="utf-8")
    assert 'id="recorded-run"' in index_html
    assert "DocDrift" in index_html
    hero = json.loads((target / "data" / "hero.json").read_text(encoding="utf-8"))
    stats = compute_hero_stats(load_hybrid_payload())
    assert hero["hybrid_true"] == stats["hybrid_true"]
    assert hero["repro_true"] == stats["repro_true"]


def test_static_readme_front_matter_matches_hf_limits(tmp_path: Path) -> None:
    """
    @brief Hugging Face rejects unknown colorTo values and short_description over 60 chars.
    """

    target = write_static_space(tmp_path / "static_space")
    readme = (target / "README.md").read_text(encoding="utf-8")
    front = readme.split("---", 2)[1]
    meta = yaml.safe_load(front)
    assert meta["colorFrom"] in HF_SPACE_COLORS
    assert meta["colorTo"] in HF_SPACE_COLORS
    assert isinstance(meta["short_description"], str)
    assert len(meta["short_description"]) <= HF_SHORT_DESCRIPTION_MAX
    assert meta["colorTo"] == "green"
    assert meta["short_description"] == "Beam finds real docs-vs-code bugs in Python libraries"
