"""Load the recorded docs-pass + py32k beam v3 experiment from results.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from repoatlas.hybrid_view import LABEL_SOURCE, RESULTS_LIVE_DIRECTORY


BEAMV3_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "beamv3" / "results.json"
BEAMV3_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "beamv3" / "beam_usage_ledger.json"

SECTION_TITLE: str = "Catching what one whole-repo call misses"
RECIPE: str = (
    "Recommended: symbol check + whole-repo Beam triage, plus 32k docstring chunks "
    "if you want more coverage at lower precision."
)
CLAIM: str = (
    "32k docstring chunks recovered more of the drifts one whole-repo call missed; "
    "the extra findings are low-precision, and most are still unlabelled."
)


class BeamV3Payload(TypedDict):
    """
    @brief Parsed beam v3 metrics used by the Benchmark tab, README, and dataset card.
    """

    available: bool
    title: str
    claim: str
    recipe: str
    headers: list[str]
    rows: list[list[str]]
    caveats: list[str]
    recovered: int
    missed: int
    py32k_extra_of_45: int
    docs_extra_of_45: int
    still_missed: list[str]
    union_of_45: int
    hybrid_of_45: int
    new_ai_verified: int
    py32k_precision_lb: str
    py32k_precision_labelled: str
    py32k_marginal: int
    docs_marginal: int
    stability_agree: int
    stability_n: int
    ledger_tokens: int
    ledger_calls: int


def load_beamv3_payload(path: Path | None = None) -> BeamV3Payload:
    """
    @brief Read results_live/beamv3/results.json into display rows. No live calls.
    """

    target: Path = path or BEAMV3_RESULTS_PATH
    empty: BeamV3Payload = {
        "available": False,
        "title": SECTION_TITLE,
        "claim": CLAIM,
        "recipe": RECIPE,
        "headers": [],
        "rows": [],
        "caveats": [],
        "recovered": 0,
        "missed": 11,
        "py32k_extra_of_45": 0,
        "docs_extra_of_45": 0,
        "still_missed": [],
        "union_of_45": 0,
        "hybrid_of_45": 0,
        "new_ai_verified": 0,
        "py32k_precision_lb": "",
        "py32k_precision_labelled": "",
        "py32k_marginal": 0,
        "docs_marginal": 0,
        "stability_agree": 0,
        "stability_n": 0,
        "ledger_tokens": 0,
        "ledger_calls": 0,
    }
    if not target.exists():
        return empty
    raw: object = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return empty
    rows_raw = raw.get("rows") if isinstance(raw.get("rows"), list) else []
    by_mode: dict[str, dict[str, object]] = {}
    for item in rows_raw:
        if isinstance(item, dict) and item.get("mode"):
            by_mode[str(item["mode"])] = item
    hybrid = by_mode.get("Hybrid (existing, for reference)", {})
    docs_new = by_mode.get("Hybrid + (a): new items only", {})
    py_new = by_mode.get("Hybrid + (b): new items only", {})
    both_new = by_mode.get("Hybrid + (a) + (b): new items only", {})
    missed_map = raw.get("hybrid_missed_11") if isinstance(raw.get("hybrid_missed_11"), dict) else {}
    still_missed = sorted(
        name for name, info in missed_map.items() if isinstance(info, dict) and not info.get("recovered")
    )
    ledger = raw.get("ledger") if isinstance(raw.get("ledger"), dict) else {}
    stability = raw.get("stability") if isinstance(raw.get("stability"), dict) else {}
    py_extra = _as_list(py_new.get("extra_of_45_vs_hybrid"))
    docs_extra = _as_list(docs_new.get("extra_of_45_vs_hybrid"))
    new_ai = _as_list(both_new.get("distinct_new_ai_verified"))
    hybrid_of_45 = int(hybrid.get("distinct_of_45") or 0)
    union_of_45 = int(both_new.get("distinct_of_45") or 0)
    recovered = int(raw.get("recovered") or 0)
    ledger_tokens = int(ledger.get("total_tokens") or 0)
    ledger_calls = int(ledger.get("calls") or 0)
    stab_agree = int(stability.get("agree") or 0)
    stab_n = int(stability.get("candidates") or 0)
    py_lb = _fmt_pct(py_new.get("precision_lower_bound"))
    py_lab = _fmt_pct(py_new.get("precision_among_labelled"))
    py_marg = int(py_new.get("marginal_tokens_per_extra_drift") or 0)
    docs_marg = int(docs_new.get("marginal_tokens_per_extra_drift") or 0)
    headers = [
        "mode",
        "findings",
        "true",
        "false",
        "unclear",
        "unlabelled",
        "precision LB",
        "among labelled",
        "of 45",
        "extra of 45 vs hybrid",
        "new (AI)",
        "tokens",
        "tokens / distinct true",
        "marginal tokens / extra drift",
    ]
    keys = (
        "mode",
        "findings",
        "true",
        "false",
        "unclear",
        "unlabelled",
        "precision_lower_bound",
        "precision_among_labelled",
        "distinct_of_45",
        "extra_of_45_vs_hybrid",
        "distinct_new_ai_verified",
        "tokens",
        "tokens_per_distinct_true",
        "marginal_tokens_per_extra_drift",
    )
    table_rows = [[_fmt_cell(item.get(key) if isinstance(item, dict) else None) for key in keys] for item in rows_raw]
    for row in table_rows:
        if row and str(row[0]).startswith("Hybrid (existing") and len(row) > 11:
            row[11] = f"{row[11]} (triage pass only)"
    claim = (
        f"32k docstring chunks recovered {len(py_extra)} of the 11 drifts hybrid missed; "
        f"the docs-focused whole-context pass recovered {len(docs_extra)}; "
        f"{len(still_missed)} prose-doc drifts are still missed. Union coverage "
        f"{hybrid_of_45} → {union_of_45} of 45. Marginal cost ~{round(py_marg / 1000)}k tokens per extra "
        f"drift for 32k chunks vs ~{docs_marg / 1_000_000:.1f}M for the docs pass. Precision of the new "
        f"findings is a lower bound: {py_lb} for hybrid + 32k-chunk new items ({py_lab} among labelled); "
        "most are unlabelled and are not counted as true. "
        f"{len(new_ai)} new true drifts sit outside the labelled 45 ({LABEL_SOURCE}). "
        f"Stability repeat: {stab_agree}/{stab_n} verdicts agreed."
    )
    return {
        "available": True,
        "title": SECTION_TITLE,
        "claim": claim,
        "recipe": RECIPE,
        "headers": headers,
        "rows": table_rows,
        "caveats": [
            "This is a Benchmark-tab experiment, not a headline number. Headline coverage stays 34 of 45.",
            "Precision LB = labelled-true / all findings. Unlabelled findings are not counted as true.",
            "'Among labelled' is biased upward: the labelled items are the ones that hit known drifts.",
            f"15 new-item labels were {LABEL_SOURCE} at the pack ref, not a human maintainer. Unclear counts as not-true.",
            f"{len(still_missed)} still-missed drifts are prose-doc: {', '.join(still_missed)}.",
            "Whole-repo is one call per repo; the extra pass is one call per 32k Python-docstring chunk; docs is one focused whole-context call per repo.",
            f"This run's own ledger is {ledger_tokens:,} tokens over {ledger_calls} calls. "
            "That is extra experimental cost, not part of the 9.3M hybrid end-to-end.",
            "The shipped CLI is still symbol check + one whole-repo triage. "
            "32k docstring chunks are an experimental extra pass (`scripts/beamv3.py`), not a `--docstring-chunks` flag.",
        ],
        "recovered": recovered,
        "missed": 11,
        "py32k_extra_of_45": len(py_extra),
        "docs_extra_of_45": len(docs_extra),
        "still_missed": still_missed,
        "union_of_45": union_of_45,
        "hybrid_of_45": hybrid_of_45,
        "new_ai_verified": len(new_ai),
        "py32k_precision_lb": py_lb,
        "py32k_precision_labelled": py_lab,
        "py32k_marginal": py_marg,
        "docs_marginal": docs_marg,
        "stability_agree": stab_agree,
        "stability_n": stab_n,
        "ledger_tokens": ledger_tokens,
        "ledger_calls": ledger_calls,
    }


def beamv3_markdown_table(payload: BeamV3Payload | None = None) -> str:
    """
    @brief Markdown table generated from results.json.
    """

    data = payload or load_beamv3_payload()
    if not data["available"]:
        return ""
    lines = [
        "| " + " | ".join(data["headers"]) + " |",
        "|" + "|".join("---" for _ in data["headers"]) + "|",
    ]
    for row in data["rows"]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def beamv3_section_markdown(payload: BeamV3Payload | None = None) -> str:
    """
    @brief README / notes block for the Benchmark-tab experiment.
    """

    data = payload or load_beamv3_payload()
    if not data["available"]:
        return ""
    caveats = "\n".join(f"- {line}" for line in data["caveats"])
    return (
        f"## {data['title']}\n\n"
        f"Sourced from `results_live/beamv3/results.json` (scored by `scripts/beamv3_analyze.py`, no Beam calls).\n\n"
        f"{data['claim']}\n\n"
        f"{data['recipe']}\n\n"
        "The table is generated from that file:\n\n"
        f"{beamv3_markdown_table(data)}\n\n"
        f"{caveats}\n\n"
        "Full write-up: `results_live/beamv3/beamv3.md`.\n"
    )


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _fmt_pct(value: object) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.1%}"


def _fmt_cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.1%}" if value <= 1 else f"{value:,.0f}"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, list):
        return str(len(value))
    return str(value)
