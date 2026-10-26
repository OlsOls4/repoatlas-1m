# Beam v3: docs-focused pass + Python-docstring 32k chunks + stability repeat

Scored by `scripts/beamv3_analyze.py` with no new Beam calls. Ground truth = existing labelled set (45-true union in hybrid.json; hybrid/chunked/symbol/index labels). Unlabelled findings are not counted as true. 15 findings labelled by AI reviewer (Grok Bot) checking against source at pack ref, 2026-10-26 (marked label_by). Unclear counts as not-true.

## Did it recover hybrid's 11 missed drifts?

**8 of 11 recovered.**

| drift | recovered | by |
|---|---|---|
| C:arrow-interval-end | yes | py:arrow#4:DD-4 |
| C:arrow-span_range-end | yes | py:arrow#4:DD-5 |
| C:attrs-force_kw_only | yes | docs:attrs:DD-1 |
| C:attrs-py2-reprs | no | - |
| C:cattrs-td251 | yes | py:cattrs#2:DD-2 |
| C:cattrs-td59 | yes | py:cattrs#2:DD-1 |
| C:cattrs-ujson-b85 | yes | py:cattrs#3:DD-1 |
| C:httpx-sslcontext | no | - |
| C:mm-quotes-400 | no | - |
| C:nox-tasks-returns | yes | py:nox#2:DD-1 |
| C:structlog-output-args | yes | py:structlog#2:DD-1 |

py32k recovered the docstring drifts. The docs pass recovered only C:attrs-force_kw_only. The 3 that were still missed are all prose-doc drifts (httpx CONTRIBUTING sslcontext, marshmallow quotes_api example, attrs api.rst py2 reprs).

## Modes

Precision LB = labelled-true / all findings. Unlabelled findings count as not-true, so this is a lower bound. 'Among labelled' is biased upward, because the labelled findings are the ones that hit known items. 'Of 45' = distinct drifts from the existing 45-true union. 'New (AI)' = distinct new trues from the 15-item AI check.

| mode | findings | true | false | unclear | unlabelled | precision LB | among labelled | of 45 | extra of 45 vs hybrid | new (AI) | tokens | tokens / distinct true | marginal tokens / extra drift |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Hybrid (existing, for reference) | 60 | 45 | - | - | - | 75.0% | - | 34 | - | - | 4,739,392 | 139,394 | - |
| Hybrid + repro strict (existing) | 41 | 38 | - | - | - | 92.7% | - | 30 | - | - | 4,877,530 | - | - |
| (a) docs-focused pass alone | 43 | 17 | 8 | 2 | 16 | 39.5% | 63.0% | 15 | 1 | 2 | 4,485,924 | 263,878 | - |
| (b) py32k docstring chunks alone | 72 | 18 | 3 | 5 | 46 | 25.0% | 69.2% | 13 | 7 | 5 | 1,680,568 | 93,365 | - |
| Hybrid + (a): new items only | 26 | 4 | 4 | 2 | 16 | 15.4% | 40.0% | 35 | 1 | 2 | 9,225,316 | 249,333 | 1,495,308 |
| Hybrid + (b): new items only | 65 | 12 | 3 | 5 | 45 | 18.5% | 60.0% | 41 | 7 | 5 | 6,419,960 | 139,564 | 140,047 |
| Hybrid + (a) + (b): new items only | 91 | 16 | 7 | 7 | 61 | 17.6% | 53.3% | 42 | 8 | 7 | 10,905,884 | 222,569 | 411,099 |
| Hybrid + v3 new items strict-confirmed by repro | 17 | 4 | 0 | 0 | 13 | 23.5% | 100.0% | 36 | 2 | 2 | 11,344,203 | 298,532 | 1,651,203 |

In the 'Hybrid + ...' rows, findings, true, false, unclear and unlabelled count only the v3 items that are new after dedupe against hybrid's 60 (repo, path, line ±3). Tokens are hybrid's plus the pass's. 'Marginal' = the pass's own tokens / extra distinct true drifts it added.

- (a) docs-focused pass alone: AI-check sample 2/7 true (Wilson 95% [0.082, 0.641]). Applying that rate to the unlabelled gives estimated precision ≈ 50%. This is rough because the sample is small.
- (b) py32k docstring chunks alone: AI-check sample 5/8 true (Wilson 95% [0.306, 0.863]). Applying that rate to the unlabelled gives estimated precision ≈ 65%. This is rough because the sample is small.
- Sensitivity (NOT ground truth) for (a) docs-focused pass alone: if the interrupted run's own unreviewed AI labels are accepted for the unlabelled, true=26, precision=60%, distinct new drifts=11.
- Sensitivity (NOT ground truth) for (b) py32k docstring chunks alone: if the interrupted run's own unreviewed AI labels are accepted for the unlabelled, true=41, precision=57%, distinct new drifts=27.
- Sensitivity (NOT ground truth) for Hybrid + (a) + (b): new items only: if the interrupted run's own unreviewed AI labels are accepted for the unlabelled, true=47, precision=52%, distinct new drifts=38.
- The AI source check agreed with those prior-run labels on true/not-true for 15/15 (13/15 exact; the 2 differences were false→unclear).

Extra true drifts beyond hybrid's 34:
- From the 45 union: C:arrow-interval-end, C:arrow-span_range-end, C:attrs-force_kw_only, C:cattrs-td251, C:cattrs-td59, C:cattrs-ujson-b85, C:nox-tasks-returns, C:structlog-output-args.
- New, AI-verified (not in any labelled set): N3:attrs-examples-attribute-repr, N3:click-progressbar-hidden, N3:jinja-parse_tuple-no_condexpr, N3:mm-email-args, N3:nox-list-header, N3:wz-expose-headers-doc, N3:wz-proxymw-remove_prefix.

## Stability repeat (triage re-run on httpx, click, cattrs)

Candidate verdict agreement: **18/19 (94.7%)**.

| repo | candidates | agree | flips | additions orig / repeat | overlap (Jaccard) | repeat tokens |
|---|---|---|---|---|---|---|
| httpx | 10 | 10 | - | 5 / 5 | 3/7 | 403,628 |
| click | 2 | 2 | - | 0 / 0 | n/a | 391,260 |
| cattrs | 7 | 6 | S25 true_drift→false | 0 / 0 | n/a | 313,754 |

The one flip is cattrs S25 (labelled true, T8), which the repeat rejected. The httpx additional findings only partly reproduce (3 of 7 distinct in both runs).

## Repro on the new items

91 attempted; status {'reproduced': 63, 'could_not_run': 20, 'not_reproduced': 8}. Strict-confirmed (reproduced + interface_error): 17, by label {'unlabelled': 13, 'true': 4}. All new items by label: {'false': 7, 'unlabelled': 61, 'unclear': 7, 'true': 16}.

## Tokens (ledger)

| kind | calls | prompt | completion | total |
|---|---|---|---|---|
| py32k | 62 | 1,527,453 | 153,115 | 1,680,568 |
| triage | 3 | 1,090,253 | 18,389 | 1,108,642 |
| docs | 12 | 4,369,786 | 116,138 | 4,485,924 |
| repro | 91 | 226,815 | 211,504 | 438,319 |
| **total** | 168 | | | **7,713,453** |

Detection cost of the v3 passes = docs + py32k = 6,166,492; repro adds 438,319; the stability repeat (1,108,642) is measurement only. Hybrid's own Beam tokens 4,739,392 + all v3 = 12,452,845. This excludes the earlier sweep, which brings hybrid end-to-end to ~9.2M.

## What this means for the Space

This belongs in a Benchmark-tab section; the headline should stay as it is. Adding py32k to hybrid is the cheap win: about 1.7M tokens bring in 7 of the 11 missed labelled drifts plus 5 AI-verified new ones (~140k tokens per extra drift). But the v3 findings that are new after dedupe have a measured precision of only 18-53%; most are unlabelled. The docs-focused pass costs 4.5M tokens for 1 recovered labelled drift and 2 AI-verified new ones. Three prose drifts are still missed. No new number here is hand-labelled at the level of the existing 45-true union.

## Notes

- The AI check used /workspace/sweep/<repo> at the pack refs (starlette at /workspace/repro_src/starlette 8aa828c). The .cache/repoatlas/packs directory holds pack JSONs, not git clones.
- This supersedes the preliminary beamv3.json/csv written by the interrupted run. That file counted its own unreviewed labels as true and mislabelled docs:marshmallow:DD-4 as a new drift; it is the known T11.
- Per-finding labels, evidence and label_by are in results.json under `findings`.
