"""Repository packing utilities for long-context Beam calls."""

from __future__ import annotations

import ast
from collections import defaultdict
from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import tempfile
from typing import Iterable
from urllib.parse import urlparse

import requests
import tiktoken

from repoatlas.config import DEFAULT_TOKEN_CALIBRATION_FACTOR, DEFAULT_TOKEN_LIMIT, MAX_TOKEN_LIMIT
from repoatlas.models import RepoFileSnapshot, RepoPack


PACK_FORMAT_VERSION: str = "1"
FILTER_SIGNATURE: str = "v4"
SOURCE_SUFFIXES: tuple[str, ...] = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
DOC_SUFFIXES: tuple[str, ...] = (".md", ".rst", ".txt", ".adoc")
IMPORT_RELATIVE_PATTERN: re.Pattern[str] = re.compile(
    r"""(?:import|export)\s+(?:[^;]*?\s+from\s+)?["'](?P<module>[^"']+)["']"""
)
DOC_PATH_REFERENCE_PATTERN: re.Pattern[str] = re.compile(r"([A-Za-z0-9_.\-/]+\.(?:py|ts|tsx|js|jsx))")
DOC_DOTTED_MODULE_PATTERN: re.Pattern[str] = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b")
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
    "uv.lock",
    "pdm.lock",
    "bun.lockb",
    "Package.resolved",
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
# - _effective_token_budget(token_limit: int, token_calibration_factor: float) -> int
# - _priority_order(repo_root: Path, paths: Iterable[Path], repo_url: str = "") -> list[Path]


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
    token_calibration_factor: float = DEFAULT_TOKEN_CALIBRATION_FACTOR,
    cache_dir: str = ".cache/repoatlas",
) -> RepoPack:
    """
    @brief Build or reuse a deterministic repository pack from a remote GitHub repository.
    @param repo_url Public GitHub repository URL.
    @param ref Branch, tag, or commit to fetch.
    @param token_limit Maximum packed token budget.
    @param token_calibration_factor Calibration factor from estimated to real prompt tokens.
    @param cache_dir Local cache directory path.
    """

    bounded_limit: int = max(1, min(token_limit, MAX_TOKEN_LIMIT))
    normalised_url: str = _normalise_repo_url(repo_url)
    cache_key: str = _cache_key(normalised_url, ref, bounded_limit, token_calibration_factor)
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
        token_calibration_factor=token_calibration_factor,
    )
    _write_cached_pack(cache_path, cache_key, pack)
    return pack


def build_pack_from_directory(
    repo_url: str,
    ref: str,
    repo_root: Path,
    token_limit: int = DEFAULT_TOKEN_LIMIT,
    token_calibration_factor: float = DEFAULT_TOKEN_CALIBRATION_FACTOR,
) -> RepoPack:
    """
    @brief Build a deterministic packed representation from a local repository directory.
    @param repo_url Repository URL metadata.
    @param ref Branch, tag, or commit metadata.
    @param repo_root Path to the extracted repository root.
    @param token_limit Maximum packed token budget.
    @param token_calibration_factor Calibration factor from estimated to real prompt tokens.
    """

    bounded_limit: int = max(1, min(token_limit, MAX_TOKEN_LIMIT))
    effective_budget: int = _effective_token_budget(bounded_limit, token_calibration_factor)
    sorted_paths: list[Path] = _priority_order(repo_root, _iter_text_files(repo_root), repo_url=repo_url)
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

        if running_tokens + file_block_tokens <= effective_budget:
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

        truncated = True
        if effective_budget - running_tokens < 64:
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


def estimate_prompt_tokens(estimated_pack_tokens: int, token_calibration_factor: float) -> int:
    """
    @brief Estimate real prompt tokens from packer-estimated tokens.
    @param estimated_pack_tokens Estimated token count from the packer.
    @param token_calibration_factor Calibration factor from estimated to real prompt tokens.
    """

    safe_factor: float = token_calibration_factor if token_calibration_factor > 0 else DEFAULT_TOKEN_CALIBRATION_FACTOR
    return int(round(estimated_pack_tokens * safe_factor))


def _normalise_repo_url(repo_url: str) -> str:
    """
    @brief Canonicalise repository URLs for stable cache keys.
    @param repo_url Original repository URL.
    """

    stripped_url: str = repo_url.strip()
    if stripped_url.endswith(".git"):
        stripped_url = stripped_url.removesuffix(".git")
    return stripped_url.rstrip("/")


def _cache_key(repo_url: str, ref: str, token_limit: int, token_calibration_factor: float) -> str:
    """
    @brief Build a stable cache key for one packing configuration.
    @param repo_url Canonical repository URL.
    @param ref Branch, tag, or commit reference.
    @param token_limit Maximum packed token budget.
    @param token_calibration_factor Calibration factor from estimated to real prompt tokens.
    """

    payload: str = json.dumps(
        {
            "repo_url": repo_url,
            "ref": ref,
            "token_limit": token_limit,
            "token_calibration_factor": token_calibration_factor,
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


DOC_DIRECTORY_NAMES: set[str] = {"docs", "doc", "documentation"}
LOW_PRIORITY_DIRECTORY_NAMES: set[str] = {
    "tests", "test", "testing", "examples", "example", "benchmarks", "bench",
    ".github", ".devcontainer", ".circleci", ".gitlab", "ci", "scripts", "docs_src",
}
LOW_PRIORITY_ROOT_NAMES: set[str] = {"CHANGES.rst", "CHANGES.md", "CHANGELOG.md", "CHANGELOG.rst", "HISTORY.md", "HISTORY.rst", "NEWS.md"}
ROOT_CONFIG_NAMES: set[str] = {
    "pyproject.toml", "setup.cfg", "setup.py", "package.json", "Cargo.toml", "go.mod", "mkdocs.yml",
    "mkdocs.yaml", "tox.ini", "hatch.toml", "tsconfig.json",
}
ROOT_DOC_NAMES: set[str] = {"README.md", "README.rst", "CONTRIBUTING.md", "CONTRIBUTING.rst"}


def _effective_token_budget(token_limit: int, token_calibration_factor: float) -> int:
    """
    @brief Convert a real-token budget into an estimated-token budget using calibration.
    @param token_limit Requested real prompt token budget.
    @param token_calibration_factor Calibration factor from estimated to real prompt tokens.
    """

    safe_factor: float = token_calibration_factor if token_calibration_factor > 0 else DEFAULT_TOKEN_CALIBRATION_FACTOR
    estimated_budget: int = int(token_limit / safe_factor)
    bounded_budget: int = max(1, min(token_limit, estimated_budget))
    return bounded_budget


def _priority_order(repo_root: Path, paths: Iterable[Path], repo_url: str = "") -> list[Path]:
    """
    @brief Deterministically rank files by package centrality and documentation relevance.
    @param repo_root Repository root path.
    @param paths Candidate file paths.
    """

    candidate_paths: list[Path] = list(paths)
    rel_by_path: dict[Path, str] = {
        path: str(path.relative_to(repo_root)).replace("\\", "/")
        for path in candidate_paths
    }
    path_by_rel: dict[str, Path] = {rel_path: path for path, rel_path in rel_by_path.items()}
    doc_reference_targets: set[str] = _collect_doc_reference_targets(candidate_paths, rel_by_path, path_by_rel)
    import_in_degree, init_import_targets = _build_import_graph_in_degree(candidate_paths, rel_by_path, path_by_rel)

    repo_name: str = repo_url.rstrip("/").split("/")[-1].removesuffix(".git").lower().replace("-", "_")
    primary_code_dirs: set[str] = {"src", "lib", repo_name}
    ranked_entries: list[tuple[int, int, int, int, int, str, bool, bool, Path]] = []

    for path in candidate_paths:
        rel_path: str = rel_by_path[path]
        parts: list[str] = rel_path.split("/")
        top_dir: str = parts[0].lower()
        suffix: str = path.suffix.lower()
        is_root: bool = len(parts) == 1
        is_low_priority: bool = (
            (is_root and parts[0] in LOW_PRIORITY_ROOT_NAMES) or
            any(part in LOW_PRIORITY_DIRECTORY_NAMES for part in parts[:-1])
        )
        is_doc: bool = top_dir in DOC_DIRECTORY_NAMES or suffix in DOC_SUFFIXES or parts[-1] in ROOT_DOC_NAMES
        is_source: bool = suffix in SOURCE_SUFFIXES
        is_init: bool = rel_path == "__init__.py" or rel_path.endswith("/__init__.py")
        is_imported_by_init: bool = rel_path in init_import_targets
        is_doc_referenced: bool = rel_path in doc_reference_targets
        indegree: int = import_in_degree.get(rel_path, 0)
        size_bytes: int = path.stat().st_size

        if is_low_priority:
            priority_band: int = 9
        elif is_init:
            priority_band = 0
        elif is_imported_by_init:
            priority_band = 1
        elif is_doc_referenced:
            priority_band = 2
        elif indegree > 0:
            priority_band = 3
        elif is_source:
            priority_band = 4
        elif is_doc:
            priority_band = 5
        elif is_root:
            priority_band = 6
        else:
            priority_band = 7

        primary_dir_penalty: int = 0 if top_dir in primary_code_dirs else 1
        translation_penalty: int = 1 if is_doc and _is_translation_path(rel_path) else 0
        ranked_entries.append(
            (
                priority_band,
                primary_dir_penalty,
                translation_penalty,
                -indegree,
                -size_bytes,
                rel_path,
                is_source,
                is_doc,
                path,
            )
        )

    ranked_entries.sort(key=lambda item: item[:6])
    # Root config (pyproject.toml, setup.cfg, package.json, mkdocs.yml, ...) defines entry points and defaults,
    # so it ranks with core modules; low-priority files (tests, CI, examples) always go last.
    root_config_paths: list[Path] = [
        entry[-1] for entry in ranked_entries
        if entry[0] == 6 and entry[5] in ROOT_CONFIG_NAMES
    ]
    root_config_set: set[Path] = set(root_config_paths)
    core_paths: list[Path] = root_config_paths + [entry[-1] for entry in ranked_entries if entry[0] <= 3]
    normal_entries = [entry for entry in ranked_entries if 4 <= entry[0] < 9 and entry[-1] not in root_config_set]
    source_paths: list[Path] = [entry[-1] for entry in normal_entries if entry[6] and not entry[7]]
    doc_paths: list[Path] = [entry[-1] for entry in normal_entries if entry[7]]
    other_paths: list[Path] = [entry[-1] for entry in normal_entries if not entry[6] and not entry[7]]
    low_priority_paths: list[Path] = [entry[-1] for entry in ranked_entries if entry[0] == 9]
    interleaved_non_core_paths: list[Path] = []
    for index in range(max(len(source_paths), len(doc_paths))):
        if index < len(source_paths):
            interleaved_non_core_paths.append(source_paths[index])
        if index < len(doc_paths):
            interleaved_non_core_paths.append(doc_paths[index])
    return core_paths + interleaved_non_core_paths + other_paths + low_priority_paths


def _collect_doc_reference_targets(
    candidate_paths: list[Path],
    rel_by_path: dict[Path, str],
    path_by_rel: dict[str, Path],
) -> set[str]:
    """
    @brief Find source files named in documentation prose.
    @param candidate_paths Candidate file paths.
    @param rel_by_path Repository-relative path map.
    @param path_by_rel Reverse path map keyed by relative path.
    """

    doc_text_blobs: list[str] = []
    for path in candidate_paths:
        rel_path: str = rel_by_path[path]
        parts: list[str] = rel_path.split("/")
        suffix: str = path.suffix.lower()
        is_doc: bool = parts[0].lower() in DOC_DIRECTORY_NAMES or suffix in DOC_SUFFIXES or parts[-1] in ROOT_DOC_NAMES
        if not is_doc:
            continue
        try:
            doc_text_blobs.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
    if not doc_text_blobs:
        return set()
    doc_text: str = "\n".join(doc_text_blobs)

    targets: set[str] = set()
    path_basename_mentions: set[str] = set()
    for match in DOC_PATH_REFERENCE_PATTERN.finditer(doc_text):
        raw_value: str = match.group(1).strip("`'\"")
        normalised: str = raw_value.lstrip("./").replace("\\", "/")
        if not normalised:
            continue
        if "/" in normalised:
            if normalised in path_by_rel:
                targets.add(normalised)
            continue
        path_basename_mentions.add(normalised)

    for dotted_match in DOC_DOTTED_MODULE_PATTERN.finditer(doc_text):
        module_value: str = dotted_match.group(1)
        module_parts: list[str] = module_value.split(".")
        for candidate in _module_to_candidate_paths(module_parts):
            if candidate in path_by_rel:
                targets.add(candidate)

    for rel_path in path_by_rel:
        basename: str = rel_path.split("/")[-1]
        if basename in path_basename_mentions:
            targets.add(rel_path)
    return targets


def _build_import_graph_in_degree(
    candidate_paths: list[Path],
    rel_by_path: dict[Path, str],
    path_by_rel: dict[str, Path],
) -> tuple[dict[str, int], set[str]]:
    """
    @brief Build in-degree centrality from repository-local import statements.
    @param candidate_paths Candidate file paths.
    @param rel_by_path Repository-relative path map.
    @param path_by_rel Reverse path map keyed by relative path.
    """

    in_degree: dict[str, int] = defaultdict(int)
    init_import_targets: set[str] = set()
    for path in candidate_paths:
        rel_path: str = rel_by_path[path]
        suffix: str = path.suffix.lower()
        if suffix not in SOURCE_SUFFIXES:
            continue
        try:
            source_text: str = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        imported_targets: set[str]
        if suffix == ".py":
            imported_targets = _python_import_targets(rel_path, source_text, path_by_rel)
        else:
            imported_targets = _typescript_import_targets(rel_path, source_text, path_by_rel)
        for target in imported_targets:
            in_degree[target] += 1
        if rel_path == "__init__.py" or rel_path.endswith("/__init__.py"):
            init_import_targets.update(imported_targets)
    return dict(in_degree), init_import_targets


def _python_import_targets(rel_path: str, source_text: str, path_by_rel: dict[str, Path]) -> set[str]:
    """
    @brief Resolve repository-local Python import statements to file paths.
    @param rel_path Importing file path.
    @param source_text Python source text.
    @param path_by_rel Reverse path map keyed by relative path.
    """

    module_parts: list[str] = _module_parts_for_python_path(rel_path)
    targets: set[str] = set()
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return targets
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_parts: list[str] = alias.name.split(".")
                for candidate in _module_to_candidate_paths(imported_parts):
                    if candidate in path_by_rel:
                        targets.add(candidate)
        elif isinstance(node, ast.ImportFrom):
            prefix_parts: list[str] = []
            if node.level > 0:
                prefix_parts = module_parts[:-node.level]
            module_name_parts: list[str] = node.module.split(".") if node.module else []
            import_base_parts: list[str] = prefix_parts + module_name_parts
            for candidate in _module_to_candidate_paths(import_base_parts):
                if candidate in path_by_rel:
                    targets.add(candidate)
            for alias in node.names:
                if alias.name == "*":
                    continue
                alias_parts: list[str] = import_base_parts + alias.name.split(".")
                for candidate in _module_to_candidate_paths(alias_parts):
                    if candidate in path_by_rel:
                        targets.add(candidate)
    return targets


def _typescript_import_targets(rel_path: str, source_text: str, path_by_rel: dict[str, Path]) -> set[str]:
    """
    @brief Resolve repository-local TypeScript/JavaScript import statements to file paths.
    @param rel_path Importing file path.
    @param source_text JavaScript or TypeScript source text.
    @param path_by_rel Reverse path map keyed by relative path.
    """

    import_dir: str = str(Path(rel_path).parent).replace("\\", "/")
    if import_dir == ".":
        import_dir = ""
    targets: set[str] = set()
    for match in IMPORT_RELATIVE_PATTERN.finditer(source_text):
        module_value: str = match.group("module")
        if not module_value.startswith("."):
            continue
        base_parts: list[str] = [part for part in import_dir.split("/") if part]
        relative_parts: list[str] = [part for part in module_value.split("/") if part and part != "."]
        while relative_parts and relative_parts[0] == "..":
            relative_parts = relative_parts[1:]
            if base_parts:
                base_parts = base_parts[:-1]
        candidate_base: str = "/".join(base_parts + relative_parts)
        for suffix in SOURCE_SUFFIXES:
            with_suffix: str = f"{candidate_base}{suffix}" if not candidate_base.endswith(suffix) else candidate_base
            if with_suffix in path_by_rel:
                targets.add(with_suffix)
        index_candidate: str = f"{candidate_base}/index.ts"
        if index_candidate in path_by_rel:
            targets.add(index_candidate)
    return targets


def _module_parts_for_python_path(rel_path: str) -> list[str]:
    """
    @brief Convert a Python file path into its module-path parts.
    @param rel_path Repository-relative Python file path.
    """

    if rel_path.endswith("/__init__.py"):
        without_suffix: str = rel_path[:-12]
    elif rel_path == "__init__.py":
        return []
    elif rel_path.endswith(".py"):
        without_suffix = rel_path[:-3]
    else:
        without_suffix = rel_path
    return [part for part in without_suffix.split("/") if part]


def _module_to_candidate_paths(module_parts: list[str]) -> list[str]:
    """
    @brief Convert module path parts into potential repository file paths.
    @param module_parts Module path parts.
    """

    if not module_parts:
        return []
    joined: str = "/".join(module_parts)
    return [f"{joined}.py", f"{joined}/__init__.py"]


def _is_translation_path(rel_path: str) -> bool:
    """
    @brief Detect localised documentation trees such as docs/de/ or docs/pt-BR/.
    @param rel_path Repository-relative path.
    """

    for part in rel_path.split("/")[:-1]:
        lowered: str = part.lower()
        if lowered in {"en", "en-us", "en_us"}:
            return False
        if (len(lowered) == 2 and lowered.isalpha()) or (
            len(lowered) == 5 and lowered[2] in "-_" and lowered[:2].isalpha() and lowered[3:].isalpha()
        ):
            return True
    return False
