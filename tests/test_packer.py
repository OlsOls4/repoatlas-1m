"""Tests for repository packer behaviour."""

from __future__ import annotations

from pathlib import Path

from repoatlas.packer import build_pack_from_directory, estimate_prompt_tokens


def test_packer_is_deterministic_for_same_inputs(tmp_path: Path) -> None:
    """
    @brief Ensure packed output hash remains stable across repeated runs.
    @param tmp_path Temporary directory provided by pytest.
    """

    (tmp_path / "README.md").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "src.py").write_text("print('hello')\n", encoding="utf-8")
    pack_a = build_pack_from_directory("https://github.com/example/repo", "main", tmp_path, token_limit=10_000)
    pack_b = build_pack_from_directory("https://github.com/example/repo", "main", tmp_path, token_limit=10_000)
    assert pack_a.prefix_hash == pack_b.prefix_hash
    assert pack_a.pack_text == pack_b.pack_text


def test_packer_skips_binary_and_lockfiles(tmp_path: Path) -> None:
    """
    @brief Confirm binary files and lockfiles are excluded from packed output.
    @param tmp_path Temporary directory provided by pytest.
    """

    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{\"lock\": true}\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02\x03")
    pack = build_pack_from_directory("https://github.com/example/repo", "main", tmp_path, token_limit=10_000)
    paths: list[str] = [file_snapshot.path for file_snapshot in pack.files]
    assert "README.md" in paths
    assert "package-lock.json" not in paths
    assert "blob.bin" not in paths


def test_packer_honours_token_limit_by_truncating(tmp_path: Path) -> None:
    """
    @brief Verify packer truncates content when the token limit is too small.
    @param tmp_path Temporary directory provided by pytest.
    """

    (tmp_path / "README.md").write_text("\n".join(f"line-{index}" for index in range(1, 200)), encoding="utf-8")
    pack = build_pack_from_directory("https://github.com/example/repo", "main", tmp_path, token_limit=120)
    assert pack.total_tokens <= 120
    assert pack.truncated is True


def test_packer_keeps_code_and_docs_under_small_budget(tmp_path: Path) -> None:
    """
    @brief Ensure a tight budget holds both source and docs, and skips uv.lock.
    @param tmp_path Temporary directory provided by pytest.
    """

    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    for index in range(5):
        (tmp_path / "docs" / f"a{index}.rst").write_text("doc line\n" * 40, encoding="utf-8")
        (tmp_path / "src" / f"m{index}.py").write_text("x = 1\n" * 40, encoding="utf-8")
    (tmp_path / "uv.lock").write_text("lock\n", encoding="utf-8")
    pack = build_pack_from_directory("https://github.com/example/repo", "main", tmp_path, token_limit=900)
    paths: list[str] = [file_snapshot.path for file_snapshot in pack.files]
    assert any(path.startswith("src/") for path in paths)
    assert any(path.startswith("docs/") for path in paths)
    assert "uv.lock" not in paths
    assert pack.total_tokens <= 900


def test_packer_prioritises_core_imported_module_over_many_small_files(tmp_path: Path) -> None:
    """
    @brief Ensure __init__ imports and doc-referenced core modules are kept in tight budgets.
    @param tmp_path Temporary directory provided by pytest.
    """

    (tmp_path / "fastapi").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "fastapi" / "__init__.py").write_text(
        "from .routing import APIRouter\n",
        encoding="utf-8",
    )
    (tmp_path / "fastapi" / "routing.py").write_text(
        "\n".join([f"class Route{index}: pass" for index in range(120)]),
        encoding="utf-8",
    )
    for index in range(30):
        (tmp_path / "docs" / f"note-{index}.md").write_text("placeholder docs text\n", encoding="utf-8")
    (tmp_path / "docs" / "api.md").write_text("Core implementation is in routing.py\n", encoding="utf-8")
    pack = build_pack_from_directory(
        "https://github.com/tiangolo/fastapi",
        "main",
        tmp_path,
        token_limit=2_500,
    )
    paths: list[str] = [file_snapshot.path for file_snapshot in pack.files]
    assert "fastapi/__init__.py" in paths
    assert "fastapi/routing.py" in paths


def test_token_calibration_factor_reduces_estimated_budget(tmp_path: Path) -> None:
    """
    @brief Verify calibration keeps estimated token usage under token_limit/factor.
    @param tmp_path Temporary directory provided by pytest.
    """

    (tmp_path / "README.md").write_text("\n".join(["line"] * 600), encoding="utf-8")
    pack = build_pack_from_directory(
        "https://github.com/example/repo",
        "main",
        tmp_path,
        token_limit=1_000,
        token_calibration_factor=2.0,
    )
    assert pack.total_tokens <= 500
    assert estimate_prompt_tokens(pack.total_tokens, 2.0) <= 1_000
