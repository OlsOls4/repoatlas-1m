"""Fixture tests for `docdrift run` with no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from repoatlas.cli import build_parser, main
from repoatlas.pipeline import TokenGuardError, format_preflight, run_docdrift


FIXTURE: Path = Path("tests/fixtures/docdrift_toy")


class FakeClient:
    """
    @brief In-memory Beam stand-in for tests.
    """

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int) -> dict[str, object]:
        self.calls += 1
        del messages, max_tokens
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
    assert result.triage["verdicts"][0]["verdict"] == "true_drift"
    assert result.repros
    assert "projected prompt tokens=" in format_preflight(result)


def test_run_without_key_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    @brief Live run without a key must not touch the network.
    """

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    assert main(["run", str(FIXTURE), "--max-tokens", "900000"]) == 2
