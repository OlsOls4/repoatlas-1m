"""Beam client abstractions for fixture and live analysis runs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
from pathlib import Path
import time
from typing import Iterator, Protocol

from pydantic import BaseModel
import requests

from repoatlas.config import RepoAtlasConfig
from repoatlas.models import AnalysisOutput, AtlasClaim, DocDriftFinding, RepoPack
from repoatlas.prompts import SYSTEM_PROMPT, build_analysis_user_prompt


REQUEST_TIMEOUT_SECONDS: int = 600
MAX_RETRY_ATTEMPTS: int = 5
INITIAL_BACKOFF_SECONDS: float = 1.0


class _StructuredModelResponse(BaseModel):
    """
    @brief Internal schema expected from the model for one analysis response.
    @param findings DocDrift findings.
    @param atlas_claims Onboarding atlas claims.
    """

    findings: list[DocDriftFinding]
    atlas_claims: list[AtlasClaim]


@dataclass(slots=True)
class AnalysisCallMetrics:
    """
    @brief Usage and latency details for one analysis call.
    @param latency_seconds End-to-end request latency.
    @param input_tokens Input token count.
    @param output_tokens Output token count.
    @param cached_input_tokens Cached input token count.
    @param rate_limit_headers Captured rate-limit headers.
    """

    latency_seconds: float
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    rate_limit_headers: dict[str, str]


class AnalysisClient(Protocol):
    """
    @brief Protocol for analysers that produce structured RepoAtlas output.
    """

    def analyse(self, pack: RepoPack, repo_url: str, ref: str) -> tuple[AnalysisOutput, AnalysisCallMetrics]:
        """
        @brief Analyse a packed repository and return output with metrics.
        @param pack Deterministically packed repository payload.
        @param repo_url Original repository URL.
        @param ref Analysed branch, tag, or commit.
        """


class FixtureAnalysisClient:
    """
    @brief Analysis client that serves deterministic local fixture responses.
    """

    def __init__(self, fixture_path: Path) -> None:
        """
        @brief Initialise the fixture analysis client.
        @param fixture_path Path to a fixture JSON file.
        """

        self._fixture_path = fixture_path

    def analyse(self, pack: RepoPack, repo_url: str, ref: str) -> tuple[AnalysisOutput, AnalysisCallMetrics]:
        """
        @brief Return fixture analysis output labelled as fixture data.
        @param pack Deterministically packed repository payload.
        @param repo_url Original repository URL.
        @param ref Analysed branch, tag, or commit.
        """

        raw_fixture: str = self._fixture_path.read_text(encoding="utf-8")
        parsed = _StructuredModelResponse.model_validate_json(raw_fixture)
        output = AnalysisOutput(
            repo_url=repo_url,
            ref=ref,
            findings=parsed.findings,
            atlas_claims=parsed.atlas_claims,
            model="fixture-beam",
            provider="fixture",
            fixture_run=True,
            raw_response=raw_fixture,
        )
        metrics = AnalysisCallMetrics(
            latency_seconds=0.12,
            input_tokens=pack.total_tokens,
            output_tokens=max(1, len(raw_fixture.split())),
            cached_input_tokens=pack.total_tokens,
            rate_limit_headers={},
        )
        return output, metrics


class OpenAICompatibleAnalysisClient:
    """
    @brief Analysis client for OpenAI-compatible chat completion endpoints.
    """

    def __init__(self, config: RepoAtlasConfig) -> None:
        """
        @brief Initialise the live analysis client.
        @param config Runtime configuration.
        """

        if not config.api_key:
            raise ValueError(f"Missing API key for provider '{config.provider}'.")
        self._config = config
        self._response_cache_dir: Path = Path(config.cache_dir) / "responses"
        self._response_cache_dir.mkdir(parents=True, exist_ok=True)
        self._concurrency_lock_path: Path = Path(config.cache_dir) / f"{config.provider}.lock"

    def analyse(self, pack: RepoPack, repo_url: str, ref: str) -> tuple[AnalysisOutput, AnalysisCallMetrics]:
        """
        @brief Perform one structured analysis call against a live provider.
        @param pack Deterministically packed repository payload.
        @param repo_url Original repository URL.
        @param ref Analysed branch, tag, or commit.
        """

        schema: dict[str, object] = _StructuredModelResponse.model_json_schema()
        payload: dict[str, object] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_analysis_user_prompt(pack)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "repoatlas_analysis",
                    "schema": schema,
                    "strict": True,
                },
            },
            "max_tokens": self._config.max_tokens,
            "reasoning_effort": self._config.reasoning_effort,
        }
        cache_key: str = _cache_key(self._config.base_url, self._config.model, payload)
        cached_response: dict[str, object] | None = self._read_cached_response(cache_key)
        if cached_response is not None:
            response_payload = cached_response["response_payload"]
            headers_payload = cached_response.get("response_headers", {})
            return self._build_output_and_metrics(
                response_payload=response_payload,
                response_headers=headers_payload if isinstance(headers_payload, dict) else {},
                repo_url=repo_url,
                ref=ref,
                latency_seconds=0.0,
            )

        with _exclusive_lock(self._concurrency_lock_path):
            start: float = time.perf_counter()
            response_payload, response_headers = self._post_with_retries(payload)
            latency: float = time.perf_counter() - start
            self._write_cached_response(cache_key, response_payload=response_payload, response_headers=response_headers)
        return self._build_output_and_metrics(
            response_payload=response_payload,
            response_headers=response_headers,
            repo_url=repo_url,
            ref=ref,
            latency_seconds=latency,
        )

    def _post_with_retries(self, payload: dict[str, object]) -> tuple[dict[str, object], dict[str, str]]:
        """
        @brief Send a completion request with retry and backoff for transient failures.
        @param payload Request JSON payload.
        """

        url: str = f"{self._config.base_url.rstrip('/')}/chat/completions"
        backoff_seconds: float = INITIAL_BACKOFF_SECONDS
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            try:
                response = requests.post(
                    url,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except requests.RequestException as exc:
                if attempt == MAX_RETRY_ATTEMPTS:
                    raise RuntimeError(f"Live request failed after {MAX_RETRY_ATTEMPTS} attempts: {exc}") from exc
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue

            status_code: int = response.status_code
            if status_code == 429 or status_code >= 500:
                if attempt == MAX_RETRY_ATTEMPTS:
                    response.raise_for_status()
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue

            response.raise_for_status()
            payload_json: dict[str, object] = response.json()
            headers_map: dict[str, str] = dict(response.headers)
            return payload_json, headers_map

        raise RuntimeError("Unexpected retry loop exit.")

    def _build_output_and_metrics(
        self,
        response_payload: dict[str, object],
        response_headers: dict[str, str],
        repo_url: str,
        ref: str,
        latency_seconds: float,
    ) -> tuple[AnalysisOutput, AnalysisCallMetrics]:
        """
        @brief Convert raw response payload and headers into typed output and metrics.
        @param response_payload Raw API response payload.
        @param response_headers Raw API response headers.
        @param repo_url Original repository URL.
        @param ref Analysed branch, tag, or commit.
        @param latency_seconds Request latency in seconds.
        """

        content: str = _extract_message_content(response_payload)
        reasoning_fallback: str = _extract_reasoning_text(response_payload)
        if not content.strip():
            raise ValueError(f"Model returned no message.content; reasoning fallback: {reasoning_fallback[:400]}")
        parsed = _StructuredModelResponse.model_validate_json(content)
        usage = _extract_usage(response_payload)
        metrics = AnalysisCallMetrics(
            latency_seconds=latency_seconds,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cached_input_tokens=usage["cached_input_tokens"],
            rate_limit_headers=_extract_rate_limit_headers(response_headers),
        )
        enriched_payload: dict[str, object] = dict(response_payload)
        if reasoning_fallback:
            enriched_payload["repoatlas_reasoning_fallback"] = reasoning_fallback
        output = AnalysisOutput(
            repo_url=repo_url,
            ref=ref,
            findings=parsed.findings,
            atlas_claims=parsed.atlas_claims,
            model=self._config.model,
            provider=self._config.provider,
            fixture_run=False,
            raw_response=json.dumps(enriched_payload, indent=2),
        )
        return output, metrics

    def _read_cached_response(self, cache_key: str) -> dict[str, object] | None:
        """
        @brief Read a cached response payload when available.
        @param cache_key Stable request cache key.
        """

        cache_path: Path = self._response_cache_dir / f"{cache_key}.json"
        if not cache_path.exists():
            return None
        return json.loads(cache_path.read_text(encoding="utf-8"))

    def _write_cached_response(
        self,
        cache_key: str,
        response_payload: dict[str, object],
        response_headers: dict[str, str],
    ) -> None:
        """
        @brief Persist response payload and headers for prompt-level cache reuse.
        @param cache_key Stable request cache key.
        @param response_payload Raw API response payload.
        @param response_headers Raw API response headers.
        """

        cache_path: Path = self._response_cache_dir / f"{cache_key}.json"
        cache_path.write_text(
            json.dumps(
                {
                    "response_payload": response_payload,
                    "response_headers": response_headers,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def make_analysis_client(config: RepoAtlasConfig, fixture_path: Path) -> AnalysisClient:
    """
    @brief Create an analysis client according to configured provider.
    @param config Runtime configuration.
    @param fixture_path Fixture file path used in fixture mode.
    """

    if config.provider == "fixture":
        return FixtureAnalysisClient(fixture_path=fixture_path)
    return OpenAICompatibleAnalysisClient(config=config)


def _extract_message_content(response_payload: dict[str, object]) -> str:
    """
    @brief Extract string message content from an OpenAI-compatible payload.
    @param response_payload Raw JSON response body.
    """

    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Missing choices in response payload.")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ValueError("Invalid choice structure in response payload.")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("Missing message object in response payload.")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_fragments: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text_fragments.append(item["text"])
        if text_fragments:
            return "".join(text_fragments)
    return ""


def _extract_reasoning_text(response_payload: dict[str, object]) -> str:
    """
    @brief Extract reasoning text when providers separate it from message.content.
    @param response_payload Raw JSON response body.
    """

    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message")
    if isinstance(message, dict):
        reasoning_field = message.get("reasoning")
        if isinstance(reasoning_field, str):
            return reasoning_field
    reasoning = first_choice.get("reasoning")
    if isinstance(reasoning, str):
        return reasoning
    return ""


def _extract_usage(response_payload: dict[str, object]) -> dict[str, int]:
    """
    @brief Extract token usage counters from a provider response payload.
    @param response_payload Raw JSON response body.
    """

    usage = response_payload.get("usage")
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
    prompt_tokens: int = int(usage.get("prompt_tokens", 0))
    completion_tokens: int = int(usage.get("completion_tokens", 0))
    prompt_details = usage.get("prompt_tokens_details")
    cached_tokens: int = 0
    if isinstance(prompt_details, dict):
        cached_tokens = int(prompt_details.get("cached_tokens", 0))
    return {
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "cached_input_tokens": cached_tokens,
    }


def _extract_rate_limit_headers(headers: dict[str, str]) -> dict[str, str]:
    """
    @brief Collect x-ratelimit headers from a provider response.
    @param headers HTTP response headers.
    """

    extracted: dict[str, str] = {}
    for key, value in headers.items():
        lowered: str = key.lower()
        if lowered.startswith("x-ratelimit-"):
            extracted[lowered] = value
    return extracted


def _cache_key(base_url: str, model: str, payload: dict[str, object]) -> str:
    """
    @brief Derive a stable cache key for a live prompt payload.
    @param base_url Provider base URL.
    @param model Model identifier.
    @param payload Request payload.
    """

    stable_blob: str = json.dumps(
        {
            "base_url": base_url.rstrip("/"),
            "model": model,
            "payload": payload,
        },
        sort_keys=True,
    )
    return hashlib.sha256(stable_blob.encode("utf-8")).hexdigest()


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    """
    @brief Acquire an exclusive file lock to enforce one concurrent live request.
    @param lock_path Lock file path.
    """

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
