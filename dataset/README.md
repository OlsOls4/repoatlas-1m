---
pretty_name: RepoAtlas-1M Live DocDrift Results (Oct 2026)
task_categories:
  - text-classification
  - summarization
language:
  - en
tags:
  - beam
  - long-context
  - docs
  - code
---

# RepoAtlas-1M live results dataset export

This folder is prepared for a companion Hugging Face dataset publication.

- Hand-checked precision across all live findings: **11/21 = 52.4%**
- Breakdown: true=11, false=8, unclear=2
- Full run narrative and caveats are in `handcheck.md`.

## Files

- `runs.jsonl`: one row per run from `results_live/benchmark_results_combined.csv`
- `findings.jsonl`: one row per finding with verifier and hand verdict labels
- `upstream_status.json`: source of truth for external status labels and links
- `reverify_line_shift.json`: ±3 line-shift verifier output used for corrected citation checks
- `traces/`: full raw trace JSON payloads (large; include pack text)
- `upstream_drafts/`: unfiled upstream issue/PR draft notes

## Notes

- `verifier_fully_verified=true` means cited snippets matched pack text; it does not prove a finding is correct.
- `hand_verdict` is the source of truth for precision reporting.
