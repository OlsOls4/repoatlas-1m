"""Shared definitions for the DocDrift baselines: the 11 hand-checked true drifts and matching helpers."""

from __future__ import annotations

# Each true drift: id, repo, list of (path, first_line, last_line) locations where it lives, and keywords
# that must appear in a finding's text/quotes for it to count as the same drift.
TRUE_DRIFTS: list[dict] = [
    {"id": "T1", "repo": "starlette", "name": "starlette receive_json(data, mode) vs no data param",
     "locs": [("docs/websockets.md", 74, 74)], "kw": ["receive_json"]},
    {"id": "T2", "repo": "httpx", "name": "httpx.Mounts does not exist (use mounts=)",
     "locs": [("docs/advanced/transports.md", 178, 193)], "kw": ["Mounts"]},
    {"id": "T3", "repo": "httpx", "name": "httpx WSGITransport docstring Client(app=app)",
     "locs": [("httpx/_transports/wsgi.py", 45, 52)], "kw": ["app"]},
    {"id": "T4", "repo": "click", "name": "click {class}FileType vs click.File",
     "locs": [("docs/exceptions.md", 108, 111)], "kw": ["FileType"]},
    {"id": "T5", "repo": "structlog", "name": "structlog _NAME_TO_LEVEL path",
     "locs": [("docs/standard-library.md", 117, 117), ("src/structlog/stdlib.py", 860, 863)], "kw": ["NAME_TO_LEVEL"]},
    {"id": "T6", "repo": "nox", "name": "nox options.reuse_venvs vs reuse_venv",
     "locs": [("docs/usage.rst", 219, 219)], "kw": ["reuse_venvs"]},
    {"id": "T7", "repo": "arrow", "name": "arrow dehumanize :param timestring: vs input_string",
     "locs": [("arrow/arrow.py", 1344, 1350)], "kw": ["timestring"]},
    {"id": "T8", "repo": "cattrs", "name": "cattrs ForbiddenExtraKeyError vs ForbiddenExtraKeysError",
     "locs": [("docs/customizing.md", 279, 279)], "kw": ["ForbiddenExtraKey"]},
    {"id": "T9", "repo": "cattrs", "name": "cattrs get_unstructure_hook :param cache: vs cache_result",
     "locs": [("src/cattrs/converters.py", 490, 503)], "kw": ["cache"]},
    {"id": "T10", "repo": "cattrs", "name": "cattrs get_structure_hook :param cache: vs cache_result",
     "locs": [("src/cattrs/converters.py", 639, 652)], "kw": ["cache"]},
    {"id": "T11", "repo": "marshmallow", "name": "marshmallow ``default`` vs load_default",
     "locs": [("docs/top_level.rst", 10, 16)], "kw": ["default"]},
]

TOLERANCE = 3


def _overlaps(path: str, start: int, end: int, loc: tuple[str, int, int]) -> bool:
    lpath, lo, hi = loc
    return path.lstrip("./") == lpath and start <= hi + TOLERANCE and end >= lo - TOLERANCE


def match_true_drifts(repo: str, citations: list[tuple[str, int, int]], text: str) -> list[str]:
    """Return ids of true drifts whose location overlaps any citation and whose keyword is in text."""
    hits = []
    for drift in TRUE_DRIFTS:
        if drift["repo"] != repo:
            continue
        if not any(k in text for k in drift["kw"]):
            continue
        if any(_overlaps(p, s, e, loc) for (p, s, e) in citations for loc in drift["locs"]):
            hits.append(drift["id"])
    return hits
