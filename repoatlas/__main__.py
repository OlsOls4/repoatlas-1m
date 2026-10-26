"""Allow `python3 -m repoatlas` to run the DocDrift CLI."""

from repoatlas.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
