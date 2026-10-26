"""Deploy helper to publish the Space-ready subset of this repository."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from huggingface_hub import HfApi


DEFAULT_COMMIT_MESSAGE: str = "Update RepoAtlas-1M Space app bundle"


# Private function prototypes:
# - _parse_args() -> argparse.Namespace
# - _resolve_token(cli_token: str | None) -> str
# - _validate_workspace_root(root_path: Path) -> None
# - _deploy_space_bundle(space_id: str, token: str, private: bool, root_path: Path, commit_message: str) -> None


def main() -> None:
    """
    @brief Parse arguments and upload the Space bundle to Hugging Face.
    """

    args: argparse.Namespace = _parse_args()
    token: str = _resolve_token(args.token)
    root_path: Path = Path(args.root).resolve()
    _validate_workspace_root(root_path)
    _deploy_space_bundle(
        space_id=args.space_id,
        token=token,
        private=not args.public,
        root_path=root_path,
        commit_message=args.commit_message,
    )


def _parse_args() -> argparse.Namespace:
    """
    @brief Parse command-line options for Space deployment.
    """

    parser = argparse.ArgumentParser(
        description="Push only Space-required files to a Hugging Face Space repository."
    )
    parser.add_argument("space_id", type=str, help="Space repo id, for example username/repoatlas-1m.")
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Hugging Face token. Defaults to HF_TOKEN environment variable.",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Create/update the Space as public. Default is private.",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=".",
        help="Repository root containing app.py, repoatlas/, and results_live/.",
    )
    parser.add_argument(
        "--commit-message",
        type=str,
        default=DEFAULT_COMMIT_MESSAGE,
        help="Commit message for the Space upload.",
    )
    return parser.parse_args()


def _resolve_token(cli_token: str | None) -> str:
    """
    @brief Resolve Hugging Face token from argument or environment.
    @param cli_token Optional token provided on CLI.
    """

    token: str = (cli_token or os.environ.get("HF_TOKEN", "")).strip()
    if not token:
        raise SystemExit("Missing Hugging Face token. Set HF_TOKEN or pass --token.")
    return token


def _validate_workspace_root(root_path: Path) -> None:
    """
    @brief Validate that the expected Space files exist under root.
    @param root_path Candidate repository root path.
    """

    required_paths: list[Path] = [
        root_path / "app.py",
        root_path / "README.md",
        root_path / "requirements.txt",
        root_path / "repoatlas",
        root_path / "results_live",
    ]
    missing: list[str] = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise SystemExit(f"Missing required files/directories: {', '.join(missing)}")


def _deploy_space_bundle(
    space_id: str,
    token: str,
    private: bool,
    root_path: Path,
    commit_message: str,
) -> None:
    """
    @brief Create/update a Space and upload only required runtime assets.
    @param space_id Hugging Face Space id.
    @param token Hugging Face API token.
    @param private Whether the Space should remain private.
    @param root_path Repository root path.
    @param commit_message Commit message for the upload.
    """

    api: HfApi = HfApi(token=token)
    api.create_repo(
        repo_id=space_id,
        repo_type="space",
        private=private,
        exist_ok=True,
    )
    api.upload_folder(
        folder_path=str(root_path),
        repo_id=space_id,
        repo_type="space",
        token=token,
        commit_message=commit_message,
        allow_patterns=[
            "app.py",
            "README.md",
            "requirements.txt",
            "repoatlas/**",
            "results_live/**",
            "docs/hero.png",
        ],
        ignore_patterns=[
            "results_live/traces/**",
            "dataset/**",
            ".git/**",
            "__pycache__/**",
            ".pytest_cache/**",
            ".cache/**",
        ],
    )
    print(
        f"Uploaded Space bundle to https://huggingface.co/spaces/{space_id} "
        f"(private={private}, traces excluded)."
    )


if __name__ == "__main__":
    main()
