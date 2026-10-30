# Matched-cost control: pre-registered EXTENSION (design_ext.md)

Status: written and frozen BEFORE any extension Beam call. Its sha256 and the hashes of the item file and scripts
are recorded in `preregistration_ext.json`, which is written right after this file. Any later change to this file
would change that hash.

## Why
In the original matched-cost control (`../matched_cost/design.md`, 56 candidates), the primary test was cross-file
right verdict + gold citation, whole vs matched. It gave whole 7-only vs matched 1-only out of 30 cross-file items,
exact McNemar p = 0.0703. That is not significant. The extension adds items so the same question has more power. It
does not change any rule from the original design.

## New items (items.json, built by scripts/ext_items.py; no new labels by guesswork)
Only items whose label and gold citation were already recorded are used, or items labelled with file:line evidence
at the pinned commit. None of these items is among the original 56.

E1. **Planted drifts (57 items).** These come from `results_live/recall/ground_truth_seed{1,2}.json`. There were 58
synonym-swap renames planted into click 2247b35, jinja 5ef7011, werkzeug b73dce5, httpx b5addb6, httpcore 10a6582
and structlog 19c4f21; the commits are as in recall.md.
  - **Label:** `true` by construction (`stale_line_check` true for all).
  - **Gold:** the recorded code location, `(code_path, code_line)` and `(code_path, def_line)`. A citation is correct
    if it overlaps either of these ±3 lines (the same SLACK as the original).
  - **cross_file:** `doc_path != code_path`.
  - **Mechanical exclusion:** a plant is dropped if its stale doc line itself defines the stale name
    (`def NAME`/`class NAME`), because the doc is then a user-defined example and not a reference. This excludes 1
    plant, P2-23 (`def open_url(ctx, param, value):` in click docs/advanced.md).
  - **Claim text** (one template for every plant; it names no file and no kind):
    `name-check: the documentation refers to \`<doc_says>\`; this name may not match the code.`
    `doc_text` is the recorded stale line, `code_hint` is empty, and `doc_line = doc_end` is the recorded line.
  - **Repo context:** that library's files from the planted haystack pack (`/workspace/recall_work/pack_seed{s}.json`,
    which contains the plant edits). The pack header is neutralised to the library's upstream URL and pinned ref, so
    the words "planted"/"recall" do not appear in any prompt. The same derived pack is used by all three arms.
  - **Unit:** (seed, library), 12 units.

E2. **structlog real candidates (6 items).** These are the 6 DocDrift v2 candidates for structlog
(`results_live/traces/structlog-400000.json`; hybrid candidate loader). They were not judged among the 56 because
the hybrid whole-repo structlog call failed to parse.
  - **Labels:** from `scripts/_symbol_verdicts.py` (S13-S16) and `results_live/handcheck.md` / `hand_labels.json`
    (DD-1, DD-2).
  - **Gold:** checked in the pinned pack at 19c4f21:
    - DD-2 true: `_log_levels.py:27`, cross.
    - S13 true: `_log_levels.py:27`, cross.
    - S14 true: `_log_levels.py:27`, cross.
    - DD-1 false: `_log_levels.py:27-36` or `_native.py:132-133`, cross. The decisive evidence is the NAME_TO_LEVEL
      superset.
    - S16 false: `dev.py:999-1008`, same-file.
    - S15 true: `twisted.py:202`, same-file.

Totals: 63 new items. 49 are cross-file: 45 planted, plus DD-1, DD-2, S13 and S14. 61 are labelled true and 2 false.

Known asymmetries, stated before running (they cut in different directions; the report stratifies by source):
  - The planted items are almost all `true`, so they test finding the renamed definition, not rejection.
  - The synonym swaps hide the new name from lexical retrieval (T1 greps for the stale name), which can favour whole
    over matched.
  - The planted claim names no file, so local context = doc file only.
  - The matched per-item budget (56,416 cl100k est. prompt) is the original constant. The per-item whole spend on
    these units differs, and both are reported.

## Arms (identical prompts and settings to the original 56)
All arms use the same model "beam" at https://ollama.com/v1, the same `SYSTEM`, `build_user_prompt`, strict
`json_schema` SCHEMA, `max_tokens=32000` and `reasoning_effort=medium` (`ablation_triage.payload_for`).
  - **whole:** one call per unit with the full unit pack and all of that unit's candidates (13 calls), like the hybrid
    whole-repo triage.
  - **local:** one call per item, with the doc file plus files named in claim/code_hint (`ablation_triage.local_files`).
  - **matched:** one call per item, with context from `matched_cost.select()` unchanged: T0 local, T1 defining files,
    T2 import neighbours, T3 BM25, greedy up to `PROMPT_BUDGET_EST = 56,416`.
  - **Run order:** unit by unit; whole first, then local and matched for each item.

## Stop rules and budget
  - Ollama free tier only, with the key read from `/home/box/.secrets/ollama_api_key`. The key is never printed or
    written.
  - Stop the whole run on ANY non-200 response: 402, 429 (no backoff), 5xx, any error body, or quota/billing wording.
  - Ledger cap 11,500,000 API tokens (`beam_usage_ledger.json` in this directory). A call is refused if the ledger
    total plus its estimate would exceed the cap. Dry-run estimate with a 15k output reserve per call is 9.32M; the
    expected actual is about 7.5M.
  - A timeout is not resent.
  - **Parse failures:** a call whose content does not parse gets exactly one re-send of the identical payload with a
    nonce (same rule as the original). If it still fails, every item in that call counts as "no verdict", which is
    wrong for a true item and right (not kept) for a false item; there is no citation. The same rule applies to all
    arms.
  - If the run stops early, I report what finished. The primary test then uses only the items that have both whole and
    matched results, and I say so.

## Analysis (scripts/ext_score.py)
  - **Right verdict:** kept (`true_drift`) == (label == true). An unclear label counts as not-true.
  - **Right citation:** path match and line overlap with gold ±3.
  - **PRIMARY (reported whatever it shows):** POOLED = original 56 (their existing whole/local/matched results, not
    rerun) + 63 new items. The test is on cross-file items (30 + 49 = 79): right verdict AND gold citation, whole vs
    matched, exact two-sided McNemar.
    - p < 0.05 with whole ahead → "whole-repo context beats matched-cost retrieval on cross-file evidence".
    - p < 0.05 with matched ahead → the reverse.
    - Otherwise → "difference not shown".
    - No other test can replace the primary in headline copy.
  - **Secondary (descriptive or exploratory, not used for the headline):**
    - the same test on new items only;
    - outside-local items (gold file not in the local context);
    - verdict accuracy;
    - all gradable items;
    - local vs matched and whole vs local on cross-file items;
    - strata (original / planted / real-structlog);
    - lenient citation (right file, any line);
    - Wilson 95% intervals on rates.
  - **Retrieval failure modes:** for cross-file items where whole is right and matched is wrong (verdict + cite), and
    for all matched cross-file failures. Each one is classified mechanically as:
    - matched parse failure / missing verdict;
    - gold file not retrieved into the matched context;
    - gold retrieved but wrong verdict;
    - gold retrieved, right verdict, citation misses gold.
  - **Tokens:** ledger totals per arm, plus calls per arm.
