"""Hand-checked verdicts for DocDrift v2 (hybrid) items that had no earlier label.

ADD: Beam's additional findings in the triage calls, keyed "<repo>:<finding_id>" -> (verdict, drift_id, evidence).
drift_id is an id from the known-true universe (KNOWN in hybrid_score.py) when the addition re-finds a known drift,
otherwise a new "N:" id for a new true drift (or "" for false/unclear). Checked against /workspace/sweep/<repo> at the pack ref.
"""
ADD = {
 "httpx:AD-1": ("true", "C:httpx-handle_request", "same as chunked-32k httpx #4: docs/advanced/transports.md:285 old 5-arg handle_request; base.py:26 takes a Request"),
 "httpx:AD-2": ("true", "N:httpx-response-next", "docs/api.md:81 and :88 list def .next() / def .anext() on Response; httpx/ has no def next/anext (grep), only the next_request attribute (_models.py:538)"),
 "httpx:AD-3": ("true", "N:httpx-url-is_ssl", "docs/api.md:126 lists URL.is_ssl; no is_ssl anywhere in httpx/ (grep)"),
 "httpx:AD-4": ("unclear", "", "docs/compatibility.md:168 mounts example is garbled Python (key/value swapped). A doc typo, not a doc-vs-code contradiction"),
 "httpx:AD-5": ("true", "N:httpx-iter_content", "docs/advanced/clients.md:183 prose names response.iter_content(); httpx has no iter_content (grep), it is iter_bytes (_models.py:884). Minor, prose"),
 "arrow:AD-1": ("false", "", "docs/guide.rst:398 '001 ... 365' is an illustrative ellipsis range in a parse+format table (guide.rst:380); same reasoning as DD-3/DD-4 false"),
 "arrow:AD-2": ("false", "", "docs/guide.rst:400 same as AD-1 for DDD"),
 "arrow:AD-3": ("false", "", "docs/guide.rst:414 'W' examples include 2019-W17; the table covers parsing too (guide.rst:380) and the parser has a W token (parser.py:201, :427)"),
 "jinja:AD-1": ("true", "N:jinja-install_translations", "docs/extensions.rst:157-158 says pass newstyle=True to env.install_translations; the i18n extension registers install_gettext_translations (ext.py:260), so env.install_translations does not exist"),
 "jinja:AD-2": ("true", "N:jinja-commend_end_string", "docs/switching.rst:141 Environment(commend_end_string=...) typo; the parameter is comment_end_string, so the example raises TypeError"),
 "marshmallow:AD-1": ("true", "N:mm-pass_many-prose", "docs/extending/pre_and_post_processing.rst:34 prose says add pass_many=True; decorators.py:152-178 only take pass_collection. Same rename as S33/S34, different (prose) site"),
 "marshmallow:AD-2": ("true", "C:mm-url-default", "same as chunked-32k marshmallow #0: fields.py:1750 Url ':param default:'; fields have load_default/dump_default (fields.py:92-93)"),
 "werkzeug:AD-1": ("true", "N:werkzeug-input_stream", "wrappers/request.py:585-586 deprecated note says use environ['REMOTE_USER']; the code's warning (:590-592) and :583 say use 'stream'"),
}

# Triage verdicts that disagree with an existing hand label (re-checked; the earlier label stands).
RECHECK = {
 "httpx:S7": "Beam: true. Kept false: docs/compatibility.md:56 is inside the requests.Session example (:50-58) showing requests' allow_redirects for contrast",
 "werkzeug:S38": "Beam: true. Kept false: proxy_fix.py:55 says the values are stored 'in the WSGI environ as werkzeug.proxy_fix.orig', which is the environ key used at :138. Beam's own reason concedes this",
 "werkzeug:S39": "Beam: true. Kept false: same as S38 (proxy_fix.py:83)",
 "werkzeug:S41": "Beam: true. Kept unclear: test.py:1103 is a historical 0.5 note; werkzeug.FileWrapper is gone but werkzeug.wsgi still has a deprecated alias (wsgi.py:623)",
 "arrow:arrow-400000:DD-2": "Beam: true. Kept false per handcheck.md: en-us and en_us are normalised (locales.py:54)",
 "arrow:arrow-400000:DD-3": "Beam: true. Kept false: the parser accepts hour 24 (parser.py:792)",
 "arrow:arrow-400000:DD-4": "Beam: true. Kept false: same as DD-3",
 "marshmallow:marshmallow-400000:DD-1": "Beam: true. Kept false: Schema calls OPTIONS_CLASS(meta), so **kwargs is empty and the example runs (reproduced earlier)",
 "jinja:jinja-400000:DD-1": "Beam: true. Kept unclear per handcheck.md",
}
