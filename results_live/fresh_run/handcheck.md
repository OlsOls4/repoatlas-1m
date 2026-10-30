# Hand check: `docdrift run` on python-poetry/tomlkit @ d7def7dbcc59b3b2d11cc73114c31d1f616523a8

**Checked by an AI reviewer (Grok Bot), not a human maintainer.** Every finding was checked against the source at the
pinned commit. The commit date is 2026-10-29 16:52 +08:00 (09:52 Europe/London). tomlkit 0.15.2 was installed from
that commit into the repro venv, running Python 3.13.5.

**Findings:** 2. The symbol check flagged 0, so both came from Beam's whole-repo "Task 2" open search.

| ID | Verdict | One-line reason | Evidence (file:line @ d7def7d) | Citations verified | Repro | Strict repro |
|---|---|---|---|---|---|---|
| AD-1 | **true** (low severity, stale) | The Sphinx docs landing page still says "1.0.0-compliant" with a TOML-1.0.0 badge, but the parser was moved to TOML 1.1.0 in 0.15.0 and the README already says 1.1.0. | `docs/index.rst:17-20` (badge + "TOML Kit is a **1.0.0-compliant**"); `README.md:16` ("**1.1.0-compliant**"); `CHANGELOG.md:86-90` (0.15.0: "Update parser to support TOML spec v1.1.0"); `tests/test_toml_tests.py:17` (`files-toml-1.1.0`) | yes (doc + code) | "reproduced" but **vacuous**: the generated script ends in a hard-coded `assert False` (see below) | no |
| AD-2 | **true** (low severity, example bug) | The quickstart "writing" example calls `datetime(1979, 5, 27, 7, 32, tzinfo=utc)`, but neither `datetime` nor `utc` is imported anywhere on the page. Run as written, it raises `NameError`. `tomlkit.datetime` exists but takes an RFC 3339 string, so importing it would not fix the line. | `docs/quickstart.rst:121-124` (the block's imports), `docs/quickstart.rst:136` (the call); `grep datetime\|utc docs/quickstart.rst` matches only line 136; `tomlkit/api.py:202` (`def datetime(raw: str) -> DateTime`) | code yes; doc **no** (quote not verbatim, see below) | reproduced, `NameError` (interface_error) | **yes** |

**True findings: 2 of 2. False: 0. Unclear: 0.** Both are minor documentation issues, not code bugs.

## Notes
- **AD-1: the claim is right, but the repro adds nothing.**
  - Beam's first script was rejected by the repro linter. Its second script parses
    `foo = {\n  bar = 1,\n}\n` and then runs `assert False, "docs claim 1.0.0 compliance…"`. "Reproduced" therefore
    shows only that the parse did not raise.
  - The strict filter correctly does not confirm it, because the evidence is an assertion and not an interface error.
  - A manual check in the same venv shows the substance:
    - `tomlkit.parse` accepts that TOML 1.1-only input (a multi-line inline table with a trailing comma);
    - Python 3.13's `tomllib`, a TOML 1.0 parser, rejects it with `TOMLDecodeError`.
    - So the library does implement 1.1.0, and the docs page is stale.
  - Severity is low: a 1.1 parser still reads valid 1.0 documents, so "1.0.0-compliant" is out of date rather than
    harmful.
- **AD-2: the doc citation failed the verifier.**
  - Beam's doc quote turns line 130 `# Using doc["title"] = …` into `>>> # Using doc["title"] = …`, so the quote is not
    verbatim and the CLI prints `(UNVERIFIED)`.
  - The cited line range (121-136) is correct, and the finding is true.
  - Manual repro in the same venv: the doc line raises `NameError: name 'datetime' is not defined`. With
    `from datetime import datetime, timezone; utc = timezone.utc` it produces `dob = 1979-05-27T07:32:00Z`, which
    matches the TOML shown at `docs/quickstart.rst:111`.
- **Not upstream-checked:** I did not search tomlkit's issue tracker or open PRs for existing reports, and nothing was
  posted anywhere.
