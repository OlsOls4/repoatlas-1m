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
  - config_name: matched_cost_ext_verdicts
    data_files: matched_cost_ext_verdicts.parquet
  - config_name: beamv3_findings
    data_files: beamv3_findings.parquet
  - config_name: token_ledger
    data_files: token_ledger.parquet
license: cc-by-4.0
size_categories:
  - n<1K
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

```python
from datasets import load_dataset
ds = load_dataset("ollymcbride4/docdrift-bugs", "findings")
```

- Space: https://huggingface.co/spaces/ollymcbride4/docdrift
- Demo video: https://huggingface.co/spaces/ollymcbride4/docdrift/resolve/main/assets/docdrift-demo.mp4
- Code: https://github.com/OlsOls4/repoatlas-1m
- Dataset: https://huggingface.co/datasets/ollymcbride4/docdrift-bugs
- HF thread: https://huggingface.co/reflection/Beam-1.0-501B-A23B/discussions/5

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
| ablation_verdicts | 56 | Whole-repo vs local-file vs matched-cost retrieval triage on the same 56 candidates | `key`, `repo`, `candidate_id`, `label`, `hand_verdict`, `hand_verdict_description`, `cross_file`, `gold_outside_local`, `whole_verdict`, `local_verdict`, `matched_verdict`, `stability_verdict`, citation flags |
| matched_cost_ext_verdicts | 63 | Scored pre-registered extension items only (63 rows in this file; 49 cross-file, 48 outside-local). Pooled 52/78 includes the original 56 from `ablation_verdicts`; those original rows are not duplicated here. | `key`, `set`, `stratum`, `label`, `hand_verdict`, `cross_file`, `gold_outside_local`, per-arm `whole_` / `local_` / `matched_` verdicts and citations |
| beamv3_findings | 115 | Extra 32k-docstring-chunk and docs-pass findings (unlabelled not counted as true) | `id`, `repo`, `pass`, `doc_path`, `doc_line`, `label`, `drift_id`, `label_by`, `hand_verdict`, `hand_verdict_description`, `new_vs_hybrid`, `strict_confirmed`, `explanation` |
| token_ledger | 493 | Hybrid + first-sweep + ablation + extra-pass token ledger | original ledger fields plus `ledger` (`first_sweep`, `hybrid`, `ablation`, `beamv3`, `matched_cost`, `matched_cost_ext`, `fresh_run`) |

`hand_verdict` means checked against the source by an AI reviewer. It is not a human annotator.

## Limits

- The 45-drift universe is the union of method output, so it favours those methods. The 45 true hybrid findings are a different set from those 45 pooled drifts.
- 11 of 12 libraries were triaged; structlog failed; cattrs needed 2 calls.
- 2 false + 1 unclear received a strict badge (werkzeug S38, S39 false; S41 unclear).
- End-to-end including repro is 9,302,105 (~9.3M) = 4,424,575 first sweep + 4,739,392 hybrid triage + 138,138 repro. The first sweep is in `token_ledger` as `ledger=first_sweep` (12 rows from the recorded 400k traces).
- Extra experimental runs, not in the 9.3M: ablation 1,948,469; beam v3 7,713,453; matched-cost control 3,957,434; matched-cost extension 7,528,878; tomlkit CLI run 185,842. Matched-cost controls plus the recording: 11,672,154.
- Long context did not change verdict accuracy on these 56 candidates; it changed citation grounding. A matched-cost retrieval control (96.7% of whole-repo spend) matched accuracy (46/56 vs 47/56) but not grounding (cross-file 19/30 vs 25/30; McNemar p = 0.070, not shown at this n). Retrieval missed the defining file in 5 of 13 outside-local items. A pre-registered extension added 63 items (57 planted renames, 6 real structlog). Pooled, retrieval grounded 38/78 cross-file cases vs 52/78 for the whole repo (McNemar p = 0.0094). Outside-local: 38/61 vs 25/61 (p = 0.0146). Accuracy still did not differ (105/118 vs 108/119). The new items alone give p = 0.096 (not shown at this n), and the pooled p is 0.18 without one pre-registered parse-failure re-send. Pre-registration: design_ext.md sha256 42f6b6fe…c996.
- 32k docstring chunks recovered 7 of 11 hybrid misses; the docs pass recovered 1. New-item precision is a lower bound (18.5% for hybrid + 32k chunks). Headline stays 34 of 45.

## Citation

DocDrift bugs: docs-vs-code drifts in 12 Python libraries, found with Beam. Labels by an AI reviewer against source at the pinned commit. Dataset: https://huggingface.co/datasets/ollymcbride4/docdrift-bugs
