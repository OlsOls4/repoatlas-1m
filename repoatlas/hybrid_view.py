"""Data-driven DocDrift v2 hybrid rendering for the Space and README-facing numbers."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import TypedDict


RESULTS_LIVE_DIRECTORY: Path = Path("results_live")
HYBRID_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "hybrid"
HYBRID_JSON_PATH: Path = HYBRID_DIRECTORY / "hybrid.json"
HYBRID_CSV_PATH: Path = HYBRID_DIRECTORY / "hybrid.csv"
HYBRID_SOURCES_PATH: Path = HYBRID_DIRECTORY / "sources.json"
HYBRID_REPROS_PATH: Path = HYBRID_DIRECTORY / "repros" / "repros.json"
HYBRID_TRIAGE_DIRECTORY: Path = HYBRID_DIRECTORY / "triage"
SYMBOL_FLAGS_PATH: Path = RESULTS_LIVE_DIRECTORY / "baselines" / "symbol_check_flags.json"
BASELINES_CSV_PATH: Path = RESULTS_LIVE_DIRECTORY / "baselines" / "baselines.csv"

WHOLE_FINDING_TO_DRIFT: dict[str, str] = {
    "starlette-400000:DD-1": "T1",
    "httpx-400000:DD-1": "T2",
    "httpx-400000:DD-2": "T3",
    "click-400000:DD-1": "T4",
    "structlog-400000:DD-2": "T5",
    "nox-400000:DD-1": "T6",
    "arrow-400000:DD-1": "T7",
    "cattrs-400000:DD-1": "T8",
    "cattrs-400000:DD-2": "T9",
    "cattrs-400000:DD-3": "T10",
    "marshmallow-400000:DD-2": "T11",
}
DRIFT_TO_WHOLE_FINDING: dict[str, str] = {value: key.replace(":", "/", 1) for key, value in WHOLE_FINDING_TO_DRIFT.items()}
CANONICAL_REPO_URLS: dict[str, str] = {
    "starlette": "https://github.com/Kludex/starlette",
}
STRICT_REPRO_EXCEPTION_TYPES: frozenset[str] = frozenset({"TypeError", "AttributeError", "ImportError", "NameError"})
LABEL_SOURCE: str = "checked against the source by an AI reviewer"
ALREADY_REPORTED_PREFIX: str = "Already reported upstream by others"
LOCAL_PATH_PATTERN: re.Pattern[str] = re.compile(
    r"(?:/workspace|/tmp|/home|/Users)[^\s)\"']+"
)
RUN_SUMMARY_PATH: Path = RESULTS_LIVE_DIRECTORY / "recall" / "run_summary.json"


class HybridPayload(TypedDict):
    """
    @brief Parsed hybrid score artifacts.
    @param available True when hybrid.json and hybrid.csv are present.
    @param rows Method rows from hybrid.json.
    @param csv_rows Method rows from hybrid.csv.
    @param universe_size Distinct-true universe size.
    @param universe Drift-id to repo map.
    @param triage_notes Per-repo triage failure notes.
    @param triage_filter_confusion Beam-vs-hand confusion counts.
    @param beam_tokens Token spend map.
    """

    available: bool
    rows: list[dict[str, object]]
    csv_rows: list[dict[str, str]]
    universe_size: int
    universe: dict[str, str]
    triage_notes: dict[str, str]
    triage_filter_confusion: dict[str, int]
    beam_tokens: dict[str, int]


class HybridHeroStats(TypedDict):
    """
    @brief Computed headline numbers for DocDrift v2.
    """

    repo_count: int
    hybrid_true: int
    hybrid_findings: int
    hybrid_true_findings: int
    hybrid_precision: float
    repro_true: int
    repro_findings: int
    repro_true_findings: int
    repro_precision: float
    universe_size: int
    judged: int
    rejected_true: int
    kept_false: int
    removed_false: int
    true_candidates_judged: int
    additions_total: int
    additions_true: int
    additions_new: int
    symbol_true: int
    whole_true: int
    whole_tokens: int
    triage_tokens: int
    repro_tokens: int
    end_to_end_tokens: int
    triage_end_to_end_tokens: int
    false_repro_badges: int
    false_repro_false: int
    false_repro_unclear: int


def load_hybrid_payload() -> HybridPayload:
    """
    @brief Load hybrid.json and hybrid.csv without touching large repro traces.
    """

    empty: HybridPayload = HybridPayload(
        available=False,
        rows=[],
        csv_rows=[],
        universe_size=0,
        universe={},
        triage_notes={},
        triage_filter_confusion={},
        beam_tokens={},
    )
    if not HYBRID_JSON_PATH.exists() or not HYBRID_CSV_PATH.exists():
        return empty
    payload: object = json.loads(HYBRID_JSON_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return empty
    with HYBRID_CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        csv_rows: list[dict[str, str]] = [dict(row) for row in csv.DictReader(handle)]
    confusion_raw: object = payload.get("triage_filter_confusion", {})
    confusion: dict[str, int] = {}
    if isinstance(confusion_raw, dict):
        confusion = {str(key): _as_int(value) for key, value in confusion_raw.items()}
    notes_raw: object = payload.get("triage_notes", {})
    notes: dict[str, str] = {}
    if isinstance(notes_raw, dict):
        notes = {str(key): str(value) for key, value in notes_raw.items()}
    tokens_raw: object = payload.get("beam_tokens", {})
    tokens: dict[str, int] = {}
    if isinstance(tokens_raw, dict):
        tokens = {str(key): _as_int(value) for key, value in tokens_raw.items()}
    universe_raw: object = payload.get("universe", {})
    universe: dict[str, str] = {}
    if isinstance(universe_raw, dict):
        universe = {str(key): str(value) for key, value in universe_raw.items()}
    rows_raw: object = payload.get("rows", [])
    rows: list[dict[str, object]] = [row for row in rows_raw if isinstance(row, dict)] if isinstance(rows_raw, list) else []
    return HybridPayload(
        available=True,
        rows=rows,
        csv_rows=csv_rows,
        universe_size=_as_int(payload.get("universe_size"), len(universe)),
        universe=universe,
        triage_notes=notes,
        triage_filter_confusion=confusion,
        beam_tokens=tokens,
    )


def compute_hero_stats(payload: HybridPayload) -> HybridHeroStats:
    """
    @brief Derive headline counts from hybrid rows.
    @param payload Loaded hybrid payload.
    """

    hybrid_row: dict[str, object] = _find_row(payload["rows"], "hybrid (symbol")
    repro_row: dict[str, object] = _find_row(payload["rows"], "repro-confirmed")
    symbol_row: dict[str, object] = _find_row(payload["rows"], "symbol check")
    whole_row: dict[str, object] = _find_row(payload["rows"], "whole-repo beam")
    if not hybrid_row:
        hybrid_row = _csv_row_as_json(_find_csv_row(payload["csv_rows"], "hybrid (symbol"))
    if not repro_row:
        repro_row = _csv_row_as_json(_find_csv_row(payload["csv_rows"], "repro-confirmed"))
    repo_names: set[str] = {repo for repo in payload["universe"].values() if repo}
    for row in payload["rows"]:
        for item in _as_dict_list(row.get("items")):
            repo_name: str = str(item.get("repo", "")).strip()
            if repo_name:
                repo_names.add(repo_name)
    if HYBRID_TRIAGE_DIRECTORY.exists():
        for path in HYBRID_TRIAGE_DIRECTORY.glob("*.json"):
            if path.name.endswith(".attempt1.json"):
                continue
            repo_names.add(path.stem)
    confusion: dict[str, int] = payload["triage_filter_confusion"]
    hybrid_items: list[dict[str, object]] = _as_dict_list(hybrid_row.get("items"))
    addition_items: list[dict[str, object]] = [item for item in hybrid_items if str(item.get("kind", "")) == "addition"]
    addition_true_ids: set[str] = {
        str(item.get("drift_id", ""))
        for item in addition_items
        if str(item.get("verdict", "")).lower() == "true" and str(item.get("drift_id", "")).startswith("N:")
    }
    false_repro_false: int = sum(
        1
        for item in hybrid_items
        if bool(item.get("strict_confirmed", False)) and str(item.get("verdict", "")).lower() == "false"
    )
    false_repro_unclear: int = sum(
        1
        for item in hybrid_items
        if bool(item.get("strict_confirmed", False)) and str(item.get("verdict", "")).lower() == "unclear"
    )
    false_repro: int = false_repro_false + false_repro_unclear
    whole_tokens: int = _as_int(whole_row.get("beam_tokens"))
    triage_tokens: int = _as_int(payload["beam_tokens"].get("triage"), _as_int(hybrid_row.get("beam_tokens")))
    repro_tokens: int = _as_int(payload["beam_tokens"].get("repro_live"))
    return HybridHeroStats(
        repo_count=len(repo_names),
        hybrid_true=_as_int(hybrid_row.get("distinct_true"), _as_int(hybrid_row.get("distinct_true_drifts"))),
        hybrid_findings=_as_int(hybrid_row.get("findings")),
        hybrid_true_findings=_as_int(hybrid_row.get("true_findings")),
        hybrid_precision=_as_float(hybrid_row.get("precision")),
        repro_true=_as_int(repro_row.get("distinct_true"), _as_int(repro_row.get("distinct_true_drifts"))),
        repro_findings=_as_int(repro_row.get("findings")),
        repro_true_findings=_as_int(repro_row.get("true_findings")),
        repro_precision=_as_float(repro_row.get("precision")),
        universe_size=payload["universe_size"],
        judged=_as_int(confusion.get("judged")),
        rejected_true=_as_int(confusion.get("beam_not_true__hand_true")),
        kept_false=_as_int(confusion.get("beam_true__hand_not_true")),
        removed_false=_as_int(confusion.get("beam_not_true__hand_not_true")),
        true_candidates_judged=_as_int(confusion.get("beam_true__hand_true")) + _as_int(confusion.get("beam_not_true__hand_true")),
        additions_total=len(addition_items),
        additions_true=sum(1 for item in addition_items if str(item.get("verdict", "")).lower() == "true"),
        additions_new=len(addition_true_ids),
        symbol_true=_as_int(symbol_row.get("distinct_true"), _as_int(symbol_row.get("distinct_true_drifts"))),
        whole_true=_as_int(whole_row.get("distinct_true"), _as_int(whole_row.get("distinct_true_drifts"))),
        whole_tokens=whole_tokens,
        triage_tokens=triage_tokens,
        repro_tokens=repro_tokens,
        end_to_end_tokens=whole_tokens + triage_tokens + repro_tokens,
        triage_end_to_end_tokens=whole_tokens + triage_tokens,
        false_repro_badges=false_repro,
        false_repro_false=false_repro_false,
        false_repro_unclear=false_repro_unclear,
    )


def headline_sentence(stats: HybridHeroStats) -> str:
    """
    @brief Build the DocDrift v2 headline from computed stats.
    @param stats Hero stats.
    """

    true_findings: int = stats["hybrid_true_findings"]
    findings: int = stats["hybrid_findings"]
    ratio_text: str = "3 in 4" if findings and abs((true_findings / findings) - 0.75) < 0.02 else f"{true_findings} of {findings}"
    return (
        f"{stats['hybrid_true']} real docs bugs in {stats['repo_count']} Python libraries. "
        f"{ratio_text} flagged findings were real ({true_findings} of {findings}); "
        f"{stats['repro_true']} bugs reproduce a real API error when you run the docs"
    )


def render_hero_html(stats: HybridHeroStats) -> str:
    """
    @brief Render the DocDrift v2 hero banner.
    @param stats Hero stats.
    """

    return (
        "<div class='repoatlas-hero'>"
        "<h2>DocDrift v2: free checker + Beam triage + executable repro</h2>"
        f"<p>{headline_sentence(stats)}.</p>"
        "<div class='repoatlas-stat-grid'>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{stats['hybrid_true']}</div>"
        f"<div class='repoatlas-stat-label'>Real docs bugs, {LABEL_SOURCE}</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{_percent(stats['hybrid_precision'])}</div>"
        f"<div class='repoatlas-stat-label'>of flagged findings were real "
        f"({stats['hybrid_true_findings']} / {stats['hybrid_findings']})</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{stats['repro_true']}</div>"
        "<div class='repoatlas-stat-label'>Reproduce an API error when you run the docs</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{stats['rejected_true']} of {stats['true_candidates_judged']}</div>"
        "<div class='repoatlas-stat-label'>Real bugs Beam's triage threw away</div></div>"
        "</div>"
        f"<p style='margin-top:10px;'>Reference set: {stats['universe_size']} true drifts "
        f"{LABEL_SOURCE}. The set is the union of what the methods found, so it favours them. "
        f"The field name is still <code>hand_verdict</code>; that label means {LABEL_SOURCE}, not a human annotator.</p>"
        "</div>"
    )


def render_pipeline_html() -> str:
    """
    @brief Render the DocDrift v2 pipeline diagram.
    """

    return (
        "<div class='repoatlas-diagram'>"
        "<div class='repoatlas-flow-row'>"
        "<div class='repoatlas-node'>Free symbol check proposes candidates</div>"
        "<div class='repoatlas-arrow'>→</div>"
        "<div class='repoatlas-node'>Beam reads docs + source (~300–400k). 11 of 12 libraries triaged in one call; structlog failed; cattrs needed 2 calls</div>"
        "<div class='repoatlas-arrow'>→</div>"
        "<div class='repoatlas-node'>Triage each candidate with citations and a suggested fix; add missed cross-file/prose drifts</div>"
        "<div class='repoatlas-arrow'>→</div>"
        "<div class='repoatlas-node'>Executable repro keeps only real API errors</div>"
        "</div>"
        "<p style='margin:10px 0 0 0;color:#475569;'>"
        "The free checker finds name and signature mismatches. Beam then triages candidates against a packed "
        "whole-repo prompt. 11 of 12 libraries were triaged; structlog's reply had no JSON so it stayed untriaged; "
        "cattrs needed two calls after attempt 1 returned empty. A later executable check keeps TypeError, "
        "AttributeError, ImportError, or NameError on a documented usage line."
        "</p>"
        "</div>"
    )


def build_comparison_table(payload: HybridPayload) -> tuple[list[str], list[list[object]]]:
    """
    @brief Build the method comparison table, including chunked baselines.
    @param payload Loaded hybrid payload.
    @return Headers and rows.
    """

    headers: list[str] = ["Method", "True drifts found", "Findings", "Precision", "Tokens"]
    rows: list[list[object]] = []
    universe_size: int = payload["universe_size"] or 0
    prior_33: int = sum(1 for drift_id in payload["universe"] if not str(drift_id).startswith("N:"))
    # The 33-drift 9-repo union excludes later jinja/werkzeug symbol trues and Beam-only N: additions.
    jinja_werkzeug_symbol: int = sum(
        1
        for drift_id, repo in payload["universe"].items()
        if str(drift_id).startswith("S") and repo in {"jinja", "werkzeug"}
    )
    union_33: int = prior_33 - jinja_werkzeug_symbol if prior_33 > jinja_werkzeug_symbol else 33
    stats: HybridHeroStats = compute_hero_stats(payload)
    for csv_row in payload["csv_rows"]:
        method: str = str(csv_row.get("method", "")).strip()
        json_row: dict[str, object] = _find_row(payload["rows"], method.split("(")[0].strip().lower())
        distinct_true: int = _as_int(csv_row.get("distinct_true_drifts"))
        of_33: int = _as_int(json_row.get("of_33_prior_9repo_union"), _as_int(csv_row.get("of_33_prior_union")))
        findings: int = _as_int(csv_row.get("findings"))
        precision: float = _as_float(csv_row.get("precision"))
        tokens: int = _as_int(csv_row.get("beam_tokens"))
        token_text: str = "0 (no model calls)" if tokens == 0 else f"{tokens:,}"
        if "hybrid (symbol" in method.lower():
            token_text = triage_only_token_text(stats)
        elif "repro-confirmed" in method.lower():
            token_text = end_to_end_repro_token_text(stats)
        found_text: str = f"{distinct_true} of {universe_size}"
        if of_33:
            found_text = f"{distinct_true} of {universe_size} ({of_33} of {union_33} on the 9-repo union)"
        rows.append([method, found_text, findings, _percent(precision), token_text])
    if BASELINES_CSV_PATH.exists():
        baseline_json_path: Path = RESULTS_LIVE_DIRECTORY / "baselines" / "baselines.json"
        baseline_rows: list[dict[str, object]] = []
        if baseline_json_path.exists():
            baseline_payload: object = json.loads(baseline_json_path.read_text(encoding="utf-8"))
            if isinstance(baseline_payload, dict):
                baseline_rows = _as_dict_list(baseline_payload.get("rows"))
        with BASELINES_CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
            for csv_row in csv.DictReader(handle):
                method = str(csv_row.get("method", "")).strip()
                if "chunked" not in method.lower():
                    continue
                json_match: dict[str, object] = {}
                for row in baseline_rows:
                    if str(row.get("method", "")).lower() == method.lower():
                        json_match = row
                        break
                of_33 = _as_int(json_match.get("true_findings"), _as_int(csv_row.get("true_recovered_of_11")))
                findings = _as_int(csv_row.get("total_findings"))
                precision = _as_float(csv_row.get("precision"))
                prompt_tokens: int = _as_int(csv_row.get("prompt_tokens"))
                completion_tokens: int = _as_int(csv_row.get("completion_tokens"))
                rows.append(
                    [
                        f"{method} (9-repo union)",
                        f"{of_33} of {union_33}",
                        findings,
                        _percent(precision),
                        f"{prompt_tokens + completion_tokens:,}",
                    ]
                )
    return headers, rows


def build_notes_markdown(payload: HybridPayload) -> str:
    """
    @brief Build honest hybrid notes from hybrid.json fields.
    @param payload Loaded hybrid payload.
    """

    stats: HybridHeroStats = compute_hero_stats(payload)
    confusion: dict[str, int] = payload["triage_filter_confusion"]
    rejected_true: int = _as_int(confusion.get("beam_not_true__hand_true"))
    kept_false: int = _as_int(confusion.get("beam_true__hand_not_true"))
    judged: int = _as_int(confusion.get("judged"))
    hybrid_row: dict[str, object] = _find_row(payload["rows"], "hybrid (symbol")
    missed: list[str] = [str(item) for item in _as_list(hybrid_row.get("missed_known"))]
    chunked_only: list[str] = [item for item in missed if item.startswith("C:")]
    lines: list[str] = [
        f"- The **{stats['universe_size']}-drift reference set** is the union of what the methods found, so it favours them. "
        f"Labels were {LABEL_SOURCE}. The stored field is still `hand_verdict`.",
        f"- Beam triage judged **{judged}** candidates and rejected **{rejected_true}** of "
        f"{stats['true_candidates_judged']} true candidates, while removing "
        f"**{stats['removed_false']}** of {stats['removed_false'] + kept_false} false or unclear ones. "
        "11 of 12 libraries were triaged; structlog failed; cattrs needed 2 calls.",
        f"- **{non_bug_badge_phrase(stats)}** received a strict repro badge. "
        "The v1 line “10 of 11 reproduce; 0 of 10 false do” is wrong for v2.",
        "- structlog: Beam's triage reply had no JSON, so its 6 candidates are shown untriaged.",
        f"- Chunked Beam alone found **{len(chunked_only)}** local docstring/prose drifts the hybrid misses.",
        "- The strict repro rule was set after the first repro run.",
        "- No prompt caching was observed on triage calls (each billed the full ~300–400k pack).",
        f"- Hybrid triage-only cost is about **9.2M** tokens "
        f"({stats['whole_tokens']:,} + {stats['triage_tokens']:,} = {stats['triage_end_to_end_tokens']:,}). "
        f"End-to-end including repro is **{stats['end_to_end_tokens']:,} (~9.3M)** "
        f"({stats['whole_tokens']:,} + {stats['triage_tokens']:,} + {stats['repro_tokens']:,}). "
        "The cheaper symbol-only-candidate variant was not run.",
        "- The local-file vs whole-repo ablation spent **1,948,469** extra tokens. That ledger is not part of the 9.3M hybrid end-to-end.",
        "- The docs-pass + 32k docstring-chunk extra pass spent **7,713,453** extra tokens. That ledger is not part of the 9.3M hybrid end-to-end.",
    ]
    return "\n".join(lines)


def build_beam_did_markdown(stats: HybridHeroStats, max_probe_tokens: int, far_hits: tuple[int, int], chunk_far: tuple[int, int]) -> str:
    """
    @brief Build the first-screen 'What Beam did' panel from computed stats.
    """

    return (
        "### What Beam did\n"
        f"- **Triage filter.** Beam judged {stats['judged']} candidates, rejected "
        f"{stats['rejected_true']} of {stats['true_candidates_judged']} true ones, and removed "
        f"{stats['removed_false']} of {stats['removed_false'] + stats['kept_false']} false or unclear ones.\n"
        f"- **New finds.** Beam's triage kept all {stats['symbol_true']} true symbol-check drifts, "
        f"kept {stats['hybrid_true'] - stats['symbol_true'] - stats['additions_true']} extra from the whole-repo pass's own candidates, "
        f"and added {stats['additions_true']} drifts the checker missed "
        f"({stats['additions_new']} new to the union): "
        f"{stats['symbol_true']} + {stats['hybrid_true'] - stats['symbol_true'] - stats['additions_true']} + "
        f"{stats['additions_true']} = {stats['hybrid_true']}.\n"
        f"- **Repro author.** Beam wrote the doc-literal repro scripts "
        f"({stats['repro_tokens']:,} tokens). The starlette headline script was written by hand from Beam's verdict. "
        f"{stats['repro_true']} distinct bugs reproduce a real API error; "
        f"{stats['repro_true_findings']} of {stats['repro_findings']} badged findings were real. "
        f"{non_bug_badge_phrase(stats)} received a strict repro badge.\n"
        f"- **Long context is grounding, not a verdict-accuracy lift.** "
        f"{_ablation_blurb()} "
        f"A separate planted-drift distance probe (seed 1 only) hit {far_hits[0]}/{far_hits[1]} plants "
        f"700k+ tokens apart vs {chunk_far[0]}/{chunk_far[1]} for chunking, at ~{focused_cost_multiplier():.1f}× tokens "
        f"({focused_pass_tokens():,} vs ~{chunk_baseline_tokens() / 1_000_000:.1f}M); "
        f"max prompt {max_probe_tokens:,}. That probe is not a triage-accuracy result."
    )


def build_long_context_markdown(stats: HybridHeroStats, max_probe_tokens: int, far_hits: tuple[int, int], chunk_far: tuple[int, int]) -> str:
    """
    @brief Measured long-context claim for the first screen and README.
    """

    return (
        "### Does long context help?\n"
        f"{_ablation_blurb()}\n\n"
        f"A free symbol checker already catches most name and signature drift "
        f"({stats['symbol_true']} of {stats['universe_size']}). "
        "Triage on the same 56 judged candidates was equally accurate with or without the whole pack; "
        "the pack is what lets Beam point at the file:line a maintainer can open.\n\n"
        f"1. **Triage filter (verdicts):** Beam threw out {stats['removed_false']} of "
        f"{stats['removed_false'] + stats['kept_false']} false flags and {stats['rejected_true']} of "
        f"{stats['true_candidates_judged']} real ones. Local-file triage matched that keep/reject split.\n"
        f"2. **New finds:** it added {stats['additions_new']} drifts nobody else found, in prose and across files.\n"
        f"3. **Planted-drift distance probe (not accuracy):** Beam accepted {max_probe_tokens:,} tokens; "
        f"focused whole-context passes found {far_hits[0]}/{far_hits[1]} plants 700k+ tokens apart on seed 1 only, "
        f"while chunked 128k/32k found {chunk_far[0]}/{chunk_far[1]}. Focused passes cost "
        f"~{focused_cost_multiplier():.1f}× tokens ({focused_pass_tokens():,} vs "
        f"~{chunk_baseline_tokens() / 1_000_000:.1f}M). Nearby docstring drift is where cheap chunks still win "
        f"(best single-call docstring score {docstring_pooled_text()}).\n"
    )


def _ablation_blurb() -> str:
    """
    @brief Late import so hybrid_view can stay importable from the ablation loader.
    """

    from repoatlas.ablation_view import ablation_long_context_blurb

    return ablation_long_context_blurb()


def merge_hybrid_true_findings(
    existing_findings: list[dict[str, object]],
    payload: HybridPayload,
) -> list[dict[str, object]]:
    """
    @brief Merge hybrid true drifts into finding cards for the bug wall.
    @param existing_findings Findings already loaded from index.json.
    @param payload Loaded hybrid payload.
    """

    existing_by_key: dict[str, dict[str, object]] = {
        str(finding.get("finding_key", "")): finding for finding in existing_findings
    }
    hybrid_row: dict[str, object] = _find_row(payload["rows"], "hybrid (symbol")
    items: list[dict[str, object]] = _as_dict_list(hybrid_row.get("items"))
    true_items: list[dict[str, object]] = [item for item in items if str(item.get("verdict", "")).lower() == "true"]
    chosen: dict[str, dict[str, object]] = {}
    for item in true_items:
        drift_id: str = str(item.get("drift_id", "")).strip() or f"{item.get('repo', '')}:{item.get('id', '')}"
        prior: dict[str, object] | None = chosen.get(drift_id)
        if prior is None or _item_rank(item) > _item_rank(prior):
            chosen[drift_id] = item

    citations: dict[str, dict[str, object]] = _load_hybrid_citations()
    sources: dict[str, dict[str, object]] = _load_hybrid_sources()
    repros: dict[str, dict[str, object]] = _load_hybrid_repros()
    merged: list[dict[str, object]] = []
    seen_existing: set[str] = set()
    for drift_id, item in chosen.items():
        whole_key: str = DRIFT_TO_WHOLE_FINDING.get(drift_id, "")
        existing: dict[str, object] | None = existing_by_key.get(whole_key) if whole_key else None
        if existing is None:
            source_id: str = str(item.get("id", "")).replace(":", "/", 1)
            if source_id in existing_by_key:
                existing = existing_by_key[source_id]
        if existing is not None:
            card: dict[str, object] = dict(existing)
            seen_existing.add(str(existing.get("finding_key", "")))
        else:
            card = _card_from_hybrid_item(item=item, drift_id=drift_id, citations=citations, sources=sources)
        _apply_hybrid_repro(card, item=item, repros=repros)
        _polish_bug_card(card, item=item, citations=citations)
        merged.append(card)

    for finding in existing_findings:
        if str(finding.get("hand_verdict", "")).lower() != "true":
            continue
        key: str = str(finding.get("finding_key", ""))
        if key and key not in seen_existing:
            leftover: dict[str, object] = dict(finding)
            _polish_bug_card(leftover, item={}, citations=citations)
            merged.append(leftover)
    return merged


def _item_rank(item: dict[str, object]) -> int:
    """
    @brief Prefer strict-confirmed items, then additions, when deduplicating.
    @param item Hybrid item.
    """

    rank: int = 0
    if bool(item.get("strict_confirmed", False)):
        rank += 4
    if str(item.get("kind", "")) == "addition":
        rank += 2
    if str(item.get("kind", "")) == "candidate":
        rank += 1
    return rank


def _card_from_hybrid_item(
    item: dict[str, object],
    drift_id: str,
    citations: dict[str, dict[str, object]],
    sources: dict[str, dict[str, object]],
) -> dict[str, object]:
    """
    @brief Build a bug-wall finding card from a hybrid-only true drift.
    @param item Hybrid item.
    @param drift_id Distinct drift identifier.
    @param citations Citation lookup keyed by repo:id.
    @param sources Repo URL/ref map.
    """

    repo: str = str(item.get("repo", ""))
    source_id: str = str(item.get("id", ""))
    lookup_key: str = f"{repo}:{source_id}"
    citation: dict[str, object] = citations.get(lookup_key, {})
    source: dict[str, object] = sources.get(repo, {})
    repo_url: str = CANONICAL_REPO_URLS.get(repo) or str(source.get("repo_url", f"https://github.com/{repo}"))
    doc_citation: dict[str, object] = _as_dict(citation.get("doc_citation"))
    code_citation: dict[str, object] = _as_dict(citation.get("code_citation"))
    doc_path: str = str(doc_citation.get("path", citation.get("doc_path", "")))
    doc_line: int = _as_int(doc_citation.get("start_line", citation.get("doc_line")))
    code_path: str = str(code_citation.get("path", citation.get("code_path", "")))
    code_line: int = _as_int(code_citation.get("start_line", citation.get("code_line")))
    if not code_path:
        parsed_path, parsed_line = _parse_code_site(str(citation.get("code_hint", "") or citation.get("claim", "")))
        code_path = parsed_path
        code_line = code_line or parsed_line
    if drift_id == "N:jinja-install_translations":
        doc_path = doc_path or "docs/extensions.rst"
        doc_line = 157
        doc_citation["end_line"] = 158
    breakage: str = _human_breakage(
        str(citation.get("explanation") or citation.get("claim") or item.get("evidence") or drift_id)
    )
    is_cross_file: bool = _is_cross_file(doc_path, code_path)
    return {
        "finding_key": f"hybrid/{repo}/{source_id}",
        "finding_id": source_id,
        "display_title": _human_title(repo, source_id, breakage, citation),
        "case_name": f"{repo}-hybrid",
        "repo_url": canonicalize_repo_url(repo_url, repo),
        "hand_verdict": "true",
        "hand_notes": breakage,
        "breakage_summary": breakage,
        "explanation": breakage,
        "drift_kind": str(citation.get("drift_kind", "")),
        "verifier_label": _citation_check_label(item),
        "finder_tag": _finder_tag(item),
        "upstream_status": "",
        "upstream_url": "",
        "upstream_prior_reported": False,
        "doc_citation": {"path": doc_path, "start_line": doc_line or "", "end_line": doc_citation.get("end_line", doc_line or "")},
        "code_citation": {"path": code_path, "start_line": code_line or "", "end_line": code_citation.get("end_line", code_line or "")},
        "doc_quote": str(doc_citation.get("quote", citation.get("doc_text", ""))),
        "code_quote": str(code_citation.get("quote", citation.get("code_hint", ""))),
        "is_cross_file": is_cross_file,
        "token_distance": None,
        "hybrid_drift_id": drift_id,
    }


def _apply_hybrid_repro(
    card: dict[str, object],
    item: dict[str, object],
    repros: dict[str, dict[str, object]],
) -> None:
    """
    @brief Attach hybrid repro badge fields onto a finding card.
    @param card Finding card to mutate.
    @param item Hybrid item.
    @param repros Repro map keyed by repo:id.
    """

    repo: str = str(item.get("repo", card.get("case_name", ""))).split("-")[0]
    source_id: str = str(item.get("id", ""))
    repro: dict[str, object] = repros.get(f"{repo}:{source_id}", {})
    status: str = str(repro.get("status") or item.get("repro_status") or "")
    evidence: str = str(repro.get("evidence") or item.get("repro_evidence") or "")
    exception_type: str = str(repro.get("exception_type", ""))
    excerpt: str = str(repro.get("error_excerpt", "")).strip()
    is_strict: bool = bool(item.get("strict_confirmed", False)) or (
        status == "reproduced"
        and evidence == "interface_error"
        and exception_type in STRICT_REPRO_EXCEPTION_TYPES
    )
    card["repro_status"] = status
    card["repro_evidence"] = evidence
    card["repro_exception_type"] = exception_type
    card["repro_error_excerpt"] = excerpt
    card["repro_is_strict_api_error"] = is_strict
    card["repro_reason"] = str(repro.get("reason", ""))
    origin: str = str(repro.get("script_origin", "")).strip()
    if origin:
        card["repro_script_origin"] = origin


def _polish_bug_card(
    card: dict[str, object],
    item: dict[str, object],
    citations: dict[str, dict[str, object]],
) -> None:
    """
    @brief Fill missing code sites, titles, provenance, and canonical URLs on a card.
    """

    repo: str = str(item.get("repo", "")).strip() or str(card.get("case_name", "")).split("-")[0]
    source_id: str = str(item.get("id", card.get("finding_id", "")))
    citation: dict[str, object] = citations.get(f"{repo}:{source_id}", {})
    doc_citation: dict[str, object] = _as_dict(card.get("doc_citation"))
    code_citation: dict[str, object] = _as_dict(card.get("code_citation"))
    if not str(code_citation.get("path", "")).strip():
        parsed_path, parsed_line = _parse_code_site(
            str(citation.get("code_hint", "") or citation.get("claim", "") or card.get("breakage_summary", ""))
        )
        if parsed_path:
            code_citation["path"] = parsed_path
            code_citation["start_line"] = parsed_line or code_citation.get("start_line", "")
            card["code_citation"] = code_citation
    if str(item.get("drift_id", card.get("hybrid_drift_id", ""))) == "N:jinja-install_translations":
        doc_citation["path"] = str(doc_citation.get("path") or "docs/extensions.rst")
        doc_citation["start_line"] = 157
        doc_citation["end_line"] = 158
        card["doc_citation"] = doc_citation
        card["doc_verified_line"] = 157
    card["repo_url"] = canonicalize_repo_url(str(card.get("repo_url", "")), repo)
    card["is_cross_file"] = _is_cross_file(str(doc_citation.get("path", "")), str(code_citation.get("path", "")))
    card["finder_tag"] = str(card.get("finder_tag") or _finder_tag(item))
    if str(card.get("verifier_label", "")).lower() in {"", "hybrid"}:
        card["verifier_label"] = _citation_check_label(item)
    breakage: str = _human_breakage(str(card.get("breakage_summary") or card.get("explanation") or ""))
    card["breakage_summary"] = breakage
    card["display_title"] = str(card.get("display_title") or _human_title(repo, source_id, breakage, citation))
    status: str = str(card.get("upstream_status", "")).strip().lower()
    if status in {"", "draft prepared, unfiled", "unfiled"}:
        card["upstream_status"] = "Not reported upstream yet"
        card["upstream_url"] = ""
    if "independently confirmed" in status or bool(card.get("upstream_prior_reported", False)):
        url: str = str(card.get("upstream_url", ""))
        pr_match = re.search(r"/pull/(\d+)", url)
        pr_number: str = pr_match.group(1) if pr_match else ""
        if pr_number:
            card["upstream_status"] = f"{ALREADY_REPORTED_PREFIX}: open PR #{pr_number}"
            card["upstream_prior_reported"] = True


def build_v2_replay_rows(payload: HybridPayload, stats: HybridHeroStats, pack_tokens: int) -> list[list[object]]:
    """
    @brief Build the Live-tab replay table using v2 pipeline steps.
    @param payload Loaded hybrid payload.
    @param stats Computed hero stats.
    @param pack_tokens Prompt tokens from the recorded starlette pack.
    """

    starlette_path: Path = HYBRID_TRIAGE_DIRECTORY / "starlette.json"
    symbol_candidates: int = 0
    kept: int = 0
    rejected: int = 0
    added: int = 0
    if starlette_path.exists():
        triage_payload: object = json.loads(starlette_path.read_text(encoding="utf-8"))
        if isinstance(triage_payload, dict):
            candidates: list[dict[str, object]] = _as_dict_list(triage_payload.get("candidates"))
            symbol_candidates = sum(1 for item in candidates if str(item.get("source", "")) == "symbol")
            verdicts: list[dict[str, object]] = _as_dict_list(triage_payload.get("verdicts"))
            kept = sum(1 for item in verdicts if "true" in str(item.get("verdict", "")).lower())
            rejected = sum(1 for item in verdicts if "true" not in str(item.get("verdict", "")).lower())
            added = len(_as_dict_list(triage_payload.get("additional_findings")))
    beam_kept: int = stats["true_candidates_judged"] - stats["rejected_true"] + stats["kept_false"]
    symbol_row: dict[str, object] = _find_row(payload["rows"], "symbol check")
    symbol_total: int = _as_int(symbol_row.get("findings"))
    return [
        [
            "Replay note",
            f"Recorded starlette pack (~{pack_tokens:,} tokens). Live scans on this Space are capped at 150k.",
        ],
        [
            "v2 steps (starlette)",
            (
                f"Symbol check: {symbol_candidates} candidates → Beam triage: kept {kept}, "
                f"rejected {rejected}, added {added} → Repro: "
                f"{'TypeError on DOC-LITERAL receive_json' if stats['repro_true'] else 'could not run'}"
            ),
        ],
        [
            "v2 steps (all libraries)",
            (
                f"Symbol check: {symbol_total} candidates → Beam triage: judged "
                f"{stats['judged']}, kept {beam_kept}, rejected {stats['judged'] - beam_kept} "
                f"({stats['rejected_true']} true), added {stats['additions_total']} → Repro: "
                f"{stats['repro_findings']} badges, {stats['repro_true']} distinct true"
            ),
        ],
    ]


def non_bug_badge_phrase(stats: HybridHeroStats) -> str:
    """
    @brief Honest wording for strict badges that are not true drifts.
    """

    return (
        f"{stats['false_repro_false']} false + {stats['false_repro_unclear']} unclear "
        "(werkzeug S38, S39 false; S41 unclear)"
    )


def triage_only_token_text(stats: HybridHeroStats) -> str:
    """
    @brief Sweep + triage cost; ~9.2M and not the repro-inclusive total.
    """

    return "~9.2M tokens (two whole-repo passes over 12 libraries)"


def end_to_end_repro_token_text(stats: HybridHeroStats) -> str:
    """
    @brief Full end-to-end including repro: 9,302,105 (~9.3M).
    """

    del stats
    return "~9.3M tokens (two whole-repo passes plus repro scripts)"


def focused_pass_tokens() -> int:
    """
    @brief Focused seed-1 token spend from results_live/recall/run_summary.json.
    """

    return _run_summary_usage("focused_seed1")


def chunk_baseline_tokens() -> int:
    """
    @brief Mean of chunked 128k/32k seed-1 usage from run_summary.json.
    """

    values = [_run_summary_usage("chunk128k_seed1"), _run_summary_usage("chunk32k_seed1")]
    values = [value for value in values if value > 0]
    if not values:
        return 0
    return int(round(sum(values) / len(values)))


def focused_cost_multiplier() -> float:
    """
    @brief Focused-pass tokens divided by the ~1M chunked baseline.
    """

    baseline = chunk_baseline_tokens()
    if baseline <= 0:
        return 0.0
    return focused_pass_tokens() / baseline


def docstring_pooled_text() -> str:
    """
    @brief Docs-last docstring hits pooled over 2 seeds (0/18 + 1/14 = 1/32).
    """

    return "1/32 pooled over 2 seeds (0/18 + 1/14)"


def strip_local_paths(text: str) -> str:
    """
    @brief Replace machine-local paths so excerpts can be published.
    """

    return LOCAL_PATH_PATTERN.sub("<local-path>", text)


def already_reported_status(url: str) -> str:
    """
    @brief Status text for other people's open PRs.
    """

    match = re.search(r"/pull/(\d+)", url)
    if not match:
        return ALREADY_REPORTED_PREFIX
    return f"{ALREADY_REPORTED_PREFIX}: open PR #{match.group(1)}"


def _run_summary_usage(run_name: str) -> int:
    """
    @brief Token usage for one recall run name.
    """

    if not RUN_SUMMARY_PATH.exists():
        return 0
    payload: object = json.loads(RUN_SUMMARY_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        rows = _as_dict_list(payload.get("rows") or payload.get("runs"))
    for row in rows:
        if str(row.get("run", "")) == run_name:
            return _as_int(row.get("usage") or row.get("prompt_tokens"))
    return 0


def canonicalize_repo_url(repo_url: str, repo_name: str = "") -> str:
    """
    @brief Rewrite known redirecting GitHub owners to the canonical URL.
    """

    if "github.com/encode/starlette" in repo_url or repo_name == "starlette":
        return CANONICAL_REPO_URLS["starlette"]
    return repo_url


def _finder_tag(item: dict[str, object]) -> str:
    """
    @brief Provenance tag for a hybrid item.
    """

    kind: str = str(item.get("kind", "")).strip().lower()
    source_id: str = str(item.get("id", ""))
    if kind == "addition":
        return "Beam (added in triage)"
    if kind == "untriaged-fallback":
        return "symbol check (untriaged)"
    if kind == "candidate" and source_id.startswith("S"):
        return "symbol check + Beam"
    if source_id.startswith("S"):
        return "symbol check + Beam"
    return "whole-repo Beam"


def _citation_check_label(item: dict[str, object]) -> str:
    """
    @brief Human citation-check label; never the word 'hybrid'.
    """

    if str(item.get("kind", "")) == "addition":
        return "Citation check: not run (Beam addition)"
    if str(item.get("id", "")).startswith("S"):
        return "Citation check: not run (found by symbol check)"
    if bool(item.get("citation_verified", False)):
        return "Citation check: verified"
    return "Citation check: from whole-repo run"


def _human_title(repo: str, source_id: str, breakage: str, citation: dict[str, object]) -> str:
    """
    @brief Build a readable card title without internal IDs.
    """

    snippet: str = breakage.strip()
    if len(snippet) > 88:
        snippet = snippet[:85].rstrip() + "…"
    if snippet:
        return f"{repo}: {snippet}"
    reference: str = str(citation.get("doc_text") or citation.get("claim") or source_id)
    return f"{repo}: {reference}"


def _human_breakage(text: str) -> str:
    """
    @brief Turn raw checker output into a short sentence.
    """

    stripped: str = text.strip()
    match = re.match(r"^(?:role|dotted|call-signature|method-call-signature|docstring-param|exception-name)(?::undefined)?:\s*`?([^`:]+)`?:?\s*(.*)$", stripped)
    if not match:
        return stripped
    reference: str = match.group(1).strip()
    detail: str = match.group(2).strip()
    if "not found" in detail or "defined nowhere" in detail:
        return f"Docs reference `{reference}`, which doesn't exist"
    if "no parameter named" in detail:
        param_match = re.search(r"no parameter named '([^']+)'", detail)
        param: str = param_match.group(1) if param_match else "this argument"
        return f"Docs pass `{param}=` to `{reference}`, which has no such parameter"
    return f"Docs mention `{reference}`: {detail}" if detail else f"Docs mention `{reference}`"


def _parse_code_site(text: str) -> tuple[str, int]:
    """
    @brief Extract a package file:line from checker detail text when present.
    """

    match = re.search(r"(?:at |def |e\.g\. )([A-Za-z0-9_./-]+\.py):(\d+)", text)
    if not match:
        match = re.search(r"([A-Za-z0-9_./-]+\.py):(\d+)", text)
    if not match:
        return "", 0
    return match.group(1), int(match.group(2))


def _is_cross_file(doc_path: str, code_path: str) -> bool:
    """
    @brief True when doc and code paths differ, including docs/ vs package.
    """

    doc: str = doc_path.strip()
    code: str = code_path.strip()
    if doc and code:
        return doc != code
    if doc.startswith("docs/") or doc.endswith((".md", ".rst")):
        return True
    return False


def _load_hybrid_citations() -> dict[str, dict[str, object]]:
    """
    @brief Load compact citation records from triage files and symbol flags.
    """

    citations: dict[str, dict[str, object]] = {}
    if SYMBOL_FLAGS_PATH.exists():
        flags_payload: object = json.loads(SYMBOL_FLAGS_PATH.read_text(encoding="utf-8"))
        flags: list[dict[str, object]] = []
        if isinstance(flags_payload, list):
            flags = [item for item in flags_payload if isinstance(item, dict)]
        elif isinstance(flags_payload, dict):
            flags = _as_dict_list(flags_payload.get("flags"))
        for index, flag in enumerate(flags):
            repo: str = str(flag.get("repo", ""))
            citations[f"{repo}:S{index}"] = {
                "doc_path": flag.get("path", ""),
                "doc_line": flag.get("line", ""),
                "doc_text": flag.get("reference", ""),
                "claim": f"{flag.get('check', '')}: {flag.get('reference', '')} — {flag.get('detail', '')}",
                "code_hint": str(flag.get("detail", "")),
            }
    if not HYBRID_TRIAGE_DIRECTORY.exists():
        return citations
    for path in sorted(HYBRID_TRIAGE_DIRECTORY.glob("*.json")):
        if path.name.endswith(".attempt1.json"):
            continue
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        repo = str(payload.get("repo", path.stem))
        for candidate in _as_dict_list(payload.get("candidates")):
            source_id: str = str(candidate.get("source_id", ""))
            citations[f"{repo}:{source_id}"] = {
                "doc_path": candidate.get("doc_path", ""),
                "doc_line": candidate.get("doc_line", ""),
                "doc_text": candidate.get("doc_text", ""),
                "claim": candidate.get("claim", ""),
                "code_hint": candidate.get("code_hint", ""),
            }
        for addition in _as_dict_list(payload.get("additional_findings")):
            finding_id: str = str(addition.get("finding_id", ""))
            citations[f"{repo}:ADD-{finding_id}"] = {
                "doc_citation": _as_dict(addition.get("doc_citation")),
                "code_citation": _as_dict(addition.get("code_citation")),
                "explanation": addition.get("explanation", ""),
                "drift_kind": addition.get("drift_kind", ""),
            }
    return citations


def _load_hybrid_sources() -> dict[str, dict[str, object]]:
    """
    @brief Load hybrid source repo URLs.
    """

    if not HYBRID_SOURCES_PATH.exists():
        return {}
    payload: object = json.loads(HYBRID_SOURCES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def _load_hybrid_repros() -> dict[str, dict[str, object]]:
    """
    @brief Load hybrid repro index only (not per-attempt logs).
    """

    if not HYBRID_REPROS_PATH.exists():
        return {}
    payload: object = json.loads(HYBRID_REPROS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def _find_row(rows: list[dict[str, object]], substring: str) -> dict[str, object]:
    """
    @brief Find a hybrid JSON row by method-name substring.
    @param rows Hybrid JSON rows.
    @param substring Case-insensitive method substring.
    """

    target: str = substring.lower()
    for row in rows:
        if target in str(row.get("method", "")).lower():
            return row
    return {}


def _find_csv_row(rows: list[dict[str, str]], substring: str) -> dict[str, str]:
    """
    @brief Find a hybrid CSV row by method-name substring.
    @param rows Hybrid CSV rows.
    @param substring Case-insensitive method substring.
    """

    target: str = substring.lower()
    for row in rows:
        if target in str(row.get("method", "")).lower():
            return row
    return {}


def _csv_row_as_json(row: dict[str, str]) -> dict[str, object]:
    """
    @brief Convert a CSV row into the JSON-row field names used by hero stats.
    @param row CSV row.
    """

    return {
        "distinct_true": _as_int(row.get("distinct_true_drifts")),
        "findings": _as_int(row.get("findings")),
        "true_findings": _as_int(row.get("true_findings")),
        "precision": _as_float(row.get("precision")),
    }


def _percent(value: float) -> str:
    """
    @brief Format a 0-1 precision as a one-decimal or whole percent.
    @param value Precision fraction.
    """

    percent: float = value * 100.0 if value <= 1.0 else value
    if abs(percent - round(percent)) < 0.05:
        return f"{round(percent):.0f}%"
    return f"{percent:.1f}%"


def _as_int(value: object, fallback: int = 0) -> int:
    """
    @brief Coerce an object to int.
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


def _as_float(value: object, fallback: float = 0.0) -> float:
    """
    @brief Coerce an object to float.
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
    @brief Coerce unknown object to dict.
    @param value Input object.
    """

    return value if isinstance(value, dict) else {}


def _as_dict_list(value: object) -> list[dict[str, object]]:
    """
    @brief Coerce unknown object to list of dicts.
    @param value Input object.
    """

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_list(value: object) -> list[object]:
    """
    @brief Coerce unknown object to list.
    @param value Input object.
    """

    return value if isinstance(value, list) else []
