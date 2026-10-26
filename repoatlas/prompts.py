"""Prompt builders for RepoAtlas analysis requests."""

from __future__ import annotations

from repoatlas.models import RepoPack


SYSTEM_PROMPT: str = (
    "You are RepoAtlas-1M. "
    "Find documentation drift and onboarding facts in a software repository. "
    "Return strict JSON that matches the requested schema. "
    "Never invent citations. "
    "Every finding must cite one documentation location and one code location with exact quotes. "
    "When unsure, omit the finding."
)


def build_analysis_user_prompt(pack: RepoPack) -> str:
    """
    @brief Build the user prompt for a single full-context analysis pass.
    @param pack Deterministic packed repository payload.
    """

    return (
        "Analyse the packed repository below.\n"
        "Task A: DocDrift findings where docs contradict code for flags, defaults, signatures, env vars, or config keys.\n"
        "Task B: Onboarding atlas claims for architecture, entry points, and data flow.\n"
        "Rules:\n"
        "1) Every citation must include path, start_line, end_line, and exact quote text from those lines.\n"
        "2) Proposed fixes must be documentation-only and local patch text.\n"
        "3) If you cannot cite line-level evidence, do not emit that finding or claim.\n"
        "4) Keep output concise and factual.\n"
        "5) Output ONLY one JSON object, no prose, with exactly this shape:\n"
        '{"findings": [{"finding_id": "DD-1", "drift_kind": "flag|default|signature|env_var|config_key|other", '
        '"explanation": "...", "doc_citation": {"path": "...", "start_line": 1, "end_line": 1, "quote": "..."}, '
        '"code_citation": {"path": "...", "start_line": 1, "end_line": 1, "quote": "..."}, "proposed_fix": "..."}], '
        '"atlas_claims": [{"claim_id": "AC-1", "section": "architecture|entry_points|data_flow", "text": "...", '
        '"citations": [{"path": "...", "start_line": 1, "end_line": 1, "quote": "..."}]}]}\n'
        "Quotes must be copied verbatim from the cited lines, without the '<line>|' prefix.\n"
        "Packed repository context follows:\n\n"
        f"{pack.pack_text}"
    )
