# Matched-cost control for the long-context ablation (round-4 fix 11): pre-registered design

Written and frozen **before any Beam call for this condition** (2026-10-30, Europe/London). The sha256 of this file and
of `scripts/matched_cost.py` are in `preregistration.sha256`, written before the run started. Nothing below was
tuned on gold labels. The dry run (`dry_run.jsonl`) checked only file counts and token estimates, not gold coverage
or verdicts.

## Question
The ablation found that whole-repo triage cites the decisive code far more often than local-file triage:
- cross-file cases, right verdict + gold citation: 25/30 vs 14/30;
- evidence outside the local files: 11/13 vs 0/13.

But whole-repo also spent about 4.8x the tokens (4,022,532 vs 830,527). Judges asked whether this is a long-context
effect or just a budget effect. **Does whole-repo still win on grounding when a per-candidate retrieval condition gets
the same total token budget?**

## Conditions
- **Whole-repo (reference, not rerun):** the hybrid verdicts reused by the ablation. That is 11 batched calls and
  4,022,532 tokens (prompt + completion, last call per repo).
- **Local (reference, not rerun):** the ablation's local-file condition, at 830,527 tokens.
- **Matched (new):** one call per candidate for all 56 candidates.
  - **Context:** the local files plus deterministic retrieval, filled up to a fixed per-candidate budget.
  - **Budget:** 4,022,532 / 56 = 71,831 API tokens per candidate. 3,000 of these are reserved for output, and the
    rest is converted with the RepoAtlas calibration factor of 1.22. That gives a prompt budget of **56,416
    cl100k tokens** (system + user prompt).
  - **Dry-run projection:** total of about 3.85M prompt + ~0.15M completion, which is about 4.0M (a match within ±10%).

## Retrieval (in `scripts/matched_cost.py`; no model involved)
Files are added greedily, tier by tier, in this order:
- **T0 local:** exactly the ablation's local files (the doc file plus any pack file named in the claim or code hint).
- **T1 symbol/grep:** files that *define* an identifier mentioned in the candidate's claim, doc text or code hint
  (`def`/`class`/assignment at any indent). They are ranked by how many identifiers each defines.
- **T2 import neighbourhood:** in-repo Python modules imported by any T0/T1 Python file, then modules that import one.
- **T3 BM25:** top-ranked remaining files, using the candidate's identifiers and words as the query.

A file that would overflow the budget is skipped and the next one is tried. The chosen files keep pack order, so line
numbers match the full snapshot.

## Held fixed (identical to the hybrid and local runs)
- The `SYSTEM` prompt and the `build_user_prompt` template, byte-identical, including "use the whole repository".
- The strict JSON schema, `max_tokens=32000` and `reasoning_effort=medium`.
- Model `beam` via `https://ollama.com/v1`.
- Pinned snapshots. Citations are verified against the full snapshot.

## Labels and grading (unchanged from the ablation)
- **Labels:** `_symbol_verdicts.py` and `hand_labels.json` (from an AI reviewer). "unclear" counts as not-true.
- **Gold:** `_ablation_gold.py`. A citation is correct when the path matches and the lines overlap gold within ±3.
  52 items are gradable, 30 are cross-file, and 13 have their evidence outside the local files.

## Pre-registered outcomes
1. **Verdict accuracy** (n=56), with Wilson 95% intervals. Paired against whole-repo with an exact McNemar test on the
   discordant pairs.
2. **Cross-file citation rate:** right verdict + gold citation on the 30 cross-file items, plus citation alone.
   Wilson intervals and exact McNemar against whole-repo.
3. **Evidence-outside-local rate:** right verdict + gold citation on the 13 items whose gold file is not among the
   local files. Also reported: how many of those 13 had the gold file brought in by retrieval (retrieval coverage).
4. **Tokens:** API-reported prompt + completion, total and per item.
5. Secondary: precision of kept items, verified citations, and gold citation on all 52 gradable items.

## Decision rule (stated before the run)
- **"Whole-repo still wins on grounding at matched cost"** if both of these hold:
  - whole-repo's cross-file right-verdict+citation count is higher than matched's;
  - the exact McNemar two-sided p < 0.05 on those 30 items.
- If whole-repo is higher but p ≥ 0.05, we report **"not shown at this n"**.
- If matched is equal or higher, we report that **retrieval at equal spend matches or beats whole-repo** on grounding.
- Accuracy is judged the same way.
- The results are reported whatever they are.

## Safety and run rules
- Calls are sequential, with the shared hybrid lock.
- The run has its own ledger (`beam_usage_ledger.json` here) with a hard cap of 4.6M tokens.
- HTTP 402 or any quota/billing text stops the run. 429 gets backoff of 60/120/240 s.
- A timeout is not resent.
- A response that will not parse is re-sent **once** with a nonce, with both raw responses kept, which is the
  ablation's rule.
- The API key is read from a file and only sent in the Authorization header.
