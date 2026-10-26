"""Write hf_dataset/ from recorded DocDrift v2 results."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT: Path = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repoatlas.hf_dataset import build_hf_dataset


def main() -> None:
    """
    @brief Generate the unpublished v2 dataset folder.
    """

    target = build_hf_dataset()
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
