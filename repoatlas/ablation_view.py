"""Load the recorded whole-repo vs local-file triage ablation from results.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from repoatlas.hybrid_view import LABEL_SOURCE, RESULTS_LIVE_DIRECTORY


ABLATION_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "results.json"
ABLATION_LEDGER_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "beam_usage_ledger.json"
MATCHED_COST_RESULTS_PATH: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "matched_cost" / "results.json"
MATCHED_COST_EXT_DIRECTORY: Path = RESULTS_LIVE_DIRECTORY / "ablation" / "matched_cost_ext"

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
    matched_available: bool
    why_matched_cost_note: str
    cross_file_cite_matched: str
    outside_cite_matched: str
    accuracy_matched: str
    matched_tokens: int
    matched_ledger_tokens: int
    matched_ledger_calls: int
    matched_mcnemar_p: str
    gold_file_retrieved: str
    gold_file_missed: int
    accuracy_frac_matched: str
    accuracy_frac_whole: str
    matched_ext_available: bool
    matched_ext_cross_whole: str
    matched_ext_cross_matched: str
    matched_ext_p: str
    matched_ext_tokens: int


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
        "matched_available": False,
        "why_matched_cost_note": "Matched-cost local bar: not run yet.",
        "cross_file_cite_matched": "",
        "outside_cite_matched": "",
        "accuracy_matched": "",
        "matched_tokens": 0,
        "matched_ledger_tokens": 0,
        "matched_ledger_calls": 0,
        "matched_mcnemar_p": "",
        "gold_file_retrieved": "",
        "gold_file_missed": 0,
        "accuracy_frac_matched": "",
        "accuracy_frac_whole": "",
        "matched_ext_available": False,
        "matched_ext_cross_whole": "",
        "matched_ext_cross_matched": "",
        "matched_ext_p": "",
        "matched_ext_tokens": 0,
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
            *_matched_cost_caveat(),
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
        **_matched_cost_fields(),
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


def _matched_cost_payload() -> dict[str, object] | None:
    """
    @brief Read results_live/ablation/matched_cost/results.json, or None if missing.
    """

    if not MATCHED_COST_RESULTS_PATH.exists():
        return None
    raw: object = json.loads(MATCHED_COST_RESULTS_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def _read_json_dict(path: Path) -> dict[str, object]:
    """
    @brief Read a JSON object, or {} if the file is missing or not an object.
    """

    if not path.exists():
        return {}
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _paired(block: object) -> tuple[str, str, str]:
    """
    @brief (whole "a/n", matched "b/n", p text) from an ext_score.py paired-comparison block.
    """

    d = block if isinstance(block, dict) else {}
    n = int(d.get("n") or 0)
    p_raw = d.get("exact_mcnemar_p")
    p_text = f"{float(p_raw):.2g}" if isinstance(p_raw, (int, float)) else ""
    return f"{int(d.get('whole_right') or 0)}/{n}", f"{int(d.get('matched_right') or 0)}/{n}", p_text


def _acc_frac(arm: object) -> str:
    """
    @brief "right/n" verdict accuracy from an ext_score.py per-arm block ([right, n, ci]).
    """

    acc = arm.get("accuracy") if isinstance(arm, dict) else None
    return f"{int(acc[0])}/{int(acc[1])}" if isinstance(acc, list) and len(acc) >= 2 else ""


def _matched_cost_ext_fields() -> dict[str, object]:
    """
    @brief Pooled pre-registered extension (results_live/ablation/matched_cost_ext), or not available.
    """

    raw = _read_json_dict(MATCHED_COST_EXT_DIRECTORY / "results.json")
    prereg = _read_json_dict(MATCHED_COST_EXT_DIRECTORY / "preregistration_ext.json")
    sens = _read_json_dict(MATCHED_COST_EXT_DIRECTORY / "resume" / "sensitivity.json")
    primary = raw.get("primary") if isinstance(raw.get("primary"), dict) else {}
    if not primary:
        return {
            "matched_ext_available": False,
            "matched_ext_note": "",
            "matched_ext_cross_whole": "",
            "matched_ext_cross_matched": "",
            "matched_ext_p": "",
            "matched_ext_tokens": 0,
        }
    pooled = raw.get("pooled") if isinstance(raw.get("pooled"), dict) else {}
    new_only = raw.get("new_only") if isinstance(raw.get("new_only"), dict) else {}
    strata = raw.get("strata") if isinstance(raw.get("strata"), dict) else {}
    tokens = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {}
    hashes = prereg.get("sha256") if isinstance(prereg.get("sha256"), dict) else {}
    design_sha = str(hashes.get("design_ext.md") or "")
    xw, xm, p_text = _paired(primary)
    arms = pooled.get("per_arm") if isinstance(pooled.get("per_arm"), dict) else {}
    aw, am = (_acc_frac(arms.get(arm)) for arm in ("whole", "matched"))
    _, _, p_new = _paired(new_only.get("cross_file_verdict_and_cite_whole_vs_matched"))
    _, _, p_no_resend = _paired(sens.get("no_resends_first_attempt_only"))
    planted = strata.get("planted") if isinstance(strata.get("planted"), dict) else {}
    real = strata.get("real_structlog") if isinstance(strata.get("real_structlog"), dict) else {}
    n_new = int(new_only.get("n_items") or 0)
    note = (
        f"**Pre-registered extension.** We then added {n_new} items "
        f"({int(planted.get('n_items') or 0)} planted renames, {int(real.get('n_items') or 0)} real structlog "
        f"candidates), frozen before any Beam call (design sha256 {design_sha[:8]}…{design_sha[-4:]}). "
        f"Pooled over {int(primary.get('n') or 0)} cross-file items, the right verdict **and** the right line came out "
        f"{xw} for the whole repo against {xm} for retrieval (exact McNemar p = {p_text}). "
        f"Verdict accuracy still did not differ ({aw} against {am}). "
        f'The new items alone give p = {p_new} ("not shown at this n")'
        + (
            f", and the pooled result relies on one pre-registered re-send of a whole-repo call that failed to parse "
            f"(p = {p_no_resend} without it)."
            if p_no_resend
            else "."
        )
    )
    return {
        "matched_ext_available": True,
        "matched_ext_note": note,
        "matched_ext_cross_whole": xw,
        "matched_ext_cross_matched": xm,
        "matched_ext_p": p_text,
        "matched_ext_tokens": int(tokens.get("ledger_total") or 0),
    }


def _matched_cost_fields() -> dict[str, object]:
    """
    @brief Display fields for the Why-1M matched-cost control, generated from results.json.
    """

    empty: dict[str, object] = {
        "matched_available": False,
        "why_matched_cost_note": "Matched-cost local bar: not run yet.",
        "cross_file_cite_matched": "",
        "outside_cite_matched": "",
        "accuracy_matched": "",
        "matched_tokens": 0,
        "matched_ledger_tokens": 0,
        "matched_ledger_calls": 0,
        "matched_mcnemar_p": "",
        "gold_file_retrieved": "",
        "gold_file_missed": 0,
        "accuracy_frac_matched": "",
        "accuracy_frac_whole": "",
        "matched_ext_available": False,
        "matched_ext_cross_whole": "",
        "matched_ext_cross_matched": "",
        "matched_ext_p": "",
        "matched_ext_tokens": 0,
    }
    raw = _matched_cost_payload()
    if raw is None:
        return empty
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    tokens = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {}
    paired = raw.get("paired_comparisons") if isinstance(raw.get("paired_comparisons"), dict) else {}
    retrieval = raw.get("retrieval_coverage") if isinstance(raw.get("retrieval_coverage"), dict) else {}
    whole = metrics.get("whole") if isinstance(metrics.get("whole"), dict) else {}
    matched = metrics.get("matched") if isinstance(metrics.get("matched"), dict) else {}
    cross_cmp = (
        paired.get("cross_file_verdict_and_cite_whole_vs_matched")
        if isinstance(paired.get("cross_file_verdict_and_cite_whole_vs_matched"), dict)
        else {}
    )
    n = int(matched.get("n") or whole.get("n") or 0)
    acc_m = int(matched.get("accuracy_count") or 0)
    acc_w = int(whole.get("accuracy_count") or 0)
    xf_m = _frac(matched, "cross_file_verdict_and_cite_right", "cross_file_cases")
    xf_w = _frac(whole, "cross_file_verdict_and_cite_right", "cross_file_cases")
    out_m = _frac(matched, "outside_local_verdict_and_cite_right", "gold_outside_local_cases")
    out_w = _frac(whole, "outside_local_verdict_and_cite_right", "gold_outside_local_cases")
    out_n = int(matched.get("gold_outside_local_cases") or retrieval.get("outside_local_items") or 0)
    retrieved = int(retrieval.get("gold_file_retrieved_into_matched_context") or 0)
    missed = max(0, out_n - retrieved)
    matched_tokens = int(tokens.get("matched") or 0)
    ledger_tokens = int(tokens.get("matched_ledger_as_spent") or 0)
    ledger_calls = int(tokens.get("matched_ledger_calls") or 0)
    whole_tokens = int(tokens.get("whole") or 0)
    pct = round(100 * matched_tokens / whole_tokens, 1) if whole_tokens else 0.0
    p_raw = cross_cmp.get("exact_mcnemar_p")
    try:
        p_text = f"{float(p_raw):.3f}"
    except (TypeError, ValueError):
        p_text = str(p_raw or "")
    note = (
        f"**Is it the whole repo, or just more tokens?** We gave a retrieval baseline the **same** "
        f"Beam budget as whole-repo triage. That came to {ledger_tokens:,} against {whole_tokens:,} "
        f"tokens as spent ({matched_tokens:,} attributable; {pct}% of whole-repo) over the same "
        f"{n} candidates. For each candidate, it got the local files plus the symbol definitions, "
        "imports and BM25 matches that fit in about 56k tokens.\n\n"
        f"Verdict accuracy came out the same ({acc_m}/{n} against {acc_w}/{n}). Grounding still "
        f"favoured the whole repo: the right verdict **and** the right cross-file line in {xf_w} "
        f"cases, against {xf_m} for retrieval. Where the evidence lives outside the files the doc "
        f"points at, the figures are {out_w} against {out_m}. Retrieval pulled in importers or "
        f"re-exports rather than the defining file in {missed} of {out_n} outside-local items.\n\n"
        f"That gap is suggestive, not proven, at this sample size (exact McNemar p = {p_text}). "
        'We pre-registered the test and report it as "not shown at this n".'
    )
    ext = _matched_cost_ext_fields()
    if ext["matched_ext_available"]:
        note += "\n\n" + str(ext["matched_ext_note"])
    note += (
        " The honest takeaway: whole-repo context doesn't make Beam **judge** better, but it helps Beam "
        "**point at the right line** more often, "
        + ("for no more spend than retrieval." if ext["matched_ext_available"] else "for the same spend.")
    )
    return {
        "matched_available": True,
        "why_matched_cost_note": note,
        "cross_file_cite_matched": xf_m,
        "outside_cite_matched": out_m,
        "accuracy_matched": _fmt_num(matched.get("accuracy")),
        "matched_tokens": matched_tokens,
        "matched_ledger_tokens": ledger_tokens,
        "matched_ledger_calls": ledger_calls,
        "matched_mcnemar_p": p_text,
        "gold_file_retrieved": f"{retrieved}/{out_n}",
        "gold_file_missed": missed,
        "accuracy_frac_matched": f"{acc_m}/{n}",
        "accuracy_frac_whole": f"{acc_w}/{n}",
        **{k: v for k, v in ext.items() if k != "matched_ext_note"},
    }


def _matched_cost_caveat() -> list[str]:
    """
    @brief Extra experimental-cost caveat for the ablation box.
    """

    fields = _matched_cost_fields()
    if not fields["matched_available"]:
        return []
    return [
        f"Matched-cost retrieval control: {int(fields['matched_tokens']):,} attributable / "
        f"{int(fields['matched_ledger_tokens']):,} as spent ({int(fields['matched_ledger_calls'])} calls; "
        "same 56 candidates). Extra experimental cost, not part of the 9.3M hybrid end-to-end.",
        *(
            [
                f"Pre-registered matched-cost extension: {int(fields['matched_ext_tokens']):,} tokens "
                "(63 more items). Extra experimental cost, not part of the 9.3M hybrid end-to-end."
            ]
            if fields.get("matched_ext_available")
            else []
        ),
    ]
