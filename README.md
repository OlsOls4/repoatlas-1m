---
title: RepoAtlas-1M
emoji: 🛰️
colorFrom: indigo
colorTo: emerald
sdk: gradio
app_file: app.py
short_description: DocDrift v2 — symbol check + Beam whole-repo triage + executable repro.
tags:
  - beam
  - long-context
  - docs
  - code
  - verification
  - gradio
---

# RepoAtlas-1M

![RepoAtlas hero](docs/hero.png)

## Headline result

**34 real docs bugs across 12 Python libraries at 75% precision; 29 confirmed by running the docs (92.3% precision).**

Numbers above come from `results_live/hybrid/hybrid.json` / `hybrid.csv` (DocDrift v2). The 12 libraries are starlette, httpx, click, structlog, nox, arrow, cattrs, marshmallow, attrs, jinja, werkzeug and pydantic-settings.

DocDrift v2 pipeline:

1. A free symbol check proposes candidates (name and signature mismatches).
2. Beam reads each library's docs and source (~300–400k tokens) in one call, triages each candidate with cited evidence and a suggested fix, and adds cross-file/prose drifts the script missed.
3. An executable repro keeps findings that raise a real API error (TypeError / AttributeError / ImportError / NameError).

Starlette story (canonical upstream repo):

- Canonical repo: **https://github.com/Kludex/starlette** (GitHub redirects from encode/starlette).
- Recorded run prompt size: **394,577** tokens.
- Drift: docs line used `receive_json(data, mode="binary")` while code signature has no `data` parameter.
- Result: hand-verified true drift.
- Upstream state: **fix submitted upstream (PR #3746, open)**  
  https://github.com/Kludex/starlette/pull/3746

## What is docs drift?

Docs drift means docs and code disagree in a way that can break users who follow the docs.
Example from starlette:

- docs/websockets.md line 74: `websocket.receive_json(data, mode="binary")`
- starlette/websockets.py line 136: `async def receive_json(self, mode: str = "text") -> Any:`
- following the docs can raise: `TypeError` (multiple values for `mode`)

## How Beam is used (required challenge section)

1. **One packed docs+source call into long context**  
   RepoAtlas packs docs plus source into one deterministic, line-numbered prompt, then submits one Beam call per run.
2. **Structured JSON schema output**  
   Beam is asked for strict structured output (`findings[]`, `atlas_claims[]`) so each claim has explicit citations.
3. **Deterministic citation verifier**  
   Every finding is checked against packed source lines. Exact quote matching is required, with a controlled **±3-line shift** tolerance for off-by-one citation ranges.
4. **Token calibration factor**  
   Prompt budgeting uses a calibration factor of **1.22x** (`REPOATLAS_TOKEN_CALIBRATION_FACTOR`) between estimated and observed prompt tokens.
5. **Why long context rather than chunked RAG**  
   Many true drifts require a docs citation and a far-away code citation in the same pass. A single packed prompt keeps those relationships available without retrieval misses.
6. **DocDrift v2 hybrid**  
   Beam is not used as a raw detector. A free checker proposes candidates; one whole-repo Beam call triages them and can add missed cross-file/prose drift; a later executable check confirms the ones that raise a real API error.

## DocDrift v2 comparison

From `results_live/hybrid/hybrid.csv` (12 libraries; distinct true measured against a 45-drift union) plus the earlier 9-repo chunked baselines in `results_live/baselines/baselines.csv`:

| Method | True drifts found | Findings | Precision | Tokens |
|---|---|---|---|---|
| Symbol check alone | 24 of 45 | 43 | 58.1% | 0 |
| Whole-repo Beam alone | 11 of 45 | 19 | 57.9% | 4,424,575 |
| Chunked Beam (~32k, 9-repo baseline) | 3 of 11 known | 25 | 60% | 3,529,945 |
| Chunked Beam (~128k, 9-repo baseline) | 4 of 11 known | 13 | 69.2% | 3,342,201 |
| Hybrid (symbol + whole-repo Beam triage) | **34 of 45** | 60 | **75%** | 4,739,392 |
| Hybrid + repro-confirmed (strict) | **29 of 45** | 39 | **92.3%** | 4,877,530 |

Honest notes, also from `hybrid.json`:

- The **45-drift reference set** is the union of what the methods found, so it favours them.
- Beam triage judged **56** candidates and rejected **0** hand-true candidates, while keeping **9** false or unclear ones.
- **structlog triage failed** (no JSON; 8,794 chars of prose), so its 6 candidates stay untriaged and have no repro.
- Chunked Beam alone found **11** local docstring/prose drifts the hybrid misses.
- The strict repro rule was set after the first repro run.
- No prompt caching was observed on triage calls.

## Earlier whole-repo-only sweep (recorded runs)

All values below are from `results_live/index.json`, generated from:
- `results_live/benchmark_results_combined.csv`
- `results_live/handcheck.md`
- `results_live/reverify_line_shift.json`
- `results_live/upstream_status.json`

- **All live hand-checked findings:** 11 true / 8 false / 2 unclear = **11/21 (52.4%)**
- **Verifier behaviour (all runs):** caught **4/8** false positives; wrongly rejected **1** true drift.
- **Verifier behaviour (11-repository subset):** caught **4/7** false positives.
- **Cross-file framing:** **8/11** true drifts are cross-file, median **89,192** tokens apart, max **122,786**.
- **Prior-art check:** **9/11** true drifts had no prior upstream PR or issue when checked.
- **Token spend:** **5.81M** prompt + **82k** completion tokens on Beam, `$0` via Ollama Cloud free tier.
- **Truncation footnote:** **10/17** packs were trimmed (tests/benchmarks dropped first; traces do not always include exact dropped paths).
- **1M naming honesty:** RepoAtlas-1M is the model-window target; current recorded long-context runs are ~294k–404k prompt tokens (plus two earlier 120k pilot runs).
- **Maintainer effort signal:** about 1 in 1.9 findings is a real drift; each check takes ~2 minutes with the SHA-pinned permalinks.

### Full run table

| Run | Prompt tok | Completion tok | Latency s | Findings | Verifier pass | Hand true | Hand false | Hand unclear |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| flask-120000 | 142,664 | 3,692 | 21.13 | 0 | 0 | 0 | 0 | 0 |
| fastapi-120000 | 146,415 | 1,834 | 12.00 | 0 | 0 | 0 | 0 | 0 |
| starlette-400000 | 394,577 | 4,733 | 21.36 | 1 | 0 | 1 | 0 | 0 |
| typer-400000 | 387,284 | 8,653 | 36.12 | 0 | 0 | 0 | 0 | 0 |
| hatch-400000 | 385,297 | 5,137 | 23.39 | 1 | 0 | 0 | 0 | 1 |
| poetry-400000 | 384,598 | 4,287 | 46.22 | 1 | 1 | 0 | 1 | 0 |
| httpx-400000 | 392,598 | 4,053 | 21.15 | 2 | 2 | 2 | 0 | 0 |
| click-400000 | 388,719 | 4,698 | 21.79 | 1 | 1 | 1 | 0 | 0 |
| attrs-400000 | 400,648 | 4,102 | 22.15 | 0 | 0 | 0 | 0 | 0 |
| pydantic-settings-400000 | 366,051 | 5,378 | 26.05 | 1 | 1 | 0 | 1 | 0 |
| structlog-400000 | 403,833 | 6,118 | 24.90 | 2 | 1 | 1 | 1 | 0 |
| jinja-400000 | 356,873 | 5,311 | 25.72 | 1 | 0 | 0 | 0 | 1 |
| nox-400000 | 346,394 | 7,014 | 27.42 | 1 | 1 | 1 | 0 | 0 |
| arrow-400000 | 329,026 | 4,457 | 15.86 | 4 | 1 | 1 | 3 | 0 |
| cattrs-400000 | 306,549 | 4,107 | 21.17 | 3 | 3 | 3 | 0 | 0 |
| marshmallow-400000 | 294,559 | 4,916 | 19.71 | 2 | 2 | 1 | 1 | 0 |
| werkzeug-400000 | 386,415 | 3,446 | 17.93 | 1 | 0 | 0 | 1 | 0 |

## Where long context helps (planted-drift test)

This section is sourced from `results_live/recall/` (`context_probe.json`, `recall_by_bucket.csv`, `run_summary.json`, `usage_ledger.json`, `recall.md`).

- **Prompt-size probe:** Beam accepted prompts up to **947,446** prompt tokens in this setup.
- **700k+ separation bucket:** focused whole-context passes hit **5/6** plants on seed 1; chunked 128k and 32k both hit **0/6**.
- **Overall strict recall:** single whole-prompt calls were not better than chunking on seed 1 (**5/30** whole vs **5/30** chunk128k and **5/30** chunk32k).
- **Focused-pass variant:** **11/30** strict on seed 1, at higher cost (4,755,853 tokens total vs 970,653 and 1,029,696 for the chunked runs; roughly 4.6-4.9x). Beam still reported about **934k-940k cached prompt tokens** on focused passes 2-5.
- **Seed-2 check:** the docs-focused pass reached **5/28** vs **4/28** for single whole-prompt seed 2 (partial hold).
- **Docstring limitation:** single-call whole-context variants mostly miss planted Python docstring drifts (best observed **1/32** in docs-last single-call runs).
- **Caveats:** one run per configuration, 4-6 plants per bucket, and small samples.

Practical recipe supported by this data: **use whole-repo context for a docs-focused audit (to catch long-range drift chunking cannot see), plus cheap chunked passes for docstrings.**

![Planted-drift recall by distance](results_live/recall/recall_vs_distance.png)

## Space behaviour

- Default view is recorded data (no inference cost).
- Hero, comparison table, and hybrid notes come from `results_live/hybrid/hybrid.json` / `hybrid.csv`.
- Bug wall includes hybrid true drifts plus earlier recorded-run cards, sorted cross-file first.
- Findings, atlas, recall, and earlier baselines stay available below the v2 headline.
- Findings tab defaults to starlette and shows verifier status separately from hand-check verdict.

## Live tab guardrails

- Provider from environment:
  - `BEAM_PROVIDER=ollama` uses `OLLAMA_API_KEY` with `https://ollama.com/v1` and model `beam`.
  - `BEAM_PROVIDER=reflection` is also supported.
- Live execution is blocked if required secrets are missing.
- Default and maximum pack cap in-app: **150k**.
- Queue concurrency: **1**.
- Per-IP session limit: **2 runs per hour**.
- Global daily cap: `REPOATLAS_LIVE_DAILY_CAP` (default 24).
- Hidden progress log is emitted during live runs.
- If `OLLAMA_API_KEY` is missing, the tab shows a recorded replay mode instead of a disabled blank state.
- API keys are never echoed in UI output.

## Dataset export

`dataset/` is prepared for companion publication and includes:

- `dataset/README.md` (dataset card),
- `dataset/runs.jsonl`,
- `dataset/findings.jsonl`,
- `dataset/upstream_status.json`,
- `dataset/reverify_line_shift.json`,
- full `dataset/traces/` and `dataset/upstream_drafts/`.

## Limitations

- Sample size remains limited.
- Verifier pass/fail is **not** correctness; it only checks citation alignment.
- Long-context outputs still include false positives and unclear calls.
- A true drift can still be rejected by strict citation matching.

## Reproduce locally

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/build_results_live_index.py
python3 -m pytest -q
python3 app.py
```

Optional live benchmark command:

```bash
BEAM_PROVIDER=ollama OLLAMA_API_KEY=YOUR_KEY python3 scripts/run_benchmark.py --repos-file benchmarks/repos_sweep_2026-10-26.yaml --repos httpx,click,attrs,pydantic-settings,structlog,jinja,nox,arrow,cattrs,marshmallow,werkzeug --token-limits 400000 --output-dir results_live
```
