"""Tests for benchmark script repo catalogue helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_benchmark as benchmark_script
from repoatlas.config import RepoAtlasConfig
from repoatlas.models import RepoPack


def test_load_repo_specs_from_yaml_and_filter_names(tmp_path: Path) -> None:
    """
    @brief Ensure YAML repo catalogues load and --repos style filtering preserves order.
    @param tmp_path Temporary directory provided by pytest.
    """

    yaml_path: Path = tmp_path / "repos.yaml"
    yaml_path.write_text(
        "repos:\n"
        "  - name: fastapi\n"
        "    repo_url: https://github.com/fastapi/fastapi\n"
        "    ref: master\n"
        "    reason: api docs\n"
        "  - name: typer\n"
        "    repo_url: https://github.com/fastapi/typer\n"
        "    ref: master\n"
        "    reason: cli docs\n",
        encoding="utf-8",
    )
    specs = benchmark_script._load_repo_specs(yaml_path)
    filtered = benchmark_script._filter_repo_specs(specs, "typer,fastapi")
    assert [spec["name"] for spec in filtered] == ["typer", "fastapi"]


def test_filter_repo_specs_rejects_unknown_names() -> None:
    """
    @brief Ensure unknown --repos values fail with a clear error.
    """

    specs = [
        benchmark_script.RepoSpec(
            name="fastapi",
            repo_url="https://github.com/fastapi/fastapi",
            ref="master",
            reason="api docs",
        )
    ]
    try:
        benchmark_script._filter_repo_specs(specs, "missing")
    except ValueError as error:
        assert "Unknown repo names" in str(error)
    else:
        raise AssertionError("Expected ValueError for unknown repo name.")


def test_dry_run_supports_nine_hundred_k_token_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    @brief Ensure dry-run output handles a ~900k token limit end to end.
    @param monkeypatch Pytest monkeypatch fixture.
    @param capsys Pytest output capture fixture.
    """

    from repoatlas.benchmark import BenchmarkCase

    def fake_pack_repository(**_: object) -> RepoPack:
        return RepoPack(
            repo_url="https://github.com/fastapi/fastapi",
            ref="master",
            prefix_hash="hash",
            total_tokens=737000,
            token_limit=900000,
            truncated=True,
            packed_at="2026-10-26T00:00:00Z",
            files=[],
            skipped_paths=[],
            pack_text="fixture",
        )

    monkeypatch.setattr(benchmark_script, "pack_repository", fake_pack_repository)
    config: RepoAtlasConfig = RepoAtlasConfig.from_environment(provider="fixture", token_limit=900000)
    case = BenchmarkCase(
        repo_url="https://github.com/fastapi/fastapi",
        ref="master",
        token_limit=900000,
        case_name="fastapi-900000",
    )
    benchmark_script._run_dry_run([case], config)
    captured: str = capsys.readouterr().out
    assert "projected_prompt_tokens=" in captured
    assert "token_limit=900000" in captured
