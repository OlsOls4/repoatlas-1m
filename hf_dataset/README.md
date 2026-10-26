---
pretty_name: DocDrift v2
configs:
  - config_name: findings
    data_files: findings.parquet
  - config_name: triage_verdicts
    data_files: triage_verdicts.parquet
  - config_name: repros
    data_files: repros.parquet
  - config_name: planted_drift
    data_files: planted_drift.parquet
  - config_name: ablation_verdicts
    data_files: ablation_verdicts.parquet
  - config_name: token_ledger
    data_files: token_ledger.parquet
license: other
task_categories:
  - text-classification
language:
  - en
tags:
  - docdrift
  - beam
  - long-context
  - docs
  - code
---

# DocDrift v2

Unpublished companion dataset for RepoAtlas-1M. Numbers come from `results_live/`. This card is sdk-free.

## Splits

| file | rows | meaning |
|---|---|---|
| findings.jsonl / .parquet | 60 | Hybrid method items (the 60 findings) |
| triage_verdicts.jsonl / .parquet | 56 | Beam triage verdicts (56 judged) |
| repros.jsonl / .parquet | 54 | Executable repro cases (54) |
| planted_drift.jsonl / .parquet | 58 | Planted-drift set + ground truth |
| ablation_verdicts.jsonl / .parquet | 56 | Whole-repo vs local-file triage on the same 56 candidates |
| token_ledger.jsonl / .parquet | 113 | Hybrid + recall + ablation token ledger |

## Fields

- `hand_verdict`: stored field name. **Description:** checked against the source by an AI reviewer. Not a human annotator.
- `verdict` / `strict_confirmed` / `repro_status`: from `hybrid.json` and `repros.json`.
- Citation fields are quote alignment only, including line-shifted matches (±3 lines).

## Limits

- The 45-drift universe is the union of method output.
- 11 of 12 libraries were triaged; structlog failed; cattrs needed 2 calls.
- 2 false + 1 unclear received a strict badge (werkzeug S38, S39 false; S41 unclear).
- End-to-end including repro is 9,302,105 (~9.3M) = 4,424,575 + 4,739,392 + 138,138.
- Ablation ledger (local + stability, not in that 9.3M): 1,948,469 tokens over 60 calls.
- Long context did not change verdict accuracy on these 56 candidates; it changed citation grounding.

