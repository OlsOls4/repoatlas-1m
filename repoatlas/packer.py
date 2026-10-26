"""Repository packing utilities for long-context Beam calls."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
from typing import Iterable
from urllib.parse import urlparse

import requests
import tiktoken

from repoatlas.config import DEFAULT_TOKEN_LIMIT, MAX_TOKEN_LIMIT
from repoatlas.models import RepoFileSnapshot, RepoPack


PACK_FORMAT_VERSION: str = "1"
FILTER_SIGNATURE: str = "v1"
SKIP_DIRECTORY_NAMES: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    "third_party",
    "third-party",
    "dist",
    "build",
    "__pycache__",
}
SKIP_FILE_NAMES: set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "composer.lock",
    "Gemfile.lock",
    "go.sum",
}
SKIP_FILE_SUFFIXES: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".7z",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".class",
    ".jar",
    ".mp3",
    ".mp4",
    ".mov",
)


# Private function prototypes:
# - _normalise_repo_url(repo_url: str) -> str
# - _cache_key(repo_url: str, ref: str, token_limit: int) -> str
# - _read_cached_pack(cache_dir: Path, key: str) -> RepoPack | None
# - _write_cached_pack(cache_dir: Path, key: str, pack: RepoPack) -> None
# - _iter_text_files(repo_root: Path) -> Iterable[Path]
# - _is_binary_bytes(raw_bytes: bytes) -> bool
# - _normalise_newlines(text: str) -> str
# - _make_file_block(path: str, lines: list[str]) -> str
# - _encode_tokens(text: str) -> int
# - _truncate_file_lines_to_limit(path: str, lines: list[str], remaining_tokens: int) -> tuple[list[str], int]


def parse_github_repo(repo_url: str) -> tuple[str, str]:
    """
    @brief Parse a public GitHub URL into owner and repository name.
    @param repo_url Public GitHub repository URL.
    """

    parsed = urlparse(repo_url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError(f"Unsupported host for repository URL: {parsed.netloc}")
    path_parts: list[str] = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2:
        raise ValueError("Repository URL must include owner and repository name.")
    owner: str = path_parts[0]
    repo_name: str = path_parts[1].removesuffix(".git")
    return owner, repo_name


def fetch_github_tarball(repo_url: str, ref: str = "main") -> Path:
    """
    @brief Download and extract a public GitHub tarball into a temporary folder.
    @param repo_url Public GitHub repository URL.
    @param ref Branch, tag, or commit to fetch.
    """

    owner, repo_name = parse_github_repo(repo_url)
    tarball_url: str = f"https://api.github.com/repos/{owner}/{repo_name}/tarball/{ref}"
    response = requests.get(
        tarball_url,
        timeout=120,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "RepoAtlas-1M"},
    )
    response.raise_for_status()
    temp_dir = Path(tempfile.mkdtemp(prefix="repoatlas-tarball-"))
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
        archive.extractall(path=temp_dir)
    extracted_children: list[Path] = [child for child in temp_dir.iterdir() if child.is_dir()]
    if not extracted_children:
        raise RuntimeError("Failed to extract repository tarball.")
    return extracted_children[0]


def pack_repository(
    repo_url: str,
    ref: str = "main",
    token_limit: int = DEFAULT_TOKEN_LIMIT,
    cache_dir: str = ".cache/repoatlas",
) -> RepoPack:
    """
    @brief Build or reuse a deterministic repository pack from a remote GitHub repository.
    @param repo_url Public GitHub repository URL.
    @param ref Branch, tag, or commit to fetch.
    @param token_limit Maximum packed token budget.
    @param cache_dir Local cache directory path.
    """

    bounded_limit: int = max(1, min(token_limit, MAX_TOKEN_LIMIT))
    normalised_url: str = _normalise_repo_url(repo_url)
    cache_key: str = _cache_key(normalised_url, ref, bounded_limit)
    cache_path = Path(cache_dir)
    cached_pack: RepoPack | None = _read_cached_pack(cache_path, cache_key)
    if cached_pack is not None:
        return cached_pack
    repo_root: Path = fetch_github_tarball(normalised_url, ref=ref)
    pack: RepoPack = build_pack_from_directory(
        repo_url=normalised_url,
        ref=ref,
        repo_root=repo_root,
        token_limit=bounded_limit,
    )
    _write_cached_pack(cache_path, cache_key, pack)
    return pack


def build_pack_from_directory(repo_url: str, ref: str, repo_root: Path, token_limit: int = DEFAULT_TOKEN_LIMIT) -> RepoPack:
    """
    @brief Build a deterministic packed representation from a local repository directory.
    @param repo_url Repository URL metadata.
    @param ref Branch, tag, or commit metadata.
    @param repo_root Path to the extracted repository root.
    @param token_limit Maximum packed token budget.
    """

    bounded_limit: int = max(1, min(token_limit, MAX_TOKEN_LIMIT))
    sorted_paths: list[Path] = sorted(_iter_text_files(repo_root), key=lambda item: str(item.relative_to(repo_root)))
    file_snapshots: list[RepoFileSnapshot] = []
    skipped_paths: list[str] = []

    header_prefix: str = (
        f"# REPOATLAS PACK FORMAT {PACK_FORMAT_VERSION}\n"
        f"REPO_URL: {_normalise_repo_url(repo_url)}\n"
        f"REF: {ref}\n"
        f"FILTER_SIGNATURE: {FILTER_SIGNATURE}\n"
        "LINE_FORMAT: <line>|<text>\n"
        "FILES_BEGIN\n"
    )
    header_suffix: str = "FILES_END\n"
    running_text: str = header_prefix
    running_tokens: int = _encode_tokens(running_text + header_suffix)
    truncated: bool = False

    for file_path in sorted_paths:
        relative_path: str = str(file_path.relative_to(repo_root)).replace("\\", "/")
        raw_bytes: bytes = file_path.read_bytes()
        if _is_binary_bytes(raw_bytes):
            skipped_paths.append(relative_path)
            continue
        try:
            decoded_text: str = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            skipped_paths.append(relative_path)
            continue
        normalised_text: str = _normalise_newlines(decoded_text)
        lines: list[str] = normalised_text.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        file_block: str = _make_file_block(relative_path, lines)
        file_block_tokens: int = _encode_tokens(file_block)

        if running_tokens + file_block_tokens <= bounded_limit:
            running_text += file_block
            running_tokens += file_block_tokens
            file_snapshots.append(
                RepoFileSnapshot(
                    path=relative_path,
                    lines=lines,
                    token_count=file_block_tokens,
                )
            )
            continue

        remaining_tokens: int = bounded_limit - running_tokens - _encode_tokens(header_suffix)
        if remaining_tokens > 0:
            truncated_lines, line_token_count = _truncate_file_lines_to_limit(relative_path, lines, remaining_tokens)
            if truncated_lines:
                truncated_block: str = _make_file_block(relative_path, truncated_lines)
                running_text += truncated_block
                running_tokens += line_token_count
                file_snapshots.append(
                    RepoFileSnapshot(
                        path=relative_path,
                        lines=truncated_lines,
                        token_count=line_token_count,
                    )
                )
        truncated = True
        break

    running_text += header_suffix
    running_tokens = _encode_tokens(running_text)
    prefix_hash: str = hashlib.sha256(running_text.encode("utf-8")).hexdigest()
    return RepoPack(
        repo_url=_normalise_repo_url(repo_url),
        ref=ref,
        prefix_hash=prefix_hash,
        total_tokens=running_tokens,
        token_limit=bounded_limit,
        truncated=truncated,
        packed_at=datetime.now(UTC).isoformat(),
        files=file_snapshots,
        skipped_paths=sorted(set(skipped_paths)),
        pack_text=running_text,
    )


def _normalise_repo_url(repo_url: str) -> str:
    """
    @brief Canonicalise repository URLs for stable cache keys.
    @param repo_url Original repository URL.
    """

    stripped_url: str = repo_url.strip()
    if stripped_url.endswith(".git"):
        stripped_url = stripped_url.removesuffix(".git")
    return stripped_url.rstrip("/")


def _cache_key(repo_url: str, ref: str, token_limit: int) -> str:
    """
    @brief Build a stable cache key for one packing configuration.
    @param repo_url Canonical repository URL.
    @param ref Branch, tag, or commit reference.
    @param token_limit Maximum packed token budget.
    """

    payload: str = json.dumps(
        {
            "repo_url": repo_url,
            "ref": ref,
            "token_limit": token_limit,
            "filter_signature": FILTER_SIGNATURE,
            "pack_format_version": PACK_FORMAT_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_cached_pack(cache_dir: Path, key: str) -> RepoPack | None:
    """
    @brief Read a previously cached pack from disk.
    @param cache_dir Cache directory root.
    @param key Stable cache key.
    """

    cache_file: Path = cache_dir / "packs" / f"{key}.json"
    if not cache_file.exists():
        return None
    return RepoPack.model_validate_json(cache_file.read_text(encoding="utf-8"))


def _write_cached_pack(cache_dir: Path, key: str, pack: RepoPack) -> None:
    """
    @brief Persist a packed repository to disk cache.
    @param cache_dir Cache directory root.
    @param key Stable cache key.
    @param pack Packed repository payload.
    """

    target_dir: Path = cache_dir / "packs"
    target_dir.mkdir(parents=True, exist_ok=True)
    cache_file: Path = target_dir / f"{key}.json"
    cache_file.write_text(pack.model_dump_json(indent=2), encoding="utf-8")


def _iter_text_files(repo_root: Path) -> Iterable[Path]:
    """
    @brief Yield candidate repository files in deterministic order.
    @param repo_root Repository root path.
    """

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts: tuple[str, ...] = path.relative_to(repo_root).parts
        if any(part in SKIP_DIRECTORY_NAMES for part in relative_parts[:-1]):
            continue
        file_name: str = relative_parts[-1]
        if file_name in SKIP_FILE_NAMES:
            continue
        if file_name.endswith(SKIP_FILE_SUFFIXES):
            continue
        yield path


def _is_binary_bytes(raw_bytes: bytes) -> bool:
    """
    @brief Heuristically detect binary files to skip from packing.
    @param raw_bytes Raw file bytes.
    """

    if not raw_bytes:
        return False
    if b"\x00" in raw_bytes:
        return True
    sample: bytes = raw_bytes[:4096]
    non_text_count: int = sum(byte < 9 or (13 < byte < 32) for byte in sample)
    ratio: float = non_text_count / max(1, len(sample))
    return ratio > 0.30


def _normalise_newlines(text: str) -> str:
    """
    @brief Normalise line endings for deterministic packing output.
    @param text Raw text content.
    """

    return text.replace("\r\n", "\n").replace("\r", "\n")


def _make_file_block(path: str, lines: list[str]) -> str:
    """
    @brief Render one file block with stable line numbering.
    @param path Repository-relative file path.
    @param lines File content lines.
    """

    numbered_lines: list[str] = [f"{index + 1}|{line}" for index, line in enumerate(lines)]
    body: str = "\n".join(numbered_lines)
    return f"--- FILE: {path} ---\n{body}\n--- END FILE: {path} ---\n"


def _encode_tokens(text: str) -> int:
    """
    @brief Count tokens with cl100k_base and degrade gracefully if unavailable.
    @param text Input text to count.
    """

    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text.split()))


def _truncate_file_lines_to_limit(path: str, lines: list[str], remaining_tokens: int) -> tuple[list[str], int]:
    """
    @brief Truncate one file block to fit remaining token budget.
    @param path Repository-relative file path.
    @param lines File lines to truncate.
    @param remaining_tokens Remaining token budget.
    """

    if remaining_tokens <= 0:
        return [], 0
    low: int = 0
    high: int = len(lines)
    best_lines: list[str] = []
    best_tokens: int = 0
    while low <= high:
        mid: int = (low + high) // 2
        candidate_lines: list[str] = lines[:mid]
        candidate_block: str = _make_file_block(path, candidate_lines)
        candidate_tokens: int = _encode_tokens(candidate_block)
        if candidate_tokens <= remaining_tokens:
            best_lines = candidate_lines
            best_tokens = candidate_tokens
            low = mid + 1
        else:
            high = mid - 1
    return best_lines, best_tokens
