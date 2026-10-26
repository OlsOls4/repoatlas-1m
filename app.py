"""Hugging Face Space entrypoint for RepoAtlas-1M."""

from __future__ import annotations

from repoatlas.app import CUSTOM_CSS, THEME, build_app


demo = build_app()
demo.queue(default_concurrency_limit=1)


def main() -> None:
    """
    @brief Launch the RepoAtlas-1M Gradio Space application.
    """

    demo.launch(server_name="0.0.0.0", server_port=7860, theme=THEME, css=CUSTOM_CSS)


if __name__ == "__main__":
    main()
