---
pretty_name: DocDrift bugs
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
  - config_name: beamv3_findings
    data_files: beamv3_findings.parquet
  - config_name: token_ledger
    data_files: token_ledger.parquet
license: cc-by-4.0
task_categories:
  - text-classification
language:
  - en
tags:
  - code
  - documentation
  - long-context
  - beam
  - docdrift
---

# DocDrift bugs: docs-vs-code drifts in 12 Python libraries, found with Beam

DocDrift gives Beam a whole Python library (docs + code, up to ~400k tokens) in one call. A free AST symbol check proposes name and signature mismatches. Beam triages those candidates against the packed repo, can add cross-file or prose drift, and writes a script that runs the documented usage. A finding counts as reproduced only if that script raises TypeError, AttributeError, ImportError, or NameError on a documented-usage line.

This dataset is the recorded output of that pipeline on 12 pinned libraries. 34 real docs bugs were found in 11 of the 12 libraries; 30 reproduce. Labels were checked against the source by an AI reviewer, not a human annotator. The stored field is still named `hand_verdict`.

**Licence.** DocDrift's own labels, verdicts, and notes are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Quoted documentation and source excerpts remain under each library's own licence (all 12 are permissive OSS).

## How it was built

1. Pin each library to a recorded commit.
2. Pack docs + source up to a 400k token cap.
3. Run a free symbol check, then one whole-repo Beam triage call per library (11 of 12 succeeded in one call; structlog failed; cattrs needed 2).
4. Beam-written repro scripts, plus one hand-written starlette script from Beam's verdict.
5. Citation check is quote alignment of cited lines vs packed source (±3-line shift). It is not a verdict that the drift is real.

## Configs

| config | rows | what it is | fields |
|---|---:|---|---|
| findings | 60 | Hybrid method items (the 60 findings) | `repo`, `id`, `kind`, `verdict`, `drift_id`, `beam`, `strict_confirmed`, `repro_status`, `evidence`, `hand_verdict`, `hand_verdict_description` |
| triage_verdicts | 56 | Beam triage verdicts (56 judged) | `repo`, `candidate_id`, `source_id`, `verdict`, `reason`, `code_path`, `code_line`, `code_quote` |
| repros | 54 | Executable repro cases | `case_id`, `repo`, `status`, `strict_confirmed`, `exception_type`, `error_excerpt`, `evidence` |
| planted_drift | 58 | Planted-drift set + ground truth | original probe fields plus `seed` |
| ablation_verdicts | 56 | Whole-repo vs local-file triage on the same 56 candidates | `key`, `repo`, `candidate_id`, `label`, `hand_verdict`, `hand_verdict_description`, `cross_file`, `gold_outside_local`, `whole_verdict`, `local_verdict`, `stability_verdict`, citation flags |
| beamv3_findings | 115 | Extra 32k-docstring-chunk and docs-pass findings (unlabelled not counted as true) | `id`, `repo`, `pass`, `doc_path`, `doc_line`, `label`, `drift_id`, `label_by`, `hand_verdict`, `hand_verdict_description`, `new_vs_hybrid`, `strict_confirmed`, `explanation` |
| token_ledger | 281 | Hybrid + recall + ablation + extra-pass token ledger | original ledger fields plus `ledger` (`hybrid`, `recall`, `ablation`, `beamv3`) |

`hand_verdict` means checked against the source by an AI reviewer. It is not a human annotator.

## Limits

- The 45-drift universe is the union of method output, so it favours those methods.
- 11 of 12 libraries were triaged; structlog failed; cattrs needed 2 calls.
- 2 false + 1 unclear received a strict badge (werkzeug S38, S39 false; S41 unclear).
- End-to-end including repro is 9,302,105 (~9.3M) = 4,424,575 + 4,739,392 + 138,138.
- Ablation ledger (local + stability, not in that 9.3M): 1,948,469 tokens over 60 calls.
- Extra coverage-pass ledger (docs + 32k chunks + stability + repro, not in that 9.3M): 7,713,453 tokens over 168 calls.
- Long context did not change verdict accuracy on these 56 candidates; it changed citation grounding.
- 32k docstring chunks recovered 7 of 11 hybrid misses; the docs pass recovered 1. New-item precision is a lower bound (18.5% for hybrid + 32k chunks). Headline stays 34 of 45.

## Citation

DocDrift bugs: docs-vs-code drifts in 12 Python libraries, found with Beam. Labels by an AI reviewer against source at the pinned commit. Dataset: https://huggingface.co/datasets/ollymcbride4/docdrift-bugs
