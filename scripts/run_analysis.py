"""Run a single RepoAtlas analysis and write artefacts locally."""

from __future__ import annotations

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
from pathlib import Path

from repoatlas.analyser import analyse_repository, save_analysis_bundle
from repoatlas.config import RepoAtlasConfig
from repoatlas.packer import pack_repository


DEFAULT_FIXTURE_PATH: Path = Path("fixtures/analysis_fixture.json")


def parse_args() -> argparse.Namespace:
    """
    @brief Parse command-line arguments for one analysis run.
    """

    parser = argparse.ArgumentParser(description="Run one RepoAtlas analysis.")
    parser.add_argument("repo_url", type=str, help="Public GitHub repository URL.")
    parser.add_argument("--ref", type=str, default="main", help="Branch, tag, or commit.")
    parser.add_argument("--provider", choices=["ollama", "reflection", "fixture"], default=None)
    parser.add_argument("--token-limit", type=int, default=400_000)
    parser.add_argument("--output-dir", type=Path, default=Path("results/live_runs"))
    parser.add_argument("--dry-run", action="store_true", help="Pack and estimate tokens only.")
    return parser.parse_args()


def main() -> None:
    """
    @brief Entrypoint for one analysis run.
    """

    args = parse_args()
    config: RepoAtlasConfig = RepoAtlasConfig.from_environment(provider=args.provider, token_limit=args.token_limit)
    if args.dry_run:
        pack = pack_repository(
            repo_url=args.repo_url,
            ref=args.ref,
            token_limit=config.token_limit,
            cache_dir=config.cache_dir,
        )
        print(
            f"Dry-run pack: context_tokens={pack.total_tokens} truncated={pack.truncated} "
            f"files={len(pack.files)} prefix_hash={pack.prefix_hash}"
        )
        return
    bundle = analyse_repository(
        repo_url=args.repo_url,
        ref=args.ref,
        config=config,
        fixture_path=DEFAULT_FIXTURE_PATH,
        run_probes=False,
    )
    save_analysis_bundle(bundle, output_directory=args.output_dir)
    print(
        f"Analysis complete for {args.repo_url}@{args.ref}: "
        f"{bundle.summary.findings_fully_verified}/{bundle.summary.findings_total} verified findings."
    )


if __name__ == "__main__":
    main()
