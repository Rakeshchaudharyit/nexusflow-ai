"""Embedding providers.

`deterministic_local` is the default: offline, reproducible and dependency-free, so tests, CI
and the local demo need no API keys. It is a feature-hashing model, not a neural one: it
captures shared vocabulary and word forms (stems, character n-grams, word pairs), not meaning.
Production deployments should use a real embedding model (e.g. the `openai` provider below,
or a local sentence-transformer) with the same 384 dimensions.
"""

import hashlib
import logging
import math
from collections.abc import Sequence
from typing import Protocol

import httpx

from app.agents.errors import AgentRuntimeError
from app.core.config import Settings
from app.knowledge.text import terms
from app.models.knowledge import EMBEDDING_DIMENSION

logger = logging.getLogger(__name__)


class EmbeddingUnavailable(AgentRuntimeError):
    """Transient provider failure (timeout, 5xx, rate limit): the ingestion job retries."""

    code = "embedding_unavailable"
    message = "The embedding provider is temporarily unavailable."


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _bucket(feature: str, dimension: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dimension, 1.0 if value >> 63 else -1.0


class DeterministicLocalEmbedder:
    """Signed feature hashing into 384 dimensions, L2-normalised.

    Features per text: stemmed words (weight 1.0), adjacent word pairs (0.5) and character
    4-grams of each word (0.25), so 'encrypt', 'encrypted' and 'encryption' land close
    together. Same text → same vector, on every machine and run.
    """

    name = "deterministic_local"

    def __init__(self, model: str = "nexusflow-hash-v1", dimension: int = EMBEDDING_DIMENSION):
        self.model = model
        self.dimension = dimension

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        words = terms(text)
        features: list[tuple[str, float]] = [(f"w:{word}", 1.0) for word in words]
        features += [(f"b:{a}_{b}", 0.5) for a, b in zip(words, words[1:], strict=False)]
        for word in words:
            padded = f"<{word}>"
            features += [(f"c:{padded[i : i + 4]}", 0.25) for i in range(len(padded) - 3)]
        for feature, weight in features:
            index, sign = _bucket(feature, self.dimension)
            vector[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        # A text with no indexable words embeds as zero; retrieval treats it as "no match".
        return [round(value / norm, 7) for value in vector] if norm else vector

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]


class OpenAIEmbedder:
    """OpenAI embeddings at 384 dimensions (text-embedding-3-*). Optional; never used in
    tests. Timeouts, rate limits and 5xx responses raise EmbeddingUnavailable (retried)."""

    name = "openai"
    URL = "https://api.openai.com/v1/embeddings"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.model = settings.knowledge_embedding_model
        self.dimension = settings.knowledge_embedding_dimension
        self._key = settings.openai_api_key
        self._timeout = settings.knowledge_embedding_timeout_seconds
        self._transport = transport

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(
                    self.URL,
                    headers={"Authorization": f"Bearer {self._key.get_secret_value()}"},
                    json={"model": self.model, "input": list(texts), "dimensions": self.dimension},
                )
        except httpx.HTTPError as error:
            logger.warning("Embedding request failed (%s)", type(error).__name__)
            raise EmbeddingUnavailable() from error
        if response.status_code == 429 or response.status_code >= 500:
            raise EmbeddingUnavailable()
        if response.status_code != 200:
            raise AgentRuntimeError(
                "The embedding provider rejected the request.", code="embedding_rejected"
            )
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]


def create_embedder(settings: Settings) -> EmbeddingProvider:
    if settings.knowledge_embedding_provider == "openai":
        return OpenAIEmbedder(settings)
    return DeterministicLocalEmbedder(settings.knowledge_embedding_model)
