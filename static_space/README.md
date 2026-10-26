---
title: DocDrift
emoji: 🛰️
colorFrom: indigo
colorTo: green
sdk: static
app_file: index.html
short_description: Beam finds real docs-vs-code bugs in Python libraries
tags:
  - beam
  - long-context
  - docs
  - code
  - verification
  - static
---

# DocDrift

Repo name: RepoAtlas-1M. **DocDrift v2** finds docs drift (docs say one thing, code does another) in Python libraries. A free symbol check proposes candidates. Beam reads each library's docs and source (about 300–400k tokens) to triage them and add cross-file or prose drift. 11 of 12 libraries were triaged in one call; structlog failed; cattrs needed 2 calls. A generated script then runs the documented usage and keeps the ones that raise a real API error.

**Results:** 34 real docs bugs in 12 Python libraries. 3 in 4 flagged findings were real (45 of 60); 29 bugs reproduce a real API error when you run the docs. Beam's triage threw away 0 of 32 real bugs.

Filed upstream: [starlette #3746](https://github.com/Kludex/starlette/pull/3746) (open) and [nox #1216](https://github.com/wntrblm/nox/pull/1216) (open). httpx #3774 and arrow #1355 were already reported upstream by others.

This Space is **static** because Hugging Face now requires a PRO subscription to host Gradio or Docker Spaces on free CPU Basic. The Gradio app (`app.py`) is still in the repository and unchanged in behaviour if a hosting grant arrives.

## What is docs drift?

Docs and code disagree in a way that can break users who follow the docs. Starlette example: `docs/websockets.md` line 74 calls `receive_json(data, mode="binary")`; `starlette/websockets.py` line 136 is `receive_json(self, mode: str = "text")`. Following the docs can raise `TypeError`.

## How Beam is used

Numbers below come from `results_live/hybrid/hybrid.json`, `results_live/hybrid/repros/repros.json`, and `results_live/recall/`.

1. Triage filter, not a raw detector. A free AST symbol check proposes name and signature mismatches. Beam judged 56 candidates across 11 of 12 libraries (structlog failed; cattrs needed 2 calls). It rejected 0 of 32 true candidates and removed 15 of 24 false or unclear ones.
2. New finds. Beam added 9 true drifts the checker missed (7 new to the union), taking distinct trues from 24 to 34.
3. Repro author. Beam wrote every doc-literal repro script (138,138 tokens). 29 distinct bugs reproduce a real API error. 36 of 39 badges were real. 2 false + 1 unclear (werkzeug S38, S39 false; S41 unclear) received a strict badge.
4. Long context, measured. Beam accepted prompts up to 947,446 tokens. Focused whole-context passes hit 5/6 plants 700k+ tokens apart vs 0/6 for chunking on seed 1 only, at ~4.8× tokens (4,755,853 vs ~1.0M). A single whole-prompt call alone is not a better detector than chunking or a symbol check. Docstring single-call score: 1/32 pooled over 2 seeds (0/18 + 1/14).

## Glossary

- Triage: Beam judges symbol-check and whole-repo candidates as true_drift, false, or unclear against one packed library prompt.
- Strict badge: TypeError, AttributeError, ImportError, or NameError raised on a DOC-LITERAL usage line.
- Line-shifted match: the cited quote matched packed source within ±3 lines of the model-cited line.
- hand_verdict: stored field name. It means checked against the source by an AI reviewer, not a human annotator.

## Limits

- The 45-drift universe is the union of method output, so it favours those methods.
- Labels were checked against the source by an AI reviewer. The stored field is still hand_verdict.
- Citation check means quote alignment of cited lines vs packed source, with a ±3-line shift allowed. It is not a verdict that the drift is real.
- A true drift can still fail the strict repro rule (starlette T1, marshmallow T11, structlog untriaged, werkzeug input_stream).
- 2 false + 1 unclear (werkzeug S38, S39 false; S41 unclear) received a strict repro badge.
- Filed by this project. Open, not merged. Recorded in results_live/upstream_status.json.
- httpx #3774 and arrow #1355 were already reported upstream by others.
- cattrs and click have drafts in the repo; they are not listed as filed.
- This page is a static recording. Hugging Face now requires PRO to host Gradio on free CPU Basic. The Gradio app in app.py is unchanged if a grant arrives.

## Run it on your repo

```bash
docdrift run https://github.com/OWNER/REPO --max-tokens 400000
```

Create a free Ollama Cloud account at https://ollama.com, open Settings, and create an API key. Export it as OLLAMA_API_KEY. No key is stored in this Space or in the archive.

Recorded Space / Gradio app:

```bash
python3 -m pip install -r requirements-dev.txt && python3 scripts/build_results_live_index.py && python3 -m pytest -q && python3 app.py
```

Earlier whole-repo sweep (your key; none is embedded here):

```bash
BEAM_PROVIDER=ollama OLLAMA_API_KEY=YOUR_KEY python3 scripts/run_benchmark.py --repos-file benchmarks/repos_sweep_2026-10-26.yaml --repos httpx,click,attrs,pydantic-settings,structlog,jinja,nox,arrow,cattrs,marshmallow,werkzeug --token-limits 400000 --output-dir results_live
```

## Exclusions

This static folder does not include:

- results_live/traces/*.json raw traces (only starlette-400000 summary and pack metadata are embedded in replay.json)
- results_live/hybrid/repros/*/attempts.json per-attempt logs
- results_live/hybrid/triage/*.json (read at build time, not shipped)
- dataset/ traces and other raw sweep artifacts
- Gradio app.py runtime, caches, and virtualenvs
