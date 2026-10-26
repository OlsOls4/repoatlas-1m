# DocDrift baselines: does whole-repo context actually help?

All numbers come from files in this directory, produced on 2026-10-26 by the scripts in `scripts/baseline_*.py`.
The scope is the 9 repos that had true drifts in the 400k sweep (starlette, httpx, click, structlog, nox, arrow, cattrs, marshmallow) plus the zero-find repo attrs.
Each Beam configuration was run once (n=1), so differences of one or two drifts are within run-to-run noise.

## Comparison (9 repos; "true drifts" = the 11 drifts from the whole-repo sweep, checked against the source by an AI reviewer)

| method | calls | prompt tokens | completion tokens | true drifts recovered (of 11) | total findings | precision |
|---|---|---|---|---|---|---|
| Whole-repo Beam (1 call/repo, ~400k) | 9 | 3,256,903 | 44,198 | **11** (9 of them pass the verifier) | 16 | 11/16 = 68.8% |
| Non-AI symbol check (`ast`, 0 cost) | 0 | 0 | 0 | **10** (misses T11) | 32 on these 9 repos (43 on all 12; compare 32 vs 16, not 43 vs 16) | 25/43 = 58.1% across all 43; 65% was a random 20-item sample (seed 20261026); 20/32 = 62.5% on the 9 repos |
| Chunked Beam, ~32k chunks | 129 | 3,318,430 | 211,515 | **3** (T7, T9, T10) | 25 | 15/25 = 60% |
| Chunked Beam, ~128k chunks | 33 | 3,269,063 | 73,138 | **4** (T3, T6, T7, T8) | 13 | 9/13 = 69.2% |

Wall time, summed per call: whole-repo 196 s, 32k 1,807 s, 128k 377 s. Symbol check: seconds.

### Missed true drifts

- Whole-repo missed none of the 11. The 11 were defined from this method's own output, so that result is circular.
- Symbol check missed T11 (marshmallow ``default`` in prose, `docs/top_level.rst:12-14`). It does not check prose.
- 32k chunks missed T1, T2, T3, T4, T5, T6, T8 and T11.
- 128k chunks missed T1, T2, T4, T5, T9, T10 and T11.

T1 starlette receive_json · T2 httpx.Mounts · T3 httpx Client(app=) · T4 click FileType · T5 structlog _NAME_TO_LEVEL · T6 nox reuse_venvs · T7 arrow timestring · T8 cattrs ForbiddenExtraKeyError · T9/T10 cattrs :param cache: · T11 marshmallow ``default``

### Union view: every true drift any method found on these 9 repos

There are 33 distinct true drifts checked against the source by an AI reviewer: the 11 known ones, 9 new ones from the symbol check, and 13 new ones from chunked Beam.

| method | distinct true drifts found (of 33) |
|---|---|
| Whole-repo Beam | 11 |
| Symbol check | 19 |
| Chunked 32k | 15 |
| Chunked 128k | 9 |

The whole-repo run found none of the 22 new drifts. Most of them are minor:
- wrong/removed kwargs in doc examples: `httpx.get/request(extensions=)`, nox `conda_install(channels=)`, marshmallow `pass_many=`
- stale param names: cattrs typeddicts, marshmallow Url `:param default:`, arrow optional `end`
- base64 vs base85 (cattrs ujson)
- 400 vs 422 (marshmallow example)
- the old 5-argument `handle_request` in httpx transport docs
- `httpx.SSLContext()` in CONTRIBUTING
- broken cross-references

## What co-location explains (`colocation.json`)

Drifts were recovered only when the doc site and the defining code landed in the same chunk, with one exception:
- At 32k, only T7, T9 and T10 were co-located, and exactly those 3 were recovered.
- At 128k, T2, T3, T7, T8, T9, T10 and T11 were co-located. Of those, T3, T7 and T8 were recovered. T6 was recovered even though it was not co-located, because the docs/tests chunk held enough of the nox option names.

So chunking loses the cross-file drifts (a doc names an API defined elsewhere). Whole-repo context fixes that, but a 0-token symbol resolver also fixes it, for every drift that is a name or signature mismatch.

## Blunt verdict

- **Whole-repo beat the chunked Beam baselines decisively, at the same token cost.** On the known drifts it recovered 11/11 vs 3/11 (32k) and 4/11 (128k) for about the same ~3.3M prompt tokens. Precision was similar (60–69%).
- **Whole-repo did not clearly beat the non-AI baseline.** The `ast` symbol check costs nothing, recovers 10/11 of the same drifts at 25/43 = 58.1% precision across all 43 flags (65% was a 20-item sample), and found 9 extra true drifts on these repos that whole-repo missed. On the same 9 repos the finding counts are 32 vs 16, not 43 vs 16. Its one miss (T11) is a prose drift. Caveat: the check types (docstring `:param:`, exception names, Sphinx roles) were designed knowing the target drifts, so 10/11 is optimistically biased. They are still standard checks (darglint / Sphinx nitpicky style).
- **The "of 11" metric is biased toward whole-repo,** because the 11 came from whole-repo's own output. On the union of 33 true drifts, whole-repo found 11, fewer than the symbol check (19) and fewer than 32k chunking (15). Chunking finds more local, within-file drifts because each call reads less text more closely.
- Fair claim: whole-repo context is what lets an LLM catch cross-file drifts. Chunking cannot, at equal cost. Unfair claim: that whole-repo is the best detector. A cheap resolver plus local LLM passes would beat it on recall.

## Method notes

- **Chunks** are rebuilt from the exact pack in `results_live/traces/<repo>-400000.json`, in the pack's own file order (no oracle pairing).
  - Files are kept whole unless a file is larger than a chunk. Larger files are split at line boundaries and keep their original line numbers.
  - The prompt (`repoatlas/prompts.py`) is unchanged. The verifier runs against the full pack.
  - Findings are deduped by doc and code path plus line (±3).
  - Calls were sequential, with retries disabled.
- **128k errors:** 2 calls returned no `message.content` (reasoning only): starlette chunk 1 and attrs chunk 0. Their tokens still count. There were no HTTP errors, 402s or 429s.
- **Verifier:** some true chunked findings fail it because of quote or line offsets (T8@128k, T3@128k, cattrs typeddicts). The precision figures above use `hand_verdict` (checked against the source by an AI reviewer).
- **Symbol check:** 43 flags on 12 repos; per-flag verdicts with evidence are in `baselines.json`.
  - The random 20 (seed 20261026) came out 13 true / 7 false. That sample happened to contain 5 of the known drifts.
  - The full 43 came out 25 true / 15 false / 3 unclear.
  - Main false-positive sources: example code using other libraries (requests, rich, dict), user-defined example exceptions, and WSGI environ keys that look like module paths.
- **Beam usage by this work:** 162 calls, 6,587,493 prompt + 284,653 completion = 6,872,146 tokens. See `beam_usage_ledger.json`; cached replays are not counted.
