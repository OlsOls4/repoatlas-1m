"""Data-driven DocDrift v2 hybrid rendering for the Space and README-facing numbers."""

from __future__ import annotations

import csv
import json
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
    @param repo_count Distinct libraries in the hybrid universe.
    @param hybrid_true Distinct true drifts recovered by hybrid triage.
    @param hybrid_findings Hybrid finding count.
    @param hybrid_true_findings Hybrid true-finding count.
    @param hybrid_precision Hybrid precision (0-1).
    @param repro_true Distinct true drifts confirmed by strict repro.
    @param repro_findings Strict-repro finding count.
    @param repro_true_findings Strict-repro true-finding count.
    @param repro_precision Strict-repro precision (0-1).
    @param universe_size Hand-checked true-drift universe size.
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
    )


def headline_sentence(stats: HybridHeroStats) -> str:
    """
    @brief Build the DocDrift v2 headline from computed stats.
    @param stats Hero stats.
    """

    return (
        f"{stats['hybrid_true']} real docs bugs across {stats['repo_count']} Python libraries "
        f"at {_percent(stats['hybrid_precision'])} precision; "
        f"{stats['repro_true']} confirmed by running the docs ({_percent(stats['repro_precision'])} precision)"
    )


def render_hero_html(stats: HybridHeroStats) -> str:
    """
    @brief Render the DocDrift v2 hero banner.
    @param stats Hero stats.
    """

    return (
        "<div class='repoatlas-hero'>"
        "<h2>DocDrift v2: symbol check + whole-repo Beam triage + executable repro</h2>"
        f"<p>{headline_sentence(stats)}.</p>"
        "<div class='repoatlas-stat-grid'>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{stats['hybrid_true']}</div>"
        "<div class='repoatlas-stat-label'>Hand-checked true docs bugs</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{stats['repo_count']}</div>"
        "<div class='repoatlas-stat-label'>Python libraries in this run</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{_percent(stats['hybrid_precision'])}</div>"
        "<div class='repoatlas-stat-label'>Hybrid precision (true findings / findings)</div></div>"
        f"<div class='repoatlas-stat-tile'><div class='repoatlas-stat-value'>{stats['repro_true']}</div>"
        f"<div class='repoatlas-stat-label'>Confirmed by running the docs ({_percent(stats['repro_precision'])})</div></div>"
        "</div>"
        f"<p style='margin-top:10px;'>Reference set: {stats['universe_size']} hand-checked true drifts "
        "(union of what the methods found).</p>"
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
        "<div class='repoatlas-node'>Beam reads docs + source (~300–400k tokens) in one call per library</div>"
        "<div class='repoatlas-arrow'>→</div>"
        "<div class='repoatlas-node'>Triage each candidate with citations and a suggested fix; add missed cross-file/prose drifts</div>"
        "<div class='repoatlas-arrow'>→</div>"
        "<div class='repoatlas-node'>Executable repro keeps only real API errors</div>"
        "</div>"
        "<p style='margin:10px 0 0 0;color:#475569;'>"
        "The free checker finds name and signature mismatches. Beam's one-call whole-repo pass is the triage "
        "and the place it can add cross-file or prose drift the script missed. A later executable check then "
        "confirms the ones that raise TypeError, AttributeError, ImportError, or NameError."
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
    for csv_row in payload["csv_rows"]:
        method: str = str(csv_row.get("method", "")).strip()
        distinct_true: int = _as_int(csv_row.get("distinct_true_drifts"))
        findings: int = _as_int(csv_row.get("findings"))
        precision: float = _as_float(csv_row.get("precision"))
        tokens: int = _as_int(csv_row.get("beam_tokens"))
        token_text: str = "0 (no model calls)" if tokens == 0 else f"{tokens:,}"
        rows.append(
            [
                method,
                f"{distinct_true} of {universe_size}",
                findings,
                _percent(precision),
                token_text,
            ]
        )
    if BASELINES_CSV_PATH.exists():
        with BASELINES_CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
            for csv_row in csv.DictReader(handle):
                method = str(csv_row.get("method", "")).strip()
                if "chunked" not in method.lower():
                    continue
                recovered: int = _as_int(csv_row.get("true_recovered_of_11"))
                findings = _as_int(csv_row.get("total_findings"))
                precision = _as_float(csv_row.get("precision"))
                prompt_tokens: int = _as_int(csv_row.get("prompt_tokens"))
                completion_tokens: int = _as_int(csv_row.get("completion_tokens"))
                rows.append(
                    [
                        f"{method} (9-repo baseline)",
                        f"{recovered} of 11 known",
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
    structlog_note: str = payload["triage_notes"].get("structlog", "")
    lines: list[str] = [
        f"- The **{stats['universe_size']}-drift reference set** is the union of what the methods found, so it favours methods that contributed to it.",
        f"- Beam triage judged **{judged}** candidates and rejected **{rejected_true}** hand-true candidates, while keeping **{kept_false}** false or unclear ones.",
    ]
    if structlog_note:
        lines.append(f"- **structlog triage failed:** {structlog_note}.")
    lines.extend(
        [
            f"- Chunked Beam alone found **{len(chunked_only)}** local docstring/prose drifts the hybrid misses: "
            + ", ".join(chunked_only)
            + ".",
            "- The strict repro rule (TypeError/AttributeError/ImportError/NameError on doc-literal lines) was set after the first repro run.",
            "- No prompt caching was observed on triage calls (each billed the full ~300–400k pack).",
        ]
    )
    return "\n".join(lines)


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
        merged.append(card)

    for finding in existing_findings:
        if str(finding.get("hand_verdict", "")).lower() != "true":
            continue
        key: str = str(finding.get("finding_key", ""))
        if key and key not in seen_existing:
            merged.append(finding)
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
    breakage: str = str(citation.get("claim") or citation.get("explanation") or item.get("evidence") or drift_id)
    is_cross_file: bool = bool(doc_path and code_path and doc_path != code_path)
    return {
        "finding_key": f"hybrid/{repo}/{source_id}",
        "finding_id": source_id,
        "case_name": f"{repo}-hybrid",
        "repo_url": repo_url,
        "hand_verdict": "true",
        "hand_notes": breakage,
        "breakage_summary": breakage,
        "explanation": breakage,
        "drift_kind": str(citation.get("drift_kind", "hybrid")),
        "verifier_label": "hybrid",
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
