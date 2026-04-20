#!/usr/bin/env python3
"""
EmbeddingService — Backend-bound text-to-vector provider

Binds to ONE backend at init time (Ollama or sentence-transformers).
Once bound, stays with that backend for its lifetime to prevent
dimension/semantic mismatches in ChromaDB collections.
"""

from __future__ import annotations

import os
from typing import List, Optional

import requests

from ..logging_config import logger
from .ollama_service import OllamaService


class EmbeddingBackendUnavailable(Exception):
    """Raised when no embedding backend can be initialized."""


class EmbeddingBackendMismatch(Exception):
    """Raised when a ChromaDB collection's embedding metadata doesn't match the active service."""


class EmbeddingService:
    """Text-to-vector conversion with backend binding."""

    def __init__(
        self,
        ollama_service: OllamaService,
        ollama_model: Optional[str] = None,
        st_model: Optional[str] = None,
        backend: Optional[str] = None,
    ):
        self._ollama = ollama_service
        self._ollama_model = ollama_model or os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        self._st_model = st_model or os.getenv("SENTENCE_TRANSFORMER_MODEL", "all-MiniLM-L6-v2")
        self._backend_choice = backend or os.getenv("EMBEDDING_BACKEND", "auto")

        self._backend: Optional[str] = None
        self._model: Optional[str] = None
        self._dimension: Optional[int] = None
        self._st_instance = None

        self._select_backend()

    # ── Backend Selection ─────────────────────────────────────────────

    def _select_backend(self) -> None:
        if self._backend_choice == "ollama":
            self._bind_ollama(raise_on_fail=True)
        elif self._backend_choice == "sentence_transformers":
            self._bind_sentence_transformers(raise_on_fail=True)
        else:  # auto
            if not self._bind_ollama(raise_on_fail=False):
                if not self._bind_sentence_transformers(raise_on_fail=False):
                    raise EmbeddingBackendUnavailable(
                        f"No embedding backend available. Tried Ollama model '{self._ollama_model}' "
                        f"and sentence-transformers model '{self._st_model}'."
                    )

    def _bind_ollama(self, raise_on_fail: bool) -> bool:
        """Probe the Ollama embeddings endpoint; bind if it responds."""
        try:
            resp = requests.post(
                f"{self._ollama.host}/api/embeddings",
                json={"model": self._ollama_model, "prompt": "probe"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embedding")
            if not embedding or not isinstance(embedding, list):
                raise ValueError("Ollama returned empty or invalid embedding")
            self._backend = "ollama"
            self._model = self._ollama_model
            self._dimension = len(embedding)
            logger.info(f"Embedding backend: Ollama ({self._ollama_model}, dim={self._dimension})")
            return True
        except Exception as e:
            logger.warning(f"Ollama embeddings probe failed: {e}")
            if raise_on_fail:
                raise EmbeddingBackendUnavailable(f"Ollama embedding backend failed: {e}") from e
            return False

    def _bind_sentence_transformers(self, raise_on_fail: bool) -> bool:
        try:
            self._load_sentence_transformer()
            vec = self._st_instance.encode(["probe"], convert_to_numpy=False)[0]
            self._backend = "sentence_transformers"
            self._model = self._st_model
            self._dimension = len(vec)
            logger.info(
                f"Embedding backend: sentence-transformers ({self._st_model}, dim={self._dimension})"
            )
            return True
        except Exception as e:
            logger.warning(f"sentence-transformers load failed: {e}")
            if raise_on_fail:
                raise EmbeddingBackendUnavailable(
                    f"sentence-transformers backend failed: {e}"
                ) from e
            return False

    def _load_sentence_transformer(self) -> None:
        """Import and instantiate sentence-transformers. Isolated for test patching."""
        from sentence_transformers import SentenceTransformer
        self._st_instance = SentenceTransformer(self._st_model)

    # ── Embedding API ─────────────────────────────────────────────────

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self._backend == "ollama":
            return [self._embed_one_ollama(t) for t in texts]
        return [list(v) for v in self._st_instance.encode(texts, convert_to_numpy=False)]

    def _embed_one_ollama(self, text: str) -> List[float]:
        resp = requests.post(
            f"{self._ollama.host}/api/embeddings",
            json={"model": self._ollama_model, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        embedding = resp.json().get("embedding")
        if not embedding:
            raise RuntimeError(f"Ollama returned empty embedding for text: {text[:60]}...")
        return embedding

    def embed_query(self, text: str) -> List[float]:
        return self.embed([text])[0]

    # ── Metadata ──────────────────────────────────────────────────────

    def get_backend(self) -> str:
        return self._backend or "unknown"

    def get_model(self) -> str:
        return self._model or "unknown"

    def get_dimension(self) -> int:
        return self._dimension or 0

    def describe(self) -> dict:
        return {
            "backend": self.get_backend(),
            "model": self.get_model(),
            "dimension": self.get_dimension(),
        }
