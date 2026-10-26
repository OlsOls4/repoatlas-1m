"""Tests for benchmark resilience and output-directory safety."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import repoatlas.benchmark as benchmark_module
from repoatlas.benchmark import BenchmarkCase, run_benchmark
from repoatlas.config import RepoAtlasConfig


def test_failed_case_becomes_error_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    @brief One failing case is recorded as an error row and later cases still run.
    """

    calls: list[str] = []

    def fake_analyse(repo_url: str, **_: object) -> object:
        calls.append(repo_url)
        raise RuntimeError("boom")

    monkeypatch.setattr(benchmark_module, "analyse_repository", fake_analyse)
    config = RepoAtlasConfig.from_environment(provider="fixture", token_limit=1000)
    cases = [
        BenchmarkCase(repo_url="https://github.com/a/a", ref="main", token_limit=1000, case_name="a-1000"),
        BenchmarkCase(repo_url="https://github.com/b/b", ref="main", token_limit=1000, case_name="b-1000"),
    ]
    df: pd.DataFrame = run_benchmark(cases, config, Path("fixtures/analysis_fixture.json"), tmp_path)
    assert len(calls) == 2
    assert list(df["status"]) == ["error", "error"]
    assert df["error"].str.contains("boom").all()
    assert (tmp_path / "benchmark_results.csv").exists()


def test_live_runs_default_to_results_live() -> None:
    """
    @brief Live runs default to results_live/ and refuse to overwrite fixture results/.
    """

    import run_benchmark as script

    assert script._resolve_output_directory(None, "ollama") == Path("results_live")
    assert script._resolve_output_directory(None, "fixture") == Path("results")
    with pytest.raises(SystemExit):
        script._resolve_output_directory(Path("results"), "ollama")
