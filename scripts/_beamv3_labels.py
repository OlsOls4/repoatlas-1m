"""Labels for the Beam v3 findings, used by beamv3_analyze.py.

Ground truth = the EXISTING labelled set only (hybrid.json items, symbol_check_flags + _symbol_verdicts,
chunked-32k/128k + _chunked_verdicts, results_live/index.json hand_verdict). A v3 finding is matched to it by
(repo, doc path, doc line +-3). Anything that does not match is "unlabelled" and is NOT counted as true.

RESOLVE: manual picks where the +-3 window hit several labelled items with different verdicts; the pick is
the labelled item making the same claim (no new judgement).

AI_CHECK: at most 15 unlabelled findings, checked by an AI reviewer (Grok Bot, 2026-10-26) against the
library source at the pack ref (/workspace/sweep/<repo>; starlette at /workspace/repro_src/starlette 8aa828c).
These are NOT hand labels. Rule: true = the doc states something the code contradicts; omissions/partial =
unclear; doc narrower than code, illustrative examples, nitpicks = false. Unclear counts as not-true.
"""

# chunked-baseline index -> drift id of the chunked-only trues (same ids as hybrid.json's universe)
C32_NEW = {"arrow:1": "C:arrow-interval-end", "arrow:2": "C:arrow-span_range-end", "attrs:1": "C:attrs-py2-reprs",
           "cattrs:2": "C:cattrs-td59", "cattrs:3": "C:cattrs-td251", "cattrs:4": "C:cattrs-ujson-b85",
           "httpx:4": "C:httpx-handle_request", "httpx:5": "C:httpx-sslcontext", "marshmallow:0": "C:mm-url-default",
           "marshmallow:2": "C:mm-quotes-400", "nox:0": "C:nox-tasks-returns", "structlog:1": "C:structlog-output-args"}
C128_NEW = {"httpx:0": "C:httpx-handle_request", "marshmallow:2": "C:mm-quotes-400", "structlog:0": "C:structlog-output-args",
            "attrs:0": "C:attrs-force_kw_only", "marshmallow:0": "S33/S34-family(prose)"}

RESOLVE = {
 "py:arrow#4:DD-1": ("true", "T7", "hybrid:arrow-400000:DD-1"),
 "py:arrow#4:DD-2": ("false", "", "index:arrow-400000/DD-2 (en-us vs en_us, hand-labelled false)"),
 "docs:arrow:DD-1": ("false", "", "hybrid:arrow-400000:DD-3 (HH 24, hand-labelled false)"),
 "docs:arrow:DD-2": ("false", "", "hybrid:arrow-400000:DD-4 (H 24, hand-labelled false)"),
 "docs:arrow:DD-3": ("false", "", "hybrid ADD-AD-2/AD-1 (guide.rst range, hand-labelled false)"),
 "docs:arrow:DD-4": ("false", "", "hybrid ADD-AD-2 (guide.rst range, hand-labelled false)"),
 "docs:marshmallow:DD-1": ("true", "N:mm-pass_many-prose", "hybrid ADD-AD-1"),
 "docs:structlog:DD-1": ("true", "T5", "hybrid S13 / index structlog-400000/DD-2 (same _log_levels claim)"),
 "docs:marshmallow:DD-4": ("true", "T11", "index marshmallow-400000/DD-2 docs/top_level.rst:10-14 (same 'default' vs load_default claim)"),
 "docs:pydantic-settings:DD-1": ("false", "", "index pydantic-settings-400000/DD-1 (same cli_kebab_case claim, hand-labelled false)"),
}

AI_REVIEWER = "AI reviewer (Grok Bot) checking against source at pack ref, 2026-10-26"
AI_CHECK = {
 "py:attrs#3:DD-1": ("false", "", "validators.py:704-718 not_(): doc says exc_types tuple; code also accepts a single type via tuple() fallback. Doc narrower than code"),
 "py:click#4:DD-2": ("true", "N3:click-progressbar-hidden", "termui.py:524-526 'Setting this to False also disables that' (no-tty label); _termui_impl.py:251 'if self.hidden: return' - it is hidden=True that suppresses the label"),
 "py:click#4:DD-3": ("unclear", "", "termui.py:528-530 show_percent default 'True if the iterable has a length'; _termui_impl.py:227-228 uses 'not self.show_pos', so with show_pos=True it is False. Omitted condition"),
 "py:jinja#3:DD-1": ("true", "N3:jinja-parse_tuple-no_condexpr", "parser.py:695-696 'The `no_condexpr` parameter is forwarded'; the parameter is with_condexpr (:684)"),
 "py:marshmallow#0:DD-2": ("true", "N3:mm-email-args", "fields.py:1793 ':param args: The same positional arguments that String receives'; Email.__init__(self, **kwargs) (:1800) takes no positional args"),
 "py:nox#0:DD-4": ("unclear", "", "sessions.py:494 ':type external: bool' but signature is ExternalType | None (also 'error'); the error option is described elsewhere. Incomplete type"),
 "py:werkzeug#10:DD-4": ("true", "N3:wz-proxymw-remove_prefix", "middleware/http_proxy.py:66-68 says the example removes the /static/ prefix; example sets no remove_prefix and the default is False (:52, :89)"),
 "py:werkzeug#5:DD-2": ("true", "N3:wz-expose-headers-doc", "sansio/response.py:822-825 access_control_expose_headers doc says 'The Access-Control-Allow-Origin header'; property maps Access-Control-Expose-Headers"),
 "docs:attrs:DD-2": ("true", "N3:attrs-examples-attribute-repr", "docs/examples.md:468 doctest output shows Attribute(..., factory=NOTHING, ...) and <type 'int'>; Attribute.__slots__ (_make.py:2511-2530) has no factory and Py3 prints <class 'int'>. Same family as C:attrs-py2-reprs, different site"),
 "docs:httpx:DD-1": ("false", "", "docs/quickstart.md:70 r.encoding 'UTF-8' is an illustrative value from the server charset; _models.py:665-671 returns the charset as given. Not a contradiction"),
 "docs:jinja:DD-2": ("unclear", "", "docs/extensions.rst:53/67 newstyle=False vs signature newstyle=None (ext.py:268); effective default is the env flag, False unless set. Partly true"),
 "docs:nox:DD-1": ("false", "", "docs/usage.rst:32 says add --json to the --list command; tasks.py:345-348 requires --list-sessions with --json. Consistent"),
 "docs:nox:DD-2": ("true", "N3:nox-list-header", "docs/config.rst:53-54 sample output 'Available sessions:'; tasks.py:291 prints 'Sessions defined in {noxfile}:'. Minor"),
 "docs:nox:DD-3": ("unclear", "", "docs/cookbook.rst:211 comment lists 3.14t before 3.15; project.py:178-180 appends free-threaded versions after all versions. Real but trivial ordering mismatch in an illustrative comment (plus a quote typo)"),
 "docs:starlette:DD-2": ("false", "", "docs/background.md:44 BackgroundTasks(tasks=[]) vs tasks=None (background.py:27); 'list(tasks) if tasks else []' - same behaviour"),
}
assert len(AI_CHECK) <= 15
