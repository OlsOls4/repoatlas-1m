"""Configuration objects for RepoAtlas-1M."""

from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_TOKEN_LIMIT: int = 400_000
MAX_TOKEN_LIMIT: int = 900_000
DEFAULT_REASONING_EFFORT: str = "medium"
DEFAULT_MAX_TOKENS: int = 32_000
DEFAULT_TOKEN_CALIBRATION_FACTOR: float = 1.22
DEFAULT_REFLECTION_BASE_URL: str = "https://api.reflection.ai/openai/v1"
DEFAULT_REFLECTION_MODEL: str = "Beam-1.0-501B-A23B"
DEFAULT_OLLAMA_BASE_URL: str = "https://ollama.com/v1"
DEFAULT_OLLAMA_MODEL: str = "beam"


@dataclass(slots=True)
class RepoAtlasConfig:
    """
    @brief Runtime configuration for RepoAtlas-1M.
    @param provider Inference provider identifier.
    @param base_url Provider API base URL.
    @param model Model identifier to call.
    @param api_key Environment key used for authenticated runs.
    @param token_limit Maximum packed input token limit.
    @param max_tokens Maximum generated token budget.
    @param token_calibration_factor Multiplier used to estimate real prompt tokens.
    @param reasoning_effort Reasoning effort level.
    @param cache_dir Local cache path for packed repositories.
    """

    provider: str
    base_url: str
    model: str
    api_key: str | None
    token_limit: int
    max_tokens: int
    token_calibration_factor: float
    reasoning_effort: str
    cache_dir: str

    @classmethod
    def from_environment(cls, provider: str | None = None, token_limit: int = DEFAULT_TOKEN_LIMIT) -> "RepoAtlasConfig":
        """
        @brief Build a runtime configuration from environment variables.
        @param provider Inference provider identifier, or None to read BEAM_PROVIDER.
        @param token_limit Maximum packed input token limit.
        """

        selected_provider: str = (provider or os.environ.get("BEAM_PROVIDER", "ollama")).strip().lower()
        bounded_limit: int = max(1, min(token_limit, MAX_TOKEN_LIMIT))
        token_calibration_factor: float = float(
            os.environ.get("REPOATLAS_TOKEN_CALIBRATION_FACTOR", str(DEFAULT_TOKEN_CALIBRATION_FACTOR))
        )
        if token_calibration_factor <= 0:
            token_calibration_factor = DEFAULT_TOKEN_CALIBRATION_FACTOR
        cache_dir: str = os.environ.get("REPOATLAS_CACHE_DIR", ".cache/repoatlas")
        if selected_provider == "reflection":
            return cls(
                provider="reflection",
                base_url=os.environ.get("REFLECTION_BASE_URL", DEFAULT_REFLECTION_BASE_URL),
                model=os.environ.get("REFLECTION_MODEL", DEFAULT_REFLECTION_MODEL),
                api_key=os.environ.get("REFLECTION_API_KEY"),
                token_limit=bounded_limit,
                max_tokens=int(
                    os.environ.get("REPOATLAS_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
                ),
                token_calibration_factor=token_calibration_factor,
                reasoning_effort=os.environ.get("REPOATLAS_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
                cache_dir=cache_dir,
            )
        if selected_provider == "ollama":
            return cls(
                provider="ollama",
                base_url=os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
                model=os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
                api_key=os.environ.get("OLLAMA_API_KEY"),
                token_limit=bounded_limit,
                max_tokens=int(
                    os.environ.get("REPOATLAS_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
                ),
                token_calibration_factor=token_calibration_factor,
                reasoning_effort=os.environ.get("REPOATLAS_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
                cache_dir=cache_dir,
            )
        return cls(
            provider="fixture",
            base_url="fixture://local",
            model="fixture-beam",
            api_key=None,
            token_limit=bounded_limit,
            max_tokens=DEFAULT_MAX_TOKENS,
            token_calibration_factor=token_calibration_factor,
            reasoning_effort=DEFAULT_REASONING_EFFORT,
            cache_dir=cache_dir,
        )
