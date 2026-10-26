"""Run RepoAtlas benchmark cases in fixture or live mode."""

from __future__ import annotations

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import json
from pathlib import Path
from typing import TypedDict

import yaml

from repoatlas.benchmark import BenchmarkCase, run_benchmark
from repoatlas.config import RepoAtlasConfig
from repoatlas.packer import estimate_prompt_tokens, pack_repository


DEFAULT_REPOS_FILE: Path = Path("fixtures/benchmark_repos.json")
DEFAULT_REPOS_CANDIDATES_FILE: Path = Path("benchmarks/repos_candidates.yaml")
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
    @param reason One-line rationale for benchmark candidacy.
    """

    name: str
    repo_url: str
    ref: str
    reason: str


# Private function prototypes:
# - _parse_token_limits(raw_limits: str) -> list[int]
# - _load_repo_specs(repos_file: Path) -> list[RepoSpec]
# - _parse_repo_specs_payload(payload: object) -> list[RepoSpec]
# - _filter_repo_specs(repo_specs: list[RepoSpec], repos_arg: str | None) -> list[RepoSpec]
# - _print_repo_catalog(repo_specs: list[RepoSpec]) -> None
# - _build_cases(repo_specs: list[RepoSpec], token_limits: list[int], max_repos: int | None) -> list[BenchmarkCase]
# - _run_dry_run(cases: list[BenchmarkCase], config: RepoAtlasConfig) -> None


def parse_args() -> argparse.Namespace:
    """
    @brief Parse command-line arguments for benchmark execution.
    """

    parser = argparse.ArgumentParser(description="Run RepoAtlas benchmark cases.")
    parser.add_argument("--repos-file", type=Path, default=DEFAULT_REPOS_FILE, help="JSON or YAML file listing repository specs.")
    parser.add_argument(
        "--repos-candidates-file",
        type=Path,
        default=DEFAULT_REPOS_CANDIDATES_FILE,
        help="YAML catalogue of repo candidates with reasons.",
    )
    parser.add_argument(
        "--repos",
        type=str,
        default=None,
        help="Comma-separated repository names to run (selected from --repos-file).",
    )
    parser.add_argument(
        "--list-repos",
        action="store_true",
        help="List candidate repositories from --repos-candidates-file and exit.",
    )
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
    if args.list_repos:
        repo_catalog_specs: list[RepoSpec] = _load_repo_specs(args.repos_candidates_file)
        _print_repo_catalog(repo_catalog_specs)
        return
    if args.dry_run:
        config.provider = "fixture"
    repo_specs: list[RepoSpec] = _load_repo_specs(args.repos_file)
    selected_repo_specs: list[RepoSpec] = _filter_repo_specs(repo_specs, args.repos)
    cases: list[BenchmarkCase] = _build_cases(selected_repo_specs, token_limits=token_limits, max_repos=args.max_repos)
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
    @brief Load repository benchmark specifications from JSON or YAML.
    @param repos_file Path to repository-spec JSON file.
    """

    suffix: str = repos_file.suffix.lower()
    raw_text: str = repos_file.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        payload: object = yaml.safe_load(raw_text)
    else:
        payload = json.loads(raw_text)
    return _parse_repo_specs_payload(payload)


def _parse_repo_specs_payload(payload: object) -> list[RepoSpec]:
    """
    @brief Parse repository-spec payloads from list or keyed YAML structures.
    @param payload Decoded JSON or YAML object.
    """

    payload_items: object = payload
    if isinstance(payload, dict):
        payload_items = payload.get("repos")
    if not isinstance(payload_items, list):
        raise ValueError("Repository specs file must contain a list or a {repos: [...]} mapping.")
    repo_specs: list[RepoSpec] = []
    for item in payload_items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        repo_url = item.get("repo_url")
        ref = item.get("ref", "main")
        reason = item.get("reason", "")
        if isinstance(name, str) and isinstance(repo_url, str) and isinstance(ref, str) and isinstance(reason, str):
            repo_specs.append(RepoSpec(name=name, repo_url=repo_url, ref=ref, reason=reason))
    return repo_specs


def _filter_repo_specs(repo_specs: list[RepoSpec], repos_arg: str | None) -> list[RepoSpec]:
    """
    @brief Filter repository specs by comma-separated names.
    @param repo_specs Repository specifications.
    @param repos_arg Comma-separated repository names, or None.
    """

    if repos_arg is None or not repos_arg.strip():
        return repo_specs
    requested_names: list[str] = [item.strip() for item in repos_arg.split(",") if item.strip()]
    requested_set: set[str] = set(requested_names)
    repo_map: dict[str, RepoSpec] = {spec["name"]: spec for spec in repo_specs}
    missing_names: list[str] = [name for name in requested_names if name not in repo_map]
    if missing_names:
        available: str = ", ".join(sorted(repo_map.keys()))
        missing: str = ", ".join(missing_names)
        raise ValueError(f"Unknown repo names: {missing}. Available: {available}")
    return [repo_map[name] for name in requested_names if name in requested_set]


def _print_repo_catalog(repo_specs: list[RepoSpec]) -> None:
    """
    @brief Print candidate repository names with one-line reasons.
    @param repo_specs Repository specifications.
    """

    for spec in repo_specs:
        print(f"{spec['name']}: {spec['reason']}")


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
            token_calibration_factor=config.token_calibration_factor,
            cache_dir=config.cache_dir,
        )
        projected_prompt_tokens: int = estimate_prompt_tokens(pack.total_tokens, config.token_calibration_factor)
        print(
            f"{case.case_name}: estimated_tokens={pack.total_tokens} projected_prompt_tokens={projected_prompt_tokens} "
            f"token_limit={case.token_limit} calibration_factor={config.token_calibration_factor:.2f} "
            f"truncated={pack.truncated} files={len(pack.files)} prefix_hash={pack.prefix_hash[:12]}"
        )


if __name__ == "__main__":
    main()
