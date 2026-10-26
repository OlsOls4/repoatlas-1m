# RepoAtlas-1M

RepoAtlas-1M is a fixture-first implementation for Reflection's **Build with Beam** challenge.  
It packs a full repository into a deterministic long-context prompt, runs one structured Beam analysis pass, and verifies every citation deterministically before presenting results.

> **Current default mode:** fixture/offline-safe.  
> Live inference is supported for your local machine with your own key, but CI/tests remain fixture-only.

---

## What is implemented

### 1) Repository packer (deterministic, cache-friendly)

- Fetches public GitHub repositories as tarballs.
- Filters lockfiles, binary files, and vendor/build directories.
- Line-numbers every packed file (`<line>|<text>` format).
- Counts tokens with `cl100k_base`.
- Enforces configurable token cap (default `400000`, max `900000`).
- Produces a stable packed prefix hash for cache reuse.
- Caches packs in `.cache/repoatlas/packs/`.

### 2) DocDrift pipeline (fixture-first, strict structure)

- Uses one structured analysis response schema:
  - `findings[]`: doc citation + code citation + drift type + explanation + proposed fix + optional local patch.
  - `atlas_claims[]`: onboarding claims with citations.
- Deterministic verifier checks:
  - file exists,
  - line ranges are valid,
  - quoted text exists in cited lines.
- Optional runnable probes are supported in code (disabled by default).
- Proposed doc fixes are kept local as patch artefacts only.

### 3) Onboarding atlas tab

- Atlas claims are included in the same structured output format.
- Citation checks are reused for atlas citation precision.

### 4) Benchmark harness + exports

- Sweep runner over repo list and context limits.
- Live benchmark rows are merged into `results_live/benchmark_results.csv` by `(repo_url, token_limit)` so reruns update those keys without dropping other rows.
- Exports:
  - `results/benchmark_results.csv`
  - `results/hand_check_sheet.csv`
  - `results/benchmark_results.jsonl` (HF-dataset-ready rows)
  - per-case traces in `results/traces/`
  - charts in `results/charts/`
- Small-budget mode via `--max-repos`.
- `--dry-run` mode estimates packed token sizes without inference.
- `--repos` allows selecting named repos from a repo catalogue file.

### 5) Gradio app (HF Space-ready pattern)

- Reads **precomputed results only** from `results/` by default.
- Displays:
  - DocDrift findings with verification status,
  - onboarding atlas claims,
  - benchmark table/charts.
- Optional BYOK live run tab for small repos (token cap enforced in UI).

---

## Beam provider configuration

Live client is OpenAI-compatible and supports two providers:

- **Default:** Ollama Cloud
  - `BEAM_PROVIDER=ollama` (default when unset)
  - base URL: `https://ollama.com/v1`
  - endpoint: `/chat/completions`
  - model: `beam`
  - key: `OLLAMA_API_KEY`

- **Optional alternative:** Reflection API
  - `BEAM_PROVIDER=reflection`
  - base URL: `https://api.reflection.ai/openai/v1`
  - endpoint: `/chat/completions`
  - model: `Beam-1.0-501B-A23B`
  - key: `REFLECTION_API_KEY`

### Live safety controls

- Enforces one concurrent live request via file lock.
- Retries on `429` and `5xx` with exponential backoff.
- Caches every live response to disk in `.cache/repoatlas/responses/`, keyed by prompt hash, to prevent re-billing identical calls.
- Uses generous `max_tokens` (`REPOATLAS_MAX_TOKENS`, default `32000`) because reasoning tokens count towards token limits.
- Applies token calibration (`REPOATLAS_TOKEN_CALIBRATION_FACTOR`, default `1.22`) so packer estimates target real prompt-token ceilings.
- Parses `message.content`; if content is empty, reasoning fallback text is captured in raw traces for debugging.

---

## Fixture vs real results (honesty policy)

- Files under `fixtures/` and current `results/` are **fixture artefacts** for offline development and UI demonstration.
- Fixture findings are explicitly labelled `fixture-generated`.
- Do not report fixture artefacts as measured live benchmark outcomes.

---

## Local setup

```bash
python3 -m pip install -e ".[dev]"
```

Or with requirements files:

```bash
python3 -m pip install -r requirements-dev.txt
```

Run tests:

```bash
python3 -m pytest -q
```

Run app:

```bash
python3 scripts/run_app.py --port 43123
```

---

## Exactly how to run the live benchmark (one command)

### Ollama Cloud (default, recommended)

```bash
BEAM_PROVIDER=ollama OLLAMA_API_KEY=YOUR_KEY python3 scripts/run_benchmark.py --max-repos 2 --token-limits 120000,240000,400000
```

Run from the candidate catalogue (select only specific repos, do not fetch all):

```bash
BEAM_PROVIDER=ollama OLLAMA_API_KEY=YOUR_KEY python3 scripts/run_benchmark.py --repos-file benchmarks/repos_candidates.yaml --repos uv,poetry,pnpm --token-limits 120000,240000
```

List candidate repos and one-line reasons:

```bash
python3 scripts/run_benchmark.py --list-repos
```

### Reflection alternative

```bash
BEAM_PROVIDER=reflection REFLECTION_API_KEY=YOUR_KEY python3 scripts/run_benchmark.py --max-repos 2 --token-limits 120000,240000,400000
```

### Dry-run estimation only (no live inference call)

```bash
python3 scripts/run_benchmark.py --dry-run --max-repos 2 --token-limits 120000,240000,400000
```

Dry-run a near-900k real-token budget (with calibration-aware projected prompt tokens):

```bash
python3 scripts/run_benchmark.py --dry-run --repos-file benchmarks/repos_candidates.yaml --repos fastapi --token-limits 900000
```

---

## Make targets

- `make install`
- `make test`
- `make app`
- `make benchmark-fixture`
- `make benchmark-dry-run`
- `make benchmark-live`
- `make analysis-dry-run`

---

## Challenge usage notes for README/HF submission

When preparing the final HF Space README, include:

- exact provider/model used per run,
- context token cap and observed token counts,
- measured latency,
- rate-limit header snapshots,
- statement that cached prompt-prefix reuse is used to reduce billable uncached tokens,
- limitations:
  - very large repos are truncated at token cap,
  - live output quality still depends on model behaviour,
  - unverified findings must remain labelled unverified.
