"""Gradio application for browsing precomputed RepoAtlas results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import gradio as gr
import pandas as pd

from repoatlas.analyser import analyse_repository
from repoatlas.config import RepoAtlasConfig


RESULTS_DIRECTORY: Path = Path("results")
FIXTURE_PATH: Path = Path("fixtures/analysis_fixture.json")
MAX_LIVE_TOKEN_LIMIT: int = 120_000


class LoadedCase(TypedDict):
    """
    @brief In-memory representation of one precomputed case.
    @param summary Summary metrics payload.
    @param output Structured model output payload.
    @param verification_results Verification payload list.
    @param pack Packed repository payload.
    """

    summary: dict[str, object]
    output: dict[str, object]
    verification_results: list[dict[str, object]]
    pack: dict[str, object]


# Private function prototypes:
# - _load_precomputed_cases() -> dict[str, LoadedCase]
# - _render_finding_rows(case: LoadedCase) -> list[list[object]]
# - _render_atlas_rows(case: LoadedCase) -> list[list[object]]
# - _render_case_summary(case: LoadedCase) -> str
# - _run_live_analysis(repo_url: str, ref: str, provider: str, api_key: str, token_limit: int) -> tuple[str, list[list[object]]]
# - _as_dict_list(value: object) -> list[dict[str, object]]
# - _as_dict(value: object) -> dict[str, object]
# - _to_float(value: object, fallback: float = 0.0) -> float


def build_app() -> gr.Blocks:
    """
    @brief Construct the Gradio interface for precomputed and optional live views.
    """

    cases: dict[str, LoadedCase] = _load_precomputed_cases()
    case_names: list[str] = sorted(cases.keys())
    default_case_name: str = case_names[0] if case_names else ""
    benchmark_results_path: Path = RESULTS_DIRECTORY / "benchmark_results.csv"
    benchmark_df: pd.DataFrame = pd.read_csv(benchmark_results_path) if benchmark_results_path.exists() else pd.DataFrame()
    precision_chart_path: Path = RESULTS_DIRECTORY / "charts" / "precision_vs_context.png"
    latency_chart_path: Path = RESULTS_DIRECTORY / "charts" / "latency_vs_context.png"
    tokens_chart_path: Path = RESULTS_DIRECTORY / "charts" / "tokens_vs_context.png"

    with gr.Blocks(title="RepoAtlas-1M") as demo:
        gr.Markdown(
            "# RepoAtlas-1M\n"
            "Precomputed fixture-first demo for verifiable documentation drift and onboarding atlas.\n\n"
            "**Important:** findings labelled `fixture` are mock outputs for offline development and are not real benchmark claims."
        )

        selected_case = gr.Dropdown(
            choices=case_names,
            value=default_case_name,
            label="Precomputed repository result",
            interactive=True,
        )

        summary_markdown = gr.Markdown(value=_render_case_summary(cases[default_case_name]) if default_case_name else "No data.")

        with gr.Tab("DocDrift"):
            doc_table = gr.Dataframe(
                headers=[
                    "Finding ID",
                    "Drift kind",
                    "Verified",
                    "Doc citation",
                    "Code citation",
                    "Explanation",
                    "Fixture label",
                ],
                value=_render_finding_rows(cases[default_case_name]) if default_case_name else [],
                interactive=False,
                wrap=True,
            )

        with gr.Tab("Onboarding atlas"):
            atlas_table = gr.Dataframe(
                headers=["Claim ID", "Section", "Claim", "Citations", "Fixture label"],
                value=_render_atlas_rows(cases[default_case_name]) if default_case_name else [],
                interactive=False,
                wrap=True,
            )

        with gr.Tab("Benchmark"):
            gr.Markdown("Precomputed benchmark metrics (fixture mode by default).")
            gr.Dataframe(value=benchmark_df, interactive=False)
            if precision_chart_path.exists():
                gr.Image(value=str(precision_chart_path), label="Precision vs context size")
            if latency_chart_path.exists():
                gr.Image(value=str(latency_chart_path), label="Latency vs context size")
            if tokens_chart_path.exists():
                gr.Image(value=str(tokens_chart_path), label="Latency/tokens vs context size")

        with gr.Tab("Optional live run (BYOK, small repos only)"):
            gr.Markdown(
                "Live calls are **off by default**. Provide your own key for a one-off run only.\n"
                f"Hard token-limit cap for live runs in the app: {MAX_LIVE_TOKEN_LIMIT}."
            )
            live_repo_url = gr.Textbox(label="GitHub repository URL", placeholder="https://github.com/pallets/flask")
            live_ref = gr.Textbox(label="Reference", value="main")
            live_provider = gr.Dropdown(choices=["ollama", "reflection"], value="ollama", label="Provider")
            live_api_key = gr.Textbox(label="Temporary API key", type="password")
            live_token_limit = gr.Slider(
                minimum=10_000,
                maximum=MAX_LIVE_TOKEN_LIMIT,
                step=10_000,
                value=80_000,
                label="Token limit",
            )
            live_button = gr.Button("Run live analysis")
            live_status = gr.Markdown()
            live_findings = gr.Dataframe(
                headers=["Finding ID", "Drift kind", "Verified", "Doc citation", "Code citation", "Explanation"],
                interactive=False,
                wrap=True,
            )

        def on_case_change(case_name: str) -> tuple[str, list[list[object]], list[list[object]]]:
            """
            @brief Update UI tables when a precomputed case is selected.
            @param case_name Selected case identifier.
            """

            case = cases[case_name]
            return _render_case_summary(case), _render_finding_rows(case), _render_atlas_rows(case)

        selected_case.change(
            fn=on_case_change,
            inputs=[selected_case],
            outputs=[summary_markdown, doc_table, atlas_table],
        )

        live_button.click(
            fn=_run_live_analysis,
            inputs=[live_repo_url, live_ref, live_provider, live_api_key, live_token_limit],
            outputs=[live_status, live_findings],
        )

    return demo


def launch_app(server_port: int = 43123) -> None:
    """
    @brief Launch the Gradio application with queue enabled.
    @param server_port Port to bind for local preview.
    """

    app = build_app()
    app.queue(default_concurrency_limit=1)
    app.launch(server_name="0.0.0.0", server_port=server_port)


def _load_precomputed_cases() -> dict[str, LoadedCase]:
    """
    @brief Load precomputed traces from the results directory.
    """

    traces_directory: Path = RESULTS_DIRECTORY / "traces"
    loaded: dict[str, LoadedCase] = {}
    if not traces_directory.exists():
        return loaded
    for trace_path in sorted(traces_directory.glob("*.json")):
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
        payload_dict: dict[str, object] = payload if isinstance(payload, dict) else {}
        loaded[trace_path.stem] = LoadedCase(
            summary=_as_dict(payload_dict.get("summary")),
            output=_as_dict(payload_dict.get("output")),
            verification_results=_as_dict_list(payload_dict.get("verification_results")),
            pack=_as_dict(payload_dict.get("pack")),
        )
    return loaded


def _render_finding_rows(case: LoadedCase) -> list[list[object]]:
    """
    @brief Render table rows for DocDrift findings.
    @param case One loaded case payload.
    """

    rows: list[list[object]] = []
    findings: list[dict[str, object]] = _as_dict_list(case["output"].get("findings"))
    verifications: list[dict[str, object]] = case["verification_results"]
    verification_map: dict[str, dict[str, object]] = {
        str(item.get("finding_id", "")): item for item in verifications
    }
    for finding in findings:
        finding_id: str = str(finding.get("finding_id", ""))
        doc_citation: dict[str, object] = _as_dict(finding.get("doc_citation"))
        code_citation: dict[str, object] = _as_dict(finding.get("code_citation"))
        verification = verification_map.get(finding_id, {})
        doc_label: str = f"{doc_citation.get('path', '')}:{doc_citation.get('start_line', '')}-{doc_citation.get('end_line', '')}"
        code_label: str = (
            f"{code_citation.get('path', '')}:{code_citation.get('start_line', '')}-{code_citation.get('end_line', '')}"
        )
        rows.append(
            [
                finding_id,
                finding.get("drift_kind", ""),
                "✅" if verification.get("fully_verified", False) else "❌",
                doc_label,
                code_label,
                finding.get("explanation", ""),
                finding.get("fixture_label", ""),
            ]
        )
    return rows


def _render_atlas_rows(case: LoadedCase) -> list[list[object]]:
    """
    @brief Render table rows for atlas claims.
    @param case One loaded case payload.
    """

    rows: list[list[object]] = []
    claims: list[dict[str, object]] = _as_dict_list(case["output"].get("atlas_claims"))
    for claim in claims:
        citations: list[dict[str, object]] = _as_dict_list(claim.get("citations"))
        citation_text: str = "; ".join(
            [
                f"{item.get('path', '')}:{item.get('start_line', '')}-{item.get('end_line', '')}"
                for item in citations
            ]
        )
        rows.append(
            [
                claim.get("claim_id", ""),
                claim.get("section", ""),
                claim.get("text", ""),
                citation_text,
                claim.get("fixture_label", ""),
            ]
        )
    return rows


def _render_case_summary(case: LoadedCase) -> str:
    """
    @brief Build summary markdown for one case.
    @param case One loaded case payload.
    """

    summary: dict[str, object] = case["summary"]
    lines: list[str] = [
        f"**Repo:** `{summary.get('repo_url', '')}` ({summary.get('ref', '')})",
        f"**Context tokens:** {summary.get('context_tokens', 0)}",
        f"**Findings:** {summary.get('findings_fully_verified', 0)} verified / {summary.get('findings_total', 0)} total",
        f"**Fixture run:** {summary.get('fixture_run', True)}",
        f"**Latency:** {_to_float(summary.get('latency_seconds', 0.0)):.2f}s",
    ]
    return "\n".join(lines)


def _run_live_analysis(
    repo_url: str,
    ref: str,
    provider: str,
    api_key: str,
    token_limit: int,
) -> tuple[str, list[list[object]]]:
    """
    @brief Run a constrained live analysis for small repositories using BYOK.
    @param repo_url Public GitHub repository URL.
    @param ref Branch, tag, or commit to analyse.
    @param provider Provider identifier.
    @param api_key User-supplied temporary API key.
    @param token_limit Requested token limit for this run.
    """

    if not repo_url.startswith("https://github.com/"):
        return "Live run rejected: only public GitHub URLs are allowed.", []
    bounded_limit: int = min(int(token_limit), MAX_LIVE_TOKEN_LIMIT)
    if not api_key.strip():
        return "Live run rejected: provide a temporary API key.", []
    config = RepoAtlasConfig.from_environment(provider=provider, token_limit=bounded_limit)
    config.api_key = api_key.strip()
    try:
        bundle = analyse_repository(
            repo_url=repo_url.strip(),
            ref=ref.strip() or "main",
            config=config,
            fixture_path=FIXTURE_PATH,
            run_probes=False,
        )
    except Exception as exc:
        return f"Live run failed: `{exc}`", []
    rows: list[list[object]] = []
    for finding, verification in zip(bundle.output.findings, bundle.verification_results):
        rows.append(
            [
                finding.finding_id,
                finding.drift_kind,
                "✅" if verification.fully_verified else "❌",
                f"{finding.doc_citation.path}:{finding.doc_citation.start_line}-{finding.doc_citation.end_line}",
                f"{finding.code_citation.path}:{finding.code_citation.start_line}-{finding.code_citation.end_line}",
                finding.explanation,
            ]
        )
    status: str = (
        f"Live run complete. Model `{bundle.output.model}`; findings {bundle.summary.findings_total}; "
        f"verified {bundle.summary.findings_fully_verified}; latency {bundle.summary.latency_seconds:.2f}s."
    )
    return status, rows


def _as_dict_list(value: object) -> list[dict[str, object]]:
    """
    @brief Convert an unknown object into a list of dictionaries.
    @param value Unknown object value.
    """

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_dict(value: object) -> dict[str, object]:
    """
    @brief Convert an unknown object into a dictionary.
    @param value Unknown object value.
    """

    if isinstance(value, dict):
        return value
    return {}


def _to_float(value: object, fallback: float = 0.0) -> float:
    """
    @brief Convert an object to float with fallback.
    @param value Input value.
    @param fallback Fallback float when conversion fails.
    """

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return fallback
    return fallback
