"""Run RepoAtlas benchmark cases in fixture or live mode."""

from __future__ import annotations

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import json
from pathlib import Path
from typing import TypedDict

from repoatlas.benchmark import BenchmarkCase, run_benchmark
from repoatlas.config import RepoAtlasConfig
from repoatlas.packer import pack_repository


DEFAULT_REPOS_FILE: Path = Path("fixtures/benchmark_repos.json")
DEFAULT_FIXTURE_PATH: Path = Path("fixtures/analysis_fixture.json")
DEFAULT_OUTPUT_DIRECTORY: Path = Path("results")
DEFAULT_LIVE_OUTPUT_DIRECTORY: Path = Path("results_live")
DEFAULT_TOKEN_LIMITS: tuple[int, ...] = (120_000, 240_000, 400_000)


class RepoSpec(TypedDict):
    """
    @brief Repository specification loaded from benchmark fixtures.
    @param name Human-readable repository name.
    @param repo_url Public GitHub repository URL.
    @param ref Branch, tag, or commit.
    """

    name: str
    repo_url: str
    ref: str


# Private function prototypes:
# - _parse_token_limits(raw_limits: str) -> list[int]
# - _load_repo_specs(repos_file: Path) -> list[RepoSpec]
# - _build_cases(repo_specs: list[RepoSpec], token_limits: list[int], max_repos: int | None) -> list[BenchmarkCase]
# - _run_dry_run(cases: list[BenchmarkCase], config: RepoAtlasConfig) -> None


def parse_args() -> argparse.Namespace:
    """
    @brief Parse command-line arguments for benchmark execution.
    """

    parser = argparse.ArgumentParser(description="Run RepoAtlas benchmark cases.")
    parser.add_argument("--repos-file", type=Path, default=DEFAULT_REPOS_FILE, help="JSON file listing repository specs.")
    parser.add_argument(
        "--token-limits",
        type=str,
        default=",".join(str(item) for item in DEFAULT_TOKEN_LIMITS),
        help="Comma-separated token limits for sweep runs.",
    )
    parser.add_argument("--provider", choices=["ollama", "reflection", "fixture"], default=None)
    parser.add_argument("--max-repos", type=int, default=None, help="Small-budget mode, for example --max-repos 2.")
    parser.add_argument("--dry-run", action="store_true", help="Estimate context sizes without making live model calls.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Results directory. Defaults to results/ for fixture runs and results_live/ for live runs.",
    )
    return parser.parse_args()


def main() -> None:
    """
    @brief Entrypoint for benchmark execution.
    """

    args = parse_args()
    token_limits: list[int] = _parse_token_limits(args.token_limits)
    provider_override: str | None = args.provider
    config: RepoAtlasConfig = RepoAtlasConfig.from_environment(provider=provider_override, token_limit=max(token_limits))
    if args.dry_run:
        config.provider = "fixture"
    repo_specs: list[RepoSpec] = _load_repo_specs(args.repos_file)
    cases: list[BenchmarkCase] = _build_cases(repo_specs, token_limits=token_limits, max_repos=args.max_repos)
    if args.dry_run:
        _run_dry_run(cases, config)
        return
    output_directory: Path = _resolve_output_directory(args.output_dir, config.provider)
    results_df = run_benchmark(
        cases=cases,
        base_config=config,
        fixture_path=DEFAULT_FIXTURE_PATH,
        output_directory=output_directory,
    )
    print(f"Benchmark complete: {len(results_df)} rows written to {output_directory / 'benchmark_results.csv'}")


def _resolve_output_directory(requested: Path | None, provider: str) -> Path:
    """
    @brief Pick the results directory; live runs never write into the committed fixture results.
    @param requested Directory from --output-dir, if any.
    @param provider Active provider name.
    """

    is_live: bool = provider != "fixture"
    if requested is None:
        return DEFAULT_LIVE_OUTPUT_DIRECTORY if is_live else DEFAULT_OUTPUT_DIRECTORY
    if is_live and requested.resolve() == DEFAULT_OUTPUT_DIRECTORY.resolve():
        raise SystemExit("Refusing to write live results into results/ (fixture results). Use results_live/ or another directory.")
    return requested


def _parse_token_limits(raw_limits: str) -> list[int]:
    """
    @brief Parse a comma-separated token-limit argument string.
    @param raw_limits Comma-separated token-limit string.
    """

    parsed: list[int] = []
    for part in raw_limits.split(","):
        stripped: str = part.strip()
        if not stripped:
            continue
        parsed.append(int(stripped))
    if not parsed:
        raise ValueError("At least one token limit is required.")
    return parsed


def _load_repo_specs(repos_file: Path) -> list[RepoSpec]:
    """
    @brief Load repository benchmark specifications from JSON.
    @param repos_file Path to repository-spec JSON file.
    """

    payload: object = json.loads(repos_file.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Repository specs file must contain a JSON list.")
    repo_specs: list[RepoSpec] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        repo_url = item.get("repo_url")
        ref = item.get("ref", "main")
        if isinstance(name, str) and isinstance(repo_url, str) and isinstance(ref, str):
            repo_specs.append(RepoSpec(name=name, repo_url=repo_url, ref=ref))
    return repo_specs


def _build_cases(repo_specs: list[RepoSpec], token_limits: list[int], max_repos: int | None) -> list[BenchmarkCase]:
    """
    @brief Build benchmark cases from repository specs and token limits.
    @param repo_specs Repository specifications.
    @param token_limits Token limits to sweep.
    @param max_repos Optional cap for small-budget mode.
    """

    selected_specs: list[RepoSpec] = repo_specs[:max_repos] if max_repos is not None else repo_specs
    cases: list[BenchmarkCase] = []
    for spec in selected_specs:
        for token_limit in token_limits:
            case_name: str = f"{spec['name']}-{token_limit}"
            cases.append(
                BenchmarkCase(
                    repo_url=spec["repo_url"],
                    ref=spec["ref"],
                    token_limit=token_limit,
                    case_name=case_name,
                )
            )
    return cases


def _run_dry_run(cases: list[BenchmarkCase], config: RepoAtlasConfig) -> None:
    """
    @brief Estimate packed-context sizes and truncation behaviour without inference calls.
    @param cases Benchmark case list.
    @param config Runtime configuration.
    """

    print("Dry-run mode: estimating packed context tokens only.")
    for case in cases:
        pack = pack_repository(
            repo_url=case.repo_url,
            ref=case.ref,
            token_limit=case.token_limit,
            cache_dir=config.cache_dir,
        )
        print(
            f"{case.case_name}: context_tokens={pack.total_tokens} "
            f"truncated={pack.truncated} files={len(pack.files)} prefix_hash={pack.prefix_hash[:12]}"
        )


if __name__ == "__main__":
    main()
