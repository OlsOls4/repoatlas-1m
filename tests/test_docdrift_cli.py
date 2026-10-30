"""Fixture tests for `docdrift run` with no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from repoatlas.cli import build_parser, main
from repoatlas.pipeline import TRIAGE_MAX_TOKENS, TokenGuardError, format_preflight, run_docdrift


FIXTURE: Path = Path("tests/fixtures/docdrift_toy")


class FakeClient:
    """
    @brief In-memory Beam stand-in for tests.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.max_tokens: list[int] = []
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int) -> dict[str, object]:
        self.calls += 1
        self.max_tokens.append(max_tokens)
        self.messages.append(messages)
        if self.calls == 1:
            return {"verdicts": [{"candidate_id": "C01", "verdict": "true_drift", "reason": "param title is not in greet"}]}
        return {"status": "planned", "script": "from toy import greet\ngreet(title='Ada')\n"}


def test_parser_has_run_and_max_tokens() -> None:
    """
    @brief CLI exposes run + --max-tokens.
    """

    parser = build_parser()
    args = parser.parse_args(["run", str(FIXTURE), "--max-tokens", "1000", "--preflight-only"])
    assert args.command == "run"
    assert args.max_tokens == 1000
    assert args.preflight_only is True
    help_text = parser.format_help()
    run_parser = parser._subparsers._group_actions[0].choices["run"]
    assert "--docstring-chunks" not in run_parser._option_string_actions
    assert "scripts/beamv3.py" in help_text
    assert "first two steps" not in help_text
    assert "executable repro" in help_text.lower()
    assert "--out" in run_parser._option_string_actions
    assert "--repro-budget" in run_parser._option_string_actions
    out_args = parser.parse_args(["run", str(FIXTURE), "--out", "fresh_run", "--repro-budget", "100000"])
    assert out_args.out == "fresh_run"
    assert out_args.repro_budget == 100000


def test_preflight_only_does_not_need_a_key(capsys: pytest.CaptureFixture[str]) -> None:
    """
    @brief --preflight-only must work without OLLAMA_API_KEY or network.
    """

    code = main(["run", str(FIXTURE), "--preflight-only", "--max-tokens", "900000"])
    captured = capsys.readouterr()
    assert code == 0
    assert "projected prompt tokens=" in captured.out
    assert "symbol flags=" in captured.out


def test_token_guard_blocks_before_client() -> None:
    """
    @brief --max-tokens must abort before the injected client is used.
    """

    client = FakeClient()
    with pytest.raises(TokenGuardError):
        run_docdrift(str(FIXTURE), max_tokens=1, client=client, pack_token_limit=400_000)
    assert client.calls == 0


def test_injected_client_runs_triage_and_repro() -> None:
    """
    @brief A fake client is enough for a full offline pipeline turn.
    """

    client = FakeClient()
    result = run_docdrift(str(FIXTURE), max_tokens=900_000, client=client)
    assert client.calls == 2
    assert TRIAGE_MAX_TOKENS == 32_000
    assert client.max_tokens[0] == 32_000
    prompt = client.messages[0][1]["content"]
    assert "Packed repository context follows" in prompt
    assert "[:20000]" not in Path("repoatlas/pipeline.py").read_text(encoding="utf-8")
    assert result.triage["verdicts"][0]["verdict"] == "true_drift"
    assert result.repros
    assert "projected prompt tokens=" in format_preflight(result)
    assert "def greet" in prompt


def test_run_without_key_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    @brief Live run without a key must not touch the network.
    """

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    assert main(["run", str(FIXTURE), "--max-tokens", "900000"]) == 2
