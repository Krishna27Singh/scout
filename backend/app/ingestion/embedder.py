import hashlib
import math
from collections.abc import Iterable, Sequence
from typing import Protocol

from app.core.config import get_settings


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one normalized embedding for each input document."""

    def embed_query(self, text: str) -> list[float]:
        """Return a normalized embedding for a single query."""


class FastEmbedder:
    def __init__(self) -> None:
        self._model: object | None = None

    def _get_model(self) -> object:
        if self._model is None:
            from fastembed import TextEmbedding

            settings = get_settings()
            self._model = TextEmbedding(
                model_name=settings.embedding_model,
                cache_dir=settings.embedding_cache_dir,
            )
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        vectors = model.embed(list(texts))  # type: ignore[attr-defined]
        return [_validated_normalized_vector(vector) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class DeterministicFakeEmbedder:
    def __init__(self, dimensions: int = 384) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        self._dimensions = dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self._dimensions:
            digest = hashlib.sha256(f"{text}\0{counter}".encode()).digest()
            for offset in range(0, len(digest), 4):
                integer = int.from_bytes(digest[offset : offset + 4], "big")
                values.append((integer / 2**32) * 2 - 1)
                if len(values) == self._dimensions:
                    break
            counter += 1
        return _normalize(values)


def _validated_normalized_vector(vector: Iterable[float]) -> list[float]:
    values = [float(value) for value in vector]
    expected_dimensions = get_settings().embedding_dim
    if len(values) != expected_dimensions:
        raise ValueError(
            f"Embedding model returned {len(values)} dimensions; expected {expected_dimensions}"
        )
    return _normalize(values)


def _normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise ValueError("Embedding model returned a zero vector")
    return [value / norm for value in values]
