# RepoAtlas-1M live hand-check (Ollama Cloud, model `beam`)

Date: Mon 26 Oct 2026 (GMT). Sources checked: flask tarball `pallets/flask@d086db8` (main), fastapi tarball
`fastapi/fastapi@79cab5b` (master), werkzeug `main@b73dce5`, fastapi-cli `main@093be9c`.

## Runs

| Run | Prompt tok | Completion tok | Latency | Schema | DocDrift findings | Verifier (findings) | Atlas citations verified |
|---|---|---|---|---|---|---|---|
| flask-120000 (old prompt, 18:55 GMT) | 142,462 | 4,276 | ~19 s (wall) | off-schema keys + `<\|im_end\|>`; parsed only via alias normaliser | 1 | 1/1 pass (doc quote only via whitespace-normalised match; strict check rejected it) | 5/6 |
| flask-120000 (new prompt, 18:58 GMT) | 142,664 | 3,692 | 21.1 s | strict schema, parsed without normalisation | 0 | n/a | 3/3 |
| fastapi-120000 (new prompt, 18:59 GMT) | 146,415 | 1,834 | 12.0 s | strict schema, parsed without normalisation | 0 | n/a | 4/4 |

## DocDrift findings emitted by the model

### flask DD-1 (old-prompt run) — FALSE POSITIVE
- Model: "Docs say enabling SESSION_COOKIE_PARTITIONED implicitly enables SESSION_COOKIE_SECURE; code reads
  SESSION_COOKIE_SECURE directly without modifying it."
- Doc `docs/config.rst:205-206`: "Enabling this implicitly enables :data:`SESSION_COOKIE_SECURE` as well, as it is
  only valid when served over HTTPS." (quote is real; model dropped the 4-space indent on line 206)
- Code `src/flask/sessions.py:202-206`: `get_cookie_secure` returns `app.config["SESSION_COOKIE_SECURE"]` (real).
- Why false: Flask passes `partitioned=` to Werkzeug's cookie writer (`sessions.py` 344, 361, 382), and Werkzeug
  `dump_cookie` (`src/werkzeug/http.py`, main) does `if partitioned: secure = True`. The docs describe actual
  behaviour; the "implicit" part lives in the dependency, outside the pack. Citations verified ≠ finding correct.

## Candidates the model considered and rejected (from its reasoning) — checked anyway

| Repo | Candidate | Verdict | Evidence |
|---|---|---|---|
| flask | `docs/config.rst:68-78` says DEBUG "Default: ``False``" but `src/flask/app.py:207` has `"DEBUG": None` | Not drift (model right to reject) | `src/flask/sansio/app.py:493` `defaults["DEBUG"] = get_debug_flag()` sets the effective default (False unless `FLASK_DEBUG`). |
| flask | `Flask.open_resource(..., encoding=None)` (`app.py:412-414`) vs `Blueprint.open_resource(..., encoding="utf-8")` (`blueprints.py:104-106`) | Unclear — code inconsistency, not doc drift | Both docstrings only say "Open the file with this encoding when opening in text mode"; no doc states a default, so nothing contradicts. Might be worth an upstream question, not a DocDrift finding. |
| fastapi | `applications.py:1296-1298` docstring: `fastapi dev` sets `FASTAPI_ENV=development`; `check_dir="auto"` skips with a warning in dev | Not drift (model couldn't check) | `fastapi/routing.py:1953` `if os.environ.get("FASTAPI_ENV") != "development": return True`; dependency fastapi-cli `src/fastapi_cli/cli.py:402` (inside `dev`) `os.environ.setdefault("FASTAPI_ENV", "development")`. `routing.py` was not in the 120k pack, so the model correctly declined to cite. |

## Takeaways
- Prompt-embedded schema fixed output format: both new runs were strict-schema JSON.
- At 120k the model returned zero DocDrift findings on both repos; precision is not measurable from these runs (0/0).
- The fastapi 120k pack omits `fastapi/routing.py`, a core file — packing priority still needs work for large packages.
- Real prompt tokens vs cl100k pack estimate: flask 1.186x, fastapi 1.219x (docs-heavy markdown tokenises worse).

---

## Live 400k runs (2026-10-26, origin 04405ab + local fix 1b40a0d, packer FILTER v4)

Source checked against the same tarball snapshots the packs were built from:
starlette `Kludex-starlette-8aa828c`, typer `fastapi-typer-a5882de`, hatch `pypa-hatch-e7495de`, poetry `python-poetry-poetry-1fe5e0a`.
The pack line numbering was confirmed correct (the pack shows `74|Use ...` and `87|    Hatch uses ...`), so the doc-citation rejections below are the model citing one line too early.

| run | prompt | completion | latency s | findings | verifier |
|---|---|---|---|---|---|
| starlette-400000 | 394,577 | 4,733 | 21.36 | 1 | reject (doc quote-not-found-in-range) |
| typer-400000 | 387,284 | 8,653 | 36.12 | 0 | n/a |
| hatch-400000 | 385,297 | 5,137 | 23.39 | 1 | reject (doc quote-not-found-in-range) |
| poetry-400000 | 384,598 | 4,287 | 46.22 | 1 | pass (fully verified) |

### starlette DD-1 (signature): TRUE DRIFT
- Doc, `docs/websockets.md:74` (the model cited 73): ``Use `websocket.receive_json(data, mode="binary")` to receive JSON over binary data frames.``
- Code, `starlette/websockets.py:136`: `async def receive_json(self, mode: str = "text") -> Any:`
- `receive_json` takes no `data` parameter. The documented call `receive_json(data, mode="binary")` would bind `data` to `mode` positionally, then fail with a TypeError for multiple values of `mode`. The line is a copy-paste of the `send_json(data, mode="binary")` line at :63 (`send_json(self, data: Any, mode: str = "text")`, websockets.py:177). The fix is `websocket.receive_json(mode="binary")`.
- Verifier rejected it only because of the off-by-one line.

### hatch DD-1 (env_var): UNCLEAR (incomplete rather than contradictory)
- Doc, `docs/config/environment/overview.md:87` (the model cited 86): "Hatch uses [pip](https://github.com/pypa/pip) to install dependencies so any [configuration](...) it supports Hatch does as well. For example, if you wanted to only use a private repository you could set the `PIP_INDEX_URL` [environment variable](#environment-variables)."
- Code, `src/hatch/env/virtual.py:92-93`: `def installer(self) -> str: return self.config.get("installer", "pip")`. `use_uv` (:88-89) switches to `UVVirtualEnv` when `installer = "uv"` or a uv path is set.
- The default installer is pip, so the tip is correct for the default case, and `docs/how-to/environment/select-installer.md` documents uv as opt-in. `src/hatch` has no PIP_* to UV_* mapping (grep finds only `PIP_IS_CI` in linehaul.py), so `PIP_INDEX_URL` advice will not apply once uv is selected. The internal envs default to uv (`docs/config/internal/static-analysis.md:142`, `type-checking.md:60`). The tip is stale or incomplete for uv envs, not wrong for the default. Verifier rejected it for the off-by-one line.

### poetry DD-1 (default): FALSE POSITIVE
- Doc, `docs/basic-usage.md:50`: `requires-python = ">=3.9"`, an example of the pyproject that `poetry new` generates.
- Code, `src/poetry/console/commands/init.py:170-176`: `">=" + Python.get_preferred_python(config, self.io).minor_version`. `new` reuses the same options and path.
- `get_preferred_python` (`src/poetry/utils/env/python/manager.py:273-295`) returns the active interpreter by default (`virtualenvs.use-poetry-python = false`), and that can be 3.9. Poetry's own `requires-python = ">=3.11"` (`pyproject.toml:5`) constrains Poetry, not the generated project. The example value is illustrative and still reachable, so the model's "should be >=3.11" is wrong. The verifier passed it, since both quotes are exact.

### typer: no findings
Its reasoning mentioned `TYPER_USE_RICH` docs vs `parse_boolean_env_var` and judged it "not contradiction exactly". 0 findings.

---

# Sweep 2026-10-26 (400k limit, Ollama Cloud `beam`, one live call per repo)

The repos are pinned in `benchmarks/repos_sweep_2026-10-26.yaml`. Every pinned SHA was still the default-branch HEAD on 2026-10-26 (checked with `git ls-remote`).
The scope was later capped at 4 repos, but by then 11 had already run, so all 11 are reported here. loguru was started but interrupted before its live call (no response in the cache), and no further calls were made.
There were no 402/429/quota errors, and no rate-limit headers were returned.

| Repo | SHA | Real prompt tok | Completion tok | Latency | Findings | Verifier pass | True | False | Unclear |
|---|---|---|---|---|---|---|---|---|---|
| httpx | b5addb6 | 392,598 | 4,053 | 21.2 s | 2 | 2 | 2 | 0 | 0 |
| click | 2247b35 | 388,719 | 4,698 | 21.8 s | 1 | 1 | 1 | 0 | 0 |
| attrs | c8bb9bf | 400,648 | 4,102 | 22.2 s | 0 | – | 0 | 0 | 0 |
| pydantic-settings | 7e2dacb | 366,051 | 5,378 | 26.1 s | 1 | 1 | 0 | 1 | 0 |
| structlog | 19c4f21 | 403,833 | 6,118 | 24.9 s | 2 | 1 | 1 | 1 | 0 |
| jinja | 5ef7011 | 356,873 | 5,311 | 25.7 s | 1 | 0 | 0 | 0 | 1 |
| nox | afa3983 | 346,394 | 7,014 | 27.4 s | 1 | 1 | 1 | 0 | 0 |
| arrow | 2224255 | 329,026 | 4,457 | 15.9 s | 4 | 1 | 1 | 3 | 0 |
| cattrs | 7a24f77 | 306,549 | 4,107 | 21.2 s | 3 | 3 | 3 | 0 | 0 |
| marshmallow | b762ea2 | 294,559 | 4,916 | 19.7 s | 2 | 2 | 1 | 1 | 0 |
| werkzeug | b73dce5 | 386,415 | 3,446 | 17.9 s | 1 | 0 | 0 | 1 | 0 |
| **Total** | | **3,971,665** | **53,600** | | **18** | 12 | **10** | **7** | **1** |

Sweep hand-checked precision is 10/18 = 55.6%. Across all live runs (starlette, hatch, poetry, typer, flask, fastapi plus the sweep) it is 11 true / 8 false / 2 unclear = 11/21 = 52.4%.
The verifier rejected 4 of the 7 false positives (arrow DD-2..4, werkzeug DD-1) and passed 3 (pydantic-settings, structlog DD-1, marshmallow DD-1). It also rejected structlog DD-2, which is a true drift (the model quoted the code text against the doc path). Citation verification is a useful filter, not a correctness oracle.

## Per-finding verdicts

- **httpx DD-1: TRUE.** `docs/advanced/transports.md:190-193` uses `httpx.Mounts(...)`, which doesn't exist (AttributeError); the correct form is `Client(mounts=...)` (`_client.py:652`). Already fixed in open PR encode/httpx#3774. Draft: `upstream_drafts/httpx-transports-mounts.md` (do not file).
- **httpx DD-2: TRUE.** `httpx/_transports/wsgi.py:47-51` shows `httpx.Client(app=app)`, which raises a TypeError on 0.28.1 because `app` was removed in 0.28. No issue found. Draft: `httpx-wsgitransport-app-arg.md`.
- **click DD-1: TRUE (minor).** `docs/exceptions.md:109-110` cites `{class}FileType`, which doesn't exist; the type is `click.File` (`types.py:915`). No issue found. Draft: `click-fileerror-filetype.md`.
- **pydantic-settings DD-1: FALSE.** `docs/index.md:1895-1897` describes what `cli_kebab_case=True` does; it doesn't claim True is the default (`main.py:726` default False).
- **structlog DD-1: FALSE.** `_native.py:121-123` lists a subset of the level names, and the code accepts a superset, so following the docs works.
- **structlog DD-2: TRUE (verifier rejected).** `docs/standard-library.md:117` gives `structlog.stdlib._NAME_TO_LEVEL` and `stdlib.py:861-862` gives `structlog.stdlib._log_levels._NAME_TO_LEVEL`. Neither exists; the mapping is `structlog._log_levels.NAME_TO_LEVEL` (`_log_levels.py:27`). No issue found. Draft: `structlog-name-to-level-path.md`.
- **jinja DD-1: UNCLEAR.** The `docs/extensions.rst` signatures show `newstyle=False`, but the code uses `None` and falls back to `env.newstyle_gettext` (default False), so the effective default is the same.
- **nox DD-1: TRUE.** `docs/usage.rst:219` says `nox.options.reuse_venvs`, which raises AttributeError (reproduced); the option is `reuse_venv` (`_options.py:333`). No issue found. Draft: `nox-reuse-venvs-typo.md`.
- **arrow DD-1: TRUE.** `arrow.py:1349` has `:param timestring:`, but the parameter is `input_string` (:1344), so `timestring=` raises TypeError. Already fixed in open PR arrow-py/arrow#1355. Draft: `arrow-dehumanize-param.md` (do not file).
- **arrow DD-2: FALSE.** `en-us` and `en_us` are normalised (`locales.py:54`).
- **arrow DD-3/DD-4: FALSE.** The token table covers parsing, and the parser accepts hour 24 (`parser.py:792`, reproduced).
- **cattrs DD-1: TRUE.** `docs/customizing.md:279` shows `ForbiddenExtraKeyError`, but the class is `ForbiddenExtraKeysError` (`errors.py:118`). No issue found. Draft: `cattrs-forbidden-extra-key-error.md`.
- **cattrs DD-2/DD-3: TRUE.** `converters.py:502` and `:650` document `:param cache:`, but the signatures use `cache_result` (:492, :641), so `cache=False` raises TypeError (reproduced). No issue found. Draft: `cattrs-get-hook-cache-param.md`.
- **marshmallow DD-1: FALSE.** `custom_options.rst:40-41` forwards `**kwargs` to `SchemaOpts.__init__(meta)`, but Schema calls `OPTIONS_CLASS(meta)`, so kwargs is always empty and the example runs (reproduced).
- **marshmallow DD-2: TRUE (minor).** `docs/top_level.rst:12-14` says the field's ``default`` value is used. `default` was removed in 4.x (`fields.Int(default=5)` raises TypeError); it is `load_default` (`fields.py:380`). No open issue found (#2040 is related and closed). Draft: `marshmallow-missing-load-default.md`.
- **werkzeug DD-1: FALSE.** `http.py:1461` is a historical `versionchanged:: 2.3` note; `:1451-1452` documents that 2.3.3 restored the `/` default, which matches `:1401`.
