"""Tests for live-mode guardrails in the Space application."""

from __future__ import annotations

from repoatlas import app as space_app


def test_live_mode_disabled_without_required_secret() -> None:
    """
    @brief Ensure live mode is disabled when the provider key is missing.
    """

    enabled, message = space_app.get_live_mode_status(
        provider="ollama",
        environment={"BEAM_PROVIDER": "ollama"},
    )
    assert enabled is False
    assert "missing OLLAMA_API_KEY" in message


def test_rate_limiter_blocks_third_request_in_one_hour_window() -> None:
    """
    @brief Ensure per-IP limiter allows two runs per hour and blocks the third.
    """

    previous_limit: int = space_app.LIVE_RATE_LIMIT_PER_HOUR_PER_IP
    space_app.LIVE_RATE_LIMIT_PER_HOUR_PER_IP = 2
    space_app._reset_live_state_for_tests()
    try:
        first_allowed, _ = space_app._record_rate_limited_request("1.2.3.4", now_epoch=1_000.0)
        second_allowed, _ = space_app._record_rate_limited_request("1.2.3.4", now_epoch=1_100.0)
        third_allowed, third_message = space_app._record_rate_limited_request("1.2.3.4", now_epoch=1_200.0)
    finally:
        space_app.LIVE_RATE_LIMIT_PER_HOUR_PER_IP = previous_limit
        space_app._reset_live_state_for_tests()

    assert first_allowed is True
    assert second_allowed is True
    assert third_allowed is False
    assert "per-IP limit reached" in third_message
