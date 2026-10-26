"""Gradio Space application for RepoAtlas-1M cached and live views."""

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
RESULTS_LIVE_HANDCHECK_PATH: Path = RESULTS_LIVE_DIRECTORY / "handcheck.md"
RESULTS_LIVE_BENCHMARK_COMBINED_PATH: Path = RESULTS_LIVE_DIRECTORY / "benchmark_results_combined.csv"
RESULTS_LIVE_CHARTS_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "charts"
FIXTURE_PATH: Path = Path("fixtures/analysis_fixture.json")
LIVE_MAX_TOKEN_LIMIT: int = 150_000
LIVE_DEFAULT_TOKEN_LIMIT: int = 150_000
LIVE_RATE_LIMIT_PER_HOUR_PER_IP: int = int(os.environ.get("REPOATLAS_LIVE_PER_HOUR_PER_IP", "2"))
LIVE_DAILY_CAP: int = int(os.environ.get("REPOATLAS_LIVE_DAILY_CAP", "24"))
LIVE_DAILY_COUNTER_PATH: Path = Path(
    os.environ.get("REPOATLAS_LIVE_DAILY_COUNTER_PATH", ".cache/repoatlas/live_daily_counter.json")
)

_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_STATE: dict[str, list[float]] = {}
_DAILY_CAP_LOCK = threading.Lock()


class LiveIndex(TypedDict):
    """
    @brief Compact loaded payload for the live Space view.
    @param summary Aggregate metrics.
    @param runs Run-level records for benchmark and atlas tabs.
    @param findings Finding-level records with hand labels.
    @param handcheck_markdown_path Relative path to hand-check narrative.
    """

    summary: dict[str, object]
    runs: list[dict[str, object]]
    findings: list[dict[str, object]]
    handcheck_markdown_path: str


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
    @param notes Human verification notes.
    """

    verifier_badge: str
    hand_badge: str
    upstream_badge: str
    doc_header: str
    code_header: str
    doc_quote: str
    code_quote: str
    notes: str


# Private function prototypes:
# - _load_live_index() -> LiveIndex
# - _build_findings_rows(findings: list[dict[str, object]]) -> list[list[object]]
# - _build_finding_choice_map(findings: list[dict[str, object]]) -> dict[str, dict[str, object]]
# - _render_finding_panel(finding: dict[str, object]) -> FindingPanelState
# - _build_atlas_rows(runs: list[dict[str, object]], findings: list[dict[str, object]]) -> list[list[object]]
# - _build_benchmark_rows(runs: list[dict[str, object]]) -> list[list[object]]
# - _build_summary_markdown(summary: dict[str, object]) -> str
# - _estimate_live_tokens(repo_url: str, ref: str, token_limit: int) -> tuple[str, str]
# - _run_live_analysis_stream(repo_url: str, ref: str, token_limit: int, request: gr.Request | None = None) -> object
# - _request_ip(request: gr.Request | None) -> str
# - _record_rate_limited_request(ip_address: str, now_epoch: float | None = None) -> tuple[bool, str]
# - _reserve_daily_live_slot(now_utc: datetime | None = None) -> tuple[bool, str]
# - _read_daily_counter() -> dict[str, object]
# - _write_daily_counter(counter_payload: dict[str, object]) -> None
# - _build_live_rows_from_bundle(bundle: object) -> list[list[object]]
# - _is_public_github_url(repo_url: str) -> bool
# - _badge_for_verifier(is_verified: bool) -> str
# - _badge_for_hand_verdict(verdict: str) -> str
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
    findings: list[dict[str, object]] = live_index["findings"]
    runs: list[dict[str, object]] = live_index["runs"]
    summary: dict[str, object] = live_index["summary"]
    finding_choice_map: dict[str, dict[str, object]] = _build_finding_choice_map(findings)
    finding_choices: list[str] = sorted(finding_choice_map.keys())
    default_finding_choice: str = finding_choices[0] if finding_choices else ""
    default_finding_panel: FindingPanelState = (
        _render_finding_panel(finding_choice_map[default_finding_choice])
        if default_finding_choice
        else FindingPanelState(
            verifier_badge="",
            hand_badge="",
            upstream_badge="",
            doc_header="No finding selected.",
            code_header="No finding selected.",
            doc_quote="",
            code_quote="",
            notes="",
        )
    )
    benchmark_rows: list[list[object]] = _build_benchmark_rows(runs)
    benchmark_headers: list[str] = [
        "Case",
        "Repo",
        "Prompt tokens",
        "Latency (s)",
        "Findings",
        "Verifier pass",
        "Hand true",
        "Hand false",
        "Hand unclear",
        "Hand precision",
    ]
    finding_rows: list[list[object]] = _build_findings_rows(findings)
    atlas_rows: list[list[object]] = _build_atlas_rows(runs, findings)
    handcheck_markdown: str = RESULTS_LIVE_HANDCHECK_PATH.read_text(encoding="utf-8")
    live_enabled, live_status_message = get_live_mode_status()
    live_mode_summary: str = (
        f"🟢 **Live mode enabled** — {live_status_message}" if live_enabled else f"⚪ **Live mode disabled** — {live_status_message}"
    )

    with gr.Blocks(title="RepoAtlas-1M") as demo:
        gr.Markdown(
            "# RepoAtlas-1M\n"
            "### 11 hand-verified docs bugs in popular Python libraries, found by Beam reading each whole repo (~300–400k tokens) in a single call.\n\n"
            "#### Headline story\n"
            "**Beam read all of starlette (395k tokens) in one call, found a docs bug, verified by hand, fixed upstream (PR #3746).**"
        )
        gr.Markdown(_build_summary_markdown(summary))

        with gr.Tab("Gallery (cached)"):
            gr.Markdown(
                "This tab is fully cached from `results_live/` and costs zero inference tokens. "
                "It is the default experience for judging and demoing."
            )
            gr.Dataframe(
                headers=benchmark_headers,
                value=benchmark_rows,
                interactive=False,
                wrap=True,
                label="Run gallery",
            )

        with gr.Tab("Findings"):
            gr.Markdown(
                "Verifier status and hand-check verdict are shown separately. "
                "A verifier pass means quote/citation alignment, not guaranteed correctness."
            )
            selected_finding = gr.Dropdown(
                choices=finding_choices,
                value=default_finding_choice,
                label="Select finding",
                interactive=True,
            )
            with gr.Row():
                verifier_badge = gr.Markdown(value=default_finding_panel["verifier_badge"])
                hand_badge = gr.Markdown(value=default_finding_panel["hand_badge"])
                upstream_badge = gr.Markdown(value=default_finding_panel["upstream_badge"])
            finding_notes = gr.Markdown(value=default_finding_panel["notes"])
            with gr.Row():
                with gr.Column():
                    doc_header = gr.Markdown(value=default_finding_panel["doc_header"])
                    doc_quote = gr.Textbox(value=default_finding_panel["doc_quote"], lines=12, label="Documentation snippet")
                with gr.Column():
                    code_header = gr.Markdown(value=default_finding_panel["code_header"])
                    code_quote = gr.Textbox(value=default_finding_panel["code_quote"], lines=12, label="Code snippet")
            gr.Dataframe(
                headers=[
                    "Finding key",
                    "Repo",
                    "Drift kind",
                    "Verifier",
                    "Hand verdict",
                    "Upstream status",
                ],
                value=finding_rows,
                interactive=False,
                wrap=True,
                label="All finding cards",
            )

        with gr.Tab("Atlas"):
            gr.Markdown("Atlas citation coverage per run from cached live traces.")
            gr.Dataframe(
                headers=[
                    "Case",
                    "Repo",
                    "Atlas citations verified",
                    "Atlas claims total",
                ],
                value=atlas_rows,
                interactive=False,
                wrap=True,
            )

        with gr.Tab("Benchmark"):
            gr.Markdown("Charts and honest benchmark table, including false positives and unclear labels.")
            if (RESULTS_LIVE_CHARTS_DIRECTORY / "tokens_vs_context.png").exists():
                gr.Image(value=str(RESULTS_LIVE_CHARTS_DIRECTORY / "tokens_vs_context.png"), label="Tokens vs context")
            if (RESULTS_LIVE_CHARTS_DIRECTORY / "latency_vs_context.png").exists():
                gr.Image(value=str(RESULTS_LIVE_CHARTS_DIRECTORY / "latency_vs_context.png"), label="Latency vs context")
            if (RESULTS_LIVE_CHARTS_DIRECTORY / "precision_vs_context.png").exists():
                gr.Image(value=str(RESULTS_LIVE_CHARTS_DIRECTORY / "precision_vs_context.png"), label="Verifier precision vs context")
            gr.Dataframe(
                headers=benchmark_headers,
                value=benchmark_rows,
                interactive=False,
                wrap=True,
                label="Honest precision table",
            )
            gr.Markdown("#### Full hand-check table (verbatim from `results_live/handcheck.md`)")
            gr.Markdown(handcheck_markdown)

        with gr.Tab("Live try it"):
            gr.Markdown(
                f"{live_mode_summary}\n\n"
                "Guardrails: one job at a time, max 150k token pack budget, per-IP rate limit (2/hour), "
                "and a global daily cap via environment."
            )
            live_repo_url = gr.Textbox(
                label="Public GitHub repository URL",
                placeholder="https://github.com/pallets/flask",
            )
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

        def on_finding_change(finding_choice: str) -> tuple[str, str, str, str, str, str, str, str]:
            """
            @brief Update finding detail panels when user selects a finding.
            @param finding_choice Selected finding key string.
            """

            finding: dict[str, object] | None = finding_choice_map.get(finding_choice)
            if finding is None:
                empty: FindingPanelState = FindingPanelState(
                    verifier_badge="",
                    hand_badge="",
                    upstream_badge="",
                    doc_header="No finding selected.",
                    code_header="No finding selected.",
                    doc_quote="",
                    code_quote="",
                    notes="",
                )
                return (
                    empty["verifier_badge"],
                    empty["hand_badge"],
                    empty["upstream_badge"],
                    empty["notes"],
                    empty["doc_header"],
                    empty["code_header"],
                    empty["doc_quote"],
                    empty["code_quote"],
                )
            panel: FindingPanelState = _render_finding_panel(finding)
            return (
                panel["verifier_badge"],
                panel["hand_badge"],
                panel["upstream_badge"],
                panel["notes"],
                panel["doc_header"],
                panel["code_header"],
                panel["doc_quote"],
                panel["code_quote"],
            )

        selected_finding.change(
            fn=on_finding_change,
            inputs=[selected_finding],
            outputs=[
                verifier_badge,
                hand_badge,
                upstream_badge,
                finding_notes,
                doc_header,
                code_header,
                doc_quote,
                code_quote,
            ],
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

    return demo


def launch_app(server_port: int = 43123) -> None:
    """
    @brief Launch the Gradio application with queue enabled.
    @param server_port Port to bind for local preview.
    """

    demo: gr.Blocks = build_app()
    demo.queue(default_concurrency_limit=1)
    demo.launch(server_name="0.0.0.0", server_port=server_port)


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
            return False, "live mode disabled, browse cached results (missing OLLAMA_API_KEY)."
        return True, "provider=ollama model=beam via https://ollama.com/v1."
    if selected_provider == "reflection":
        if not env_map.get("REFLECTION_API_KEY", "").strip():
            return False, "live mode disabled, browse cached results (missing REFLECTION_API_KEY)."
        return True, "provider=reflection using configured Reflection endpoint."
    return False, f"live mode disabled, browse cached results (unsupported BEAM_PROVIDER={selected_provider})."


def _load_live_index() -> LiveIndex:
    """
    @brief Load compact cached live index generated from results_live traces.
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
    )


def _build_findings_rows(findings: list[dict[str, object]]) -> list[list[object]]:
    """
    @brief Render a compact finding table for quick browsing.
    @param findings Finding records from index.json.
    """

    rows: list[list[object]] = []
    for finding in findings:
        rows.append(
            [
                finding.get("finding_key", ""),
                finding.get("repo_url", ""),
                finding.get("drift_kind", ""),
                "pass" if bool(finding.get("verifier_fully_verified", False)) else "reject",
                finding.get("hand_verdict", ""),
                finding.get("upstream_status", ""),
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
        verifier: str = "pass" if bool(finding.get("verifier_fully_verified", False)) else "reject"
        label: str = f"{finding_key} · hand={hand_verdict} · verifier={verifier}"
        choice_map[label] = finding
    return choice_map


def _render_finding_panel(finding: dict[str, object]) -> FindingPanelState:
    """
    @brief Build markdown and snippet panel content for one finding.
    @param finding Finding record.
    """

    doc_citation: dict[str, object] = _as_dict(finding.get("doc_citation"))
    code_citation: dict[str, object] = _as_dict(finding.get("code_citation"))
    verifier_badge: str = _badge_for_verifier(bool(finding.get("verifier_fully_verified", False)))
    hand_badge: str = _badge_for_hand_verdict(str(finding.get("hand_verdict", "unknown")))
    upstream_status: str = str(finding.get("upstream_status", "")).strip()
    upstream_badge: str = f"**Upstream:** {upstream_status}" if upstream_status else "**Upstream:** draft prepared, unfiled"
    doc_header: str = (
        f"**Doc citation:** `{doc_citation.get('path', '')}` "
        f"L{doc_citation.get('start_line', '')}–L{doc_citation.get('end_line', '')}"
    )
    code_header: str = (
        f"**Code citation:** `{code_citation.get('path', '')}` "
        f"L{code_citation.get('start_line', '')}–L{code_citation.get('end_line', '')}"
    )
    return FindingPanelState(
        verifier_badge=verifier_badge,
        hand_badge=hand_badge,
        upstream_badge=upstream_badge,
        doc_header=doc_header,
        code_header=code_header,
        doc_quote=str(finding.get("doc_quote", "")),
        code_quote=str(finding.get("code_quote", "")),
        notes=(
            f"**Explanation:** {finding.get('explanation', '')}\n\n"
            f"**Hand-check note:** {finding.get('hand_notes', '')}\n\n"
            f"**Verifier reasons:** doc={finding.get('verifier_doc_reason', '') or 'n/a'}, "
            f"code={finding.get('verifier_code_reason', '') or 'n/a'}"
        ),
    )


def _build_atlas_rows(runs: list[dict[str, object]], findings: list[dict[str, object]]) -> list[list[object]]:
    """
    @brief Build atlas coverage table rows from run records.
    @param runs Run records from index.json.
    """

    atlas_by_case: dict[str, tuple[int, int]] = {}
    for finding in findings:
        case_name: str = str(finding.get("case_name", ""))
        claims_total: int = _coerce_int(finding.get("atlas_claims_total"), 0)
        citations_verified: int = _coerce_int(finding.get("atlas_citations_verified"), 0)
        existing: tuple[int, int] = atlas_by_case.get(case_name, (0, 0))
        atlas_by_case[case_name] = (
            max(existing[0], citations_verified),
            max(existing[1], claims_total),
        )
    rows: list[list[object]] = []
    for run in runs:
        case_name: str = str(run.get("case_name", ""))
        atlas_verified, atlas_total = atlas_by_case.get(case_name, (0, 0))
        rows.append(
            [
                case_name,
                run.get("repo_url", ""),
                atlas_verified,
                atlas_total,
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
                f"{_coerce_float(run.get('latency_seconds', 0.0)):.2f}",
                run.get("findings_total", ""),
                run.get("findings_fully_verified", ""),
                run.get("hand_true", ""),
                run.get("hand_false", ""),
                run.get("hand_unclear", ""),
                run.get("hand_precision", ""),
            ]
        )
    return rows


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
    verifier_false_total: int = _coerce_int(summary.get("verifier_false_total_count"), 0)
    verifier_caught_false: int = _coerce_int(summary.get("verifier_caught_false_count"), 0)
    verifier_rejected_true: int = _coerce_int(summary.get("verifier_rejected_true_count"), 0)
    return (
        f"- **Live hand-checked precision:** {true_count}/{judged_count} = {precision_percent:.1f}% "
        f"(true={true_count}, false={false_count}, unclear={unclear_count})\n"
        f"- **Verifier behaviour (sweep):** caught {verifier_caught_false}/{verifier_false_total} false positives; "
        f"wrongly rejected {verifier_rejected_true} true drift.\n"
        "- **External validation:** starlette fix merged as PR #3746; "
        "httpx-mounts and arrow findings were independently confirmed by open upstream PRs."
    )


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


def _badge_for_verifier(is_verified: bool) -> str:
    """
    @brief Build a colour badge for verifier status.
    @param is_verified Whether citation verifier passed.
    """

    if is_verified:
        return "🟢 **Verifier:** pass"
    return "🔴 **Verifier:** reject"


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
