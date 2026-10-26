"""Gradio Space application for RepoAtlas-1M recorded and live views."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import threading
import time
from typing import Mapping, TypedDict

import gradio as gr
import pandas as pd

from repoatlas.analyser import analyse_repository
from repoatlas.config import RepoAtlasConfig
from repoatlas.packer import estimate_prompt_tokens, pack_repository


RESULTS_LIVE_DIRECTORY: Path = Path("results_live")
RESULTS_LIVE_INDEX_PATH: Path = RESULTS_LIVE_DIRECTORY / "index.json"
RESULTS_LIVE_REPROS_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "repros"
RESULTS_LIVE_REPROS_INDEX_PATH: Path = RESULTS_LIVE_REPROS_DIRECTORY / "repros.json"
RESULTS_LIVE_REPROS_SUMMARY_PATH: Path = RESULTS_LIVE_REPROS_DIRECTORY / "summary.json"
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


# Private function prototypes:
# - _load_live_index() -> LiveIndex
# - _load_repro_results() -> tuple[dict[str, dict[str, object]], dict[str, object]]
# - _attach_repro_records(findings: list[dict[str, object]], repros_map: dict[str, dict[str, object]]) -> list[dict[str, object]]
# - _finding_case_id(finding: dict[str, object]) -> str
# - _render_hero_html(summary: dict[str, object]) -> str
# - _render_long_context_diagram_html() -> str
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
    findings: list[dict[str, object]] = _attach_repro_records(live_index["findings"], repros_map=repros_map)
    runs: list[dict[str, object]] = live_index["runs"]
    summary: dict[str, object] = live_index["summary"]
    hero_html: str = _render_hero_html(summary)
    true_findings: list[dict[str, object]] = _filter_findings(findings, "true")
    bug_wall_html: str = _render_bug_wall_html(true_findings)
    live_enabled, live_status_message = get_live_mode_status()
    live_mode_summary: str = (
        f"🟢 **Live mode enabled** — {live_status_message}"
        if live_enabled
        else "🟡 **Replay mode** — showing a recorded starlette run because no live provider key is set."
    )

    all_choice_map: dict[str, dict[str, object]] = _build_finding_choice_map(findings)
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
    replay_rows: list[list[object]] = _build_replay_rows(findings=findings, runs=runs)
    benchmark_plot_rows: pd.DataFrame = pd.DataFrame(
        [
            {
                "case_name": str(run.get("case_name", "")),
                "input_tokens": _coerce_int(run.get("input_tokens"), 0),
                "output_tokens": _coerce_int(run.get("output_tokens"), 0),
                "latency_seconds": _coerce_float(run.get("latency_seconds"), 0.0),
            }
            for run in runs
        ]
    )
    baselines_directory: Path = RESULTS_LIVE_DIRECTORY / "baselines"
    has_baselines: bool = baselines_directory.exists() and any(baselines_directory.iterdir())
    example_repo_rows: list[list[str]] = _build_example_repo_rows()
    example_flask_button: gr.Button | None = None
    example_fastapi_button: gr.Button | None = None
    example_starlette_button: gr.Button | None = None

    with gr.Blocks(title="RepoAtlas-1M") as demo:
        gr.Markdown(
            "# RepoAtlas-1M\n"
            "### 11 hand-verified docs bugs in popular Python libraries, found by Beam reading each library's docs and source "
            "(up to ~400k tokens) in one call.\n\n"
            "**What is docs drift?** Documentation says one thing, but the code actually does another.\n\n"
            "**Worked example (starlette):** docs line `receive_json(data, mode=\"binary\")`; code signature "
            "`receive_json(self, mode: str = \"text\")`; following the docs can raise `TypeError`.\n\n"
            "Headline story: Beam read starlette (~395k tokens) in one call, found this drift, verified by hand, and the "
            f"upstream status is **{starlette_status_markdown}** on "
            "[github.com/Kludex/starlette](https://github.com/Kludex/starlette), sourced from "
            "`results_live/upstream_status.json`."
        )
        gr.Markdown(_build_summary_markdown(summary))
        repro_summary_markdown: str = _build_repro_summary_markdown(repro_summary)
        if repro_summary_markdown:
            gr.Markdown(repro_summary_markdown)

        with gr.Tab("Recorded runs"):
            gr.HTML(hero_html)
            gr.Markdown(
                "### Why long context matters\n"
                "Most true drifts need a docs line and a far-away code line in the same prompt. "
                "A single long-context call can compare those directly."
            )
            gr.HTML(_render_long_context_diagram_html())
            gr.Markdown("### Bug wall (true drifts)")
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
                "Verifier status and hand-check verdict are separate. "
                "Verifier pass means quote/citation alignment only, not guaranteed correctness."
            )
            if repro_summary_markdown:
                gr.Markdown(repro_summary_markdown)
            verdict_filter = gr.Dropdown(
                choices=["all", "true", "false", "unclear"],
                value="all",
                label="Filter by hand verdict",
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
                    "Hand verdict",
                    "Upstream status",
                    "Executable repro",
                    "Cross-file",
                    "Token distance",
                ],
                value=_build_findings_rows(findings),
                interactive=False,
                wrap=True,
            )

        with gr.Tab("Atlas"):
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

        with gr.Tab("Benchmark"):
            gr.Markdown(
                "Token scales are split to avoid mixing prompt and completion counts on one axis."
            )
            gr.BarPlot(
                value=benchmark_plot_rows,
                x="case_name",
                y="input_tokens",
                title="Prompt tokens by run",
                y_title="Prompt tokens",
                x_label_angle=35,
            )
            gr.BarPlot(
                value=benchmark_plot_rows,
                x="case_name",
                y="output_tokens",
                title="Completion tokens by run",
                y_title="Completion tokens",
                x_label_angle=35,
            )
            gr.LinePlot(
                value=benchmark_plot_rows,
                x="case_name",
                y="latency_seconds",
                title="Latency by run",
                y_title="Latency (seconds)",
                x_label_angle=35,
            )
            gr.Dataframe(
                headers=benchmark_headers,
                value=benchmark_rows,
                interactive=False,
                wrap=True,
            )
            if has_baselines:
                baseline_files: list[list[str]] = [[item.name] for item in sorted(baselines_directory.iterdir())]
                with gr.Accordion("Baselines", open=False):
                    gr.Dataframe(
                        headers=["Available baseline files"],
                        value=baseline_files,
                        interactive=False,
                        wrap=True,
                    )

        with gr.Tab("Live try it"):
            gr.Markdown(
                f"{live_mode_summary}\n\n"
                "Guardrails: one job at a time, max 150k token pack budget, per-IP rate limit (2/hour), "
                "and a global daily cap via environment."
            )
            if not live_enabled:
                gr.Markdown(
                    "#### Recorded replay: starlette (~395k prompt tokens)\n"
                    "This is a step-by-step replay from a recorded run: pack size, model call, finding, and verifier outcome."
                )
                gr.Dataframe(
                    headers=["Step", "Details"],
                    value=replay_rows,
                    interactive=False,
                    wrap=True,
                )
            else:
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
            live_ref = gr.Textbox(label="Reference", value="main")
            live_token_limit = gr.Slider(
                minimum=40_000,
                maximum=LIVE_MAX_TOKEN_LIMIT,
                step=10_000,
                value=LIVE_DEFAULT_TOKEN_LIMIT,
                label="Pack token cap",
            )
            with gr.Row():
                estimate_button = gr.Button("Dry-run token estimate")
                run_button = gr.Button("Run DocDrift live")
            live_estimate = gr.Markdown(value="Estimate not run yet.")
            live_status = gr.Markdown(value="No live run started.")
            live_findings = gr.Dataframe(
                headers=["Finding ID", "Drift kind", "Verifier", "Doc citation", "Code citation", "Explanation"],
                value=[],
                interactive=False,
                wrap=True,
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

            filtered: list[dict[str, object]] = _filter_findings(findings, verdict)
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
        finding_copy["repro_error_excerpt"] = str(repro.get("error_excerpt", ""))
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
        "<div class='repoatlas-stat-label'>Hand-verified docs bugs</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{repo_count}</div>"
        "<div class='repoatlas-stat-label'>Libraries around 300k–400k prompt tokens</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{calls_text}</div>"
        "<div class='repoatlas-stat-label'>Model call cadence</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{precision:.1f}%</div>"
        "<div class='repoatlas-stat-label'>Hand-checked precision</div></div>"
        "</div>"
        f"<p style='margin-top:10px;'>Footnote: {pack_trimmed_count} of {pack_total_count} packs were trimmed "
        "(tests/benchmarks dropped first; trace files do not always list exact dropped paths).</p>"
        "</div>"
    )


def _render_long_context_diagram_html() -> str:
    """
    @brief Render a compact HTML diagram describing the long-context flow.
    """

    return (
        "<div class='repoatlas-diagram'>"
        "<div class='repoatlas-flow-row'>"
        "<div class='repoatlas-node'>docs/… citation</div>"
        "<div class='repoatlas-arrow'>→</div>"
        "<div class='repoatlas-node'>single packed prompt</div>"
        "<div class='repoatlas-arrow'>→</div>"
        "<div class='repoatlas-node'>Beam one-call reasoning</div>"
        "<div class='repoatlas-arrow'>→</div>"
        "<div class='repoatlas-node'>code/… citation</div>"
        "</div>"
        "<p style='margin:10px 0 0 0;color:#475569;'>"
        "True drifts often link a docs line and a far-away implementation line. "
        "Keeping both in one prompt allows direct cross-file comparison without retrieval hops."
        "</p>"
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
        upstream_status: str = str(finding.get("upstream_status", "draft prepared, unfiled"))
        upstream_url: str = str(finding.get("upstream_url", ""))
        verifier_label: str = str(finding.get("verifier_label", ""))
        doc_model_line: int = _coerce_int(finding.get("doc_model_line"), 0)
        doc_verified_line: int = _coerce_int(finding.get("doc_verified_line"), 0)
        cross_file: bool = bool(finding.get("is_cross_file", False))
        cross_file_label: str = "cross-file" if cross_file else "same-file"
        token_distance = finding.get("token_distance")
        token_distance_text: str = (
            f"{cross_file_label}, {int(token_distance):,} tokens apart"
            if isinstance(token_distance, int)
            else f"{cross_file_label}, distance not derivable"
        )
        badge_class: str = "repoatlas-badge-open" if "open" in upstream_status.lower() else "repoatlas-badge-linked"
        prior_reported: bool = bool(finding.get("upstream_prior_reported", False))
        prior_badge: str = (
            "<span class='repoatlas-badge repoatlas-badge-linked'>already reported upstream</span>"
            if prior_reported
            else ""
        )
        repro_status: str = str(finding.get("repro_status", ""))
        repro_evidence: str = str(finding.get("repro_evidence", ""))
        repro_error_excerpt: str = str(finding.get("repro_error_excerpt", "")).strip()
        repro_is_strict: bool = bool(finding.get("repro_is_strict_api_error", False))
        repro_badge_html: str = ""
        if repro_is_strict:
            excerpt: str = repro_error_excerpt[:160] if repro_error_excerpt else "API error observed."
            repro_badge_html = f"<span class='repoatlas-badge repoatlas-badge-open'>Reproduced: {excerpt}</span>"
        elif repro_status == "reproduced" and repro_evidence == "assertion":
            repro_badge_html = "<span class='repoatlas-badge repoatlas-badge-linked'>repro: assertion only (weak)</span>"
        elif repro_status == "reproduced":
            repro_badge_html = "<span class='repoatlas-badge repoatlas-badge-linked'>repro: non-interface exception (weak)</span>"
        upstream_markup: str = (
            f"<a href='{upstream_url}' target='_blank'>{upstream_status}</a>"
            if upstream_url
            else upstream_status
        )
        line_match_text: str = ""
        if doc_verified_line > 0 and doc_model_line > 0 and doc_verified_line != doc_model_line:
            line_match_text = (
                f"<div style='font-size:0.82rem;margin-top:6px;'><b>Verifier line match</b>: "
                f"model cited L{doc_model_line}, verifier matched L{doc_verified_line}.</div>"
            )
        cards.append(
            "<div class='repoatlas-bug-card'>"
            f"<div class='repoatlas-bug-title'>{library_name}: {finding.get('finding_id', '')}</div>"
            f"<div style='font-size:0.88rem;color:var(--body-text-color, #334155);margin-bottom:8px;'>{breakage_summary}</div>"
            f"<div style='font-size:0.84rem;'><b>Doc</b>: {doc_citation.get('path', '')}:{doc_citation.get('start_line', '')}</div>"
            f"<div style='font-size:0.84rem;'><b>Code</b>: {code_citation.get('path', '')}:{code_citation.get('start_line', '')}</div>"
            f"<div style='font-size:0.84rem;margin-top:6px;'><b>Distance</b>: {token_distance_text}</div>"
            f"<div style='font-size:0.82rem;margin-top:6px;'><b>Verifier</b>: {verifier_label}</div>"
            f"{line_match_text}"
            f"<div style='font-size:0.84rem;margin-top:6px;'><b>Repo</b>: <a href='{repo_url}' target='_blank'>{repo_url}</a></div>"
            f"<div style='margin-top:8px;'>{repro_badge_html}{prior_badge}<span class='repoatlas-badge {badge_class}'>{upstream_markup}</span></div>"
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
        verifier: str = str(finding.get("verifier_label", "reject"))
        label: str = f"{finding_key} · hand={hand_verdict} · verifier={verifier}"
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
    else:
        upstream_badge = f"**Upstream:** {upstream_status}" if upstream_status else "**Upstream:** unfiled"
    doc_header: str = (
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
        else "**Doc/code token distance:** not derivable from pack order"
    )
    doc_model_line: int = _coerce_int(finding.get("doc_model_line"), 0)
    doc_verified_line: int = _coerce_int(finding.get("doc_verified_line"), 0)
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
    repro_line: str = ""
    if bool(finding.get("repro_is_strict_api_error", False)):
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
    findings_per_true: float = judged_count / true_count if true_count else 0.0
    return (
        f"- **Live hand-checked precision:** {true_count}/{judged_count} = {precision_percent:.1f}% "
        f"(true={true_count}, false={false_count}, unclear={unclear_count})\n"
        f"- **Verifier behaviour (all runs):** caught {verifier_caught_false_all}/{verifier_false_total_all} false positives; "
        f"wrongly rejected {verifier_rejected_true_all} true drift.\n"
        f"- **Verifier behaviour (11-repository subset):** caught {verifier_caught_false_sweep}/{verifier_false_total_sweep} false positives.\n"
        f"- **Cross-file framing:** {true_cross_file_count}/{true_count} true drifts are cross-file, median ~{true_cross_file_median:,} tokens apart, max ~{true_cross_file_max:,}.\n"
        f"- **Prior-art check:** {true_no_prior} of {true_count} true drifts had no prior upstream PR or issue when checked.\n"
        f"- **Cost (recorded runs):** {total_input_tokens / 1_000_000:.2f}M prompt + {total_output_tokens / 1_000:.0f}k completion tokens on Beam, $0 via Ollama Cloud free tier.\n"
        f"- **Packing footnote:** {pack_trimmed_count} of {pack_total_count} packs were trimmed; when trimming happens, tests/benchmarks are dropped first.\n"
        f"- **Maintainer note:** about 1 in {findings_per_true:.1f} findings is a real drift; each takes roughly two minutes to check with the permalinks."
    )


def _build_repro_summary_markdown(repro_summary: dict[str, object]) -> str:
    """
    @brief Build markdown for strict executable repro metrics.
    @param repro_summary Summary payload from results_live/repros/summary.json.
    """

    if not repro_summary:
        return ""
    true_total: int = _coerce_int(repro_summary.get("hand_true"), 0)
    false_unclear_total: int = _coerce_int(repro_summary.get("hand_false_or_unclear"), 0)
    strict_kept: int = _coerce_int(repro_summary.get("kept_with_strict_filter"), 0)
    strict_true: int = _coerce_int(repro_summary.get("kept_true_with_strict_filter"), 0)
    strict_false_unclear: int = max(0, strict_kept - strict_true)
    return (
        f"- **Executable check:** {strict_true} of {true_total} true drifts reproduce as a real API error when you run "
        f"the docs literally; {strict_false_unclear} of {false_unclear_total} false/unclear findings do.\n"
        "- **Strict rule note:** the API-error rule (TypeError/AttributeError/ImportError/NameError) was defined "
        "after seeing these 21 results, and is pending confirmation on new findings."
    )


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
    if not live_enabled:
        yield (f"Live run blocked: {live_mode_message}", [], "Estimate unavailable.", "live: disabled")
        return
    if not _is_public_github_url(stripped_url):
        yield ("Live run rejected: only public GitHub URLs are allowed.", [], "Estimate unavailable.", "live: invalid-url")
        return

    ip_address: str = _request_ip(request)
    allowed, rate_message = _record_rate_limited_request(ip_address=ip_address)
    if not allowed:
        yield (f"Live run blocked: {rate_message}", [], "Estimate unavailable.", "live: rate-limited")
        return

    daily_ok, daily_message = _reserve_daily_live_slot()
    if not daily_ok:
        yield (f"Live run blocked: {daily_message}", [], "Estimate unavailable.", "live: daily-cap-reached")
        return

    yield ("Preparing live run…", [], "Estimating token usage…", "live: started")
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
            [],
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
            rows,
            (
                f"Estimated pack tokens: **{pack.total_tokens:,}**; projected prompt tokens: **{projected_tokens:,}**; "
                f"truncated={pack.truncated}."
            ),
            "live: complete",
        )
        return
    except Exception as exc:
        yield (f"Live run failed: `{exc}`", [], "Estimate available above.", "live: failed")
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
    @brief Build a colour badge for hand-check verdict.
    @param verdict Verdict string.
    """

    normalised: str = verdict.strip().lower()
    if normalised == "true":
        return "🟢 **Hand-check:** true drift"
    if normalised == "false":
        return "🔴 **Hand-check:** false positive"
    if normalised == "unclear":
        return "🟠 **Hand-check:** unclear"
    return "⚪ **Hand-check:** unlabelled"


def _badge_for_repro(finding: dict[str, object]) -> str:
    """
    @brief Build a badge that distinguishes strict API-error repros from weaker signals.
    @param finding Finding record with attached repro metadata.
    """

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
