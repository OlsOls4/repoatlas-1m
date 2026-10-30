"""Load the recorded whole-repo vs local-file triage ablation from results.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from repoatlas.hybrid_view import LABEL_SOURCE, RESULTS_LIVE_DIRECTORY


ABLATION_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "results.json"
ABLATION_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "beam_usage_ledger.json"

CLAIM: str = (
    "Long context didn't make verdicts more accurate here; it made them cite the real evidence "
    "across files, which is what we verify and show maintainers."
)


class AblationPayload(TypedDict):
    """
    @brief Parsed ablation metrics used by the Space, README, and dataset card.
    """

    available: bool
    headers: list[str]
    rows: list[list[str]]
    claim: str
    caveats: list[str]
    n: int
    disagreements: int
    stability_agree: int
    stability_n: int
    whole_tokens: int
    local_tokens: int
    token_multiplier: float
    ablation_ledger_tokens: int
    ablation_ledger_calls: int
    cross_file_cite_whole: str
    cross_file_cite_local: str
    outside_cite_whole: str
    outside_cite_local: str
    accuracy_whole: str
    accuracy_local: str
    accuracy_whole_subset: str
    accuracy_local_subset: str
    outside_cite_whole_subset: str
    outside_cite_local_subset: str
    subset_note: str


def load_ablation_payload(path: Path | None = None) -> AblationPayload:
    """
    @brief Read results_live/ablation/results.json into display rows. No live calls.
    """

    target: Path = path or ABLATION_RESULTS_PATH
    empty: AblationPayload = {
        "available": False,
        "headers": [],
        "rows": [],
        "claim": CLAIM,
        "caveats": [],
        "n": 0,
        "disagreements": 0,
        "stability_agree": 0,
        "stability_n": 0,
        "whole_tokens": 0,
        "local_tokens": 0,
        "token_multiplier": 0.0,
        "ablation_ledger_tokens": 0,
        "ablation_ledger_calls": 0,
        "cross_file_cite_whole": "",
        "cross_file_cite_local": "",
        "outside_cite_whole": "",
        "outside_cite_local": "",
        "accuracy_whole": "",
        "accuracy_local": "",
        "accuracy_whole_subset": "",
        "accuracy_local_subset": "",
        "outside_cite_whole_subset": "",
        "outside_cite_local_subset": "",
        "subset_note": "",
    }
    if not target.exists():
        return empty
    raw: object = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return empty
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    tokens = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {}
    stability = raw.get("stability") if isinstance(raw.get("stability"), dict) else {}
    disagreements = raw.get("local_vs_whole_disagreements")
    n_disagree = len(disagreements) if isinstance(disagreements, list) else 0
    whole = metrics.get("whole") if isinstance(metrics.get("whole"), dict) else {}
    local = metrics.get("local") if isinstance(metrics.get("local"), dict) else {}
    whole_sub = metrics.get("whole_on_stability_subset") if isinstance(metrics.get("whole_on_stability_subset"), dict) else {}
    local_sub = metrics.get("local_on_stability_subset") if isinstance(metrics.get("local_on_stability_subset"), dict) else {}
    stab = metrics.get("stability") if isinstance(metrics.get("stability"), dict) else {}
    whole_tokens = int(tokens.get("whole_final_call_per_repo") or 0)
    local_tokens = int(tokens.get("local") or 0)
    ledger_tokens = int(tokens.get("ablation_ledger_total") or 0)
    ledger_calls = int(tokens.get("ablation_ledger_calls") or 0)
    multiplier = round(whole_tokens / local_tokens, 1) if local_tokens else 0.0
    n = int(whole.get("n") or 0)
    stab_n = int(stability.get("n") or 0)
    headers = [
        "Metric",
        "Whole-repo (reused hybrid)",
        "Local-file only",
        f"Whole-repo, subset ({stab_n})",
        f"Local, subset ({stab_n})",
        f"Whole-repo rerun, subset ({stab_n})",
    ]
    cols = [whole, local, whole_sub, local_sub, stab]
    rows = [
        ["True candidates kept", *_fracs(cols, "kept_true", "n_true")],
        ["False/unclear candidates rejected", *_fracs(cols, "rejected_false", "n_false_or_unclear")],
        ["Precision (kept that are true)", *_precisions(cols)],
        ["Verdict accuracy", *[ _fmt_num(c.get("accuracy")) for c in cols ]],
        ["Citation hits gold file:line (gradable)", *_fracs(cols, "cite_correct", "gradable_for_citation")],
        ["Right verdict + gold citation", *_fracs(cols, "verdict_and_cite_correct", "gradable_for_citation")],
        ["Citation verified (quote matches source)", *_fracs(cols, "cite_verified", "n")],
        ["Cross-file cases: right verdict", *_fracs(cols, "cross_file_verdict_right", "cross_file_cases")],
        ["Cross-file cases: right verdict + citation", *_fracs(cols, "cross_file_verdict_and_cite_right", "cross_file_cases")],
        ["Evidence outside local context: right verdict", *_fracs(cols, "outside_local_verdict_right", "gold_outside_local_cases")],
        ["Evidence outside local context: right verdict + citation", *_fracs(cols, "outside_local_verdict_and_cite_right", "gold_outside_local_cases")],
        [
            "Beam tokens",
            f"{whole_tokens:,} (11 calls; {int(tokens.get('whole') or 0):,} as spent incl. a cattrs re-send)",
            f"{local_tokens:,} (56 calls; {int(tokens.get('local_as_spent') or 0):,} as spent incl. 1 re-send)",
            "—",
            "—",
            f"{int(tokens.get('stability') or 0):,}",
        ],
    ]
    return {
        "available": True,
        "headers": headers,
        "rows": rows,
        "claim": CLAIM,
        "caveats": [
            f"n={n} judged candidates (structlog excluded; its hybrid triage failed).",
            f"Labels and gold file:line were {LABEL_SOURCE}, not a human maintainer.",
            "Whole-repo is one batched call per repo; local is one call per candidate.",
            "Local was given every file the candidate already named.",
            f"6 of {n} disagreements split 3-3. Stability rerun: "
            f"{int(stability.get('stability_vs_whole_verdict_agreement') or 0)}/{stab_n} verdicts matched.",
            f"Whole-repo used {whole_tokens:,} tokens vs {local_tokens:,} for local (~{multiplier}×). "
            f"This ablation run's own ledger is {ledger_tokens:,} tokens over {ledger_calls} calls; "
            "that is extra experimental cost, not part of the 9.3M hybrid end-to-end.",
        ],
        "n": n,
        "disagreements": n_disagree,
        "stability_agree": int(stability.get("stability_vs_whole_verdict_agreement") or 0),
        "stability_n": stab_n,
        "whole_tokens": whole_tokens,
        "local_tokens": local_tokens,
        "token_multiplier": multiplier,
        "ablation_ledger_tokens": ledger_tokens,
        "ablation_ledger_calls": ledger_calls,
        "cross_file_cite_whole": _frac(whole, "cross_file_verdict_and_cite_right", "cross_file_cases"),
        "cross_file_cite_local": _frac(local, "cross_file_verdict_and_cite_right", "cross_file_cases"),
        "outside_cite_whole": _frac(whole, "outside_local_verdict_and_cite_right", "gold_outside_local_cases"),
        "outside_cite_local": _frac(local, "outside_local_verdict_and_cite_right", "gold_outside_local_cases"),
        "accuracy_whole": _fmt_num(whole.get("accuracy")),
        "accuracy_local": _fmt_num(local.get("accuracy")),
        "accuracy_whole_subset": _fmt_num(whole_sub.get("accuracy")),
        "accuracy_local_subset": _fmt_num(local_sub.get("accuracy")),
        "outside_cite_whole_subset": _frac(whole_sub, "outside_local_verdict_and_cite_right", "gold_outside_local_cases"),
        "outside_cite_local_subset": _frac(local_sub, "outside_local_verdict_and_cite_right", "gold_outside_local_cases"),
        "subset_note": (
            f"On the {stab_n}-item rerun subset, local-only scored higher on verdict accuracy "
            f"({_fmt_num(local_sub.get('accuracy'))} vs {_fmt_num(whole_sub.get('accuracy'))}). "
            "Whole-repo's advantage is citation: "
            f"{_frac(whole_sub, 'outside_local_verdict_and_cite_right', 'gold_outside_local_cases')} vs "
            f"{_frac(local_sub, 'outside_local_verdict_and_cite_right', 'gold_outside_local_cases')} "
            "when the proof lives outside the candidate's files."
        ),
    }


def ablation_markdown_table(payload: AblationPayload | None = None) -> str:
    """
    @brief Markdown table generated from results.json.
    """

    data = payload or load_ablation_payload()
    if not data["available"]:
        return ""
    lines = [
        "| " + " | ".join(data["headers"]) + " |",
        "|" + "|".join("---" for _ in data["headers"]) + "|",
    ]
    for row in data["rows"]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def ablation_long_context_blurb(payload: AblationPayload | None = None) -> str:
    """
    @brief One-paragraph grounding claim for hero / What Beam did.
    """

    data = payload or load_ablation_payload()
    if not data["available"]:
        return CLAIM
    return (
        f"{CLAIM} On the same {data['n']} candidates, whole-repo and local-file triage both kept 32/32 true "
        f"and rejected 15/24 false; {data['disagreements']} of {data['n']} disagreements split 3-3. "
        f"Whole-repo cited the correct file:line in {data['cross_file_cite_whole']} cross-file cases vs "
        f"{data['cross_file_cite_local']} for local, and {data['outside_cite_whole']} vs "
        f"{data['outside_cite_local']} when the evidence lives outside the candidate's own files, "
        f"at ~{data['token_multiplier']}× tokens ({data['whole_tokens']:,} vs {data['local_tokens']:,}). "
        f"Stability rerun: {data['stability_agree']}/{data['stability_n']} verdicts matched."
    )


def _frac(block: dict[str, object], num_key: str, den_key: str) -> str:
    if not block:
        return "—"
    return f"{int(block.get(num_key) or 0)}/{int(block.get(den_key) or 0)}"


def _fracs(cols: list[dict[str, object]], num_key: str, den_key: str) -> list[str]:
    return [_frac(col, num_key, den_key) for col in cols]


def _precisions(cols: list[dict[str, object]]) -> list[str]:
    out: list[str] = []
    for col in cols:
        if not col:
            out.append("—")
            continue
        out.append(f"{_fmt_num(col.get('precision'))} ({int(col.get('kept_true') or 0)}/{int(col.get('kept') or 0)})")
    return out


def _fmt_num(value: object) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    return text
