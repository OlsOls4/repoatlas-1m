"""Gradio Space application for RepoAtlas-1M recorded and live views."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Mapping, TypedDict

import gradio as gr
import pandas as pd

from repoatlas.analyser import analyse_repository
from repoatlas.config import RepoAtlasConfig
from repoatlas.hybrid_view import (
    LABEL_SOURCE,
    already_reported_status,
    build_beam_did_markdown,
    build_comparison_table,
    build_long_context_markdown,
    build_notes_markdown,
    build_v2_replay_rows,
    canonicalize_repo_url,
    compute_hero_stats,
    docstring_pooled_text,
    headline_sentence,
    load_hybrid_payload,
    merge_hybrid_true_findings,
    non_bug_badge_phrase,
    render_hero_html as render_hybrid_hero_html,
    render_pipeline_html,
    strip_local_paths,
)
from repoatlas.packer import estimate_prompt_tokens, pack_repository


RESULTS_LIVE_DIRECTORY: Path = Path("results_live")
RESULTS_LIVE_INDEX_PATH: Path = RESULTS_LIVE_DIRECTORY / "index.json"
RESULTS_LIVE_REPROS_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "repros"
RESULTS_LIVE_REPROS_INDEX_PATH: Path = RESULTS_LIVE_REPROS_DIRECTORY / "repros.json"
RESULTS_LIVE_REPROS_SUMMARY_PATH: Path = RESULTS_LIVE_REPROS_DIRECTORY / "summary.json"
RESULTS_LIVE_RECALL_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "recall"
RESULTS_LIVE_RECALL_RUN_SUMMARY_PATH: Path = RESULTS_LIVE_RECALL_DIRECTORY / "run_summary.json"
RESULTS_LIVE_RECALL_BUCKETS_PATH: Path = RESULTS_LIVE_RECALL_DIRECTORY / "recall_by_bucket.csv"
RESULTS_LIVE_RECALL_CONTEXT_PROBE_PATH: Path = RESULTS_LIVE_RECALL_DIRECTORY / "context_probe.json"
RESULTS_LIVE_RECALL_USAGE_LEDGER_PATH: Path = RESULTS_LIVE_RECALL_DIRECTORY / "usage_ledger.json"
RESULTS_LIVE_RECALL_NOTE_PATH: Path = RESULTS_LIVE_RECALL_DIRECTORY / "recall.md"
RESULTS_LIVE_RECALL_CHART_PATH: Path = RESULTS_LIVE_RECALL_DIRECTORY / "recall_vs_distance.png"
RESULTS_LIVE_BASELINES_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "baselines"
RESULTS_LIVE_BASELINES_CSV_PATH: Path = RESULTS_LIVE_BASELINES_DIRECTORY / "baselines.csv"
RESULTS_LIVE_BASELINES_JSON_PATH: Path = RESULTS_LIVE_BASELINES_DIRECTORY / "baselines.json"
RESULTS_LIVE_BASELINES_COLOCATION_PATH: Path = RESULTS_LIVE_BASELINES_DIRECTORY / "colocation.json"
FIXTURE_PATH: Path = Path("fixtures/analysis_fixture.json")
LIVE_MAX_TOKEN_LIMIT: int = 150_000
LIVE_DEFAULT_TOKEN_LIMIT: int = 150_000
LIVE_RATE_LIMIT_PER_HOUR_PER_IP: int = int(os.environ.get("REPOATLAS_LIVE_PER_HOUR_PER_IP", "2"))
LIVE_DAILY_CAP: int = int(os.environ.get("REPOATLAS_LIVE_DAILY_CAP", "24"))
LIVE_DAILY_COUNTER_PATH: Path = Path(
    os.environ.get("REPOATLAS_LIVE_DAILY_COUNTER_PATH", ".cache/repoatlas/live_daily_counter.json")
)
THEME = gr.themes.Soft(primary_hue="indigo", secondary_hue="emerald", neutral_hue="slate")
CUSTOM_CSS: str = """
.repoatlas-hero {
  background: linear-gradient(135deg, #0f172a, #1e293b);
  color: #f8fafc;
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 16px;
}
.repoatlas-hero h2 {
  margin: 0 0 8px 0;
  font-size: 1.5rem;
  color: #f8fafc !important;
}
.repoatlas-hero p {
  margin: 0;
  color: #cbd5e1;
}
.repoatlas-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.repoatlas-stat-tile {
  background: rgba(30, 41, 59, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 12px;
  padding: 14px;
}
.repoatlas-stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 4px;
  color: #f8fafc !important;
}
.repoatlas-stat-label {
  font-size: 0.82rem;
  color: #f8fafc !important;
}
.repoatlas-diagram {
  border: 1px solid #dbeafe;
  border-radius: 12px;
  padding: 14px;
  background: #f8fafc;
}
.repoatlas-flow-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.repoatlas-node {
  background: #e2e8f0;
  border-radius: 10px;
  padding: 8px 10px;
  font-weight: 600;
}
.repoatlas-arrow {
  font-size: 1.2rem;
  color: #475569;
}
.repoatlas-bug-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 12px;
}
.repoatlas-bug-card {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  background: color-mix(in srgb, var(--block-background-fill, #ffffff) 95%, #0f172a 5%);
}
.repoatlas-bug-title {
  font-size: 1.03rem;
  font-weight: 700;
  margin-bottom: 6px;
}
.repoatlas-badge {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.76rem;
  margin-right: 6px;
  margin-bottom: 6px;
}
.repoatlas-badge-open {
  background: #fff7ed;
  color: #9a3412;
}
.repoatlas-badge-linked {
  background: #ecfeff;
  color: #155e75;
}
"""

_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_STATE: dict[str, list[float]] = {}
_DAILY_CAP_LOCK = threading.Lock()
STRICT_REPRO_EXCEPTION_TYPES: frozenset[str] = frozenset({"TypeError", "AttributeError", "ImportError", "NameError"})


class LiveIndex(TypedDict):
    """
    @brief Compact loaded payload for the Space view.
    @param summary Aggregate metrics.
    @param runs Run-level records.
    @param findings Finding-level records.
    @param handcheck_markdown_path Relative path to hand-check narrative.
    @param upstream_status_path Relative path to status source file.
    """

    summary: dict[str, object]
    runs: list[dict[str, object]]
    findings: list[dict[str, object]]
    handcheck_markdown_path: str
    upstream_status_path: str


class FindingPanelState(TypedDict):
    """
    @brief Pre-rendered finding details for UI display.
    @param verifier_badge Verifier status badge markdown.
    @param hand_badge Hand-check status badge markdown.
    @param upstream_badge Upstream status badge markdown.
    @param doc_header Documentation citation header.
    @param code_header Code citation header.
    @param doc_quote Documentation quote.
    @param code_quote Code quote.
    @param notes Human verification notes and context.
    @param repro_badge Reproduction outcome badge markdown.
    @param links Permalink and issue-draft metadata block.
    @param issue_draft_text Draft issue text for copy action.
    """

    verifier_badge: str
    hand_badge: str
    upstream_badge: str
    doc_header: str
    code_header: str
    doc_quote: str
    code_quote: str
    notes: str
    repro_badge: str
    links: str
    issue_draft_text: str


class RecallPanelData(TypedDict):
    """
    @brief Data bundle for the benchmark tab planted-drift recall section.
    @param available True when recall artifacts are present and parseable.
    @param summary_markdown Honest summary text derived from recall artifacts.
    @param probe_rows Probe table rows (target, observed prompt tokens, status, latency).
    @param bucket_headers Headers from recall_by_bucket.csv.
    @param bucket_rows Rows from recall_by_bucket.csv.
    @param run_rows Rows from run_summary.json.
    @param chart_path Path to recall_vs_distance.png when present.
    """

    available: bool
    summary_markdown: str
    probe_rows: list[list[object]]
    bucket_headers: list[str]
    bucket_rows: list[list[object]]
    run_rows: list[list[object]]
    chart_path: str
    max_probe_tokens: int
    far_hits: tuple[int, int]
    chunk_far: tuple[int, int]


class BaselinePanelData(TypedDict):
    """
    @brief Data bundle for benchmark baseline comparison rendering.
    @param available True when baseline artifacts are present and parseable.
    @param takeaway_markdown One-line takeaway shown at top of section.
    @param notes_markdown Honest caveats and interpretation notes.
    @param headers Baseline comparison table headers.
    @param rows Baseline comparison rows.
    """

    available: bool
    takeaway_markdown: str
    notes_markdown: str
    headers: list[str]
    rows: list[list[object]]


# Private function prototypes:
# - _load_live_index() -> LiveIndex
# - _load_repro_results() -> tuple[dict[str, dict[str, object]], dict[str, object]]
# - _load_recall_panel_data() -> RecallPanelData
# - _load_baseline_panel_data() -> BaselinePanelData
# - _attach_repro_records(findings: list[dict[str, object]], repros_map: dict[str, dict[str, object]]) -> list[dict[str, object]]
# - _finding_case_id(finding: dict[str, object]) -> str
# - _render_hero_html(summary: dict[str, object]) -> str
# - _render_bug_wall_html(findings: list[dict[str, object]]) -> str
# - _build_findings_rows(findings: list[dict[str, object]]) -> list[list[object]]
# - _build_finding_choice_map(findings: list[dict[str, object]]) -> dict[str, dict[str, object]]
# - _build_atlas_rows(runs: list[dict[str, object]], findings: list[dict[str, object]]) -> list[list[object]]
# - _build_benchmark_rows(runs: list[dict[str, object]]) -> list[list[object]]
# - _build_replay_rows(findings: list[dict[str, object]], runs: list[dict[str, object]]) -> list[list[object]]
# - _build_example_repo_rows() -> list[list[str]]
# - _default_finding_label(choice_map: dict[str, dict[str, object]]) -> str
# - _filter_findings(findings: list[dict[str, object]], verdict_filter: str) -> list[dict[str, object]]
# - _render_finding_panel(finding: dict[str, object]) -> FindingPanelState
# - _build_summary_markdown(summary: dict[str, object]) -> str
# - _build_repro_summary_markdown(repro_summary: dict[str, object]) -> str
# - _copy_issue_draft(text: str) -> str
# - _estimate_live_tokens(repo_url: str, ref: str, token_limit: int) -> tuple[str, str]
# - _run_live_analysis_stream(repo_url: str, ref: str, token_limit: int, request: gr.Request | None = None) -> object
# - _request_ip(request: gr.Request | None) -> str
# - _record_rate_limited_request(ip_address: str, now_epoch: float | None = None) -> tuple[bool, str]
# - _reserve_daily_live_slot(now_utc: datetime | None = None) -> tuple[bool, str]
# - _read_daily_counter() -> dict[str, object]
# - _write_daily_counter(counter_payload: dict[str, object]) -> None
# - _build_live_rows_from_bundle(bundle: object) -> list[list[object]]
# - _is_public_github_url(repo_url: str) -> bool
# - _badge_for_verifier(verifier_label: str) -> str
# - _badge_for_hand_verdict(verdict: str) -> str
# - _badge_for_repro(finding: dict[str, object]) -> str
# - _coerce_int(value: object, fallback: int = 0) -> int
# - _coerce_float(value: object, fallback: float = 0.0) -> float
# - _as_dict(value: object) -> dict[str, object]
# - _as_dict_list(value: object) -> list[dict[str, object]]
# - _reset_live_state_for_tests() -> None


def build_app() -> gr.Blocks:
    """
    @brief Construct the RepoAtlas-1M Hugging Face Space interface.
    """

    live_index: LiveIndex = _load_live_index()
    repros_map, repro_summary = _load_repro_results()
    recall_panel_data: RecallPanelData = _load_recall_panel_data()
    baseline_panel_data: BaselinePanelData = _load_baseline_panel_data()
    hybrid_payload = load_hybrid_payload()
    hybrid_stats = compute_hero_stats(hybrid_payload) if hybrid_payload["available"] else None
    findings: list[dict[str, object]] = [
        _rewrite_finding_display_fields(finding)
        for finding in _attach_repro_records(live_index["findings"], repros_map=repros_map)
    ]
    runs: list[dict[str, object]] = [
        {**run, "repo_url": canonicalize_repo_url(str(run.get("repo_url", "")), str(run.get("case_name", "")).split("-")[0])}
        for run in live_index["runs"]
    ]
    summary: dict[str, object] = live_index["summary"]
    hero_html: str = (
        render_hybrid_hero_html(hybrid_stats) if hybrid_stats is not None else _render_hero_html(summary)
    )
    hybrid_true_findings: list[dict[str, object]] = (
        merge_hybrid_true_findings(findings, hybrid_payload) if hybrid_payload["available"] else _filter_findings(findings, "true")
    )
    bug_wall_html: str = _render_bug_wall_html(hybrid_true_findings)
    live_enabled, live_status_message = get_live_mode_status()
    live_mode_summary: str = (
        f"🟢 **Live mode enabled** — {live_status_message} Live scans are capped at 150k tokens, so they cover smaller libraries only."
        if live_enabled
        else (
            "🟡 **Replay** of a recorded starlette run (about 395k tokens). "
            "Live scans are off on this Space (no API key set) and are capped at 150k tokens when on, "
            "so they cover smaller libraries only."
        )
    )

    v2_explorer_findings: list[dict[str, object]] = hybrid_true_findings
    v2_keys: set[str] = {str(item.get("finding_key", "")) for item in v2_explorer_findings}
    v1_only_findings: list[dict[str, object]] = [
        item for item in findings if str(item.get("finding_key", "")) not in v2_keys
    ]
    all_choice_map: dict[str, dict[str, object]] = _build_finding_choice_map(v2_explorer_findings)
    default_finding_label: str = _default_finding_label(all_choice_map)
    default_finding_panel: FindingPanelState = _render_finding_panel(all_choice_map[default_finding_label])
    starlette_finding: dict[str, object] = next(
        (finding for finding in findings if str(finding.get("finding_key", "")) == "starlette-400000/DD-1"),
        {},
    )
    starlette_status: str = str(starlette_finding.get("upstream_status", "status unavailable"))
    starlette_status_url: str = str(starlette_finding.get("upstream_url", "")).strip()
    if starlette_status_url:
        starlette_status_markdown: str = f"[{starlette_status}]({starlette_status_url})"
    else:
        starlette_status_markdown = starlette_status
    finding_map_state = gr.State(value=all_choice_map)
    finding_issue_draft_state = gr.State(value=default_finding_panel["issue_draft_text"])

    benchmark_headers: list[str] = [
        "Case",
        "Repo",
        "Prompt tokens",
        "Completion tokens",
        "Latency (s)",
        "Findings",
        "Verifier pass",
        "Hand true",
        "Hand false",
        "Hand unclear",
        "Hand precision",
        "Pack trim detail",
    ]
    atlas_rows: list[list[object]] = _build_atlas_rows(runs, findings)
    benchmark_rows: list[list[object]] = _build_benchmark_rows(runs)
    starlette_pack_tokens: int = 0
    for run in runs:
        if str(run.get("case_name", "")) == "starlette-400000":
            starlette_pack_tokens = _coerce_int(run.get("input_tokens"), 0)
            break
    replay_rows: list[list[object]] = _build_replay_rows(findings=findings, runs=runs)
    if hybrid_stats is not None:
        replay_rows = build_v2_replay_rows(hybrid_payload, hybrid_stats, starlette_pack_tokens) + replay_rows
    benchmark_plot_rows: pd.DataFrame = pd.DataFrame(
        [
            {
                "library_budget": str(run.get("case_name", "")),
                "input_tokens": _coerce_int(run.get("input_tokens"), 0),
                "output_tokens": _coerce_int(run.get("output_tokens"), 0),
                "latency_seconds": _coerce_float(run.get("latency_seconds"), 0.0),
            }
            for run in runs
        ]
    )
    has_baselines: bool = baseline_panel_data["available"]
    example_repo_rows: list[list[str]] = _build_example_repo_rows()
    example_flask_button: gr.Button | None = None
    example_fastapi_button: gr.Button | None = None
    example_starlette_button: gr.Button | None = None

    with gr.Blocks(title="DocDrift") as demo:
        hybrid_headline: str = (
            headline_sentence(hybrid_stats)
            if hybrid_stats is not None
            else "Recorded DocDrift results from whole-repo Beam runs."
        )
        gr.HTML(hero_html)
        gr.Markdown(
            "# DocDrift\n"
            "Repo name: RepoAtlas-1M.\n\n"
            f"**{hybrid_headline}.**\n\n"
            "**What is docs drift?** Docs say one thing, but the code does another.\n\n"
            "**Worked example (starlette):** docs line `receive_json(data, mode=\"binary\")`; code signature "
            "`receive_json(self, mode: str = \"text\")`; following the docs can raise `TypeError`.\n\n"
            "Starlette status: **"
            f"{starlette_status_markdown}** on "
            "[github.com/Kludex/starlette](https://github.com/Kludex/starlette)."
        )
        if hybrid_stats is not None:
            gr.Markdown(
                build_beam_did_markdown(
                    hybrid_stats,
                    recall_panel_data["max_probe_tokens"],
                    recall_panel_data["far_hits"],
                    recall_panel_data["chunk_far"],
                )
            )
            gr.Markdown(
                build_long_context_markdown(
                    hybrid_stats,
                    recall_panel_data["max_probe_tokens"],
                    recall_panel_data["far_hits"],
                    recall_panel_data["chunk_far"],
                )
            )
        with gr.Accordion("v1 recorded runs (earlier method)", open=False):
            gr.Markdown(_build_summary_markdown(summary))

        with gr.Tab("Recorded runs"):
            gr.Markdown("### DocDrift v2 pipeline")
            gr.HTML(render_pipeline_html())
            gr.Markdown("### Bug wall (true drifts, hybrid + earlier recorded runs)")
            gr.HTML(bug_wall_html)
            with gr.Accordion("Full run table", open=False):
                gr.Dataframe(
                    headers=benchmark_headers,
                    value=benchmark_rows,
                    interactive=False,
                    wrap=True,
                    label="All recorded runs",
                )

        with gr.Tab("Findings"):
            gr.Markdown(
                "### v2 34-bug wall\n"
                "Citation-check chips mean quote alignment of cited lines vs packed source "
                "(±3-line shift allowed). They are not a verdict that the drift is real. "
                f"The source-checked verdict was {LABEL_SOURCE}. "
                f"{non_bug_badge_phrase(hybrid_stats) if hybrid_stats is not None else '2 false + 1 unclear'} "
                "received a strict repro badge; "
                "the earlier “10 of 11 reproduce; 0 of 10 false do” line does not apply here.\n\n"
                "**Glossary:** *Triage* = Beam judges candidates against one packed library. "
                "*Strict badge* = TypeError / AttributeError / ImportError / NameError on a DOC-LITERAL line. "
                "*Line-shifted match* = the quote matched within ±3 lines of the cited line."
            )
            verdict_filter = gr.Dropdown(
                choices=["all", "true", "false", "unclear"],
                value="all",
                label="Filter by source-checked verdict",
                interactive=True,
            )
            selected_finding = gr.Dropdown(
                choices=sorted(all_choice_map.keys()),
                value=default_finding_label,
                label="Select finding",
                interactive=True,
            )
            with gr.Row():
                verifier_badge = gr.Markdown(value=default_finding_panel["verifier_badge"])
                hand_badge = gr.Markdown(value=default_finding_panel["hand_badge"])
                upstream_badge = gr.Markdown(value=default_finding_panel["upstream_badge"])
                repro_badge = gr.Markdown(value=default_finding_panel["repro_badge"])
            finding_notes = gr.Markdown(value=default_finding_panel["notes"])
            finding_links = gr.Markdown(value=default_finding_panel["links"])
            with gr.Row():
                with gr.Column():
                    doc_header = gr.Markdown(value=default_finding_panel["doc_header"])
                    doc_quote = gr.Textbox(value=default_finding_panel["doc_quote"], lines=12, label="Documentation snippet")
                with gr.Column():
                    code_header = gr.Markdown(value=default_finding_panel["code_header"])
                    code_quote = gr.Textbox(value=default_finding_panel["code_quote"], lines=12, label="Code snippet")
            with gr.Row():
                copy_issue_button = gr.Button("Copy issue text")
                copy_issue_status = gr.Markdown(value="")
            findings_table = gr.Dataframe(
                headers=[
                    "Finding key",
                    "Repo",
                    "Drift kind",
                    "Verifier",
                    "Source-checked verdict",
                    "Upstream status",
                    "Executable repro",
                    "Cross-file",
                    "Token distance",
                ],
                value=_build_findings_rows(v2_explorer_findings),
                interactive=False,
                wrap=True,
            )
            with gr.Accordion("Earlier v1 recorded findings", open=False):
                gr.Markdown("Folded away. These are the earlier whole-repo-only sweep cards, not the v2 34-bug wall.")
                gr.Dataframe(
                    headers=[
                        "Finding key",
                        "Repo",
                        "Drift kind",
                        "Verifier",
                        "Source-checked verdict",
                        "Upstream status",
                        "Executable repro",
                        "Cross-file",
                        "Token distance",
                    ],
                    value=_build_findings_rows(v1_only_findings),
                    interactive=False,
                    wrap=True,
                )

        with gr.Tab("Benchmark"):
            if hybrid_payload["available"]:
                hybrid_headers, hybrid_rows = build_comparison_table(hybrid_payload)
                gr.Markdown("### DocDrift v2 comparison")
                gr.Markdown(headline_sentence(hybrid_stats) + "." if hybrid_stats is not None else "")
                gr.Dataframe(
                    headers=hybrid_headers,
                    value=hybrid_rows,
                    interactive=False,
                    wrap=True,
                )
                gr.Markdown(build_notes_markdown(hybrid_payload))
            if recall_panel_data["available"]:
                gr.Markdown("### Planted-drift recall")
                gr.Markdown(
                    f"Beam accepted prompts up to **{recall_panel_data['max_probe_tokens']:,}** tokens "
                    "with no silent truncation (`results_live/recall/recall.md`)."
                )
                gr.Markdown(recall_panel_data["summary_markdown"])
                if recall_panel_data["chart_path"]:
                    gr.Image(
                        value=recall_panel_data["chart_path"],
                        label="Planted-drift strict recall by distance bucket",
                        interactive=False,
                        buttons=["fullscreen"],
                    )
                if recall_panel_data["probe_rows"]:
                    with gr.Accordion("Context probe table (Beam prompt-size acceptance)", open=False):
                        gr.Dataframe(
                            headers=["Target prompt tokens", "Observed prompt tokens", "HTTP", "Latency (s)"],
                            value=recall_panel_data["probe_rows"],
                            interactive=False,
                            wrap=True,
                        )
                with gr.Accordion("Bucket recall table (strict and loose)", open=False):
                    gr.Dataframe(
                        headers=recall_panel_data["bucket_headers"],
                        value=recall_panel_data["bucket_rows"],
                        interactive=False,
                        wrap=True,
                    )
                with gr.Accordion("Run-level token and finding summary", open=False):
                    gr.Dataframe(
                        headers=[
                            "Run",
                            "Calls",
                            "Tokens used",
                            "Findings",
                            "Verifier pass",
                            "Matched plants",
                            "Unplanted findings",
                        ],
                        value=recall_panel_data["run_rows"],
                        interactive=False,
                        wrap=True,
                    )
            else:
                gr.Markdown("### Planted-drift recall\nRecall artifacts are not available in this checkout.")
            if has_baselines:
                gr.Markdown("### Baselines")
                gr.Markdown("**Takeaway:** " + baseline_panel_data["takeaway_markdown"])
                gr.Dataframe(
                    headers=baseline_panel_data["headers"],
                    value=baseline_panel_data["rows"],
                    interactive=False,
                    wrap=True,
                )
                gr.Markdown(baseline_panel_data["notes_markdown"])
            gr.Markdown("### Earlier v1 whole-repo runs")
            gr.BarPlot(
                value=benchmark_plot_rows,
                x="library_budget",
                y="input_tokens",
                title="Earlier v1 whole-repo runs: prompt size",
                x_title="Library (token budget)",
                y_title="Prompt tokens",
                y_lim=[0, None],
                x_label_angle=35,
            )
            gr.BarPlot(
                value=benchmark_plot_rows,
                x="library_budget",
                y="output_tokens",
                title="Earlier v1 whole-repo runs: completion size",
                x_title="Library (token budget)",
                y_title="Completion tokens",
                y_lim=[0, None],
                x_label_angle=35,
            )
            gr.LinePlot(
                value=benchmark_plot_rows,
                x="library_budget",
                y="latency_seconds",
                title="Earlier v1 whole-repo runs: latency",
                x_title="Library (token budget)",
                y_title="Latency (seconds)",
                y_lim=[0, None],
                x_label_angle=35,
            )
            with gr.Accordion("Atlas (all 17 recorded v1 runs)", open=False):
                if atlas_rows:
                    gr.Dataframe(
                        headers=[
                            "Case",
                            "Repo",
                            "Atlas claims",
                            "Atlas citations",
                            "Atlas citations verified",
                            "Verifier finding passes",
                            "Model findings",
                        ],
                        value=atlas_rows,
                        interactive=False,
                        wrap=True,
                    )
                else:
                    gr.Markdown("Atlas rows are unavailable for this run set.")
                gr.Dataframe(
                    headers=benchmark_headers,
                    value=benchmark_rows,
                    interactive=False,
                    wrap=True,
                )

        with gr.Tab("Try it live"):
            gr.Markdown(
                f"{live_mode_summary}\n\n"
                "Guardrails: one job at a time, 150k live token cap, per-IP rate limit (2/hour), "
                "and a global daily cap via environment."
            )
            gr.Markdown(
                "#### Recorded replay: starlette (~395k prompt tokens)\n"
                "v2 steps from the later hybrid run, plus the earlier recorded pack size. "
                "A 150k live scan cannot reproduce this 395k pack."
            )
            gr.Dataframe(
                headers=["Step", "Details"],
                value=replay_rows,
                interactive=False,
                wrap=True,
            )
            if live_enabled:
                gr.Markdown("### One-click example repositories")
                gr.Dataframe(
                    headers=["Repo URL", "Ref"],
                    value=example_repo_rows,
                    interactive=False,
                    wrap=True,
                )
                with gr.Row():
                    example_flask_button = gr.Button("Use pallets/flask")
                    example_fastapi_button = gr.Button("Use fastapi/fastapi")
                    example_starlette_button = gr.Button("Use Kludex/starlette")
            live_repo_url = gr.Textbox(label="Public GitHub repository URL", placeholder="https://github.com/pallets/flask")
            live_ref = gr.Textbox(label="Branch, tag or commit", value="main")
            live_token_limit = gr.Slider(
                minimum=40_000,
                maximum=LIVE_MAX_TOKEN_LIMIT,
                step=10_000,
                value=LIVE_DEFAULT_TOKEN_LIMIT,
                label="How much of the repo to read (tokens)",
            )
            with gr.Row():
                estimate_button = gr.Button("Dry-run token estimate", interactive=live_enabled)
                run_button = gr.Button(
                    "Scan a repo" if live_enabled else "Scan a repo (needs API key)",
                    interactive=live_enabled,
                )
            live_estimate = gr.Markdown(value="Estimate not run yet." if live_enabled else "Live estimate needs an API key.")
            live_status = gr.Markdown(value="No live run started.")
            live_findings = gr.Dataframe(
                headers=["Finding ID", "Drift kind", "Verifier", "Doc citation", "Code citation", "Explanation"],
                value=[],
                interactive=False,
                wrap=True,
                visible=False,
            )
            hidden_progress_log = gr.Textbox(visible=False, label="Hidden live progress log", value="")

        def on_finding_change(
            finding_choice: str,
            choice_map: dict[str, dict[str, object]],
        ) -> tuple[str, str, str, str, str, str, str, str, str, str, str]:
            """
            @brief Update finding detail panels when user selects a finding.
            @param finding_choice Selected finding label.
            @param choice_map Current choice-to-finding map.
            """

            finding: dict[str, object] | None = choice_map.get(finding_choice)
            if finding is None and choice_map:
                fallback_label: str = sorted(choice_map.keys())[0]
                finding = choice_map[fallback_label]
            if finding is None:
                empty: FindingPanelState = FindingPanelState(
                    verifier_badge="",
                    hand_badge="",
                    upstream_badge="",
                    repro_badge="",
                    doc_header="No finding selected.",
                    code_header="No finding selected.",
                    doc_quote="",
                    code_quote="",
                    notes="",
                    links="",
                    issue_draft_text="",
                )
                return (
                    empty["verifier_badge"],
                    empty["hand_badge"],
                    empty["upstream_badge"],
                    empty["repro_badge"],
                    empty["notes"],
                    empty["links"],
                    empty["doc_header"],
                    empty["code_header"],
                    empty["doc_quote"],
                    empty["code_quote"],
                    empty["issue_draft_text"],
                )
            panel: FindingPanelState = _render_finding_panel(finding)
            return (
                panel["verifier_badge"],
                panel["hand_badge"],
                panel["upstream_badge"],
                panel["repro_badge"],
                panel["notes"],
                panel["links"],
                panel["doc_header"],
                panel["code_header"],
                panel["doc_quote"],
                panel["code_quote"],
                panel["issue_draft_text"],
            )

        def on_verdict_filter_change(
            verdict: str,
        ) -> tuple[
            object,
            list[list[object]],
            dict[str, dict[str, object]],
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
        ]:
            """
            @brief Filter finding choices and table rows by hand verdict.
            @param verdict Verdict filter value.
            """

            filtered: list[dict[str, object]] = _filter_findings(v2_explorer_findings, verdict)
            filtered_choice_map: dict[str, dict[str, object]] = _build_finding_choice_map(filtered)
            if not filtered_choice_map:
                return (
                    gr.update(choices=[], value=None),
                    [],
                    filtered_choice_map,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "No finding selected.",
                    "No finding selected.",
                    "",
                    "",
                    "",
                )
            if verdict == "all":
                selected_label: str = _default_finding_label(filtered_choice_map)
            else:
                selected_label = sorted(filtered_choice_map.keys())[0]
            selected_finding_item: dict[str, object] = filtered_choice_map[selected_label]
            panel: FindingPanelState = _render_finding_panel(selected_finding_item)
            return (
                gr.update(choices=sorted(filtered_choice_map.keys()), value=selected_label),
                _build_findings_rows(filtered),
                filtered_choice_map,
                panel["verifier_badge"],
                panel["hand_badge"],
                panel["upstream_badge"],
                panel["repro_badge"],
                panel["notes"],
                panel["links"],
                panel["doc_header"],
                panel["code_header"],
                panel["doc_quote"],
                panel["code_quote"],
                panel["issue_draft_text"],
            )

        verdict_filter.change(
            fn=on_verdict_filter_change,
            inputs=[verdict_filter],
            outputs=[
                selected_finding,
                findings_table,
                finding_map_state,
                verifier_badge,
                hand_badge,
                upstream_badge,
                repro_badge,
                finding_notes,
                finding_links,
                doc_header,
                code_header,
                doc_quote,
                code_quote,
                finding_issue_draft_state,
            ],
        )

        selected_finding.change(
            fn=on_finding_change,
            inputs=[selected_finding, finding_map_state],
            outputs=[
                verifier_badge,
                hand_badge,
                upstream_badge,
                repro_badge,
                finding_notes,
                finding_links,
                doc_header,
                code_header,
                doc_quote,
                code_quote,
                finding_issue_draft_state,
            ],
        )

        copy_issue_button.click(
            fn=_copy_issue_draft,
            inputs=[finding_issue_draft_state],
            outputs=[copy_issue_status],
        )

        estimate_button.click(
            fn=_estimate_live_tokens,
            inputs=[live_repo_url, live_ref, live_token_limit],
            outputs=[live_estimate, hidden_progress_log],
        )
        run_button.click(
            fn=_run_live_analysis_stream,
            inputs=[live_repo_url, live_ref, live_token_limit],
            outputs=[live_status, live_findings, live_estimate, hidden_progress_log],
        )
        if live_enabled and example_flask_button and example_fastapi_button and example_starlette_button:
            example_flask_button.click(
                fn=lambda: ("https://github.com/pallets/flask", "main"),
                inputs=[],
                outputs=[live_repo_url, live_ref],
            )
            example_fastapi_button.click(
                fn=lambda: ("https://github.com/fastapi/fastapi", "master"),
                inputs=[],
                outputs=[live_repo_url, live_ref],
            )
            example_starlette_button.click(
                fn=lambda: ("https://github.com/Kludex/starlette", "master"),
                inputs=[],
                outputs=[live_repo_url, live_ref],
            )

    return demo


def launch_app(server_port: int = 43123) -> None:
    """
    @brief Launch the Gradio application with queue enabled.
    @param server_port Port to bind for local preview.
    """

    demo: gr.Blocks = build_app()
    demo.queue(default_concurrency_limit=1)
    demo.launch(server_name="0.0.0.0", server_port=server_port, theme=THEME, css=CUSTOM_CSS)


def get_live_mode_status(provider: str | None = None, environment: Mapping[str, str] | None = None) -> tuple[bool, str]:
    """
    @brief Resolve whether live mode is enabled from environment configuration.
    @param provider Optional provider override.
    @param environment Optional environment mapping for testability.
    """

    env_map: Mapping[str, str] = environment or os.environ
    selected_provider: str = (provider or env_map.get("BEAM_PROVIDER", "ollama")).strip().lower()
    if selected_provider == "ollama":
        if not env_map.get("OLLAMA_API_KEY", "").strip():
            return False, "live mode disabled, browse recorded runs (missing OLLAMA_API_KEY)."
        return True, "provider=ollama model=beam via https://ollama.com/v1."
    if selected_provider == "reflection":
        if not env_map.get("REFLECTION_API_KEY", "").strip():
            return False, "live mode disabled, browse recorded runs (missing REFLECTION_API_KEY)."
        return True, "provider=reflection using configured Reflection endpoint."
    return False, f"live mode disabled, browse recorded runs (unsupported BEAM_PROVIDER={selected_provider})."


def _load_live_index() -> LiveIndex:
    """
    @brief Load compact recorded-run index generated from results_live traces.
    """

    if not RESULTS_LIVE_INDEX_PATH.exists():
        raise FileNotFoundError(
            "results_live/index.json not found. Run `python3 scripts/build_results_live_index.py` first."
        )
    payload: dict[str, object] = json.loads(RESULTS_LIVE_INDEX_PATH.read_text(encoding="utf-8"))
    return LiveIndex(
        summary=_as_dict(payload.get("summary")),
        runs=_as_dict_list(payload.get("runs")),
        findings=_as_dict_list(payload.get("findings")),
        handcheck_markdown_path=str(payload.get("handcheck_markdown_path", "")),
        upstream_status_path=str(payload.get("upstream_status_path", "")),
    )


def _load_repro_results() -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    """
    @brief Load optional repro records and aggregate summary.
    @return Tuple of (repros map, repro summary map).
    """

    repros_map: dict[str, dict[str, object]] = {}
    repro_summary: dict[str, object] = {}
    if RESULTS_LIVE_REPROS_INDEX_PATH.exists():
        payload: object = json.loads(RESULTS_LIVE_REPROS_INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            repros_map = {str(key): value for key, value in payload.items() if isinstance(value, dict)}
    if RESULTS_LIVE_REPROS_SUMMARY_PATH.exists():
        payload = json.loads(RESULTS_LIVE_REPROS_SUMMARY_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            summary_payload: object = payload.get("summary", payload)
            if isinstance(summary_payload, dict):
                repro_summary = summary_payload
    return repros_map, repro_summary


def _load_recall_panel_data() -> RecallPanelData:
    """
    @brief Load planted-drift recall artifacts for benchmark rendering.
    """

    required_paths: list[Path] = [
        RESULTS_LIVE_RECALL_RUN_SUMMARY_PATH,
        RESULTS_LIVE_RECALL_BUCKETS_PATH,
        RESULTS_LIVE_RECALL_CONTEXT_PROBE_PATH,
    ]
    if not all(path.exists() for path in required_paths):
        return RecallPanelData(
            available=False,
            summary_markdown="",
            probe_rows=[],
            bucket_headers=[],
            bucket_rows=[],
            run_rows=[],
            chart_path="",
            max_probe_tokens=0,
            far_hits=(0, 0),
            chunk_far=(0, 0),
        )

    run_summary_payload: object = json.loads(RESULTS_LIVE_RECALL_RUN_SUMMARY_PATH.read_text(encoding="utf-8"))
    context_probe_payload: object = json.loads(RESULTS_LIVE_RECALL_CONTEXT_PROBE_PATH.read_text(encoding="utf-8"))
    usage_ledger_payload: object = {}
    if RESULTS_LIVE_RECALL_USAGE_LEDGER_PATH.exists():
        usage_ledger_payload = json.loads(RESULTS_LIVE_RECALL_USAGE_LEDGER_PATH.read_text(encoding="utf-8"))

    with RESULTS_LIVE_RECALL_BUCKETS_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        bucket_headers: list[str] = list(reader.fieldnames or [])
        bucket_records: list[dict[str, str]] = [dict(record) for record in reader]

    run_summary_rows: list[dict[str, object]] = [row for row in run_summary_payload if isinstance(row, dict)] if isinstance(run_summary_payload, list) else []
    context_probe_rows: list[dict[str, object]] = [row for row in context_probe_payload if isinstance(row, dict)] if isinstance(context_probe_payload, list) else []
    usage_calls: list[dict[str, object]] = []
    if isinstance(usage_ledger_payload, dict):
        raw_calls: object = usage_ledger_payload.get("calls", [])
        if isinstance(raw_calls, list):
            usage_calls = [entry for entry in raw_calls if isinstance(entry, dict)]

    bucket_by_run: dict[str, dict[str, str]] = {
        str(row.get("run", "")).strip(): row for row in bucket_records if str(row.get("run", "")).strip()
    }
    run_by_name: dict[str, dict[str, object]] = {
        str(row.get("run", "")).strip(): row for row in run_summary_rows if str(row.get("run", "")).strip()
    }

    focused_later_cached_tokens: list[int] = []
    for call in usage_calls:
        label: str = str(call.get("label", ""))
        if not label.startswith("focused-seed1-u"):
            continue
        if label.endswith("-u0"):
            continue
        usage: dict[str, object] = _as_dict(call.get("usage"))
        prompt_details: dict[str, object] = _as_dict(usage.get("prompt_tokens_details"))
        cached_tokens: int = _coerce_int(prompt_details.get("cached_tokens"), 0)
        if cached_tokens > 0:
            focused_later_cached_tokens.append(cached_tokens)
    cached_tokens_average: int = (
        int(sum(focused_later_cached_tokens) / len(focused_later_cached_tokens))
        if focused_later_cached_tokens
        else 0
    )

    probe_rows: list[list[object]] = []
    max_probe_prompt_tokens: int = 0
    for row in context_probe_rows:
        usage: dict[str, object] = _as_dict(row.get("usage"))
        prompt_tokens: int = _coerce_int(usage.get("prompt_tokens"), 0)
        max_probe_prompt_tokens = max(max_probe_prompt_tokens, prompt_tokens)
        target_tokens: int = _coerce_int(row.get("target_real_tokens"), 0)
        probe_rows.append(
            [
                f"{target_tokens:,}",
                f"{prompt_tokens:,}",
                _coerce_int(row.get("status"), 0),
                f"{_coerce_float(row.get('latency_s'), 0.0):.1f}",
            ]
        )

    whole_seed1_strict = _parse_fraction(str(bucket_by_run.get("whole_seed1", {}).get("all strict", "")))
    whole_seed2_strict = _parse_fraction(str(bucket_by_run.get("whole_seed2", {}).get("all strict", "")))
    chunk128_seed1_strict = _parse_fraction(str(bucket_by_run.get("chunk128k_seed1", {}).get("all strict", "")))
    chunk32_seed1_strict = _parse_fraction(str(bucket_by_run.get("chunk32k_seed1", {}).get("all strict", "")))
    focused_seed1_strict = _parse_fraction(str(bucket_by_run.get("focused_seed1", {}).get("all strict", "")))
    focusdocs_seed2_strict = _parse_fraction(str(bucket_by_run.get("focusdocs_seed2", {}).get("all strict", "")))
    focused_seed1_far = _parse_fraction(str(bucket_by_run.get("focused_seed1", {}).get("700k+ strict", "")))
    chunk128_seed1_far = _parse_fraction(str(bucket_by_run.get("chunk128k_seed1", {}).get("700k+ strict", "")))
    chunk32_seed1_far = _parse_fraction(str(bucket_by_run.get("chunk32k_seed1", {}).get("700k+ strict", "")))

    focused_usage: int = _coerce_int(run_by_name.get("focused_seed1", {}).get("usage"), 0)
    chunk_token_baseline_values: list[int] = [
        _coerce_int(run_by_name.get("chunk128k_seed1", {}).get("usage"), 0),
        _coerce_int(run_by_name.get("chunk32k_seed1", {}).get("usage"), 0),
    ]
    chunk_token_baseline_values = [value for value in chunk_token_baseline_values if value > 0]
    chunk_token_baseline: float = float(sum(chunk_token_baseline_values) / len(chunk_token_baseline_values)) if chunk_token_baseline_values else 0.0
    focused_cost_multiplier: float = (focused_usage / chunk_token_baseline) if chunk_token_baseline > 0 else 0.0

    docstring_ratio: tuple[int, int] | None = None
    if RESULTS_LIVE_RECALL_NOTE_PATH.exists():
        docstring_ratio = _extract_docstring_single_call_docstring_ratio(
            RESULTS_LIVE_RECALL_NOTE_PATH.read_text(encoding="utf-8")
        )
    docstring_ratio_text: str = (
        f"{docstring_ratio[0]}/{docstring_ratio[1]}" if docstring_ratio else "0–1/32 (see recall.md)"
    )

    summary_markdown: str = (
        f"- **Probe:** Beam accepted prompts up to **~{max_probe_prompt_tokens:,}** prompt tokens (see context probe table below).\n"
        f"- **700k+ separation bucket:** focused whole-context passes caught **{focused_seed1_far[0]}/{focused_seed1_far[1]}** "
        f"(seed 1), while chunked 128k and 32k runs caught **{chunk128_seed1_far[0]}/{chunk128_seed1_far[1]}** and "
        f"**{chunk32_seed1_far[0]}/{chunk32_seed1_far[1]}**.\n"
        f"- **Overall:** a single whole-prompt call is not better than chunking on seed 1 "
        f"(**{whole_seed1_strict[0]}/{whole_seed1_strict[1]}** vs **{chunk128_seed1_strict[0]}/{chunk128_seed1_strict[1]}** "
        f"for chunk128k and **{chunk32_seed1_strict[0]}/{chunk32_seed1_strict[1]}** for chunk32k).\n"
        f"- **Focused variant:** **{focused_seed1_strict[0]}/{focused_seed1_strict[1]}** strict hits on seed 1 at "
        f"about **{focused_cost_multiplier:.1f}×** token cost versus ~1M-token chunked baselines "
        f"(focused={focused_usage:,}; chunked mean≈{int(chunk_token_baseline):,}). "
        f"Later focused passes still reported about **{cached_tokens_average:,} cached prompt tokens** each.\n"
        f"- **Seed-2 signal:** docs-focused pass reached **{focusdocs_seed2_strict[0]}/{focusdocs_seed2_strict[1]}** "
        f"vs **{whole_seed2_strict[0]}/{whole_seed2_strict[1]}** for whole seed 2 (partial hold).\n"
        f"- **Docstring caveat:** single-call whole-context variants mostly miss Python docstring drifts "
        f"(best observed **{docstring_pooled_text()}**).\n"
        "- **Caveats:** one run per configuration, only 4-6 plants per distance bucket, and small samples.\n"
        "- **Practical recipe:** use whole-repo context for a docs-focused audit (to catch long-range drift chunking "
        "cannot see), plus cheap chunked passes for docstrings."
    )

    bucket_rows: list[list[object]] = [[record.get(header, "") for header in bucket_headers] for record in bucket_records]
    run_rows: list[list[object]] = [
        [
            row.get("run", ""),
            row.get("units", ""),
            f"{_coerce_int(row.get('usage'), 0):,}",
            row.get("findings", ""),
            row.get("fully_verified", ""),
            row.get("matched_findings", ""),
            row.get("unplanted", ""),
        ]
        for row in run_summary_rows
    ]
    chart_path: str = str(RESULTS_LIVE_RECALL_CHART_PATH) if RESULTS_LIVE_RECALL_CHART_PATH.exists() else ""
    return RecallPanelData(
        available=True,
        summary_markdown=summary_markdown,
        probe_rows=probe_rows,
        bucket_headers=bucket_headers,
        bucket_rows=bucket_rows,
        run_rows=run_rows,
        chart_path=chart_path,
        max_probe_tokens=max_probe_prompt_tokens,
        far_hits=focused_seed1_far,
        chunk_far=chunk128_seed1_far if chunk128_seed1_far[1] else chunk32_seed1_far,
    )


def _load_baseline_panel_data() -> BaselinePanelData:
    """
    @brief Load baseline comparison data for benchmark rendering.
    """

    if not RESULTS_LIVE_BASELINES_CSV_PATH.exists() or not RESULTS_LIVE_BASELINES_JSON_PATH.exists():
        return BaselinePanelData(
            available=False,
            takeaway_markdown="",
            notes_markdown="",
            headers=[],
            rows=[],
        )

    with RESULTS_LIVE_BASELINES_CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        csv_reader = csv.DictReader(handle)
        csv_rows: list[dict[str, str]] = [dict(row) for row in csv_reader]

    baselines_json_payload: object = json.loads(RESULTS_LIVE_BASELINES_JSON_PATH.read_text(encoding="utf-8"))
    baseline_json_rows: list[dict[str, object]] = []
    if isinstance(baselines_json_payload, dict):
        raw_rows: object = baselines_json_payload.get("rows", [])
        if isinstance(raw_rows, list):
            baseline_json_rows = [row for row in raw_rows if isinstance(row, dict)]

    colocation_payload: object = {}
    if RESULTS_LIVE_BASELINES_COLOCATION_PATH.exists():
        colocation_payload = json.loads(RESULTS_LIVE_BASELINES_COLOCATION_PATH.read_text(encoding="utf-8"))
    colocation_map: dict[str, object] = colocation_payload if isinstance(colocation_payload, dict) else {}

    headers: list[str] = [
        "Method",
        "Calls",
        "Tokens",
        "Known true drifts recovered (of 11)",
        "Findings",
        "Precision",
    ]
    rendered_rows: list[list[object]] = []
    for row in csv_rows:
        method: str = str(row.get("method", "")).strip()
        calls: int = _coerce_int(row.get("calls"), 0)
        prompt_tokens: int = _coerce_int(row.get("prompt_tokens"), 0)
        completion_tokens: int = _coerce_int(row.get("completion_tokens"), 0)
        recovered_count: int = _coerce_int(row.get("true_recovered_of_11"), 0)
        findings_total: int = _coerce_int(row.get("total_findings"), 0)
        precision_value: float = _coerce_float(row.get("precision"), 0.0)
        precision_text: str = f"{precision_value * 100.0:.1f}%" if precision_value <= 1.0 else f"{precision_value:.1f}%"
        tokens_text: str = (
            "0 (rule-based)"
            if prompt_tokens == 0 and completion_tokens == 0
            else f"{prompt_tokens:,} prompt + {completion_tokens:,} completion"
        )
        rendered_rows.append(
            [
                method,
                calls,
                tokens_text,
                f"{recovered_count}/11",
                findings_total,
                precision_text,
            ]
        )

    whole_csv_row: dict[str, str] | None = _find_csv_baseline_row(csv_rows, "whole-repo beam")
    symbol_csv_row: dict[str, str] | None = _find_csv_baseline_row(csv_rows, "symbol check")
    chunk32_csv_row: dict[str, str] | None = _find_csv_baseline_row(csv_rows, "~32k")
    chunk128_csv_row: dict[str, str] | None = _find_csv_baseline_row(csv_rows, "~128k")
    whole_json_row: dict[str, object] | None = _find_json_baseline_row(baseline_json_rows, "whole-repo beam")
    symbol_json_row: dict[str, object] | None = _find_json_baseline_row(baseline_json_rows, "symbol check")
    chunk32_json_row: dict[str, object] | None = _find_json_baseline_row(baseline_json_rows, "~32k")
    chunk128_json_row: dict[str, object] | None = _find_json_baseline_row(baseline_json_rows, "~128k")

    whole_recovered: int = _coerce_int(whole_csv_row.get("true_recovered_of_11") if whole_csv_row else 0, 0)
    chunk32_recovered: int = _coerce_int(chunk32_csv_row.get("true_recovered_of_11") if chunk32_csv_row else 0, 0)
    chunk128_recovered: int = _coerce_int(chunk128_csv_row.get("true_recovered_of_11") if chunk128_csv_row else 0, 0)
    symbol_recovered: int = _coerce_int(symbol_csv_row.get("true_recovered_of_11") if symbol_csv_row else 0, 0)

    whole_prompt_tokens: int = _coerce_int(whole_csv_row.get("prompt_tokens") if whole_csv_row else 0, 0)
    chunk32_prompt_tokens: int = _coerce_int(chunk32_csv_row.get("prompt_tokens") if chunk32_csv_row else 0, 0)
    chunk128_prompt_tokens: int = _coerce_int(chunk128_csv_row.get("prompt_tokens") if chunk128_csv_row else 0, 0)

    symbol_findings_all: int = _coerce_int(symbol_json_row.get("total_findings") if symbol_json_row else 0, 0)
    symbol_findings_9: int = _coerce_int(symbol_json_row.get("total_findings_9repos") if symbol_json_row else 0, 0)
    whole_findings: int = _coerce_int(whole_csv_row.get("total_findings") if whole_csv_row else 0, 0)

    chunk32_same_chunk_hits: int = _count_chunk_colocated_recovered(
        method_suffix="32k",
        recovered_true_ids=_string_list(chunk32_json_row.get("true_recovered") if chunk32_json_row else []),
        colocation_map=colocation_map,
    )
    chunk128_same_chunk_hits: int = _count_chunk_colocated_recovered(
        method_suffix="128k",
        recovered_true_ids=_string_list(chunk128_json_row.get("true_recovered") if chunk128_json_row else []),
        colocation_map=colocation_map,
    )
    chunk32_same_chunk_denom: int = chunk32_recovered if chunk32_recovered > 0 else 0
    chunk128_same_chunk_denom: int = chunk128_recovered if chunk128_recovered > 0 else 0

    takeaway_markdown: str = (
        f"At similar prompt spend (~{whole_prompt_tokens / 1_000_000:.2f}M to {chunk32_prompt_tokens / 1_000_000:.2f}M), "
        f"whole-repo Beam recovered {whole_recovered}/11 known drifts vs {chunk32_recovered}/11 (32k chunks) and "
        f"{chunk128_recovered}/11 (128k chunks), while the no-AI symbol check recovered {symbol_recovered}/11 at zero token cost."
    )

    notes_markdown: str = (
        f"- The **11-of-11** whole-repo score is circular: the 11 known drifts were defined from that whole-repo sweep itself.\n"
        f"- Chunked baselines recovered **{chunk32_recovered}/11** (32k) and **{chunk128_recovered}/11** (128k) at similar prompt spend "
        f"({chunk32_prompt_tokens:,} and {chunk128_prompt_tokens:,} prompt tokens vs {whole_prompt_tokens:,} for whole-repo), "
        f"and mostly where doc and code co-located in one chunk "
        f"({chunk32_same_chunk_hits}/{chunk32_same_chunk_denom} at 32k; {chunk128_same_chunk_hits}/{chunk128_same_chunk_denom} at 128k).\n"
        f"- The no-AI symbol check recovered **{symbol_recovered}/11** and surfaced more drifts on the same 9 repos "
        f"({symbol_findings_9} findings vs {whole_findings} whole-repo findings; {symbol_findings_all} flags across all 12). "
        "Precision on all 43 flags is 25/43 = 58.1%. The 65% figure was a 20-item sample (seed 20261026). "
        "DocDrift's value is cross-file/prose drift handling plus triage, not raw detection count alone.\n"
        "- The table is data-driven from `results_live/baselines/baselines.csv`. Hybrid v2 rows live in the comparison table above."
    )

    return BaselinePanelData(
        available=True,
        takeaway_markdown=takeaway_markdown,
        notes_markdown=notes_markdown,
        headers=headers,
        rows=rendered_rows,
    )


def _find_csv_baseline_row(rows: list[dict[str, str]], method_substring: str) -> dict[str, str] | None:
    """
    @brief Find a baseline CSV row by case-insensitive method-name substring.
    @param rows Parsed baselines CSV rows.
    @param method_substring Substring to match in method name.
    """

    target: str = method_substring.strip().lower()
    for row in rows:
        method: str = str(row.get("method", "")).lower()
        if target in method:
            return row
    return None


def _find_json_baseline_row(rows: list[dict[str, object]], method_substring: str) -> dict[str, object] | None:
    """
    @brief Find a baseline JSON row by case-insensitive method-name substring.
    @param rows Parsed baselines JSON rows.
    @param method_substring Substring to match in method name.
    """

    target: str = method_substring.strip().lower()
    for row in rows:
        method: str = str(row.get("method", "")).lower()
        if target in method:
            return row
    return None


def _count_chunk_colocated_recovered(
    method_suffix: str,
    recovered_true_ids: list[str],
    colocation_map: dict[str, object],
) -> int:
    """
    @brief Count recovered known drifts that were in the same chunk for a chunk size.
    @param method_suffix Chunk label suffix (`32k` or `128k`).
    @param recovered_true_ids Known recovered true IDs.
    @param colocation_map Colocation payload map.
    """

    hits: int = 0
    for true_id in recovered_true_ids:
        key: str = f"{true_id}@{method_suffix}"
        payload: dict[str, object] = _as_dict(colocation_map.get(key))
        if bool(payload.get("same_chunk", False)):
            hits += 1
    return hits


def _string_list(value: object) -> list[str]:
    """
    @brief Coerce unknown list payload to list[str].
    @param value Candidate list object.
    """

    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float))]


def _parse_fraction(value: str) -> tuple[int, int]:
    """
    @brief Parse a fraction string like "5/30" into integer numerator/denominator.
    @param value Fraction text.
    """

    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", value)
    if not match:
        return (0, 0)
    return int(match.group(1)), int(match.group(2))


def _extract_docstring_single_call_docstring_ratio(recall_markdown: str) -> tuple[int, int] | None:
    """
    @brief Parse docs-last docstring hit ratio from recall.md ("0/18, 1/14" -> 1/32).
    @param recall_markdown Full recall markdown text.
    """

    match = re.search(
        r"\| A docs-last s1 / s2 \|[^|]*\|\s*(\d+)\s*/\s*(\d+)\s*,\s*(\d+)\s*/\s*(\d+)\s*\|",
        recall_markdown,
    )
    if not match:
        return None
    hits: int = int(match.group(1)) + int(match.group(3))
    total: int = int(match.group(2)) + int(match.group(4))
    if total <= 0:
        return None
    return hits, total


def _finding_case_id(finding: dict[str, object]) -> str:
    """
    @brief Build repro case id from finding metadata.
    @param finding Finding record.
    """

    finding_key: str = str(finding.get("finding_key", ""))
    if "/" in finding_key:
        return finding_key.replace("/", ":", 1)
    case_name: str = str(finding.get("case_name", "")).strip()
    finding_id: str = str(finding.get("finding_id", "")).strip()
    if case_name and finding_id:
        return f"{case_name}:{finding_id}"
    return ""


def _attach_repro_records(
    findings: list[dict[str, object]],
    repros_map: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """
    @brief Attach repro metadata to finding rows.
    @param findings Finding rows from index.json.
    @param repros_map Repro map keyed by case id.
    """

    enriched: list[dict[str, object]] = []
    for finding in findings:
        finding_copy: dict[str, object] = dict(finding)
        case_id: str = _finding_case_id(finding_copy)
        repro: dict[str, object] = repros_map.get(case_id, {})
        repro_status: str = str(repro.get("status", ""))
        repro_evidence: str = str(repro.get("evidence", ""))
        repro_exception_type: str = str(repro.get("exception_type", ""))
        is_strict_api_error_repro: bool = (
            repro_status == "reproduced"
            and repro_evidence == "interface_error"
            and repro_exception_type in STRICT_REPRO_EXCEPTION_TYPES
        )
        finding_copy["repro_case_id"] = case_id
        finding_copy["repro_status"] = repro_status
        finding_copy["repro_reason"] = str(repro.get("reason", ""))
        finding_copy["repro_evidence"] = repro_evidence
        finding_copy["repro_exception_type"] = repro_exception_type
        finding_copy["repro_error_excerpt"] = strip_local_paths(str(repro.get("error_excerpt", "")))
        finding_copy["repro_is_strict_api_error"] = is_strict_api_error_repro
        enriched.append(finding_copy)
    return enriched


def _render_hero_html(summary: dict[str, object]) -> str:
    """
    @brief Render hero banner HTML with stat tiles derived from summary data.
    @param summary Summary payload from index.json.
    """

    true_count: int = _coerce_int(summary.get("true_count"), 0)
    repo_count: int = _coerce_int(summary.get("hero_repos_300k_to_400k_count"), 0)
    precision: float = _coerce_float(summary.get("precision"), 0.0) * 100.0
    calls_per_repo: float = _coerce_float(summary.get("hero_calls_per_repo"), 1.0)
    pack_trimmed_count: int = _coerce_int(summary.get("pack_trimmed_count"), 0)
    pack_total_count: int = _coerce_int(summary.get("pack_total_count"), 0)
    calls_text: str = "1 call per repo" if abs(calls_per_repo - 1.0) < 0.01 else f"{calls_per_repo:.2f} calls per repo"
    return (
        "<div class='repoatlas-hero'>"
        "<h2>Beam long-context docs drift showcase</h2>"
        "<p>Recorded runs view (no live inference needed to browse).</p>"
        "<div class='repoatlas-stat-grid'>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{true_count}</div>"
        "<div class='repoatlas-stat-label'>Docs bugs checked against the source (file:line evidence)</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{repo_count}</div>"
        "<div class='repoatlas-stat-label'>Libraries around 300k–400k prompt tokens</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{calls_text}</div>"
        "<div class='repoatlas-stat-label'>Model call cadence</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{precision:.1f}%</div>"
        "<div class='repoatlas-stat-label'>Precision, checked against the source (file:line evidence)</div></div>"
        "</div>"
        f"<p style='margin-top:10px;'>Footnote: {pack_trimmed_count} of {pack_total_count} packs were trimmed "
        "(tests/benchmarks dropped first; trace files do not always list exact dropped paths).</p>"
        "</div>"
    )


def _render_bug_wall_html(findings: list[dict[str, object]]) -> str:
    """
    @brief Render HTML cards for true-drift findings.
    @param findings Filtered true-drift finding records.
    """

    sorted_findings: list[dict[str, object]] = sorted(
        findings,
        key=lambda row: (
            0 if bool(row.get("is_cross_file", False)) else 1,
            -_coerce_int(row.get("token_distance"), 0),
            str(row.get("finding_key", "")),
        ),
    )
    cards: list[str] = []
    for finding in sorted_findings:
        repo_url: str = str(finding.get("repo_url", ""))
        library_name: str = repo_url.rstrip("/").split("/")[-1] if repo_url else str(finding.get("case_name", ""))
        doc_citation: dict[str, object] = _as_dict(finding.get("doc_citation"))
        code_citation: dict[str, object] = _as_dict(finding.get("code_citation"))
        breakage_summary: str = str(finding.get("breakage_summary", "")).strip() or str(finding.get("hand_notes", ""))
        display_title: str = str(finding.get("display_title", "")).strip() or f"{library_name}: {breakage_summary.split('.')[0]}"
        upstream_status: str = str(finding.get("upstream_status", "")).strip()
        upstream_url: str = str(finding.get("upstream_url", "")).strip()
        verifier_label: str = str(finding.get("verifier_label", "")).strip()
        finder_tag: str = str(finding.get("finder_tag", "")).strip()
        doc_model_line: int = _coerce_int(finding.get("doc_model_line"), 0)
        doc_verified_line: int = _coerce_int(finding.get("doc_verified_line"), 0)
        cross_file: bool = bool(finding.get("is_cross_file", False))
        cross_file_label: str = "cross-file" if cross_file else "same-file"
        token_distance = finding.get("token_distance")
        token_distance_text: str = (
            f"{cross_file_label}, {int(token_distance):,} tokens apart"
            if isinstance(token_distance, int)
            else cross_file_label
        )
        badge_class: str = "repoatlas-badge-open" if "open" in upstream_status.lower() else "repoatlas-badge-linked"
        repro_status: str = str(finding.get("repro_status", ""))
        repro_evidence: str = str(finding.get("repro_evidence", ""))
        repro_error_excerpt: str = str(finding.get("repro_error_excerpt", "")).strip()
        repro_is_strict: bool = bool(finding.get("repro_is_strict_api_error", False))
        repro_override: str = str(finding.get("repro_badge_override", "")).strip()
        repro_badge_html: str = ""
        if repro_override:
            repro_badge_html = f"<span class='repoatlas-badge repoatlas-badge-open'>{repro_override}</span>"
        elif repro_is_strict:
            excerpt: str = repro_error_excerpt[:160] if repro_error_excerpt else "API error observed."
            repro_badge_html = f"<span class='repoatlas-badge repoatlas-badge-open'>Reproduced: {excerpt}</span>"
        elif repro_status == "reproduced" and repro_evidence == "assertion":
            repro_badge_html = "<span class='repoatlas-badge repoatlas-badge-linked'>repro: assertion only (weak)</span>"
        elif repro_status == "reproduced":
            repro_badge_html = "<span class='repoatlas-badge repoatlas-badge-linked'>repro: non-interface exception (weak)</span>"
        finder_badge_html: str = (
            f"<span class='repoatlas-badge repoatlas-badge-linked'>{finder_tag}</span>" if finder_tag else ""
        )
        upstream_badge_html: str = ""
        if upstream_status:
            upstream_markup: str = (
                f"<a href='{upstream_url}' target='_blank'>{upstream_status}</a>"
                if upstream_url
                else upstream_status
            )
            upstream_badge_html = f"<span class='repoatlas-badge {badge_class}'>{upstream_markup}</span>"
        line_match_text: str = ""
        if doc_verified_line > 0 and doc_model_line > 0 and doc_verified_line != doc_model_line:
            line_match_text = (
                f"<div style='font-size:0.82rem;margin-top:6px;'><b>Citation line match</b>: "
                f"model cited L{doc_model_line}, verifier matched L{doc_verified_line}.</div>"
            )
        doc_path: str = str(doc_citation.get("path", "")).strip()
        doc_line: str = str(doc_citation.get("start_line", "")).strip()
        doc_end: str = str(doc_citation.get("end_line", "")).strip()
        if doc_verified_line > 0 and doc_model_line > 0 and doc_verified_line != doc_model_line:
            doc_line_text: str = f"{doc_path} L{doc_verified_line} (model cited L{doc_model_line})"
        elif doc_end and doc_end != doc_line and doc_path:
            doc_line_text = f"{doc_path} L{doc_line}–{doc_end}"
        elif doc_path:
            doc_line_text = f"{doc_path}:{doc_line}" if doc_line else doc_path
        else:
            doc_line_text = ""
        code_path: str = str(code_citation.get("path", "")).strip()
        code_line: str = str(code_citation.get("start_line", "")).strip()
        code_line_html: str = ""
        if code_path:
            code_site: str = f"{code_path}:{code_line}" if code_line else code_path
            code_line_html = f"<div style='font-size:0.84rem;'><b>Code</b>: {code_site}</div>"
        citation_line: str = ""
        if verifier_label and verifier_label.lower() != "hybrid":
            citation_heading: str = "Citation check" if verifier_label.lower().startswith("citation") else "Citation check"
            citation_value: str = verifier_label
            citation_line = (
                f"<div style='font-size:0.82rem;margin-top:6px;'><b>{citation_heading}</b>: {citation_value}</div>"
            )
        doc_line_html: str = (
            f"<div style='font-size:0.84rem;'><b>Doc</b>: {doc_line_text}</div>" if doc_line_text else ""
        )
        pills: str = "".join(part for part in (finder_badge_html, repro_badge_html, upstream_badge_html) if part)
        cards.append(
            "<div class='repoatlas-bug-card'>"
            f"<div class='repoatlas-bug-title'>{display_title}</div>"
            f"<div style='font-size:0.88rem;color:var(--body-text-color, #334155);margin-bottom:8px;'>{breakage_summary}</div>"
            f"{doc_line_html}"
            f"{code_line_html}"
            f"<div style='font-size:0.84rem;margin-top:6px;'><b>Distance</b>: {token_distance_text}</div>"
            f"{citation_line}"
            f"{line_match_text}"
            f"<div style='font-size:0.84rem;margin-top:6px;'><b>Repo</b>: <a href='{repo_url}' target='_blank'>{repo_url}</a></div>"
            f"{'<div style=\"margin-top:8px;\">' + pills + '</div>' if pills else ''}"
            "</div>"
        )
    return "<div class='repoatlas-bug-grid'>" + "".join(cards) + "</div>"


def _build_findings_rows(findings: list[dict[str, object]]) -> list[list[object]]:
    """
    @brief Render finding table rows for quick browsing.
    @param findings Finding records from index.json.
    """

    rows: list[list[object]] = []
    for finding in findings:
        token_distance = finding.get("token_distance")
        rows.append(
            [
                finding.get("finding_key", ""),
                finding.get("repo_url", ""),
                finding.get("drift_kind", ""),
                finding.get("verifier_label", ""),
                finding.get("hand_verdict", ""),
                finding.get("upstream_status", ""),
                (
                    "reproduced (API error)"
                    if bool(finding.get("repro_is_strict_api_error", False))
                    else (
                        "repro: assertion only (weak)"
                        if str(finding.get("repro_status", "")) == "reproduced"
                        and str(finding.get("repro_evidence", "")) == "assertion"
                        else str(finding.get("repro_status", "")) or "n/a"
                    )
                ),
                "yes" if bool(finding.get("is_cross_file", False)) else "no",
                token_distance if isinstance(token_distance, int) else "",
            ]
        )
    return rows


def _build_finding_choice_map(findings: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """
    @brief Build dropdown labels mapped to finding records.
    @param findings Finding records from index.json.
    """

    choice_map: dict[str, dict[str, object]] = {}
    for finding in findings:
        finding_key: str = str(finding.get("finding_key", ""))
        hand_verdict: str = str(finding.get("hand_verdict", ""))
        display_title: str = str(finding.get("display_title", "")).strip()
        label: str = f"{display_title or finding_key} · source-checked={hand_verdict}"
        choice_map[label] = finding
    return choice_map


def _build_atlas_rows(runs: list[dict[str, object]], findings: list[dict[str, object]]) -> list[list[object]]:
    """
    @brief Build atlas coverage rows from trace-derived run records.
    @param runs Run records from index.json.
    @param findings Finding records from index.json.
    """

    findings_by_case: dict[str, int] = {}
    for finding in findings:
        case_name: str = str(finding.get("case_name", ""))
        findings_by_case[case_name] = findings_by_case.get(case_name, 0) + 1
    rows: list[list[object]] = []
    for run in runs:
        case_name: str = str(run.get("case_name", ""))
        claims_total: int = _coerce_int(run.get("atlas_claims_total"), 0)
        citations_total: int = _coerce_int(run.get("atlas_citations_total"), 0)
        citations_verified: int = _coerce_int(run.get("atlas_citations_verified"), 0)
        findings_verified: int = _coerce_int(run.get("findings_fully_verified"), 0)
        rows.append(
            [
                case_name,
                run.get("repo_url", ""),
                claims_total,
                citations_total,
                citations_verified,
                findings_verified,
                findings_by_case.get(case_name, 0),
            ]
        )
    return rows


def _build_benchmark_rows(runs: list[dict[str, object]]) -> list[list[object]]:
    """
    @brief Build benchmark rows with hand-check columns.
    @param runs Run records from index.json.
    """

    rows: list[list[object]] = []
    for run in runs:
        rows.append(
            [
                run.get("case_name", ""),
                run.get("repo_url", ""),
                run.get("input_tokens", ""),
                run.get("output_tokens", ""),
                f"{_coerce_float(run.get('latency_seconds', 0.0)):.2f}",
                run.get("findings_total", ""),
                run.get("findings_fully_verified", ""),
                run.get("hand_true", ""),
                run.get("hand_false", ""),
                run.get("hand_unclear", ""),
                run.get("hand_precision", ""),
                run.get("pack_dropped_summary", ""),
            ]
        )
    return rows


def _build_replay_rows(findings: list[dict[str, object]], runs: list[dict[str, object]]) -> list[list[object]]:
    """
    @brief Build a compact replay table from the recorded starlette run.
    @param findings Finding records from index.json.
    @param runs Run records from index.json.
    """

    starlette_run: dict[str, object] | None = None
    for run in runs:
        if str(run.get("case_name", "")) == "starlette-400000":
            starlette_run = run
            break
    starlette_finding: dict[str, object] | None = None
    for finding in findings:
        if str(finding.get("finding_key", "")) == "starlette-400000/DD-1":
            starlette_finding = finding
            break
    if starlette_run is None:
        return [["Recorded run", "starlette-400000 trace not found."]]
    rows: list[list[object]] = [
        ["Pack size", f"{_coerce_int(starlette_run.get('input_tokens'), 0):,} prompt tokens"],
        ["Model call time", f"{_coerce_float(starlette_run.get('latency_seconds'), 0.0):.2f} seconds"],
    ]
    if starlette_finding is None:
        rows.append(["Finding", "No finding payload available in this index build."])
        return rows
    rows.extend(
        [
            ["Finding", f"{starlette_finding.get('finding_id', 'DD-1')} ({starlette_finding.get('drift_kind', '')})"],
            [
                "Verifier outcome",
                f"{starlette_finding.get('verifier_label', '')}; model cited L{_coerce_int(starlette_finding.get('doc_model_line'), 0)}, "
                f"verifier matched L{_coerce_int(starlette_finding.get('doc_verified_line'), 0)}.",
            ],
        ]
    )
    return rows


def _build_example_repo_rows() -> list[list[str]]:
    """
    @brief Build one-click example repositories for live mode.
    """

    return [
        ["https://github.com/pallets/flask", "main"],
        ["https://github.com/fastapi/fastapi", "master"],
        ["https://github.com/Kludex/starlette", "master"],
    ]


def _default_finding_label(choice_map: dict[str, dict[str, object]]) -> str:
    """
    @brief Select default finding label, preferring the starlette finding.
    @param choice_map Mapping from dropdown label to finding payload.
    """

    for label in sorted(choice_map.keys()):
        if "starlette-400000/DD-1" in label:
            return label
    return sorted(choice_map.keys())[0]


def _filter_findings(findings: list[dict[str, object]], verdict_filter: str) -> list[dict[str, object]]:
    """
    @brief Filter findings by hand verdict.
    @param findings Finding rows.
    @param verdict_filter Selected verdict filter.
    """

    normalised: str = verdict_filter.strip().lower()
    if normalised == "all":
        return findings
    return [finding for finding in findings if str(finding.get("hand_verdict", "")).lower() == normalised]


def _render_finding_panel(finding: dict[str, object]) -> FindingPanelState:
    """
    @brief Build markdown and snippet panel content for one finding.
    @param finding Finding record.
    """

    doc_citation: dict[str, object] = _as_dict(finding.get("doc_citation"))
    code_citation: dict[str, object] = _as_dict(finding.get("code_citation"))
    verifier_badge: str = _badge_for_verifier(str(finding.get("verifier_label", "")))
    hand_badge: str = _badge_for_hand_verdict(str(finding.get("hand_verdict", "unknown")))
    hand_verdict: str = str(finding.get("hand_verdict", "")).strip().lower()
    upstream_status: str = str(finding.get("upstream_status", "")).strip()
    upstream_url: str = str(finding.get("upstream_url", "")).strip()
    if upstream_url:
        upstream_badge = f"**Upstream:** [{upstream_status}]({upstream_url})"
    elif upstream_status:
        upstream_badge = f"**Upstream:** {upstream_status}"
    elif hand_verdict == "true":
        upstream_badge = "**Upstream:** Not reported upstream yet"
    else:
        upstream_badge = "**Upstream:** n/a"
    doc_model_line: int = _coerce_int(finding.get("doc_model_line"), 0)
    doc_verified_line: int = _coerce_int(finding.get("doc_verified_line"), 0)
    if doc_verified_line > 0 and doc_model_line > 0 and doc_verified_line != doc_model_line:
        doc_header = (
            f"**Doc citation:** `{doc_citation.get('path', '')}` "
            f"L{doc_verified_line} (model cited L{doc_model_line})"
        )
    else:
        doc_header = (
            f"**Doc citation:** `{doc_citation.get('path', '')}` "
            f"L{doc_citation.get('start_line', '')}–L{doc_citation.get('end_line', '')}"
        )
    code_header: str = (
        f"**Code citation:** `{code_citation.get('path', '')}` "
        f"L{code_citation.get('start_line', '')}–L{code_citation.get('end_line', '')}"
    )
    token_distance = finding.get("token_distance")
    token_distance_line: str = (
        f"**Doc/code token distance:** {int(token_distance):,}"
        if isinstance(token_distance, int)
        else "**Doc/code token distance:** not computed for this card"
    )
    line_shift_line: str = ""
    if doc_model_line > 0 and doc_verified_line > 0 and doc_model_line != doc_verified_line:
        line_shift_line = (
            f"**Verifier line match:** model cited L{doc_model_line}, verifier matched L{doc_verified_line}."
        )
    doc_permalink: str = str(finding.get("doc_permalink", "")).strip()
    code_permalink: str = str(finding.get("code_permalink", "")).strip()
    links_parts: list[str] = []
    if hand_verdict == "true":
        if doc_permalink:
            links_parts.append(f"- [Doc permalink]({doc_permalink})")
        if code_permalink:
            links_parts.append(f"- [Code permalink]({code_permalink})")
        issue_draft_path: str = str(finding.get("issue_draft_path", "")).strip()
        if issue_draft_path:
            links_parts.append(f"- Draft source: `{issue_draft_path}`")
    links_markdown: str = "\n".join(links_parts)
    issue_draft_text: str = str(finding.get("issue_draft_text", "")) if hand_verdict == "true" else ""
    upstream_badge_text: str = upstream_badge
    if hand_verdict == "false" and upstream_badge_text.lower().endswith("draft prepared, unfiled"):
        upstream_badge_text = "**Upstream:** n/a for false positive"
    repro_badge_text: str = _badge_for_repro(finding)
    repro_error_excerpt: str = str(finding.get("repro_error_excerpt", "")).strip()
    repro_override: str = str(finding.get("repro_badge_override", "")).strip()
    repro_line: str = ""
    if repro_override:
        repro_line = f"**Executable repro:** {repro_override}"
    elif bool(finding.get("repro_is_strict_api_error", False)):
        repro_line = f"**Executable repro:** Reproduced via API error: `{repro_error_excerpt}`."
    elif str(finding.get("repro_status", "")) == "reproduced" and str(finding.get("repro_evidence", "")) == "assertion":
        repro_line = "**Executable repro:** repro: assertion only (weak)."
    elif str(finding.get("repro_status", "")):
        repro_line = (
            f"**Executable repro:** {finding.get('repro_status')} "
            f"({finding.get('repro_reason', 'n/a')})."
        )
    return FindingPanelState(
        verifier_badge=verifier_badge,
        hand_badge=hand_badge,
        upstream_badge=upstream_badge_text,
        repro_badge=repro_badge_text,
        doc_header=doc_header,
        code_header=code_header,
        doc_quote=str(finding.get("doc_quote", "")),
        code_quote=str(finding.get("code_quote", "")),
        notes=(
            f"**Explanation:** {finding.get('explanation', '')}\n\n"
            f"**What breaks:** {finding.get('breakage_summary', '') or finding.get('hand_notes', '')}\n\n"
            f"{token_distance_line}\n\n"
            f"{line_shift_line}\n\n"
            f"{repro_line}\n\n"
            f"**Verifier reasons:** doc={finding.get('verifier_doc_reason', '') or 'n/a'}, "
            f"code={finding.get('verifier_code_reason', '') or 'n/a'}"
        ),
        links=links_markdown,
        issue_draft_text=issue_draft_text,
    )


def _build_summary_markdown(summary: dict[str, object]) -> str:
    """
    @brief Build top-level summary markdown from index metrics.
    @param summary Summary payload from index.json.
    """

    true_count: int = _coerce_int(summary.get("true_count"), 0)
    judged_count: int = _coerce_int(summary.get("judged_count"), 0)
    false_count: int = _coerce_int(summary.get("false_count"), 0)
    unclear_count: int = _coerce_int(summary.get("unclear_count"), 0)
    precision_percent: float = _coerce_float(summary.get("precision"), 0.0) * 100.0
    verifier_false_total_all: int = _coerce_int(summary.get("verifier_false_total_count_all"), 0)
    verifier_caught_false_all: int = _coerce_int(summary.get("verifier_caught_false_count_all"), 0)
    verifier_rejected_true_all: int = _coerce_int(summary.get("verifier_rejected_true_count_all"), 0)
    verifier_false_total_sweep: int = _coerce_int(summary.get("verifier_false_total_count_sweep"), 0)
    verifier_caught_false_sweep: int = _coerce_int(summary.get("verifier_caught_false_count_sweep"), 0)
    true_cross_file_count: int = _coerce_int(summary.get("true_cross_file_count"), 0)
    true_cross_file_median: int = _coerce_int(summary.get("true_cross_file_median_token_distance"), 0)
    true_cross_file_max: int = _coerce_int(summary.get("true_cross_file_max_token_distance"), 0)
    true_no_prior: int = _coerce_int(summary.get("true_no_prior_report_count"), 0)
    total_input_tokens: int = _coerce_int(summary.get("total_input_tokens"), 0)
    total_output_tokens: int = _coerce_int(summary.get("total_output_tokens"), 0)
    pack_trimmed_count: int = _coerce_int(summary.get("pack_trimmed_count"), 0)
    pack_total_count: int = _coerce_int(summary.get("pack_total_count"), 0)
    return (
        "These numbers are the earlier **v1 whole-repo-only sweep** (17 runs), not DocDrift v2.\n\n"
        f"- Findings checked against the source (file:line evidence): {true_count}/{judged_count} = {precision_percent:.1f}% "
        f"(true={true_count}, false={false_count}, unclear={unclear_count}).\n"
        f"- Citation verifier: caught {verifier_caught_false_all}/{verifier_false_total_all} false positives; "
        f"wrongly rejected {verifier_rejected_true_all} true drift "
        f"(11-repository subset: {verifier_caught_false_sweep}/{verifier_false_total_sweep}).\n"
        f"- {true_cross_file_count}/{true_count} true drifts were cross-file, median ~{true_cross_file_median:,} tokens apart, max ~{true_cross_file_max:,}.\n"
        f"- {true_no_prior} of {true_count} true drifts had no prior upstream PR or issue when checked.\n"
        f"- Cost: {total_input_tokens / 1_000_000:.2f}M prompt + {total_output_tokens / 1_000:.0f}k completion tokens on Beam, $0 via Ollama Cloud free tier.\n"
        f"- {pack_trimmed_count} of {pack_total_count} packs were trimmed to fit the token cap.\n"
        "- v2 has 2 false + 1 unclear repro-badged findings (werkzeug S38, S39 false; S41 unclear). "
        "The v1 line “10 of 11 reproduce; 0 of 10 false do” does not apply to v2."
    )


def _rewrite_finding_display_fields(finding: dict[str, object]) -> dict[str, object]:
    """
    @brief Rewrite recorded-finding badges for honest v2 display.
    @param finding Finding row from index.json.
    """

    rewritten: dict[str, object] = dict(finding)
    repo_name: str = str(rewritten.get("case_name", "")).split("-")[0]
    rewritten["repo_url"] = canonicalize_repo_url(str(rewritten.get("repo_url", "")), repo_name)
    status: str = str(rewritten.get("upstream_status", "")).strip()
    status_lower: str = status.lower()
    if status_lower in {"", "draft prepared, unfiled", "unfiled"}:
        rewritten["upstream_status"] = "Not reported upstream yet" if str(rewritten.get("hand_verdict", "")).lower() == "true" else ""
        rewritten["upstream_url"] = ""
    if str(rewritten.get("finding_key", "")) == "nox-400000/DD-1":
        rewritten["upstream_status"] = "fix submitted upstream (PR #1216, open)"
        rewritten["upstream_url"] = "https://github.com/wntrblm/nox/pull/1216"
    if "independently confirmed" in status_lower or bool(rewritten.get("upstream_prior_reported", False)):
        url: str = str(rewritten.get("upstream_url", ""))
        if url:
            rewritten["upstream_status"] = already_reported_status(url)
            rewritten["upstream_prior_reported"] = True
    if str(rewritten.get("finding_key", "")) == "starlette-400000/DD-1":
        rewritten["repro_is_strict_api_error"] = False
        rewritten["repro_badge_override"] = (
            "Reproduced in our earlier docs-runner (TypeError). "
            "The v2 strict repro couldn't start the test session, so it isn't counted in the 29."
        )
    return rewritten


def _build_repro_summary_markdown(repro_summary: dict[str, object]) -> str:
    """
    @brief Unused v1 repro blurb kept for tests; v2 copy lives in the first-screen panels.
    @param repro_summary Summary payload from results_live/repros/summary.json.
    """

    del repro_summary
    return ""


def _copy_issue_draft(text: str) -> str:
    """
    @brief Return issue draft text in a copy-ready response.
    @param text Draft markdown text for one finding.
    """

    if not text.strip():
        return "No issue draft is available for this finding."
    return f"```markdown\n{text}\n```"


def _estimate_live_tokens(repo_url: str, ref: str, token_limit: int) -> tuple[str, str]:
    """
    @brief Estimate token usage for a live run without making an inference call.
    @param repo_url Public GitHub URL.
    @param ref Branch, tag, or commit.
    @param token_limit Requested token limit.
    """

    stripped_url: str = repo_url.strip()
    if not _is_public_github_url(stripped_url):
        return "Estimate rejected: only public GitHub URLs are allowed.", "estimate: rejected invalid URL"
    bounded_limit: int = max(1, min(int(token_limit), LIVE_MAX_TOKEN_LIMIT))
    config: RepoAtlasConfig = RepoAtlasConfig.from_environment(token_limit=bounded_limit)
    pack = pack_repository(
        repo_url=stripped_url,
        ref=ref.strip() or "main",
        token_limit=bounded_limit,
        token_calibration_factor=config.token_calibration_factor,
        cache_dir=config.cache_dir,
    )
    projected: int = estimate_prompt_tokens(pack.total_tokens, config.token_calibration_factor)
    return (
        f"Estimated pack tokens: **{pack.total_tokens:,}**; projected prompt tokens: **{projected:,}**; "
        f"truncated={pack.truncated}.",
        f"estimate: repo={stripped_url} ref={ref.strip() or 'main'} limit={bounded_limit} projected={projected}",
    )


def _run_live_analysis_stream(
    repo_url: str,
    ref: str,
    token_limit: int,
    request: gr.Request | None = None,
) -> object:
    """
    @brief Execute a guarded live DocDrift run and emit streamed status snapshots.
    @param repo_url Public GitHub repository URL.
    @param ref Branch, tag, or commit.
    @param token_limit Requested token cap.
    @param request Optional Gradio request context.
    """

    stripped_url: str = repo_url.strip()
    selected_ref: str = ref.strip() or "main"
    bounded_limit: int = max(1, min(int(token_limit), LIVE_MAX_TOKEN_LIMIT))
    live_enabled, live_mode_message = get_live_mode_status()
    hidden_table: object = gr.update(value=[], visible=False)
    if not live_enabled:
        yield (f"Live run blocked: {live_mode_message}", hidden_table, "Estimate unavailable.", "live: disabled")
        return
    if not _is_public_github_url(stripped_url):
        yield ("Live run rejected: only public GitHub URLs are allowed.", hidden_table, "Estimate unavailable.", "live: invalid-url")
        return

    ip_address: str = _request_ip(request)
    allowed, rate_message = _record_rate_limited_request(ip_address=ip_address)
    if not allowed:
        yield (f"Live run blocked: {rate_message}", hidden_table, "Estimate unavailable.", "live: rate-limited")
        return

    daily_ok, daily_message = _reserve_daily_live_slot()
    if not daily_ok:
        yield (f"Live run blocked: {daily_message}", hidden_table, "Estimate unavailable.", "live: daily-cap-reached")
        return

    yield ("Preparing live run…", hidden_table, "Estimating token usage…", "live: started")
    try:
        config: RepoAtlasConfig = RepoAtlasConfig.from_environment(token_limit=bounded_limit)
        pack = pack_repository(
            repo_url=stripped_url,
            ref=selected_ref,
            token_limit=bounded_limit,
            token_calibration_factor=config.token_calibration_factor,
            cache_dir=config.cache_dir,
        )
        projected_tokens: int = estimate_prompt_tokens(pack.total_tokens, config.token_calibration_factor)
        yield (
            "Pack ready. Running Beam DocDrift analysis…",
            hidden_table,
            (
                f"Estimated pack tokens: **{pack.total_tokens:,}**; projected prompt tokens: **{projected_tokens:,}**; "
                f"truncated={pack.truncated}."
            ),
            f"live: pack-ready provider={config.provider} ip={ip_address}",
        )
        bundle = analyse_repository(
            repo_url=stripped_url,
            ref=selected_ref,
            config=config,
            fixture_path=FIXTURE_PATH,
            run_probes=False,
        )
        rows: list[list[object]] = _build_live_rows_from_bundle(bundle)
        status: str = (
            f"Live run complete. Provider `{bundle.output.provider}` model `{bundle.output.model}`; "
            f"findings={bundle.summary.findings_total}; verifier_pass={bundle.summary.findings_fully_verified}; "
            f"latency={bundle.summary.latency_seconds:.2f}s."
        )
        yield (
            status,
            gr.update(value=rows, visible=bool(rows)),
            (
                f"Estimated pack tokens: **{pack.total_tokens:,}**; projected prompt tokens: **{projected_tokens:,}**; "
                f"truncated={pack.truncated}."
            ),
            "live: complete",
        )
        return
    except Exception as exc:
        yield (f"Live run failed: `{exc}`", hidden_table, "Estimate available above.", "live: failed")
        return


def _request_ip(request: gr.Request | None) -> str:
    """
    @brief Derive caller IP string from Gradio request metadata.
    @param request Optional Gradio request object.
    """

    if request is None:
        return "unknown"
    try:
        if request.client is not None and request.client.host:
            return str(request.client.host)
    except Exception:
        return "unknown"
    return "unknown"


def _record_rate_limited_request(ip_address: str, now_epoch: float | None = None) -> tuple[bool, str]:
    """
    @brief Enforce per-IP run budget over a rolling one-hour window.
    @param ip_address Request source IP.
    @param now_epoch Optional timestamp for tests.
    """

    timestamp: float = now_epoch if now_epoch is not None else time.time()
    with _RATE_LIMIT_LOCK:
        prior_timestamps: list[float] = _RATE_LIMIT_STATE.get(ip_address, [])
        retained: list[float] = [value for value in prior_timestamps if (timestamp - value) < 3600]
        if len(retained) >= LIVE_RATE_LIMIT_PER_HOUR_PER_IP:
            return False, (
                f"per-IP limit reached ({LIVE_RATE_LIMIT_PER_HOUR_PER_IP}/hour). "
                "Please wait before trying another live run."
            )
        retained.append(timestamp)
        _RATE_LIMIT_STATE[ip_address] = retained
    return True, "allowed"


def _reserve_daily_live_slot(now_utc: datetime | None = None) -> tuple[bool, str]:
    """
    @brief Reserve one global daily slot for live runs.
    @param now_utc Optional injected current UTC time for tests.
    """

    now_value: datetime = now_utc or datetime.now(UTC)
    today: str = now_value.date().isoformat()
    with _DAILY_CAP_LOCK:
        counter_payload: dict[str, object] = _read_daily_counter()
        counter_date: str = str(counter_payload.get("date", ""))
        counter_count: int = _coerce_int(counter_payload.get("count"), 0)
        if counter_date != today:
            counter_count = 0
        if counter_count >= LIVE_DAILY_CAP:
            return False, f"global daily cap reached ({LIVE_DAILY_CAP}/{LIVE_DAILY_CAP})."
        counter_count += 1
        _write_daily_counter({"date": today, "count": counter_count})
    return True, f"reserved daily slot {counter_count}/{LIVE_DAILY_CAP}."


def _read_daily_counter() -> dict[str, object]:
    """
    @brief Read the persisted live daily counter file.
    """

    if not LIVE_DAILY_COUNTER_PATH.exists():
        return {"date": "", "count": 0}
    try:
        payload: dict[str, object] = json.loads(LIVE_DAILY_COUNTER_PATH.read_text(encoding="utf-8"))
        return payload
    except Exception:
        return {"date": "", "count": 0}


def _write_daily_counter(counter_payload: dict[str, object]) -> None:
    """
    @brief Persist the live daily counter file.
    @param counter_payload Counter payload map.
    """

    LIVE_DAILY_COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIVE_DAILY_COUNTER_PATH.write_text(json.dumps(counter_payload, indent=2), encoding="utf-8")


def _build_live_rows_from_bundle(bundle: object) -> list[list[object]]:
    """
    @brief Render live result rows from an analysis bundle.
    @param bundle Analysis bundle object returned by analyse_repository.
    """

    rows: list[list[object]] = []
    bundle_output = getattr(bundle, "output")
    bundle_verification = getattr(bundle, "verification_results")
    for finding, verification in zip(bundle_output.findings, bundle_verification):
        rows.append(
            [
                finding.finding_id,
                finding.drift_kind,
                "pass" if verification.fully_verified else "reject",
                f"{finding.doc_citation.path}:{finding.doc_citation.start_line}-{finding.doc_citation.end_line}",
                f"{finding.code_citation.path}:{finding.code_citation.start_line}-{finding.code_citation.end_line}",
                finding.explanation,
            ]
        )
    return rows


def _is_public_github_url(repo_url: str) -> bool:
    """
    @brief Validate that a repository URL is a public GitHub HTTPS URL.
    @param repo_url Candidate repository URL.
    """

    lowered: str = repo_url.lower()
    return lowered.startswith("https://github.com/") and "@" not in lowered


def _badge_for_verifier(verifier_label: str) -> str:
    """
    @brief Build a colour badge for verifier status.
    @param verifier_label Verifier status label.
    """

    normalised: str = verifier_label.strip().lower()
    if normalised == "verified (line-shifted)":
        return "🟢 **Verifier:** verified (line-shifted)"
    if normalised == "verified":
        return "🟢 **Verifier:** verified"
    if normalised == "reject":
        return "🔴 **Verifier:** reject"
    return f"⚪ **Verifier:** {verifier_label or 'unknown'}"


def _badge_for_hand_verdict(verdict: str) -> str:
    """
    @brief Build a colour badge for the source-checked verdict.
    @param verdict Verdict string stored as hand_verdict (checked against the source by an AI reviewer).
    """

    normalised: str = verdict.strip().lower()
    if normalised == "true":
        return "🟢 **Checked against the source:** true drift"
    if normalised == "false":
        return "🔴 **Checked against the source:** false positive"
    if normalised == "unclear":
        return "🟠 **Checked against the source:** unclear"
    return "⚪ **Checked against the source:** unlabelled"


def _badge_for_repro(finding: dict[str, object]) -> str:
    """
    @brief Build a badge that distinguishes strict API-error repros from weaker signals.
    @param finding Finding record with attached repro metadata.
    """

    override: str = str(finding.get("repro_badge_override", "")).strip()
    if override:
        return f"🟢 **Reproduced:** {override}"
    status: str = str(finding.get("repro_status", "")).strip()
    evidence: str = str(finding.get("repro_evidence", "")).strip()
    excerpt: str = str(finding.get("repro_error_excerpt", "")).strip()
    if bool(finding.get("repro_is_strict_api_error", False)):
        snippet: str = excerpt[:180] if excerpt else "API error observed."
        return f"🟢 **Reproduced:** `{snippet}`"
    if status == "reproduced" and evidence == "assertion":
        return "🟠 **Repro:** repro: assertion only (weak)"
    if status == "reproduced":
        return "🟠 **Repro:** reproduced, but not via strict API error (weak)"
    if status:
        return f"⚪ **Repro:** {status}"
    return "⚪ **Repro:** n/a"


def _coerce_int(value: object, fallback: int = 0) -> int:
    """
    @brief Coerce an object to int with fallback.
    @param value Input object.
    @param fallback Fallback integer.
    """

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return fallback
    return fallback


def _coerce_float(value: object, fallback: float = 0.0) -> float:
    """
    @brief Coerce an object to float with fallback.
    @param value Input object.
    @param fallback Fallback float.
    """

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return fallback
    return fallback


def _as_dict(value: object) -> dict[str, object]:
    """
    @brief Convert unknown object to dictionary.
    @param value Input object.
    """

    if isinstance(value, dict):
        return value
    return {}


def _as_dict_list(value: object) -> list[dict[str, object]]:
    """
    @brief Convert unknown object to list of dictionaries.
    @param value Input object.
    """

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _reset_live_state_for_tests() -> None:
    """
    @brief Reset in-memory rate limiter state for deterministic unit tests.
    """

    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_STATE.clear()
