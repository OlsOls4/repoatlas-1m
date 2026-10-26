---
title: RepoAtlas-1M
emoji: 🛰️
colorFrom: indigo
colorTo: emerald
sdk: gradio
app_file: app.py
short_description: Beam-powered whole-repo DocDrift finder with hand-checked benchmark evidence.
tags:
  - beam
  - long-context
  - docs
  - code
  - verification
  - gradio
---

# RepoAtlas-1M

## Hero media

- Hero screenshot: `docs/hero.png`
- Animated demo placeholder: add your GIF at `docs/hero.gif` and reference it here once available.

![RepoAtlas hero](docs/hero.png)

## Headline result

**11 hand-verified docs bugs in popular Python libraries, found by Beam reading each whole repo (~300–400k tokens) in a single call.**

Signature story:

- Canonical repo: **https://github.com/Kludex/starlette** (GitHub redirects from encode/starlette).
- Beam read a 394,577-token prompt and flagged the `receive_json(data, mode="binary")` doc line against the implementation signature.
- Hand-verified true drift.
- **Fix submitted upstream (PR #3746, open):** https://github.com/Kludex/starlette/pull/3746

## How Beam is used

1. **One whole-repo call into long context**  
   RepoAtlas packs an entire repository into one prompt (line-numbered, deterministic format), then submits a single Beam call per run.
2. **Structured JSON schema output**  
   Beam is asked for strict structured output (`findings[]`, `atlas_claims[]`) so each claim has explicit citations.
3. **Deterministic citation verifier**  
   Every finding is checked against packed source lines. Exact quote matching is required, with a controlled **±3-line shift** tolerance for off-by-one citation ranges.
4. **Token calibration factor**  
   Prompt budgeting uses a calibration factor of **1.22x** (`REPOATLAS_TOKEN_CALIBRATION_FACTOR`) between estimated and observed prompt tokens.
5. **Why long context rather than chunked RAG**  
   Many drifts require a docs citation and a distant code citation in the same pass. One packed prompt keeps those relationships available without retrieval misses.

## Results (real live runs only)

All values below come from `results_live/handcheck.md` and `results_live/benchmark_results_combined.csv`.

- **All live hand-checked findings:** 11 true / 8 false / 2 unclear = **11/21 (52.4%)**
- **Verifier caveat from hand-check:** caught **4/7** false positives, but wrongly rejected **1** true drift.
- **Upstream status source:** `results_live/upstream_status.json`
  - starlette: fix submitted upstream (PR #3746, open)
  - httpx-mounts and arrow: independently confirmed by open upstream PRs

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

## Space behaviour

- Default tab is cached, from `results_live/index.json` (no inference cost).
- Hero banner stats are data-derived:
  - 11 verified docs bugs,
  - 13 repos around 300k–400k prompt tokens,
  - 1 call per repo,
  - 52.4% hand-checked precision.
- Bug wall shows one card per true drift, including upstream status and token distance when derivable from pack order.
- Findings tab supports verdict filtering (`true`, `false`, `unclear`) and defaults to starlette.

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
- API keys are never echoed in UI output.

## Dataset export

`dataset/` is prepared for companion publication and includes:

- `dataset/README.md` (dataset card),
- `dataset/runs.jsonl`,
- `dataset/findings.jsonl`,
- `dataset/upstream_status.json`,
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

Optional live sweep command:

```bash
BEAM_PROVIDER=ollama OLLAMA_API_KEY=YOUR_KEY python3 scripts/run_benchmark.py --repos-file benchmarks/repos_sweep_2026-10-26.yaml --repos httpx,click,attrs,pydantic-settings,structlog,jinja,nox,arrow,cattrs,marshmallow,werkzeug --token-limits 400000 --output-dir results_live
```
