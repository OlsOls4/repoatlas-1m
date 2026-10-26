"""Build data-driven JSON and files for the static Hugging Face Space."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
from typing import TypedDict

from repoatlas.hybrid_view import (
    CANONICAL_REPO_URLS,
    HYBRID_JSON_PATH,
    HYBRID_REPROS_PATH,
    HYBRID_SOURCES_PATH,
    HYBRID_TRIAGE_DIRECTORY,
    RESULTS_LIVE_DIRECTORY,
    HybridHeroStats,
    HybridPayload,
    _as_dict,
    _as_dict_list,
    _as_int,
    _human_breakage,
    _human_title,
    _load_hybrid_citations,
    _parse_code_site,
    build_comparison_table,
    build_notes_markdown,
    canonicalize_repo_url,
    compute_hero_stats,
    headline_sentence,
    load_hybrid_payload,
    merge_hybrid_true_findings,
)


ROOT: Path = Path(__file__).resolve().parents[1]
ASSETS_SOURCE_DIRECTORY: Path = Path(__file__).resolve().parent / "static_assets"
STATIC_SPACE_DIRECTORY: Path = ROOT / "static_space"
UPSTREAM_STATUS_PATH: Path = RESULTS_LIVE_DIRECTORY / "upstream_status.json"
INDEX_PATH: Path = RESULTS_LIVE_DIRECTORY / "index.json"
STARLETTE_TRACE_PATH: Path = RESULTS_LIVE_DIRECTORY / "traces" / "starlette-400000.json"
RECALL_CHART_PATH: Path = RESULTS_LIVE_DIRECTORY / "recall" / "recall_vs_distance.png"
RECALL_CONTEXT_PROBE_PATH: Path = RESULTS_LIVE_DIRECTORY / "recall" / "context_probe.json"
RECALL_BUCKETS_PATH: Path = RESULTS_LIVE_DIRECTORY / "recall" / "recall_by_bucket.csv"
HYBRID_TRIAGE_STARLETTE_PATH: Path = RESULTS_LIVE_DIRECTORY / "hybrid" / "triage" / "starlette.json"
NEVER_FILED_REPOS: frozenset[str] = frozenset({"cattrs", "click"})
NOX_PR_URL: str = "https://github.com/wntrblm/nox/pull/1216"
NOX_PR_NOTE: str = (
    "Open PR #1216 was confirmed on GitHub after results_live/upstream_status.json "
    "was written (that file only lists starlette #3746, httpx #3774, and arrow #1355)."
)


class StaticPayload(TypedDict):
    """
    @brief JSON documents written into static_space/data.
    """

    hero: dict[str, object]
    bugs: list[dict[str, object]]
    benchmark: dict[str, object]
    repros: list[dict[str, object]]
    replay: dict[str, object]
    copy: dict[str, object]


def build_static_payload() -> StaticPayload:
    """
    @brief Assemble every static-site document from recorded results files.
    """

    payload: HybridPayload = load_hybrid_payload()
    if not payload["available"]:
        raise FileNotFoundError("results_live/hybrid/hybrid.json is required to build the static Space")
    stats: HybridHeroStats = compute_hero_stats(payload)
    sources: dict[str, dict[str, object]] = _load_sources()
    index_findings: list[dict[str, object]] = _load_index_findings()
    upstream: list[dict[str, object]] = _load_upstream_status()
    citations: dict[str, dict[str, object]] = _load_hybrid_citations()
    verdict_sites: dict[str, dict[str, object]] = _load_triage_verdict_sites()
    bugs: list[dict[str, object]] = _build_bug_cards(
        payload=payload,
        stats=stats,
        sources=sources,
        index_findings=index_findings,
        upstream=upstream,
        citations=citations,
        verdict_sites=verdict_sites,
    )
    return StaticPayload(
        hero=_build_hero(payload, stats),
        bugs=bugs,
        benchmark=_build_benchmark(payload, stats),
        repros=_build_repros(payload, sources),
        replay=_build_replay(stats, index_findings),
        copy=_build_copy(stats),
    )


def write_static_space(destination: Path | None = None) -> Path:
    """
    @brief Write the static Space directory from recorded results.
    @param destination Output directory; defaults to static_space/.
    """

    target: Path = destination or STATIC_SPACE_DIRECTORY
    if target.exists():
        shutil.rmtree(target)
    data_dir: Path = target / "data"
    assets_dir: Path = target / "assets"
    data_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    documents: StaticPayload = build_static_payload()
    for name in ("hero", "bugs", "benchmark", "repros", "replay", "copy"):
        (data_dir / f"{name}.json").write_text(
            json.dumps(documents[name], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    for asset_name in ("index.html", "app.css", "app.js"):
        source: Path = ASSETS_SOURCE_DIRECTORY / asset_name
        if not source.exists():
            raise FileNotFoundError(f"missing static asset {source}")
        if asset_name == "index.html":
            shutil.copy2(source, target / "index.html")
        else:
            shutil.copy2(source, assets_dir / asset_name)
    if RECALL_CHART_PATH.exists():
        shutil.copy2(RECALL_CHART_PATH, assets_dir / "recall_vs_distance.png")
    (target / "README.md").write_text(_static_readme(documents["hero"], documents["copy"]), encoding="utf-8")
    return target


def _build_hero(payload: HybridPayload, stats: HybridHeroStats) -> dict[str, object]:
    """
    @brief Hero numbers derived from hybrid.json via compute_hero_stats.
    """

    max_probe: int = _max_probe_tokens()
    return {
        "headline": headline_sentence(stats),
        "hybrid_true": stats["hybrid_true"],
        "repo_count": stats["repo_count"],
        "hybrid_findings": stats["hybrid_findings"],
        "hybrid_true_findings": stats["hybrid_true_findings"],
        "hybrid_precision": stats["hybrid_precision"],
        "repro_true": stats["repro_true"],
        "repro_findings": stats["repro_findings"],
        "repro_true_findings": stats["repro_true_findings"],
        "repro_precision": stats["repro_precision"],
        "rejected_true": stats["rejected_true"],
        "true_candidates_judged": stats["true_candidates_judged"],
        "removed_false": stats["removed_false"],
        "kept_false": stats["kept_false"],
        "universe_size": stats["universe_size"],
        "symbol_true": stats["symbol_true"],
        "whole_true": stats["whole_true"],
        "additions_total": stats["additions_total"],
        "additions_true": stats["additions_true"],
        "additions_new": stats["additions_new"],
        "false_repro_badges": stats["false_repro_badges"],
        "whole_tokens": stats["whole_tokens"],
        "triage_tokens": stats["triage_tokens"],
        "repro_tokens": stats["repro_tokens"],
        "end_to_end_tokens": stats["end_to_end_tokens"],
        "judged": stats["judged"],
        "max_probe_tokens": max_probe,
        "label_note": (
            "Labels were made by an AI reviewer checking file:line evidence, not by a human. "
            f"The {stats['universe_size']}-drift set is the union of what the methods found, so it favours them."
        ),
    }


def _build_bug_cards(
    payload: HybridPayload,
    stats: HybridHeroStats,
    sources: dict[str, dict[str, object]],
    index_findings: list[dict[str, object]],
    upstream: list[dict[str, object]],
    citations: dict[str, dict[str, object]],
    verdict_sites: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """
    @brief Finding cards for the bug wall, including false repro-badged items.
    """

    existing: list[dict[str, object]] = list(index_findings)
    merged: list[dict[str, object]] = merge_hybrid_true_findings(existing, payload)
    cards: list[dict[str, object]] = []
    seen: set[str] = set()
    for card in merged:
        rendered = _card_from_merged(card, sources=sources, upstream=upstream, stats=stats)
        key = str(rendered.get("id", ""))
        if key and key not in seen:
            seen.add(key)
            cards.append(rendered)
    hybrid_row: dict[str, object] = {}
    for row in payload["rows"]:
        if "hybrid (symbol" in str(row.get("method", "")).lower():
            hybrid_row = row
            break
    for item in _as_dict_list(hybrid_row.get("items")):
        if str(item.get("verdict", "")).lower() == "true":
            continue
        rendered = _card_from_hybrid_item(
            item,
            sources=sources,
            upstream=upstream,
            stats=stats,
            citations=citations,
            verdict_sites=verdict_sites,
        )
        key = str(rendered.get("id", ""))
        if key and key not in seen:
            seen.add(key)
            cards.append(rendered)
    cards.sort(
        key=lambda row: (
            0 if row.get("verdict") == "true" else 1,
            0 if row.get("badge") == "reproduced" else 1,
            str(row.get("library", "")),
            str(row.get("title", "")),
        )
    )
    return cards


def _card_from_merged(
    card: dict[str, object],
    sources: dict[str, dict[str, object]],
    upstream: list[dict[str, object]],
    stats: HybridHeroStats,
) -> dict[str, object]:
    """
    @brief Convert a polished hybrid/index card into the static bug-wall shape.
    """

    repo: str = str(card.get("case_name", "")).split("-")[0] or str(card.get("repo", ""))
    if str(card.get("finding_key", "")).startswith("hybrid/"):
        parts = str(card.get("finding_key", "")).split("/")
        if len(parts) >= 2:
            repo = parts[1]
    source: dict[str, object] = sources.get(repo, {})
    repo_url: str = canonicalize_repo_url(str(card.get("repo_url") or source.get("repo_url") or ""), repo)
    ref: str = str(source.get("ref") or card.get("ref") or "")
    doc = _as_dict(card.get("doc_citation"))
    code = _as_dict(card.get("code_citation"))
    doc_line = _preferred_doc_line(card, doc)
    code_line = _as_int(code.get("start_line"))
    finding_key = str(card.get("finding_key") or f"{repo}/{card.get('finding_id', '')}")
    badge, badge_note = _badge_for_card(card, stats)
    title = str(card.get("display_title") or _human_title(repo, str(card.get("finding_id", "")), str(card.get("breakage_summary", "")), {}))
    return {
        "id": finding_key,
        "library": repo,
        "title": title,
        "summary": str(card.get("breakage_summary") or card.get("explanation") or ""),
        "verdict": "true",
        "badge": badge,
        "badge_note": badge_note,
        "finder": str(card.get("finder_tag") or ""),
        "doc_path": str(doc.get("path", "")),
        "doc_line": doc_line,
        "doc_url": _permalink(repo_url, ref, str(doc.get("path", "")), doc_line) or str(card.get("doc_permalink", "")),
        "code_path": str(code.get("path", "")),
        "code_line": code_line or None,
        "code_url": _permalink(repo_url, ref, str(code.get("path", "")), code_line) or str(card.get("code_permalink", "")),
        "repo_url": repo_url,
        "ref": ref[:7] if _looks_like_sha(ref) else ref,
        "upstream": _upstream_for(repo, finding_key, card, upstream),
        "cross_file": bool(card.get("is_cross_file", False)),
    }


def _card_from_hybrid_item(
    item: dict[str, object],
    sources: dict[str, dict[str, object]],
    upstream: list[dict[str, object]],
    stats: HybridHeroStats,
    citations: dict[str, dict[str, object]],
    verdict_sites: dict[str, dict[str, object]],
) -> dict[str, object]:
    """
    @brief Convert a non-true hybrid item (for the false badge) into a card.
    """

    repo: str = str(item.get("repo", ""))
    source_id: str = str(item.get("id", ""))
    source: dict[str, object] = sources.get(repo, {})
    repo_url: str = canonicalize_repo_url(str(source.get("repo_url", "")), repo)
    ref: str = str(source.get("ref", ""))
    lookup: str = f"{repo}:{source_id}"
    citation: dict[str, object] = citations.get(lookup, {})
    site: dict[str, object] = verdict_sites.get(lookup, {})
    doc_path: str = str(citation.get("doc_path") or site.get("doc_path") or "")
    doc_line: int = _as_int(citation.get("doc_line") or site.get("doc_line"))
    code_path: str = str(site.get("code_path") or "")
    code_line: int = _as_int(site.get("code_line"))
    if not code_path:
        parsed_path, parsed_line = _parse_code_site(str(citation.get("code_hint", "") or citation.get("claim", "")))
        code_path = parsed_path
        code_line = code_line or parsed_line
    evidence_raw: str = str(
        item.get("recheck")
        or item.get("evidence")
        or site.get("reason")
        or citation.get("claim")
        or item.get("repro_evidence")
        or source_id
    )
    if not doc_path:
        evidence_doc = re.search(r"([\w./-]+\.(?:rst|md|py)):(\d+)", evidence_raw)
        if evidence_doc:
            doc_path = evidence_doc.group(1)
            doc_line = doc_line or int(evidence_doc.group(2))
    evidence: str = _human_breakage(evidence_raw)
    verdict: str = str(item.get("verdict", "false")).lower() or "false"
    badge = "false"
    badge_note = ""
    if bool(item.get("strict_confirmed", False)):
        badge_note = (
            f"Strict repro badge on a {verdict} finding "
            f"({stats['false_repro_badges']} such badges: werkzeug S38, S39, S41)."
        )
    return {
        "id": f"{repo}/{source_id}",
        "library": repo,
        "title": _human_title(repo, source_id, evidence, citation),
        "summary": evidence,
        "verdict": verdict,
        "badge": badge,
        "badge_note": badge_note,
        "finder": "symbol check + Beam" if source_id.startswith("S") else "whole-repo Beam",
        "doc_path": doc_path,
        "doc_line": doc_line or None,
        "doc_url": _permalink(repo_url, ref, doc_path, doc_line or None),
        "code_path": code_path,
        "code_line": code_line or None,
        "code_url": _permalink(repo_url, ref, code_path, code_line or None),
        "repo_url": repo_url,
        "ref": ref[:7] if _looks_like_sha(ref) else ref,
        "upstream": None,
        "cross_file": bool(doc_path and code_path and doc_path != code_path),
    }


def _badge_for_card(card: dict[str, object], stats: HybridHeroStats) -> tuple[str, str]:
    """
    @brief Map a true finding onto reproduced / checked.
    """

    override: str = str(card.get("repro_badge_override", "")).strip()
    if override:
        return "reproduced", override
    if bool(card.get("repro_is_strict_api_error", False)):
        excerpt: str = str(card.get("repro_error_excerpt", "")).strip()
        return "reproduced", excerpt[:180]
    if str(card.get("repro_status", "")) == "reproduced":
        return "checked", "Ran, but not a strict API error (not counted in the 29)."
    return "checked", "Checked against the source (file:line evidence); no strict v2 repro badge."


def _upstream_for(
    repo: str,
    finding_key: str,
    card: dict[str, object],
    upstream: list[dict[str, object]],
) -> dict[str, object] | None:
    """
    @brief Filed/open or also-reported status. Never marks cattrs or click as filed.
    """

    if repo in NEVER_FILED_REPOS:
        return None
    if finding_key in {"nox-400000/DD-1", "nox-400000:DD-1"} or finding_key.endswith("nox-400000/DD-1"):
        return {
            "kind": "filed_open",
            "label": "Open PR #1216",
            "url": NOX_PR_URL,
            "note": NOX_PR_NOTE,
        }
    for row in upstream:
        if str(row.get("finding", "")) != finding_key and not finding_key.endswith(str(row.get("finding", ""))):
            continue
        url: str = str(row.get("url", ""))
        pr_match = re.search(r"/pull/(\d+)", url)
        if not pr_match:
            continue
        number: str = pr_match.group(1)
        status: str = str(row.get("status", "")).lower()
        if "independently confirmed" in status:
            return {
                "kind": "also_reported",
                "label": f"Also reported by someone else: open PR #{number}",
                "url": url,
                "note": "From results_live/upstream_status.json.",
            }
        return {
            "kind": "filed_open",
            "label": f"Open PR #{number}",
            "url": url,
            "note": "From results_live/upstream_status.json.",
        }
    status = str(card.get("upstream_status", ""))
    url = str(card.get("upstream_url", ""))
    if "Also reported by someone else" in status and url:
        return {"kind": "also_reported", "label": status, "url": url, "note": "From results_live/upstream_status.json."}
    if "PR #" in status and "open" in status.lower() and url:
        return {"kind": "filed_open", "label": status, "url": url, "note": "From results_live/upstream_status.json."}
    return None


def _build_benchmark(payload: HybridPayload, stats: HybridHeroStats) -> dict[str, object]:
    """
    @brief Comparison table, recall highlights, and hybrid funnel from artifacts.
    """

    headers, rows = build_comparison_table(payload)
    far_hits, chunk_far = _recall_far_hits()
    return {
        "headers": headers,
        "rows": rows,
        "notes_markdown": build_notes_markdown(payload),
        "funnel": [
            {"step": "Symbol check", "true": stats["symbol_true"], "detail": "0 Beam tokens"},
            {
                "step": "Beam triage",
                "true": stats["hybrid_true"],
                "detail": (
                    f"rejected {stats['rejected_true']} of {stats['true_candidates_judged']} true; "
                    f"removed {stats['removed_false']} of {stats['removed_false'] + stats['kept_false']} false/unclear"
                ),
            },
            {
                "step": "Strict repro",
                "true": stats["repro_true"],
                "detail": (
                    f"{stats['repro_true_findings']} of {stats['repro_findings']} badges were real; "
                    f"{stats['false_repro_badges']} false badges (werkzeug S38, S39, S41)"
                ),
            },
        ],
        "recall": {
            "max_probe_tokens": _max_probe_tokens(),
            "far_hits": list(far_hits),
            "chunk_far": list(chunk_far),
            "chart": "assets/recall_vs_distance.png",
            "source": "results_live/recall/",
        },
        "chart_present": RECALL_CHART_PATH.exists(),
    }


def _build_repros(payload: HybridPayload, sources: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    """
    @brief Compact repro rows from hybrid/repros/repros.json plus hybrid verdicts.
    """

    if not HYBRID_REPROS_PATH.exists():
        return []
    raw: object = json.loads(HYBRID_REPROS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    verdict_by_id: dict[str, str] = {}
    for row in payload["rows"]:
        if "hybrid (symbol" not in str(row.get("method", "")).lower():
            continue
        for item in _as_dict_list(row.get("items")):
            verdict_by_id[f"{item.get('repo')}:{item.get('id')}"] = str(item.get("verdict", ""))
    rows: list[dict[str, object]] = []
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        repo: str = str(value.get("repo", key.split(":")[0]))
        rows.append(
            {
                "id": str(value.get("case_id", key)),
                "library": repo,
                "verdict": verdict_by_id.get(str(key), ""),
                "status": str(value.get("status", "")),
                "evidence": str(value.get("evidence") or ""),
                "exception_type": str(value.get("exception_type") or ""),
                "error_excerpt": str(value.get("error_excerpt") or ""),
                "strict_confirmed": bool(value.get("strict_confirmed", False)),
                "ref": str(sources.get(repo, {}).get("ref", ""))[:7],
            }
        )
    rows.sort(key=lambda row: (0 if row["strict_confirmed"] else 1, str(row["library"]), str(row["id"])))
    return rows


def _build_replay(stats: HybridHeroStats, index_findings: list[dict[str, object]]) -> dict[str, object]:
    """
    @brief Compact recorded starlette trace plus later v2 triage steps.
    """

    if not STARLETTE_TRACE_PATH.exists():
        raise FileNotFoundError(STARLETTE_TRACE_PATH)
    trace: dict[str, object] = json.loads(STARLETTE_TRACE_PATH.read_text(encoding="utf-8"))
    summary: dict[str, object] = _as_dict(trace.get("summary"))
    pack: dict[str, object] = _as_dict(trace.get("pack"))
    output: dict[str, object] = _as_dict(trace.get("output"))
    findings: list[dict[str, object]] = _as_dict_list(output.get("findings"))
    finding: dict[str, object] = findings[0] if findings else {}
    doc = _as_dict(finding.get("doc_citation"))
    code = _as_dict(finding.get("code_citation"))
    indexed: dict[str, object] = {}
    for row in index_findings:
        if str(row.get("finding_key", "")) == "starlette-400000/DD-1":
            indexed = row
            break
    symbol_candidates = 0
    kept = 0
    rejected = 0
    added = 0
    if HYBRID_TRIAGE_STARLETTE_PATH.exists():
        triage: dict[str, object] = _as_dict(json.loads(HYBRID_TRIAGE_STARLETTE_PATH.read_text(encoding="utf-8")))
        candidates = _as_dict_list(triage.get("candidates"))
        symbol_candidates = sum(1 for item in candidates if str(item.get("source", "")) == "symbol")
        verdicts = _as_dict_list(triage.get("verdicts"))
        kept = sum(1 for item in verdicts if "true" in str(item.get("verdict", "")).lower())
        rejected = len(verdicts) - kept
        added = len(_as_dict_list(triage.get("additional_findings")))
    packed_at: str = str(pack.get("packed_at") or "")
    sources: dict[str, dict[str, object]] = _load_sources()
    starlette_ref: str = str(sources.get("starlette", {}).get("ref") or indexed.get("ref") or "")
    verifier_label: str = str(indexed.get("verifier_label") or "")
    model_line: int = _as_int(indexed.get("doc_model_line") or doc.get("start_line"))
    verified_line: int = _as_int(indexed.get("doc_verified_line"))
    if verifier_label and model_line and verified_line:
        citation_detail = (
            f"{verifier_label}; model cited L{model_line}, verifier matched L{verified_line}."
        )
    elif verifier_label:
        citation_detail = verifier_label
    else:
        citation_detail = "Citation check not recorded on this finding."
    return {
        "is_recording": True,
        "title": "Recorded live run: starlette",
        "recorded_at": packed_at,
        "repo_url": CANONICAL_REPO_URLS["starlette"],
        "source_repo_url": str(summary.get("repo_url", "")),
        "ref": starlette_ref[:7] if _looks_like_sha(starlette_ref) else starlette_ref,
        "pack_tokens": _as_int(pack.get("total_tokens")),
        "prompt_tokens": _as_int(summary.get("input_tokens")),
        "completion_tokens": _as_int(summary.get("output_tokens")),
        "latency_seconds": float(summary.get("latency_seconds") or 0.0),
        "truncated": bool(pack.get("truncated", False)),
        "token_limit": _as_int(pack.get("token_limit")),
        "trace_path": "results_live/traces/starlette-400000.json",
        "steps": [
            {
                "name": "Pack",
                "detail": (
                    f"Packed { _as_int(pack.get('total_tokens')):,} tokens "
                    f"(limit { _as_int(pack.get('token_limit')):,}, truncated={bool(pack.get('truncated'))}) "
                    f"at {packed_at}."
                ),
            },
            {
                "name": "Beam call",
                "detail": (
                    f"{_as_int(summary.get('input_tokens')):,} prompt tokens, "
                    f"{_as_int(summary.get('output_tokens')):,} completion tokens, "
                    f"{float(summary.get('latency_seconds') or 0.0):.2f}s."
                ),
            },
            {
                "name": "Finding",
                "detail": (
                    f"{finding.get('finding_id', 'DD-1')}: {finding.get('explanation', '')} "
                    f"Doc {doc.get('path', '')}:{doc.get('start_line', '')}; "
                    f"code {code.get('path', '')}:{code.get('start_line', '')}."
                ),
            },
            {
                "name": "Citation check",
                "detail": citation_detail,
            },
            {
                "name": "Later v2 steps",
                "detail": (
                    f"Symbol check: {symbol_candidates} candidates → Beam triage: kept {kept}, "
                    f"rejected {rejected}, added {added} → Repro: could not run "
                    f"(earlier docs-runner only; not counted in the {stats['repro_true']})."
                ),
            },
        ],
    }


def _build_copy(stats: HybridHeroStats) -> dict[str, object]:
    """
    @brief Judge-facing copy blocks. Numeric slots come from stats, not literals in HTML.
    """

    return {
        "how_beam": [
            (
                "Triage filter, not a raw detector. A free AST symbol check proposes name and signature "
                f"mismatches. Beam reads each library's docs and source in one packed prompt and judged "
                f"{stats['judged']} candidates. It rejected {stats['rejected_true']} of "
                f"{stats['true_candidates_judged']} true candidates and removed {stats['removed_false']} of "
                f"{stats['removed_false'] + stats['kept_false']} false or unclear ones."
            ),
            (
                f"New finds. Beam added {stats['additions_true']} true drifts the checker missed "
                f"({stats['additions_new']} new to the union), taking distinct trues from "
                f"{stats['symbol_true']} to {stats['hybrid_true']}."
            ),
            (
                f"Repro author. Beam wrote every doc-literal repro script ({stats['repro_tokens']:,} tokens). "
                f"{stats['repro_true']} distinct bugs reproduce a real API error. "
                f"{stats['repro_true_findings']} of {stats['repro_findings']} badges were real. "
                f"{stats['false_repro_badges']} badges landed on non-bugs (werkzeug S38, S39, S41)."
            ),
            (
                f"Long context, measured. Beam accepted prompts up to {_max_probe_tokens():,} tokens. "
                "Focused whole-context passes caught far-apart planted drifts that chunking missed. "
                "A single whole-prompt call alone is not a better detector than chunking or a symbol check, "
                "which is why v2 combines them."
            ),
        ],
        "limits": [
            "The 45-drift universe is the union of method output, so it favours those methods.",
            "Labels were made by an AI reviewer checking file:line evidence, not by a human annotator.",
            "Citation pass/fail is quote alignment, not correctness.",
            "A true drift can still fail the strict repro rule (starlette T1, marshmallow T11, structlog untriaged, werkzeug input_stream).",
            "Three false findings received a repro badge (werkzeug S38, S39, S41).",
            NOX_PR_NOTE,
            "cattrs and click have drafts in the repo; they are not listed as filed.",
            "This page is a static recording. Hugging Face now requires PRO to host Gradio on free CPU Basic. The Gradio app in app.py is unchanged if a grant arrives.",
        ],
        "cli": (
            "BEAM_PROVIDER=ollama OLLAMA_API_KEY=YOUR_KEY python3 scripts/run_benchmark.py "
            "--repos-file benchmarks/repos_sweep_2026-10-26.yaml "
            "--repos httpx,click,attrs,pydantic-settings,structlog,jinja,nox,arrow,cattrs,marshmallow,werkzeug "
            "--token-limits 400000 --output-dir results_live"
        ),
        "ollama_key": (
            "Create a free Ollama Cloud account at https://ollama.com, open Settings, and create an API key. "
            "Export it as OLLAMA_API_KEY. No key is stored in this Space or in the archive."
        ),
        "local": (
            "python3 -m pip install -r requirements-dev.txt && "
            "python3 scripts/build_results_live_index.py && python3 -m pytest -q && python3 app.py"
        ),
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [
            "results_live/hybrid/hybrid.json",
            "results_live/hybrid/hybrid.csv",
            "results_live/hybrid/repros/repros.json",
            "results_live/baselines/baselines.json",
            "results_live/recall/",
            "results_live/index.json",
            "results_live/upstream_status.json",
            "results_live/traces/starlette-400000.json (summary and pack metadata only)",
        ],
        "exclusions": [
            "results_live/traces/*.json raw traces (only starlette-400000 summary and pack metadata are embedded in replay.json)",
            "results_live/hybrid/repros/*/attempts.json per-attempt logs",
            "results_live/hybrid/triage/*.json (read at build time, not shipped)",
            "dataset/ traces and other raw sweep artifacts",
            "Gradio app.py runtime, caches, and virtualenvs",
        ],
    }


def _static_readme(hero: dict[str, object], copy: dict[str, object]) -> str:
    """
    @brief Hugging Face static-Space README with the same judge-facing story.
    """

    how_beam = "\n".join(f"{index}. {paragraph}" for index, paragraph in enumerate(copy["how_beam"], start=1))
    limits = "\n".join(f"- {line}" for line in copy["limits"])
    exclusions = "\n".join(f"- {line}" for line in copy["exclusions"])
    return f"""---
title: RepoAtlas-1M
emoji: 🛰️
colorFrom: indigo
colorTo: emerald
sdk: static
app_file: index.html
short_description: DocDrift v2 — recorded docs-drift bugs, Beam triage, and executable repros.
tags:
  - beam
  - long-context
  - docs
  - code
  - verification
  - static
---

# RepoAtlas-1M

**DocDrift v2** finds docs drift (docs say one thing, code does another) in Python libraries. A free symbol check proposes candidates. Beam reads each library's docs and source (about 300–400k tokens) in one call to triage them and add cross-file or prose drift. A generated script then runs the documented usage and keeps the ones that raise a real API error.

**Results:** {hero['headline']}. Beam's triage threw away {hero['rejected_true']} of {hero['true_candidates_judged']} real bugs.

This Space is **static** because Hugging Face now requires a PRO subscription to host Gradio or Docker Spaces on free CPU Basic. The Gradio app (`app.py`) is still in the repository and unchanged in behaviour if a hosting grant arrives.

## What is docs drift?

Docs and code disagree in a way that can break users who follow the docs. Starlette example: `docs/websockets.md` line 74 calls `receive_json(data, mode="binary")`; `starlette/websockets.py` line 136 is `receive_json(self, mode: str = "text")`. Following the docs can raise `TypeError`.

## How Beam is used

Numbers below come from `results_live/hybrid/hybrid.json`, `results_live/hybrid/repros/repros.json`, and `results_live/recall/`.

{how_beam}

## Limits

{limits}

## Run it yourself

```bash
{copy['local']}
```

Live sweep (needs your own key; none is embedded here):

```bash
{copy['cli']}
```

{copy['ollama_key']}

## Exclusions

This static folder does not include:

{exclusions}
"""


def _preferred_doc_line(card: dict[str, object], doc: dict[str, object]) -> int | None:
    """
    @brief Prefer the verifier-matched line when the model was off by a few lines.
    """

    verified: int = _as_int(card.get("doc_verified_line"))
    if verified:
        return verified
    start: int = _as_int(doc.get("start_line"))
    return start or None


def _permalink(repo_url: str, ref: str, path: str, line: int | None) -> str:
    """
    @brief GitHub blob URL at the pinned commit, or empty if a piece is missing.
    """

    if not repo_url or not path:
        return ""
    short_ref: str = ref[:7] if _looks_like_sha(ref) else (ref or "HEAD")
    if line:
        return f"{repo_url.rstrip('/')}/blob/{short_ref}/{path}#L{line}"
    return f"{repo_url.rstrip('/')}/blob/{short_ref}/{path}"


def _looks_like_sha(value: str) -> bool:
    """
    @brief True when value looks like a hex git object name.
    """

    return bool(re.fullmatch(r"[0-9a-f]{7,40}", value))


def _load_sources() -> dict[str, dict[str, object]]:
    """
    @brief Repo URL and ref map from hybrid/sources.json.
    """

    if not HYBRID_SOURCES_PATH.exists():
        return {}
    payload: object = json.loads(HYBRID_SOURCES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def _load_index_findings() -> list[dict[str, object]]:
    """
    @brief Finding rows from results_live/index.json.
    """

    if not INDEX_PATH.exists():
        return []
    payload: object = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    return _as_dict_list(payload.get("findings"))


def _load_triage_verdict_sites() -> dict[str, dict[str, object]]:
    """
    @brief Doc/code sites from triage verdicts, keyed by repo:source_id.
    """

    sites: dict[str, dict[str, object]] = {}
    if not HYBRID_TRIAGE_DIRECTORY.exists():
        return sites
    for path in sorted(HYBRID_TRIAGE_DIRECTORY.glob("*.json")):
        if path.name.endswith(".attempt1.json"):
            continue
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        repo: str = str(payload.get("repo", path.stem))
        candidates: dict[str, dict[str, object]] = {}
        for candidate in _as_dict_list(payload.get("candidates")):
            source_id: str = str(candidate.get("source_id", ""))
            if source_id:
                candidates[str(candidate.get("candidate_id", ""))] = candidate
                candidates[source_id] = candidate
        for verdict in _as_dict_list(payload.get("verdicts")):
            source_id = str(verdict.get("source_id", ""))
            candidate = candidates.get(str(verdict.get("candidate_id", "")), {})
            if not source_id:
                source_id = str(candidate.get("source_id", ""))
            if not source_id:
                continue
            code = _as_dict(verdict.get("code_citation"))
            sites[f"{repo}:{source_id}"] = {
                "doc_path": candidate.get("doc_path", ""),
                "doc_line": candidate.get("doc_line", ""),
                "code_path": code.get("path", ""),
                "code_line": code.get("start_line", ""),
                "reason": verdict.get("reason", ""),
            }
    return sites


def _load_upstream_status() -> list[dict[str, object]]:
    """
    @brief Recorded upstream PR rows.
    """

    if not UPSTREAM_STATUS_PATH.exists():
        return []
    payload: object = json.loads(UPSTREAM_STATUS_PATH.read_text(encoding="utf-8"))
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _max_probe_tokens() -> int:
    """
    @brief Largest accepted prompt_tokens in results_live/recall/context_probe.json.
    """

    if not RECALL_CONTEXT_PROBE_PATH.exists():
        return 0
    payload: object = json.loads(RECALL_CONTEXT_PROBE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return 0
    maximum: int = 0
    for row in payload:
        if isinstance(row, dict):
            usage = row.get("usage")
            if isinstance(usage, dict):
                maximum = max(maximum, _as_int(usage.get("prompt_tokens")))
    return maximum


def _recall_far_hits() -> tuple[tuple[int, int], tuple[int, int]]:
    """
    @brief 700k+ strict fractions for focused vs chunked 128k from recall_by_bucket.csv.
    """

    if not RECALL_BUCKETS_PATH.exists():
        return (0, 0), (0, 0)
    focused = (0, 0)
    chunked = (0, 0)
    with RECALL_BUCKETS_PATH.open("r", encoding="utf-8") as handle:
        import csv

        for row in csv.DictReader(handle):
            run = str(row.get("run", ""))
            fraction = str(row.get("700k+ strict", ""))
            match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", fraction)
            if not match:
                continue
            pair = (int(match.group(1)), int(match.group(2)))
            if run == "focused_seed1":
                focused = pair
            elif run == "chunk128k_seed1":
                chunked = pair
    return focused, chunked
