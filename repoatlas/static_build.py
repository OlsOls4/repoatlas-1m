"""Build data-driven JSON and files for the static Hugging Face Space."""

from __future__ import annotations

from datetime import UTC, datetime
import html
import json
from pathlib import Path
import re
import shutil
from typing import TypedDict

from repoatlas.ablation_view import (
    load_ablation_payload,
)
from repoatlas.beamv3_view import load_beamv3_payload
from repoatlas.hybrid_view import (
    ALREADY_REPORTED_PREFIX,
    CANONICAL_REPO_URLS,
    HYBRID_JSON_PATH,
    HYBRID_REPROS_PATH,
    HYBRID_SOURCES_PATH,
    HYBRID_TRIAGE_DIRECTORY,
    LABEL_SOURCE,
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
    already_reported_status,
    build_comparison_table,
    build_notes_markdown,
    canonicalize_repo_url,
    chunk_baseline_tokens,
    compute_hero_stats,
    docstring_pooled_text,
    end_to_end_repro_token_text,
    focused_cost_multiplier,
    focused_pass_tokens,
    headline_sentence,
    load_extra_experiment_tokens,
    load_hybrid_payload,
    merge_hybrid_true_findings,
    non_bug_badge_phrase,
    strip_local_paths,
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
    "Filed by this project. Open, not merged. Status checked 30 Oct 2026."
)
HF_SPACE_COLORS: frozenset[str] = frozenset(
    {"red", "yellow", "green", "blue", "indigo", "purple", "pink", "gray"}
)
HF_SHORT_DESCRIPTION: str = "Beam finds real docs-vs-code bugs in Python libraries"
HF_SHORT_DESCRIPTION_MAX: int = 60
DISPLAY_PREFIX: dict[str, str] = {
    "arrow": "ARW",
    "attrs": "ATR",
    "cattrs": "CAT",
    "click": "CLK",
    "httpx": "HTX",
    "jinja": "JIN",
    "marshmallow": "MM",
    "nox": "NOX",
    "pydantic-settings": "PDS",
    "starlette": "STR",
    "structlog": "STL",
    "werkzeug": "WZG",
}
PUBLIC_CODE_URL: str = "https://github.com/OlsOls4/repoatlas-1m"
PUBLIC_DATASET_URL: str = "https://huggingface.co/datasets/ollymcbride4/docdrift-bugs"
PUBLIC_THREAD_URL: str = "https://huggingface.co/reflection/Beam-1.0-501B-A23B/discussions/5"
# One-line switch once the Space is public:
OG_IMAGE_URL: str = "assets/og.png"
# OG_IMAGE_URL: str = "https://huggingface.co/spaces/ollymcbride4/docdrift/resolve/main/assets/og.png"
# OG_IMAGE_URL: str = "https://ollymcbride4-docdrift.static.hf.space/assets/og.png"
VIDEO_BASENAME: str = "docdrift-demo"
PACK_CACHE: dict[str, dict[str, list[str]]] = {}


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
        hero=_build_hero(payload, stats, bugs),
        bugs=bugs,
        benchmark=_build_benchmark(payload, stats),
        repros=_attach_repro_display_ids(_build_repros(payload, sources), bugs),
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
            (target / "index.html").write_text(
                _fill_index_html(source.read_text(encoding="utf-8"), documents["hero"], documents["copy"]),
                encoding="utf-8",
            )
        else:
            shutil.copy2(source, assets_dir / asset_name)
    for vendor_name in ("asciinema-player.min.js", "asciinema-player.css"):
        vendor = ASSETS_SOURCE_DIRECTORY / vendor_name
        if vendor.exists():
            shutil.copy2(vendor, assets_dir / vendor_name)
    cast_source = RESULTS_LIVE_DIRECTORY / "fresh_run" / "docdrift_tomlkit.cast"
    if cast_source.exists():
        shutil.copy2(cast_source, assets_dir / "docdrift_tomlkit.cast")
    for media_name in (f"{VIDEO_BASENAME}.mp4", "docdrift-poster.png", f"{VIDEO_BASENAME}.vtt"):
        media = ASSETS_SOURCE_DIRECTORY / media_name
        if media.exists():
            shutil.copy2(media, assets_dir / media_name)
    if RECALL_CHART_PATH.exists():
        shutil.copy2(RECALL_CHART_PATH, assets_dir / "recall_vs_distance.png")
    og_source: Path = ASSETS_SOURCE_DIRECTORY / "og.png"
    if og_source.exists():
        shutil.copy2(og_source, assets_dir / "og.png")
    (target / ".gitattributes").write_text("*.mp4 filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")
    (target / "README.md").write_text(_static_readme(documents["hero"], documents["copy"]), encoding="utf-8")
    return target


def _build_hero(
    payload: HybridPayload,
    stats: HybridHeroStats,
    bugs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """
    @brief Hero numbers derived from hybrid.json via compute_hero_stats.
    """

    del payload
    max_probe: int = _max_probe_tokens()
    cards = bugs or []
    true_libs = sorted(
        {
            str(bug.get("library", ""))
            for bug in cards
            if str(bug.get("verdict", "")).lower() == "true" and bug.get("library")
        }
    )
    true_n = len(true_libs)
    none_true = sorted(set(DISPLAY_PREFIX) - set(true_libs))
    none_clause = ""
    if none_true:
        none_clause = f"; {', '.join(none_true)} had none"
    return {
        "headline": headline_sentence(stats).replace(
            f"in {stats['repo_count']} Python libraries",
            f"in {true_n} of {stats['repo_count']} Python libraries",
        ),
        "lead": (
            f"DocDrift gives Beam an entire Python library (docs + code, up to ~400k tokens) in one call. "
            f"Beam checks every suspicious doc example against the whole codebase, then writes a script that runs it. "
            f"Across {stats['repo_count']} popular libraries (bugs in {true_n} of {stats['repo_count']} libraries"
            f"{none_clause}) it found "
            f"{stats['hybrid_true']} real docs bugs; {stats['repro_true']} crash exactly as the docs are written."
        ),
        "lead_short": (
            f"Beam read {stats['repo_count']} whole Python libraries and ran their docs: "
            f"{stats['hybrid_true']} real bugs, {stats['repro_true']} reproduce."
        ),
        "tiles": [
            [stats["hybrid_true"], f"real docs bugs · {true_n} of {stats['repo_count']} libraries"],
            [stats["repro_true"], "crash when you run the docs"],
            ["2", "fixes filed upstream (starlette #3746, nox #1216)"],
        ],
        "true_library_count": true_n,
        "libraries_without_true": none_true,
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
            f"Labels: {LABEL_SOURCE}, not a human. Recall is measured against the "
            f"{stats['universe_size']} drifts any method found, so it flatters the methods."
        ),
        "end_to_end_tokens_text": end_to_end_repro_token_text(stats),
        "non_bug_badges": non_bug_badge_phrase(stats),
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
            0 if row.get("badge") == "reproduced" else 1,
            str(row.get("library", "")),
            str(row.get("title", "")),
        )
    )
    _assign_display_ids(cards)
    _attach_quotes(cards)
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
        "summary": strip_local_paths(str(card.get("breakage_summary") or card.get("explanation") or "")),
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
            f"Strict repro badge on a {verdict} finding. "
            f"{non_bug_badge_phrase(stats)} received a strict badge."
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
        return "reproduced", strip_local_paths(override)
    if bool(card.get("repro_is_strict_api_error", False)):
        excerpt: str = strip_local_paths(str(card.get("repro_error_excerpt", "")).strip())
        return "reproduced", excerpt[:180]
    if str(card.get("repro_status", "")) == "reproduced":
        return "checked", f"Ran, but not a strict API error (not counted in the {stats['repro_true']})."
    return "checked", "Checked against the source (file:line evidence); no strict repro badge."


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
        if "independently confirmed" in status or ALREADY_REPORTED_PREFIX.lower() in status:
            return {
                "kind": "also_reported",
                "label": already_reported_status(url),
                "url": url,
                "note": "From results_live/upstream_status.json. Other people's PRs.",
            }
        return {
            "kind": "filed_open",
            "label": f"Open PR #{number}",
            "url": url,
            "note": "From results_live/upstream_status.json.",
        }
    status = str(card.get("upstream_status", ""))
    url = str(card.get("upstream_url", ""))
    if (ALREADY_REPORTED_PREFIX in status or "Also reported by someone else" in status) and url:
        return {
            "kind": "also_reported",
            "label": already_reported_status(url) if "PR #" not in status else status,
            "url": url,
            "note": "From results_live/upstream_status.json. Other people's PRs.",
        }
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
                    f"{non_bug_badge_phrase(stats)}"
                ),
            },
        ],
        "recall": {
            "max_probe_tokens": _max_probe_tokens(),
            "far_hits": list(far_hits),
            "chunk_far": list(chunk_far),
            "focused_tokens": focused_pass_tokens(),
            "chunk_baseline_tokens": chunk_baseline_tokens(),
            "focused_multiplier": round(focused_cost_multiplier(), 1),
            "docstring_pooled": docstring_pooled_text(),
            "chart": "assets/recall_vs_distance.png",
            "source": "results_live/recall/",
            "buckets": ["~1k", "~10k", "~50k", "~100k", "~200k", "~400k", "700k+"],
            "default_series": _recall_default_series(),
        },
        "chart_present": RECALL_CHART_PATH.exists(),
        "ablation": load_ablation_payload(),
        "beamv3": load_beamv3_payload(),
        "token_footnote": _token_footnote(stats),
        "pack_coverage": _pack_coverage(),
        "recall_extra": True,
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
        case_id = str(value.get("case_id", key))
        source_id = case_id.split(":", 1)[-1] if ":" in case_id else case_id
        rows.append(
            {
                "id": case_id,
                "library": repo,
                "source_id": source_id,
                "verdict": verdict_by_id.get(str(key), ""),
                "status": str(value.get("status", "")),
                "evidence": str(value.get("evidence") or ""),
                "exception_type": str(value.get("exception_type") or ""),
                "error_excerpt": strip_local_paths(str(value.get("error_excerpt") or "")),
                "strict_confirmed": bool(value.get("strict_confirmed", False)),
                "ref": str(sources.get(repo, {}).get("ref", ""))[:7],
            }
        )
    rows.sort(key=lambda row: (0 if row["strict_confirmed"] else 1, str(row["library"]), str(row["id"])))
    return rows


def _build_replay(stats: HybridHeroStats, index_findings: list[dict[str, object]]) -> dict[str, object]:
    """
    @brief Recorded starlette pack player: candidates, verdicts, traceback, PR.
    """

    if not STARLETTE_TRACE_PATH.exists():
        raise FileNotFoundError(STARLETTE_TRACE_PATH)
    trace: dict[str, object] = json.loads(STARLETTE_TRACE_PATH.read_text(encoding="utf-8"))
    summary: dict[str, object] = _as_dict(trace.get("summary"))
    pack: dict[str, object] = _as_dict(trace.get("pack"))
    indexed: dict[str, object] = {}
    for row in index_findings:
        if str(row.get("finding_key", "")) == "starlette-400000/DD-1":
            indexed = row
            break
    triage: dict[str, object] = {}
    if HYBRID_TRIAGE_STARLETTE_PATH.exists():
        triage = _as_dict(json.loads(HYBRID_TRIAGE_STARLETTE_PATH.read_text(encoding="utf-8")))
    candidates_raw = _as_dict_list(triage.get("candidates"))
    verdicts_raw = _as_dict_list(triage.get("verdicts"))
    verdict_by_id = {str(item.get("candidate_id", "")): item for item in verdicts_raw}
    candidates: list[dict[str, object]] = []
    for candidate in candidates_raw:
        verdict = _as_dict(verdict_by_id.get(str(candidate.get("candidate_id", "")), {}))
        code = _as_dict(verdict.get("code_citation"))
        source = str(candidate.get("source", ""))
        source_label = "symbol check" if source == "symbol" else "whole-repo pass"
        candidates.append(
            {
                "id": str(candidate.get("candidate_id", "")),
                "source": source_label,
                "claim": str(candidate.get("claim", "")),
                "doc_path": str(candidate.get("doc_path", "")),
                "doc_line": _as_int(candidate.get("doc_line")),
                "verdict": str(verdict.get("verdict", "")),
                "reason": str(verdict.get("reason", "")),
                "code_path": str(code.get("path", "")),
                "code_line": _as_int(code.get("start_line")),
            }
        )
    symbol_candidates = sum(1 for item in candidates_raw if str(item.get("source", "")) == "symbol")
    whole_candidates = sum(1 for item in candidates_raw if str(item.get("source", "")) != "symbol")
    kept = sum(1 for item in verdicts_raw if "true" in str(item.get("verdict", "")).lower())
    rejected = len(verdicts_raw) - kept
    attempts_path: Path = RESULTS_LIVE_DIRECTORY / "hybrid" / "repros" / "starlette_starlette-400000_DD-1" / "attempts.json"
    tracebacks: list[dict[str, object]] = []
    if attempts_path.exists():
        attempts_raw: object = json.loads(attempts_path.read_text(encoding="utf-8"))
        attempts = attempts_raw if isinstance(attempts_raw, list) else []
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            classification = _as_dict(attempt.get("classification"))
            origin = str(attempt.get("script_origin") or _as_dict(attempt.get("plan")).get("script_origin") or "")
            tracebacks.append(
                {
                    "attempt": _as_int(attempt.get("attempt")),
                    "status": str(classification.get("status", "")),
                    "exception_type": str(classification.get("exception_type", "")),
                    "excerpt": strip_local_paths(str(classification.get("error_excerpt", ""))),
                    "script_origin": origin,
                }
            )
    packed_at: str = str(pack.get("packed_at") or "")
    sources: dict[str, dict[str, object]] = _load_sources()
    starlette_ref: str = str(sources.get("starlette", {}).get("ref") or indexed.get("ref") or "")
    pr_url: str = str(indexed.get("upstream_url") or "https://github.com/Kludex/starlette/pull/3746")
    return {
        "is_recording": True,
        "title": "Recorded starlette pack",
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
        "candidate_count": len(candidates),
        "symbol_candidates": symbol_candidates,
        "whole_candidates": whole_candidates,
        "kept": kept,
        "rejected": rejected,
        "candidates": candidates,
        "tracebacks": [row for row in tracebacks if str(row.get("status")) == "reproduced"] or tracebacks,
        "pr": {
            "label": "Open PR #3746",
            "url": pr_url,
            "note": "Filed by this project. Open, not merged.",
        },
        "repro_note": _starlette_repro_note(tracebacks, stats),
        "drift_card": _starlette_drift_card(pack, tracebacks),
    }


def _starlette_repro_note(tracebacks: list[dict[str, object]], stats: HybridHeroStats) -> str:
    """
    @brief Player caption for the starlette strict repro.
    """

    reproduced = [row for row in tracebacks if str(row.get("status")) == "reproduced"]
    if reproduced:
        origin = str(reproduced[-1].get("script_origin") or "script written by hand from Beam's verdict")
        kind = str(reproduced[-1].get("exception_type") or "TypeError")
        origin_sentence = origin[:1].upper() + origin[1:]
        if not origin_sentence.endswith("."):
            origin_sentence += "."
        return (
            f"Strict repro: {kind} on the documented-usage "
            f"receive_json(data, mode=\"binary\") line. Counted in the {stats['repro_true']}. "
            f"{origin_sentence}"
        )
    return (
        f"Strict repro could not run (setup RuntimeError). "
        f"Not counted in the {stats['repro_true']}. An earlier docs-runner did raise TypeError."
    )


def _build_copy(stats: HybridHeroStats) -> dict[str, object]:
    """
    @brief Judge-facing copy blocks. Numeric slots come from stats, not literals in HTML.
    """

    max_probe_tokens: int = _max_probe_tokens()
    ablation = load_ablation_payload()
    return {
        "how_beam": [
            (
                "Triage filter, not a raw detector. A free AST symbol check proposes name and signature "
                f"mismatches. Beam judged {stats['judged']} candidates across 11 of 12 libraries "
                "(structlog failed; cattrs needed 2 calls). It rejected "
                f"{stats['rejected_true']} of {stats['true_candidates_judged']} true candidates and removed "
                f"{stats['removed_false']} of {stats['removed_false'] + stats['kept_false']} false or unclear ones."
            ),
            (
                f"Beam's triage kept all {stats['symbol_true']} true symbol-check drifts, "
                f"kept {stats['hybrid_true'] - stats['symbol_true'] - stats['additions_true']} extra "
                "from the whole-repo pass's own candidates, "
                f"and added {stats['additions_true']} drifts the checker missed "
                f"({stats['additions_new']} new to the union): "
                f"{stats['symbol_true']} + "
                f"{stats['hybrid_true'] - stats['symbol_true'] - stats['additions_true']} + "
                f"{stats['additions_true']} = {stats['hybrid_true']}."
            ),
            (
                f"Repro author. Beam wrote the doc-literal repro scripts ({stats['repro_tokens']:,} tokens). "
                "The starlette headline script was written by hand from Beam's verdict. "
                f"{stats['repro_true']} distinct bugs reproduce a real API error. "
                f"{stats['repro_true_findings']} of {stats['repro_findings']} badges were real. "
                f"{non_bug_badge_phrase(stats)} received a strict badge."
            ),
        ],
        "limits": [
            "The 45-drift universe is the union of method output, so it favours those methods.",
            f"Labels were {LABEL_SOURCE}. (Field name in the dataset: `hand_verdict`.)",
            "Citation check means quote alignment of cited lines vs packed source, with a ±3-line shift allowed. It is not a verdict that the drift is real.",
            "A true drift can still fail the strict repro rule (marshmallow T11, structlog untriaged, werkzeug input_stream).",
            f"{non_bug_badge_phrase(stats)} received a strict repro badge.",
            NOX_PR_NOTE,
            "httpx #3774 and arrow #1355 were already reported upstream by others.",
            "cattrs and click have drafts in the repo; they are not listed as filed.",
            *_structlog_failure_notes(),
            "This Space is a static recording; it makes no Beam calls. Run DocDrift yourself with the CLI.",
        ],
        "glossary": [
            "Triage: Beam judges symbol-check and whole-repo candidates as true_drift, false, or unclear against one packed library prompt.",
            "Strict badge: TypeError, AttributeError, ImportError, or NameError raised on a DOC-LITERAL usage line.",
            "Line-shifted match: the cited quote matched packed source within ±3 lines of the model-cited line.",
        ],
        "cli": (
            "pip install git+https://github.com/OlsOls4/repoatlas-1m\n"
            "export OLLAMA_API_KEY=YOUR_KEY\n"
            "docdrift run https://github.com/OWNER/REPO --max-tokens 400000 --out findings"
        ),
        "cli_sweep": "",
        "ollama_key": (
            "Create a free Ollama Cloud account at [ollama.com](https://ollama.com), open Settings, and create an API key. "
            "Export it as OLLAMA_API_KEY, or set OLLAMA_API_KEY_FILE to a file that contains the key. "
            "`docdrift run` packs the whole repository, sends it to Beam for triage (32k output tokens, "
            "citation verify), then runs Beam-written doc-literal scripts in an isolated venv with no network. "
            "Skip the scripts with --no-repro. Cap repro tokens with --repro-budget. Stops on HTTP 402/quota (exit 4). "
            "No key is stored in this Space or in the archive."
        ),
        "local": "",
        "links": {
            "code": PUBLIC_CODE_URL,
            "dataset": PUBLIC_DATASET_URL,
            "thread": PUBLIC_THREAD_URL,
        },
        "criteria": [
            {
                "title": "Creativity",
                "body": "Treats docs as executable claims. Beam reads the whole library, then writes a script that **runs the docs**. A bug counts only if the doc's own line crashes.",
            },
            {
                "title": "Technical execution",
                "body": (
                    f"- {stats['repo_count']} pinned libraries\n"
                    f"- a strict repro gate: {stats['repro_true']} bugs crash on the doc's own line\n"
                    f"- {stats['repro_true_findings']} of {stats['repro_findings']} badges real\n"
                    f"- ablation + stability rerun ({ablation['stability_agree']}/{ablation['stability_n']})\n"
                    "- every number traces to the dataset"
                ),
            },
            {
                "title": "Usefulness",
                "body": (
                    f"{stats['hybrid_true']} real docs bugs in libraries people use (httpx, marshmallow, werkzeug, starlette, attrs, click…). "
                    "2 PRs filed upstream (starlette #3746, nox #1216), both open. A CLI for your own repo."
                ),
            },
            {
                "title": "Beam",
                "body": (
                    "One whole-repo call per library (11 of 12; structlog failed, cattrs needed 2), "
                    f"with prompts up to {max_probe_tokens:,} tokens accepted. "
                    f"With the whole repo, Beam cited the proof in another file {ablation['outside_cite_whole']} times, "
                    f"vs {ablation['outside_cite_local']} with local files. "
                    f"Beam also wrote the repro scripts ({stats['repro_tokens']:,} tokens). "
                    + (
                        f"At the same token budget, retrieval matched verdicts "
                        f"({ablation['accuracy_frac_matched']} vs {ablation['accuracy_frac_whole']}) "
                        f"but grounded fewer cross-file cases "
                        f"({ablation['cross_file_cite_matched']} vs {ablation['cross_file_cite_whole']}; "
                        f"p = {ablation['matched_mcnemar_p']}, not shown at this n)."
                        if ablation.get("matched_available")
                        else ""
                    )
                ),
            },
        ],
        "why_caption": (
            "Long context didn't change verdicts here. It changed whether Beam could point to the proof in another file. "
            f"Cost: ~{ablation['token_multiplier']}× tokens ({ablation['whole_tokens']:,} vs {ablation['local_tokens']:,})."
        ),
        "why_matched_cost_note": ablation.get("why_matched_cost_note") or "Matched-cost local bar: not run yet.",
        "why_subset_note": ablation.get("subset_note") or "",
        "video": (
            f"assets/{VIDEO_BASENAME}.mp4" if (ASSETS_SOURCE_DIRECTORY / f"{VIDEO_BASENAME}.mp4").exists() else None
        ),
        "video_poster": (
            "assets/docdrift-poster.png" if (ASSETS_SOURCE_DIRECTORY / "docdrift-poster.png").exists() else None
        ),
        "video_captions": (
            f"assets/{VIDEO_BASENAME}.vtt" if (ASSETS_SOURCE_DIRECTORY / f"{VIDEO_BASENAME}.vtt").exists() else None
        ),
        "sample_output": _fresh_run_sample_output(),
        "sample_cast": (
            "assets/docdrift_tomlkit.cast"
            if (RESULTS_LIVE_DIRECTORY / "fresh_run" / "docdrift_tomlkit.cast").exists()
            else ""
        ),
        "sample_note": _fresh_run_sample_note(),
        "repro_caption": (
            f"Some bugs have 2 scripts (one per candidate); {stats['repro_true']} distinct bugs reproduce."
        ),
        "cross_file_note": (
            "Cross-file means the documented claim and the cited implementation are in different files "
            "(including a docs/ page vs package source). It is true when recorded doc_path and code_path differ, "
            "or when the docs live under docs/ or a .md/.rst file and no code path was cited."
        ),
        "bench_caption": (
            f"{stats['universe_size']} = all real drifts any method found. "
            f"{stats['hybrid_findings']} = what the hybrid flagged. "
            f"{stats['repro_true']} of {stats['hybrid_true']} = bugs whose doc line crashes when run."
        ),
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources_public": (
            "Every number is in the companion dataset "
            "(findings, triage verdicts, repros, ablation, token ledger)."
        ),
        "sources": [
            "results_live/hybrid/hybrid.json",
            "results_live/hybrid/hybrid.csv",
            "results_live/hybrid/repros/repros.json",
            "results_live/baselines/baselines.json",
            "results_live/recall/",
            "results_live/index.json",
            "results_live/upstream_status.json",
            "results_live/traces/starlette-400000.json (summary and pack metadata only)",
            "results_live/ablation/results.json",
            "results_live/ablation/matched_cost/results.json",
            "results_live/beamv3/results.json",
            "results_live/fresh_run/findings.json",
            "results_live/fresh_run/stdout.log",
        ],
        "exclusions": [
            "results_live/traces/*.json raw traces (only starlette-400000 summary and pack metadata are embedded in replay.json)",
            "results_live/hybrid/repros/*/attempts.json per-attempt logs",
            "results_live/hybrid/triage/*.json (read at build time, not shipped)",
            "results_live/ablation/raw/ API bodies",
            "results_live/ablation/matched_cost/raw/ API bodies",
            "results_live/beamv3/repros/*/ per-attempt logs",
            "dataset/ traces and other raw sweep artifacts",
            "raw pack traces (only starlette-400000 summary and pack metadata are embedded in replay.json)",
        ],
    }


def _token_footnote(stats: HybridHeroStats) -> str:
    """
    @brief Hybrid 9.3M plus extra experimental ledgers, generated from recorded files.
    """

    extra = load_extra_experiment_tokens()
    ablation = load_ablation_payload()
    beamv3 = load_beamv3_payload()
    return (
        f"~9.2M tokens (two whole-repo passes over 12 libraries). "
        f"{stats['whole_tokens']:,} first sweep + {stats['triage_tokens']:,} hybrid triage. "
        f"+{stats['repro_tokens']:,} for repro scripts = {stats['end_to_end_tokens']:,} end to end. "
        "Extra experimental runs, not in the 9.3M: "
        f"ablation {int(ablation.get('ablation_ledger_tokens') or 0):,}; "
        f"beam v3 {int(beamv3.get('ledger_tokens') or 0):,}; "
        f"matched-cost control {extra['matched_cost']:,}; "
        f"tomlkit CLI run {extra['fresh_run']:,}."
    )


def _fresh_run_sample_note() -> str:
    """
    @brief Honest tomlkit recording note from findings.json (verified vs arguable).
    """

    path = RESULTS_LIVE_DIRECTORY / "fresh_run" / "findings.json"
    if not path.exists():
        return ""
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return ""
    tokens = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {}
    triage = raw.get("triage") if isinstance(raw.get("triage"), dict) else {}
    findings = triage.get("additional_findings") if isinstance(triage.get("additional_findings"), list) else []
    repros = raw.get("repros") if isinstance(raw.get("repros"), list) else []
    total = int(tokens.get("total") or 0)
    wall = raw.get("wall_seconds")
    ref = str(raw.get("ref") or "")[:7]
    wall_text = f" · {wall:.0f} s" if isinstance(wall, (int, float)) else ""
    ad1 = next((row for row in findings if isinstance(row, dict) and row.get("finding_id") == "AD-1"), {})
    ad1_verified = bool(ad1.get("fully_verified")) if isinstance(ad1, dict) else False
    ad2_strict = any(
        isinstance(row, dict) and str(row.get("case_id") or "").endswith("AD-2") and row.get("strict_confirmed")
        for row in repros
    )
    if len(findings) == 2 and ad1_verified:
        return (
            f"tomlkit @ {ref} · {len(findings)} findings: a version-claim drift "
            "(citation verified; docs say TOML 1.0.0, tests accept 1.1.0) and a quickstart snippet "
            f"missing its imports (NameError, {'strict-confirmed' if ad2_strict else 'reproduced'}; "
            f"arguable as drift) · {total:,} tokens{wall_text}"
        )
    strict = sum(1 for row in repros if isinstance(row, dict) and row.get("strict_confirmed"))
    return f"tomlkit @ {ref} · {len(findings)} findings, {strict} strict-confirmed · {total:,} tokens{wall_text}"


def _fresh_run_sample_output() -> str:
    """
    @brief Terminal excerpt from the recorded tomlkit `docdrift run`.
    """

    path = RESULTS_LIVE_DIRECTORY / "fresh_run" / "stdout.log"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").rstrip() + "\n"


def _static_readme(hero: dict[str, object], copy: dict[str, object]) -> str:
    """
    @brief Hugging Face static-Space README with the same judge-facing story.
    """

    how_beam = "\n".join(f"{index}. {paragraph}" for index, paragraph in enumerate(copy["how_beam"], start=1))
    limits = "\n".join(f"- {line}" for line in copy["limits"])
    exclusions = "\n".join(f"- {line}" for line in copy["exclusions"])
    glossary = "\n".join(f"- {line}" for line in copy["glossary"])
    return f"""---
title: DocDrift
emoji: 🛰️
colorFrom: indigo
colorTo: green
sdk: static
app_file: index.html
short_description: {HF_SHORT_DESCRIPTION}
tags:
  - beam
  - long-context
  - docs
  - code
  - verification
  - static
---

# DocDrift

**DocDrift** finds docs drift (docs say one thing, code does another) in Python libraries. A free symbol check proposes candidates. Beam reads each library's docs and source (about 300–400k tokens) to triage them and add cross-file or prose drift. 11 of 12 libraries were triaged in one call; structlog failed; cattrs needed 2 calls. A generated script then runs the documented usage and keeps the ones that raise a real API error.

**Results:** {hero['hybrid_true']} real docs bugs in {hero['true_library_count']} of {hero['repo_count']} libraries; {hero['repro_true']} reproduce. Beam's triage threw away {hero['rejected_true']} of {hero['true_candidates_judged']} real bugs.

Filed upstream: [starlette #3746](https://github.com/Kludex/starlette/pull/3746) (open) and [nox #1216](https://github.com/wntrblm/nox/pull/1216) (open). httpx #3774 and arrow #1355 were already reported upstream by others.

This Space is a **static recording**; it makes no Beam calls. Code is [MIT](https://github.com/OlsOls4/repoatlas-1m/blob/main/LICENSE) (copyright 2026 Olly McBride). Dataset labels are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## What is docs drift?

Docs and code disagree in a way that can break users who follow the docs. Starlette example: `docs/websockets.md` line 74 calls `receive_json(data, mode="binary")`; `starlette/websockets.py` line 136 is `receive_json(self, mode: str = "text")`. Following the docs can raise `TypeError`.

## How Beam is used

Numbers below come from the companion dataset.

{how_beam}

## Glossary

{glossary}

## Limits

{limits}

## Run it on your repo

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


def _assign_display_ids(cards: list[dict[str, object]]) -> None:
    """
    @brief Stable ARW-01 style IDs per library. Raw id stays on the card.
    """

    counters: dict[str, int] = {}
    for card in cards:
        library = str(card.get("library", ""))
        counters[library] = counters.get(library, 0) + 1
        prefix = DISPLAY_PREFIX.get(library, library[:3].upper())
        card["display_id"] = f"{prefix}-{counters[library]:02d}"
        title = str(card.get("title") or "")
        card["short_title"] = re.sub(rf"^{re.escape(library)}:\s*", "", title, count=1)


def _attach_quotes(cards: list[dict[str, object]]) -> None:
    """
    @brief Pull doc/code lines from the recorded pack, not a live clone.
    """

    for card in cards:
        library = str(card.get("library", ""))
        card["doc_quote"] = _pack_quote(library, str(card.get("doc_path") or ""), card.get("doc_line"))
        card["code_quote"] = _pack_quote(library, str(card.get("code_path") or ""), card.get("code_line"))


def _pack_files(library: str) -> dict[str, list[str]]:
    """
    @brief Path -> packed source lines for one library's 400k trace.
    """

    if library in PACK_CACHE:
        return PACK_CACHE[library]
    path: Path = RESULTS_LIVE_DIRECTORY / "traces" / f"{library}-400000.json"
    files: dict[str, list[str]] = {}
    if path.exists():
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        pack = payload.get("pack") if isinstance(payload, dict) else {}
        for item in _as_dict_list(pack.get("files") if isinstance(pack, dict) else []):
            files[str(item.get("path", ""))] = [str(line) for line in item.get("lines") or []]
    PACK_CACHE[library] = files
    return files


def _pack_quote(library: str, path: str, line: object) -> str:
    """
    @brief Line ±1 from the packed file, or empty if that file was not packed.
    """

    if not path:
        return ""
    try:
        number = int(line) if line else 0
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        return ""
    lines = _pack_files(library).get(path) or []
    if not lines:
        return ""
    start = max(0, number - 2)
    end = min(len(lines), number + 1)
    chunk = [lines[index].rstrip() for index in range(start, end)]
    content = [item for item in chunk if item.strip() and not set(item.strip()) <= set("=-~")]
    heading_only = bool(content) and all(
        item.lstrip().startswith(":") or item.lstrip().startswith("..") for item in content
    )
    if heading_only:
        cursor = end
        while cursor < len(lines):
            text = lines[cursor].rstrip()
            cursor += 1
            if not text.strip() or set(text.strip()) <= set("=-~"):
                continue
            chunk.append(text)
            break
    return "\n".join(chunk).strip()


def _starlette_drift_card(pack: dict[str, object], tracebacks: list[dict[str, object]]) -> dict[str, object]:
    """
    @brief Hero drift card from packed starlette lines. The call is on line 74, not 73.
    """

    files: dict[str, list[str]] = {}
    for item in _as_dict_list(pack.get("files")):
        files[str(item.get("path", ""))] = [str(line) for line in item.get("lines") or []]
    doc_lines = files.get("docs/websockets.md") or []
    code_lines = files.get("starlette/websockets.py") or []
    doc_quote = doc_lines[73].strip() if len(doc_lines) >= 74 else 'websocket.receive_json(data, mode="binary")'
    code_quote = (
        code_lines[135].strip()
        if len(code_lines) >= 136
        else 'async def receive_json(self, mode: str = "text") -> Any:'
    )
    reproduced = [row for row in tracebacks if str(row.get("status")) == "reproduced"]
    error = "TypeError: WebSocket.receive_json() got multiple values for argument 'mode'"
    if reproduced:
        excerpt = str(reproduced[-1].get("excerpt") or "")
        if "TypeError" in excerpt:
            error = excerpt.splitlines()[0]
    return {
        "doc_path": "docs/websockets.md",
        "doc_line": 74,
        "doc_line_note": (
            "The whole-repo pass recorded docs/websockets.md:73, the sentence before the call. "
            "The call is on line 74 at 8aa828c. The symbol check flagged the same call."
        ),
        "doc_quote": doc_quote,
        "code_path": "starlette/websockets.py",
        "code_line": 136,
        "code_quote": code_quote,
        "error": error,
        "found_by": "Beam's whole-repo pass (also flagged by the symbol check)",
        "pr_url": "https://github.com/Kludex/starlette/pull/3746",
        "pr_label": "PR #3746 open, not merged",
        "hand_written": True,
        "hand_written_note": (
            "Repro script for this one was written by hand from Beam's verdict; the other repros were written by Beam."
        ),
    }


def _pack_coverage() -> dict[str, object]:
    """
    @brief Per-library pack size and truncation from recorded traces.
    """

    libraries = [
        "starlette",
        "httpx",
        "click",
        "structlog",
        "nox",
        "arrow",
        "cattrs",
        "marshmallow",
        "attrs",
        "jinja",
        "werkzeug",
        "pydantic-settings",
    ]
    headers = ["Library", "Files packed", "Tokens packed", "Cap", "Truncated", "Skipped (binary/undecodable)", "Last packed file"]
    rows: list[list[str]] = []
    for library in libraries:
        path = RESULTS_LIVE_DIRECTORY / "traces" / f"{library}-400000.json"
        if not path.exists():
            continue
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        pack = payload.get("pack") if isinstance(payload, dict) else {}
        if not isinstance(pack, dict):
            continue
        files = _as_dict_list(pack.get("files"))
        skipped = pack.get("skipped_paths") if isinstance(pack.get("skipped_paths"), list) else []
        last = str(files[-1].get("path", "")) if files else ""
        rows.append(
            [
                library,
                str(len(files)),
                f"{_as_int(pack.get('total_tokens')):,}",
                f"{_as_int(pack.get('token_limit')):,}",
                "yes" if pack.get("truncated") else "no",
                str(len(skipped)),
                last,
            ]
        )
    return {
        "available": bool(rows),
        "headers": headers,
        "rows": rows,
        "note": (
            "truncated: true means the packer hit the remaining-budget cutoff while files were still in the queue. "
            "skipped_paths only records binary or undecodable files, so the dropped remainder is not listed. "
            "Starlette packed 119 files (327,836 of a 400,000 token cap), including test files; "
            "the last packed file was tests/middleware/test_middleware.py."
        ),
    }


def _recall_default_series() -> list[dict[str, object]]:
    """
    @brief Three planted-drift series for the default chart: focused, whole-repo, chunked 128k.
    """

    wanted = {
        "focused_seed1": "focused whole-context",
        "whole_seed1": "whole-repo",
        "chunk128k_seed1": "chunked 128k",
    }
    columns = [
        "~1k strict",
        "~10k strict",
        "~50k strict",
        "~100k strict",
        "~200k strict",
        "~400k strict",
        "700k+ strict",
    ]
    series: list[dict[str, object]] = []
    if not RECALL_BUCKETS_PATH.exists():
        return series
    import csv

    with RECALL_BUCKETS_PATH.open("r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            run = str(row.get("run", ""))
            if run not in wanted:
                continue
            points: list[float] = []
            for column in columns:
                match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", str(row.get(column, "")))
                points.append((int(match.group(1)) / int(match.group(2))) if match and int(match.group(2)) else 0.0)
            series.append({"id": run, "label": wanted[run], "points": points})
    order = list(wanted.keys())
    series.sort(key=lambda item: order.index(str(item["id"])))
    return series


def _attach_repro_display_ids(
    repros: list[dict[str, object]],
    bugs: list[dict[str, object]],
) -> list[dict[str, object]]:
    """
    @brief Map repro rows onto ARW-01 style ids from the bug wall.
    """

    lookup: dict[str, str] = {}
    error_map: list[tuple[str, str, str]] = []
    for bug in bugs:
        display = str(bug.get("display_id") or "")
        raw = str(bug.get("id") or "")
        library = str(bug.get("library") or "")
        if not display:
            continue
        lookup[raw] = display
        lookup[raw.replace("/", ":")] = display
        lookup[f"{library}:{raw.replace('/', ':')}"] = display
        tail = raw.rsplit("/", 1)[-1]
        lookup[f"{library}:{tail}"] = display
        lookup[f"{library}/{tail}"] = display
        note = str(bug.get("badge_note") or "")
        if note:
            error_map.append((library, note, display))
    for row in repros:
        rid = str(row.get("id") or "")
        library = str(row.get("library") or "")
        display = lookup.get(rid) or lookup.get(f"{library}:{rid}") or lookup.get(rid.replace(":", "/"))
        if not display:
            excerpt = str(row.get("error_excerpt") or "")
            needle = excerpt[:40]
            if needle:
                for lib, note, mapped in error_map:
                    if lib == library and needle in note:
                        display = mapped
                        break
        row["display_id"] = display or rid
    return repros


def _fill_index_html(source: str, hero: dict[str, object], copy: dict[str, object]) -> str:
    """
    @brief Inline the recorded lead and tiles so the first paint does not swap placeholder copy.
    """

    tiles = "".join(
        f"<div class='tile'><strong>{html.escape(str(tile[0]))}</strong><span>{html.escape(str(tile[1]))}</span></div>"
        for tile in (hero.get("tiles") or [])
        if isinstance(tile, (list, tuple)) and len(tile) >= 2
    )
    links = copy.get("links") if isinstance(copy.get("links"), dict) else {}
    link_html = " · ".join(
        f'<a href="{html.escape(str(links[key]), quote=True)}">{label}</a>'
        for key, label in (("code", "Code"), ("dataset", "Dataset"), ("thread", "Thread"))
        if links.get(key)
    )
    filled = source.replace("<!--LEAD_FULL-->", html.escape(str(hero.get("lead") or "")))
    filled = filled.replace("<!--LEAD_SHORT-->", html.escape(str(hero.get("lead_short") or "")))
    filled = filled.replace("<!--TILES-->", tiles)
    filled = filled.replace("<!--HERO_NOTE-->", html.escape(str(hero.get("label_note") or "")))
    filled = filled.replace("<!--HERO_LINKS-->", link_html)
    filled = filled.replace('content="assets/og.png"', f'content="{html.escape(OG_IMAGE_URL, quote=True)}"')
    video = copy.get("video")
    if video:
        filled = filled.replace('id="demo-video" class="demo-video" hidden', 'id="demo-video" class="demo-video"')
        filled = filled.replace(
            'id="demo-video-el"',
            f'id="demo-video-el" src="{html.escape(str(video), quote=True)}"',
        )
        filled = filled.replace("<!--VIDEO_TRANSCRIPT-->", _video_transcript_html())
    else:
        filled = filled.replace("<!--VIDEO_TRANSCRIPT-->", "")
    return filled


def _structlog_failure_notes() -> list[str]:
    """
    @brief Honest structlog failure from hybrid triage JSON; skip if the file is missing.
    """

    path = HYBRID_TRIAGE_DIRECTORY / "structlog.json"
    if not path.exists():
        return []
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    error = str(raw.get("error") or "")
    prompt = int(raw.get("prompt_tokens") or 0)
    if "no JSON" not in error and "parse" not in error.lower():
        return []
    if prompt <= 0:
        return []
    return [
        f"structlog: Beam's whole-repo reply had no parseable JSON (prompt {prompt:,} tokens); not retried."
    ]


def _video_transcript_html() -> str:
    """
    @brief Collapsible transcript under the hero video, generated from the shipped WebVTT.
    """

    path = ASSETS_SOURCE_DIRECTORY / f"{VIDEO_BASENAME}.vtt"
    if not path.exists():
        return ""
    cues: list[str] = []
    pending: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped in {"WEBVTT", ""} or stripped.isdigit() or "-->" in stripped:
            if stripped == "" and pending:
                cues.append(" ".join(pending))
                pending = []
            continue
        pending.append(stripped)
    if pending:
        cues.append(" ".join(pending))
    if not cues:
        return ""
    body = "".join(f"<p>{html.escape(cue)}</p>" for cue in cues)
    return f'<details class="transcript"><summary>Transcript</summary>{body}</details>'


