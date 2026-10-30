# Fresh end-to-end `docdrift run`: tomlkit (round-4 fix 8)

- **Library:** [python-poetry/tomlkit](https://github.com/python-poetry/tomlkit). It is popular and pure Python, and
  it is not one of the 12 benchmark repos.
- **Commit:** `d7def7dbcc59b3b2d11cc73114c31d1f616523a8`. This was HEAD of the default branch when the run cloned it
  (`git clone --depth 1`); the commit date is 2026-10-29.
- **Command, recorded live in a 100x30 terminal:**
  `docdrift run https://github.com/python-poetry/tomlkit --max-tokens 400000 --out fresh_run`
- **Run started:** 2026-10-30 11:31:40 Europe/London (GMT). **Wall time:** 96.2 s end to end, including the clone, the
  venv install and the repro. The triage call itself took 34.6 s.
- **Model:** `beam` via Ollama Cloud (`https://ollama.com/v1`). Triage used strict JSON schema, `max_tokens=32000` and
  `reasoning_effort=medium`.

## Pipeline numbers
| Step | Result |
|---|---|
| Symbol check | 0 flags |
| RepoAtlas pack | 141,326 tokens, 81 files, **not truncated**; projected prompt 172,418 (guard 400,000) |
| Whole-repo Beam triage | 1 call: **167,937 prompt + 4,975 completion tokens**, `finish_reason=stop` |
| Findings | 2 extra findings from the open whole-repo search (0 candidates to judge). Citation verifier: AD-1 fully verified, AD-2 code citation verified and doc quote not verbatim |
| Executable repro | 3 Beam calls (12,930 tokens). Isolated venv, `unshare -rn` (no network), 60 s timeout. AD-1 "reproduced" (assertion, vacuous); AD-2 reproduced `NameError` → **strict-confirmed** |
| **Total Beam tokens** | **185,842** |

## Hand check (details in `handcheck.md`)
**2 of 2 findings are true. Both are small documentation issues; neither is a code bug.**
- **AD-1: stale compliance claim.**
  - `docs/index.rst:17-20` says "1.0.0-compliant" and shows a TOML-1.0.0 badge.
  - `README.md:16` says 1.1.0, and `CHANGELOG.md:90` records that 0.15.0 moved the parser to TOML 1.1.0.
  - Beam's repro script for this one is vacuous (a hard-coded `assert False`). The strict filter correctly does not
    confirm it.
- **AD-2: broken quickstart example.**
  - `docs/quickstart.rst:136` uses `datetime(...)` and `utc`, but nothing on the page imports either.
  - Running the example as written raises `NameError`. This is strict-confirmed by the executed repro and confirmed by
    a manual rerun.
- **Strict repro:** 1 finding confirmed (AD-2), and it is true.

## Files
- `docdrift_tomlkit.cast`: asciinema v2 cast, 100x30, 96 s, recorded live (not replayed: the response caches were
  empty).
- `script_typescript.log` + `script_timing.log`: the `script -T` fallback recording of the same session (play it with
  `scriptreplay -t script_timing.log script_typescript.log`).
- `stdout.log`: full terminal output. `exit_code.txt`: exit 0.
- `findings.json`: pack stats, the triage JSON with citation checks, the repro records with their generated scripts,
  and token counts.
- `handcheck.md`: per-finding verdict, reason and file:line evidence.

## CLI used for this recording

This run used the committed `docdrift run` pipeline:

- send the **full** pack, using the hybrid run's own `SYSTEM`, `build_user_prompt` template and strict schema
  (32k max_tokens, medium reasoning);
- verify the citations;
- execute repros through `repoatlas.repro.run_case`;
- stop on 402 or quota responses.
