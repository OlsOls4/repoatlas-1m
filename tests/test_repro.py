"""Offline tests for the DocDrift tutorial runner (no Beam calls, no pip installs)."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from repoatlas.repro import (
    STATUS_COULD_NOT_RUN,
    STATUS_NOT_REPRODUCED,
    STATUS_REPRODUCED,
    BeamReproClient,
    ReproCase,
    ReproPlan,
    RunResult,
    TokenBudgetExceeded,
    build_repro_messages,
    classify_run,
    lint_script,
    load_cases_from_traces,
    parse_repro_response,
    read_region,
    run_case,
    run_script,
    summarise,
)

NO_ISOLATION: tuple[list[str], str] = ([], "none")


def _plan(expected: str = "TypeError", script: str = "print('DOCS_OK')\n") -> ReproPlan:
    """
    @brief Build a minimal plan.
    """

    return ReproPlan(script, expected, "", "", "", "unclear")


def _run(script: str, tmp_path: Path) -> tuple[RunResult, Path]:
    """
    @brief Run a script with the current interpreter (no venv, no isolation).
    """

    workdir: Path = tmp_path / "w"
    return run_script(Path(sys.executable), script, workdir, 20, NO_ISOLATION), workdir / "repro.py"


def _make_case(tmp_path: Path) -> ReproCase:
    """
    @brief A fake library checkout with one doc line and one function.
    """

    src: Path = tmp_path / "src"
    (src / "docs").mkdir(parents=True)
    (src / "docs" / "usage.md").write_text("Intro\n\nCall `fakelib.go(cache=False)` to skip caching.\n", encoding="utf-8")
    (src / "fakelib.py").write_text("def go(cache_result=True):\n    return cache_result\n", encoding="utf-8")
    finding: dict = {
        "finding_id": "DD-1",
        "drift_kind": "signature",
        "explanation": "docs say cache, code says cache_result",
        "proposed_fix": "rename",
        "doc_citation": {"path": "docs/usage.md", "start_line": 3, "end_line": 3, "quote": "Call `fakelib.go(cache=False)`"},
        "code_citation": {"path": "fakelib.py", "start_line": 1, "end_line": 1, "quote": "def go(cache_result=True):"},
    }
    return ReproCase("fakelib-1:DD-1", "fakelib", "https://example.invalid/fakelib", "0" * 40, src, finding)


def test_read_region_numbers_lines_and_handles_missing(tmp_path: Path) -> None:
    case = _make_case(tmp_path)
    region = read_region(case.source_dir, "docs/usage.md", 3, 3, 1, 1)
    assert "    3| Call `fakelib.go(cache=False)`" in region and "    2| " in region
    assert "not found" in read_region(case.source_dir, "../../etc/passwd", 1, 1, 0, 0)


def test_build_messages_include_regions_and_retry_feedback(tmp_path: Path) -> None:
    case = _make_case(tmp_path)
    first = build_repro_messages(case)
    assert len(first) == 2 and "def go(cache_result=True)" in first[1]["content"] and "argue" in first[1]["content"]
    retry = build_repro_messages(case, {"script": "x", "error": "NameError: boom", "raw_response": "{}"})
    assert len(retry) == 4 and "NameError: boom" in retry[3]["content"]


def test_parse_response_handles_fences_and_truncation() -> None:
    body = {"repro_script": "```python\nimport x\n```", "expected_exception_type": "TypeError", "extra_requirements": ["httpx"]}
    plan = parse_repro_response("```json\n" + json.dumps(body) + "\n```")
    assert plan.repro_script == "import x\n" and plan.extra_requirements == ["httpx"]
    truncated = '{"expected_exception_type": "TypeError", "repro_script": "import y'
    assert parse_repro_response(truncated).repro_script.startswith("import y")
    with pytest.raises(ValueError):
        parse_repro_response('{"expected_exception_type": "x"}')


@pytest.mark.parametrize(
    ("script", "fragment"),
    [
        ("try:\n    f()\nexcept TypeError:\n    pass\n", "try/except"),
        ("raise TypeError('fake')\n", "explicit raise"),
        ("import sys\nsys.exit(1)\n", "sys.exit"),
        ("def (:\n", "SyntaxError"),
    ],
)
def test_lint_rejects_scripts_that_could_fake_results(script: str, fragment: str) -> None:
    assert any(fragment in problem for problem in lint_script(script))


def test_lint_accepts_plain_doc_literal_script() -> None:
    assert lint_script("import json\njson.loads('1', bogus=1)  # DOC-LITERAL\n") == []
    assert any("DOC-LITERAL" in p for p in lint_script("import json\n"))


def test_classify_reproduced_from_library_typeerror(tmp_path: Path) -> None:
    run, script = _run("import json\njson.dumps({}, not_a_param=1)  # DOC-LITERAL\n", tmp_path)
    result = classify_run(run, _plan("TypeError"), script, {"json"})
    assert result.status == STATUS_REPRODUCED and result.evidence == "interface_error" and result.exception_type == "TypeError"


def test_classify_base_class_match(tmp_path: Path) -> None:
    run, script = _run("from json import NoSuchThing  # DOC-LITERAL\n", tmp_path)
    assert classify_run(run, _plan("ImportError"), script, {"json"}).status == STATUS_REPRODUCED


def test_classify_not_reproduced_when_script_completes(tmp_path: Path) -> None:
    run, script = _run("print('DOCS_OK')\n", tmp_path)
    result = classify_run(run, _plan("TypeError"), script, set())
    assert result.status == STATUS_NOT_REPRODUCED and result.error_excerpt == "DOCS_OK" and not result.retryable


def test_classify_assertion_is_marked_as_assertion_evidence(tmp_path: Path) -> None:
    run, script = _run("assert 1 + 1 == 3, 'docs say 3'  # DOC-LITERAL\n", tmp_path)
    result = classify_run(run, _plan("AssertionError"), script, set())
    assert result.status == STATUS_REPRODUCED and result.evidence == "assertion"


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ("raise TypeError('fake')\n", "self_raised"),
        ("import definitely_missing_dep_xyz\n", "missing_dependency"),
        ("{}['k']  # DOC-LITERAL\n", "unexpected_exception"),
        ("import sys\nsys.exit(3)\n", "script_exit"),
        ("raise OSError(101, 'Network is unreachable')\n", "environment"),
    ],
)
def test_classify_could_not_run_cases(script: str, reason: str, tmp_path: Path) -> None:
    run, path = _run(script, tmp_path)
    result = classify_run(run, _plan("TypeError"), path, {"json"})
    assert result.status == STATUS_COULD_NOT_RUN and result.reason == reason and result.retryable


def test_classify_timeout(tmp_path: Path) -> None:
    run = run_script(Path(sys.executable), "import time\ntime.sleep(5)\n", tmp_path / "w", 1, NO_ISOLATION)
    assert run.timed_out and classify_run(run, _plan(), tmp_path / "w" / "repro.py", set()).reason == "timeout"


def test_classify_missing_library_module_counts_as_doc_failure(tmp_path: Path) -> None:
    run, script = _run("import fakelib_submodule_typo  # DOC-LITERAL\n", tmp_path)
    assert classify_run(run, _plan("ModuleNotFoundError"), script, {"fakelib_submodule_typo"}).status == STATUS_REPRODUCED


def test_run_script_scrubs_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "secret-should-not-leak")
    run, _ = _run("import os\nprint(os.environ.get('OLLAMA_API_KEY'))\n", tmp_path)
    assert "secret-should-not-leak" not in run.stdout and "None" in run.stdout


class _StubClient:
    """
    @brief Returns canned responses in order and records calls.
    """

    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
        self.calls.append(messages)
        return json.dumps(self.responses[len(self.calls) - 1]), {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 0}


class _StubVenvs:
    """
    @brief Uses the current interpreter with the fake library on sys.path via a copied module.
    """

    def __init__(self, case: ReproCase) -> None:
        self.case = case

    def ensure(self, case: ReproCase, extras: list[str]) -> tuple[Path, set[str], str]:
        return Path(sys.executable), {"fakelib"}, ""


def _response(script: str, expected: str = "TypeError") -> dict:
    return {
        "argument_finding_is_false": "maybe an alias",
        "model_verdict": "likely_true",
        "doc_literal_usage": "fakelib.go(cache=False)",
        "expected_exception_type": expected,
        "expected_failure": "TypeError unexpected keyword",
        "extra_requirements": [],
        "needs_network_or_server": False,
        "repro_script": script,
    }


def test_run_case_retries_once_with_error_fed_back(tmp_path: Path) -> None:
    case = _make_case(tmp_path)
    lib = case.source_dir
    bad = "import fakelibb  # DOC-LITERAL\n"
    good = f"import sys\nsys.path.insert(0, {str(lib)!r})\nimport fakelib\nfakelib.go(cache=False)  # DOC-LITERAL\n"
    client = _StubClient([_response(bad), _response(good)])
    record = run_case(case, client, _StubVenvs(case), tmp_path / "out", NO_ISOLATION, timeout=20, log=lambda _: None)
    assert record["status"] == STATUS_REPRODUCED and record["attempts"] == 2
    assert "fakelibb" in client.calls[1][-1]["content"]
    case_dir = tmp_path / "out" / "fakelib-1_DD-1"
    assert (case_dir / "attempt1.py").is_file() and (case_dir / "attempt2.log").is_file()
    assert record["script_path"].endswith("attempt2.py")


def test_run_case_does_not_retry_when_docs_work(tmp_path: Path) -> None:
    case = _make_case(tmp_path)
    client = _StubClient([_response("print('DOCS_OK')  # DOC-LITERAL\n", "none")])
    record = run_case(case, client, _StubVenvs(case), tmp_path / "out", NO_ISOLATION, timeout=20, log=lambda _: None)
    assert record["status"] == STATUS_NOT_REPRODUCED and len(client.calls) == 1


def test_load_cases_from_traces(tmp_path: Path) -> None:
    case = _make_case(tmp_path)
    trace = tmp_path / "fakelib-1.json"
    trace.write_text(json.dumps({"summary": {"repo_url": "u"}, "output": {"findings": [case.finding]}}), encoding="utf-8")
    cases = load_cases_from_traces([trace], {"fakelib": {"path": str(case.source_dir), "ref": "abc"}})
    assert [c.case_id for c in cases] == ["fakelib-1:DD-1"] and cases[0].ref == "abc"
    with pytest.raises(KeyError):
        load_cases_from_traces([trace], {})


def test_summarise_precision_with_and_without_filter() -> None:
    results = {
        "a": {"status": STATUS_REPRODUCED, "evidence": "interface_error"},
        "b": {"status": STATUS_REPRODUCED, "evidence": "assertion"},
        "c": {"status": STATUS_NOT_REPRODUCED},
        "d": {"status": STATUS_COULD_NOT_RUN},
    }
    labels = {"a": "true", "b": "false", "c": "true", "d": "unclear"}
    summary = summarise(results, labels)
    assert summary["precision_without_filter"] == 0.5
    assert summary["precision_with_filter"] == 0.5 and summary["kept_with_filter"] == 2
    assert summary["true_by_status"] == {STATUS_REPRODUCED: 1, STATUS_NOT_REPRODUCED: 1, STATUS_COULD_NOT_RUN: 0}
    assert summary["reproduced_via_assertion"] == 1
    assert summary["precision_with_strict_filter"] == 1.0 and summary["kept_with_strict_filter"] == 1


def test_beam_client_uses_cache_and_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = BeamReproClient("https://example.invalid/v1", "beam", "k", tmp_path / "c", tmp_path / "lock", token_budget=10)
    with pytest.raises(TokenBudgetExceeded):
        client.complete([{"role": "user", "content": "hello"}])

    calls: list[int] = []

    class _Resp:
        status_code = 200
        headers: dict = {}

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}

    def fake_post(*args, **kwargs):
        calls.append(1)
        assert kwargs["headers"]["Authorization"] == "Bearer k"
        return _Resp()

    monkeypatch.setattr("repoatlas.repro.requests.post", fake_post)
    client = BeamReproClient("https://example.invalid/v1", "beam", "k", tmp_path / "c", tmp_path / "lock", max_tokens=10)
    messages = [{"role": "user", "content": "hello"}]
    assert client.complete(messages)[0] == "{}" and client.complete(messages)[0] == "{}"
    assert calls == [1] and client.total_tokens == 10 and client.usage["cached_calls"] == 1


def test_beam_client_backs_off_on_429(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    statuses = [429, 200]
    sleeps: list[float] = []

    class _Resp:
        def __init__(self, code: int) -> None:
            self.status_code = code
            self.headers = {"retry-after": "2"} if code == 429 else {}
            self.text = "rate limited"

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr("repoatlas.repro.requests.post", lambda *a, **k: _Resp(statuses.pop(0)))
    monkeypatch.setattr("repoatlas.repro.time.sleep", sleeps.append)
    client = BeamReproClient("https://example.invalid/v1", "beam", "k", tmp_path / "c", tmp_path / "lock")
    assert client.complete([{"role": "user", "content": "x"}])[0] == "ok"
    assert client.usage["http_429"] == 1 and sleeps == [5.0]


def test_exception_in_setup_does_not_count(tmp_path: Path) -> None:
    script = "import json\njson.dumps({}, bad_setup=1)\njson.dumps({})  # DOC-LITERAL\n"
    run, path = _run(script, tmp_path)
    result = classify_run(run, _plan("TypeError"), path, {"json"})
    assert result.status == STATUS_COULD_NOT_RUN and result.reason == "failed_outside_doc_literal" and result.retryable


def test_doc_literal_block_markers(tmp_path: Path) -> None:
    script = "import json\n# DOC-LITERAL-BEGIN\nx = 1\njson.dumps({}, nope=1)\n# DOC-LITERAL-END\n"
    run, path = _run(script, tmp_path)
    assert classify_run(run, _plan("TypeError"), path, {"json"}).status == STATUS_REPRODUCED


def test_marker_on_comment_only_is_rejected() -> None:
    assert any("DOC-LITERAL" in p for p in lint_script("import json\n# DOC-LITERAL\nprint('DOCS_OK')\n"))


def test_other_exception_evidence(tmp_path: Path) -> None:
    run, path = _run("int('x')  # DOC-LITERAL\n", tmp_path)
    assert classify_run(run, _plan("ValueError"), path, set()).evidence == "other_exception"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("finding is real", "likely_true"), ("True", "likely_true"), ("false positive", "likely_false"), ("", "unclear"), ("likely_false", "likely_false")],
)
def test_normalise_verdict(raw: str, expected: str) -> None:
    from repoatlas.repro import normalise_verdict

    assert normalise_verdict(raw) == expected
