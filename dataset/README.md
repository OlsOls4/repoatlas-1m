---
pretty_name: DocDrift v2 results (RepoAtlas-1M, Oct 2026)
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
  - docdrift
---

# DocDrift v2 dataset card

This folder is the earlier v1 live-results export. The v2 publication folder is `hf_dataset/` (60 findings, 56 triage verdicts, 54 repros, planted-drift set, ablation verdicts, token ledger including the 1,948,469-token ablation run).

**v2 headline** (from `results_live/hybrid/hybrid.json`): 34 real docs bugs in 12 Python libraries; 45 of 60 flagged findings were real; 30 strict repros. Labels were checked against the source by an AI reviewer. The stored field is still `hand_verdict`.

## Field: `hand_verdict`

Kept for compatibility. **Description:** checked against the source by an AI reviewer (file:line evidence). Not a human annotator. Not “mine”.

## Files in this folder

- `runs.jsonl`: one row per v1 run
- `findings.jsonl`: one row per v1 finding with verifier and `hand_verdict`
- `upstream_status.json`: starlette #3746 and nox #1216 filed open; httpx #3774 and arrow #1355 already reported upstream by others
- `reverify_line_shift.json`: ±3 line-shift verifier output
- `traces/`: full raw trace JSON (large)
- `upstream_drafts/`: unfiled drafts

## Limits

- Citation pass/fail is quote alignment, not correctness.
- The 45-drift v2 universe is the union of method output.
- 2 false + 1 unclear received a strict repro badge (werkzeug S38, S39 false; S41 unclear).
