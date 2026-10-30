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

**DocDrift** finds docs drift (docs say one thing, code does another) in Python libraries. A free symbol check proposes candidates. Beam reads each library's docs and source (about 300–400k tokens) to triage them and add cross-file or prose drift. 11 of 12 libraries were triaged in one call; structlog failed; cattrs needed 2 calls. A generated script then runs the documented usage and keeps the ones that raise a real API error.

**Results:** 34 real docs bugs in 11 of 12 libraries; 30 reproduce. Beam's triage threw away 0 of 32 real bugs.

Filed upstream: [starlette #3746](https://github.com/Kludex/starlette/pull/3746) (open) and [nox #1216](https://github.com/wntrblm/nox/pull/1216) (open). httpx #3774 and arrow #1355 were already reported upstream by others.

This Space is a **static recording**; it makes no Beam calls. Code is [MIT](https://github.com/OlsOls4/repoatlas-1m/blob/main/LICENSE) (copyright 2026 Olly McBride). Dataset labels are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## What is docs drift?

Docs and code disagree in a way that can break users who follow the docs. Starlette example: `docs/websockets.md` line 74 calls `receive_json(data, mode="binary")`; `starlette/websockets.py` line 136 is `receive_json(self, mode: str = "text")`. Following the docs can raise `TypeError`.

## How Beam is used

Numbers below come from the companion dataset.

1. Triage filter, not a raw detector. A free AST symbol check proposes name and signature mismatches. Beam judged 56 candidates across 11 of 12 libraries (structlog failed; cattrs needed 2 calls). It rejected 0 of 32 true candidates and removed 15 of 24 false or unclear ones.
2. Beam's triage kept all 24 true symbol-check drifts, kept 1 extra from the whole-repo pass's own candidates, and added 9 drifts the checker missed (7 new to the union): 24 + 1 + 9 = 34.
3. Repro author. Beam wrote the doc-literal repro scripts (138,138 tokens). The starlette headline script was written by hand from Beam's verdict. 30 distinct bugs reproduce a real API error. 38 of 41 badges were real. 2 false + 1 unclear (werkzeug S38, S39 false; S41 unclear) received a strict badge.

## Glossary

- Triage: Beam judges symbol-check and whole-repo candidates as true_drift, false, or unclear against one packed library prompt.
- Strict badge: TypeError, AttributeError, ImportError, or NameError raised on a DOC-LITERAL usage line.
- Line-shifted match: the cited quote matched packed source within ±3 lines of the model-cited line.

## Limits

- The 45-drift universe is the union of method output, so it favours those methods.
- Labels were checked against the source by an AI reviewer. (Field name in the dataset: `hand_verdict`.)
- Citation check means quote alignment of cited lines vs packed source, with a ±3-line shift allowed. It is not a verdict that the drift is real.
- A true drift can still fail the strict repro rule (marshmallow T11, structlog untriaged, werkzeug input_stream).
- 2 false + 1 unclear (werkzeug S38, S39 false; S41 unclear) received a strict repro badge.
- Filed by this project. Open, not merged. Status checked 30 Oct 2026.
- httpx #3774 and arrow #1355 were already reported upstream by others.
- cattrs and click have drafts in the repo; they are not listed as filed.
- structlog: Beam's whole-repo reply had no parseable JSON (prompt 404,652 tokens); not retried.
- This Space is a static recording; it makes no Beam calls. Run DocDrift yourself with the CLI.

## Run it on your repo

```bash
pip install git+https://github.com/OlsOls4/repoatlas-1m
export OLLAMA_API_KEY=YOUR_KEY
docdrift run https://github.com/OWNER/REPO --max-tokens 400000 --out findings
```

Create a free Ollama Cloud account at [ollama.com](https://ollama.com), open Settings, and create an API key. Export it as OLLAMA_API_KEY, or set OLLAMA_API_KEY_FILE to a file that contains the key. `docdrift run` packs the whole repository, sends it to Beam for triage (32k output tokens, citation verify), then runs Beam-written doc-literal scripts in an isolated venv with no network. Skip the scripts with --no-repro. Cap repro tokens with --repro-budget. Stops on HTTP 402/quota (exit 4). No key is stored in this Space or in the archive.

## Exclusions

This static folder does not include:

- results_live/traces/*.json raw traces (only starlette-400000 summary and pack metadata are embedded in replay.json)
- results_live/hybrid/repros/*/attempts.json per-attempt logs
- results_live/hybrid/triage/*.json (read at build time, not shipped)
- results_live/ablation/raw/ API bodies
- results_live/ablation/matched_cost/raw/ API bodies
- results_live/beamv3/repros/*/ per-attempt logs
- dataset/ traces and other raw sweep artifacts
- raw pack traces (only starlette-400000 summary and pack metadata are embedded in replay.json)
