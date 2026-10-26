"""Write the static Hugging Face Space from recorded DocDrift results."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT: Path = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repoatlas.static_build import write_static_space


def main() -> None:
    """
    @brief Generate static_space/ from results_live artifacts.
    """

    target: Path = write_static_space()
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
