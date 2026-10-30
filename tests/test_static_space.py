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
    assert hero["headline"] == headline_sentence(stats).replace(
        f"in {stats['repo_count']} Python libraries",
        f"in {hero['true_library_count']} of {stats['repo_count']} Python libraries",
    )
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
    strict_tokens = str(next(row[4] for row in compare_rows if "repro-confirmed" in str(row[0]).lower()))
    assert "~9.2M tokens (two whole-repo passes over 12 libraries)" in hybrid_tokens
    assert "9,302,105" not in hybrid_tokens
    assert "~9.3M tokens (two whole-repo passes plus repro scripts)" in strict_tokens
    assert "9,302,105" in documents["benchmark"]["token_footnote"]
    assert "4,739,392" in documents["benchmark"]["token_footnote"]
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
    assert "bugs in 11 of 12 libraries" in hero["lead"]
    assert "pydantic-settings had none" in hero["lead"]
    assert hero["true_library_count"] == 11
    replay = documents["replay"]
    assert replay["drift_card"]["doc_line"] == 74
    assert "receive_json(data, mode=\"binary\")" in replay["drift_card"]["doc_quote"]
    assert "mode: str = \"text\"" in replay["drift_card"]["code_quote"]
    assert replay["drift_card"]["error"].startswith("TypeError")
    assert replay["candidates"][1]["doc_line"] == 73
    assert "line 74" in replay["drift_card"]["doc_line_note"]
    starlette_cards = [bug for bug in documents["bugs"] if bug["library"] == "starlette"]
    assert starlette_cards
    assert starlette_cards[0]["display_id"].startswith("STR-")
    true_libs = {bug["library"] for bug in documents["bugs"] if bug["verdict"] == "true"}
    assert len(true_libs) == 11
    pack = documents["benchmark"]["pack_coverage"]
    assert pack["available"] is True
    starlette_pack = next(row for row in pack["rows"] if row[0] == "starlette")
    assert starlette_pack[4] == "yes"
    assert "327,836" in pack["note"]
    copy = documents["copy"]
    assert "app.py" not in copy["cli"]
    assert "run_benchmark.py" not in copy["cli"]
    assert copy["local"] == ""
    assert copy["links"]["code"].endswith("repoatlas-1m")
    assert copy["video"] == "assets/docdrift-demo.mp4"
    assert copy["video_poster"] == "assets/docdrift-poster.png"
    assert copy["video_captions"] == "assets/docdrift-demo.vtt"
    assert "185,842" in copy["sample_output"]
    assert "tomlkit" in copy["sample_output"].lower()
    assert "STRICT-CONFIRMED" in copy["sample_output"]
    assert "185,842" in copy["sample_note"]
    assert "strict-confirmed" in copy["sample_note"]
    assert "arguable as drift" in copy["sample_note"]
    assert "both true when checked against the source" not in copy["sample_note"]
    assert copy["sample_cast"] == "assets/docdrift_tomlkit.cast"
    assert "not run yet" not in copy["why_matched_cost_note"].lower()
    assert "46/56" in copy["why_matched_cost_note"]
    assert "25/30" in copy["why_matched_cost_note"] and "19/30" in copy["why_matched_cost_note"]
    assert "11/13" in copy["why_matched_cost_note"] and "6/13" in copy["why_matched_cost_note"]
    assert "not shown at this n" in copy["why_matched_cost_note"]
    assert "5 of 13" in copy["why_matched_cost_note"]
    assert "Extra experimental runs, not in the 9.3M" in documents["benchmark"]["token_footnote"]
    assert "3,957,434" in documents["benchmark"]["token_footnote"]
    assert "together" not in documents["benchmark"]["token_footnote"].lower()
    assert "4,143,276" not in documents["benchmark"]["token_footnote"]
    assert "isolated venv" in copy["ollama_key"]
    assert "--out findings" in copy["cli"]
    assert "24 + 1 + 9 = 34" in copy["how_beam"][1]
    assert "taking distinct trues from 24 to 34" not in copy["how_beam"][1]
    assert len(copy["how_beam"]) == 3
    assert all("Long context didn't make verdicts" not in item for item in copy["how_beam"])
    assert "[ollama.com](https://ollama.com)" in copy["ollama_key"]
    beam_row = next(row for row in copy["criteria"] if row["title"] == "Beam")
    assert "46/56" in beam_row["body"] and "47/56" in beam_row["body"]
    assert "19/30" in beam_row["body"] and "25/30" in beam_row["body"]
    assert "not shown at this n" in beam_row["body"]
    assert any("prompt 404,652 tokens" in item for item in copy["limits"])
    assert "11 of 12" in hero["headline"]
    assert "in 12 Python libraries" not in hero["headline"]
    assert copy["repro_caption"].startswith("Some bugs have 2 scripts")
    assert any(row.get("source_id") for row in documents["repros"])
    assert "0.926" in copy["why_subset_note"]
    assert "0.815" in copy["why_subset_note"]
    arw02 = next(bug for bug in documents["bugs"] if bug["display_id"] == "ARW-02")
    assert "automodule:: arrow.locales" in arw02["doc_quote"]
    dumped = json.dumps(documents)
    assert "Symbol not found anywhere" not in dumped
    assert "C02" not in json.dumps(documents["replay"]["drift_card"])
    assert "C03" not in json.dumps(documents["replay"]["drift_card"])
    assert "whole-repo pass" in documents["replay"]["drift_card"]["found_by"]
    assert "v2" not in documents["replay"]["repro_note"]
    assert all("v2" not in str(bug.get("badge_note") or "") for bug in documents["bugs"])
    hybrid_beamv3 = next(row for row in beamv3["rows"] if str(row[0]).startswith("Hybrid (existing"))
    assert "triage pass only" in str(hybrid_beamv3[11])
    dumped = json.dumps(documents).lower()
    assert "improves accuracy" not in dumped
    assert "improves precision" not in dumped
    assert "not run yet" not in dumped
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
    assert "python3 app.py" not in index_html
    assert "run_benchmark.py" not in index_html
    assert "Gradio" not in index_html
    assert 'role="tab"' in index_html
    assert 'id="drift-card"' in index_html
    assert 'tabindex="-1"' in index_html
    assert 'src="assets/docdrift-demo.mp4"' in index_html
    assert 'preload="metadata"' in index_html
    assert "playsinline" in index_html
    assert "muted" in index_html
    assert 'poster="assets/docdrift-poster.png"' in index_html
    assert 'src="assets/docdrift-demo.vtt"' in index_html
    assert 'width="1280"' in index_html and 'height="720"' in index_html
    assert 'aria-label="DocDrift demo, 87 seconds, silent with on-screen captions"' in index_html
    assert 'label="English (same as on-screen)"' in index_html
    assert '<details class="transcript">' in index_html
    assert "32 of the 34 bugs ship a script" in index_html
    assert "Result of a real run at pinned commit 8aa828c" in index_html
    assert "Every bug ships a script that ran its documented line" not in index_html
    assert "Every bug ships a script that runs the documented line" not in index_html
    assert (target / "assets" / "docdrift-demo.mp4").exists()
    assert (target / "assets" / "docdrift-poster.png").exists()
    assert (target / "assets" / "docdrift-demo.vtt").exists()
    assert not (target / "assets" / "docdrift-75s.mp4").exists()
    assert "*.mp4 filter=lfs diff=lfs merge=lfs -text" in (target / ".gitattributes").read_text(encoding="utf-8")
    assert 'id="demo-video" class="demo-video" hidden' not in index_html
    assert index_html.find('id="demo-video"') > index_html.find('id="drift-card"')
    assert 'content="assets/og.png"' in index_html
    css = (target / "assets" / "app.css").read_text(encoding="utf-8")
    assert "video{display:none}" not in css.replace(" ", "")
    assert ".ap-player *" in css
    assert "aspect-ratio: 16 / 9" in css or "aspect-ratio:16/9" in css
    assert "grid-column: 1 / -1" in css or "grid-column:1/-1" in css
    js = (target / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'sample.addEventListener("toggle"' in js
    assert "terminalFontSize" in js
    sample_pos = index_html.find('id="sample-output"')
    cli_pos = index_html.find("<h3>CLI</h3>")
    assert 0 < sample_pos < cli_pos
    assert "See a real run on tomlkit" in index_html
    assert Path("LICENSE").is_file()
    assert "Copyright (c) 2026 Olly McBride" in Path("LICENSE").read_text(encoding="utf-8")
    assert "MIT" in Path("README.md").read_text(encoding="utf-8")
    assert index_html.find('id="story"') < index_html.find('id="recorded-run"')
    assert "Loading recorded results" not in index_html
    assert "lead-full" in index_html
    assert 'id="sample-output"' in index_html
    assert 'id="sample-cast"' in index_html
    assert "asciinema-player.min.js" in index_html
    assert "cdn.jsdelivr" not in index_html
    assert "unpkg.com" not in index_html
    assert (target / "assets" / "asciinema-player.min.js").exists()
    assert (target / "assets" / "asciinema-player.css").exists()
    assert (target / "assets" / "docdrift_tomlkit.cast").exists()
    assert "Code not recorded" not in (target / "assets" / "app.js").read_text(encoding="utf-8")
    assert "Symbol not found anywhere" not in (target / "assets" / "app.js").read_text(encoding="utf-8")
    assert "False / unclear" in (target / "assets" / "app.js").read_text(encoding="utf-8")
    documents = build_static_payload()
    starlette_s1 = next(row for row in documents["repros"] if row["id"] == "starlette:S1")
    assert str(starlette_s1["display_id"]).startswith("STR-")
    arrow_s24 = next(row for row in documents["repros"] if row["id"] == "arrow:S24")
    assert str(arrow_s24["display_id"]).startswith("ARW-")
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "python3 app.py" not in readme
    assert "run_benchmark.py" not in readme
    assert "Gradio" not in readme
    assert "RepoAtlas-1M" not in readme
    assert "11 of 12" in readme
    assert "34 real docs bugs in 12 Python libraries" not in readme
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
