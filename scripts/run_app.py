"""Launch the RepoAtlas Gradio app."""

from __future__ import annotations

import argparse

from repoatlas.app import launch_app


def parse_args() -> argparse.Namespace:
    """
    @brief Parse command-line arguments for launching the Gradio app.
    """

    parser = argparse.ArgumentParser(description="Run RepoAtlas Gradio app.")
    parser.add_argument("--port", type=int, default=43123, help="Port to bind for preview.")
    return parser.parse_args()


def main() -> None:
    """
    @brief Entrypoint for Gradio app launch.
    """

    args = parse_args()
    launch_app(server_port=args.port)


if __name__ == "__main__":
    main()
