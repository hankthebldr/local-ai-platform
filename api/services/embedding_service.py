#!/usr/bin/env python3
"""
EmbeddingService — Backend-bound text-to-vector provider

Binds to ONE backend at init time (Ollama, ONNX, or sentence-transformers).
Once bound, stays with that backend for its lifetime to prevent
dimension/semantic mismatches in ChromaDB collections. Auto-select order is
Ollama → ONNX → sentence-transformers (the last is the torch-based failsafe).
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import requests

from ..logging_config import logger
from .ollama_service import OllamaService
from .onnx.models import DEFAULT_ONNX_EMBEDDING_MODEL


def normalized_family(model: str) -> str:
    """Reduce a model id to its comparable family: drop namespace prefix and
    any ':tag'/quant suffix, lowercase. So sentence-transformers/all-MiniLM-L6-v2
    and onnx all-MiniLM-L6-v2 compare equal."""
    base = model.split("/")[-1]
    base = base.split(":")[0]
    return base.lower()


def collection_compatible(existing: dict, active: dict) -> Tuple[bool, Optional[str]]:
    """Decide whether the active embedding service may use a Chroma collection
    built by `existing` (both are describe() dicts).

    Default: strict exact match. With ENCLAVE_EMBEDDING_ALLOW_REBIND=true,
    lenient on {normalized_family, dimension}; a dimension change ALWAYS fails.
    Returns (compatible, warning_message_or_none).
    """
    if existing == active:
        return True, None

    allow_rebind = os.getenv("ENCLAVE_EMBEDDING_ALLOW_REBIND", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    if not allow_rebind:
        return False, None

    if existing.get("dimension") != active.get("dimension"):
        return False, None  # hard incompatibility — re-index required

    same_family = normalized_family(
        str(existing.get("model", ""))
    ) == normalized_family(str(active.get("model", "")))
    if not same_family:
        return False, None

    warning = (
        f"Rebinding embedding collection from {existing} to {active} via "
        f"ENCLAVE_EMBEDDING_ALLOW_REBIND. Vectors may differ subtly across "
        f"backends; retrieval quality could degrade. Re-index to be safe."
    )
    return True, warning


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
        onnx_model: Optional[str] = None,
        backend: Optional[str] = None,
    ):
        self._ollama = ollama_service
        self._ollama_model = ollama_model or os.getenv(
            "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"
        )
        self._st_model = st_model or os.getenv(
            "SENTENCE_TRANSFORMER_MODEL", "all-MiniLM-L6-v2"
        )
        self._onnx_model = onnx_model or os.getenv(
            "ONNX_EMBEDDING_MODEL", DEFAULT_ONNX_EMBEDDING_MODEL
        )
        self._backend_choice = backend or os.getenv("EMBEDDING_BACKEND", "auto")

        self._backend: Optional[str] = None
        self._model: Optional[str] = None
        self._dimension: Optional[int] = None
        self._st_instance = None
        self._onnx_instance = None

        self._select_backend()

    # ── Backend Selection ─────────────────────────────────────────────

    def _select_backend(self) -> None:
        if self._backend_choice == "ollama":
            self._bind_ollama(raise_on_fail=True)
        elif self._backend_choice == "onnx":
            self._bind_onnx(raise_on_fail=True)
        elif self._backend_choice == "sentence_transformers":
            self._bind_sentence_transformers(raise_on_fail=True)
        else:  # auto: Ollama -> ONNX -> sentence-transformers (ST is the failsafe)
            if not self._bind_ollama(raise_on_fail=False):
                if not self._bind_onnx(raise_on_fail=False):
                    if not self._bind_sentence_transformers(raise_on_fail=False):
                        raise EmbeddingBackendUnavailable(
                            f"No embedding backend available. Tried Ollama model "
                            f"'{self._ollama_model}', ONNX model '{self._onnx_model}', "
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
            logger.info(
                f"Embedding backend: Ollama ({self._ollama_model}, dim={self._dimension})"
            )
            return True
        except Exception as e:
            logger.warning(f"Ollama embeddings probe failed: {e}")
            if raise_on_fail:
                raise EmbeddingBackendUnavailable(
                    f"Ollama embedding backend failed: {e}"
                ) from e
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

    def _load_onnx_encoder(self) -> None:
        """Import and instantiate the ONNX encoder. Isolated for test patching."""
        from .onnx.encoder import OnnxTextEncoder

        self._onnx_instance = OnnxTextEncoder(self._onnx_model)

    def _bind_onnx(self, raise_on_fail: bool) -> bool:
        try:
            self._load_onnx_encoder()
            # Probe with a >1 batch on purpose: some accelerator EPs build a
            # session fine but fail at inference on batches >1 (e.g. CoreML's
            # dynamic-batch limit). A single-text probe would bind with false
            # confidence and then crash on the first real multi-chunk document.
            vecs = self._onnx_instance.encode(["probe one", "probe two"])
            vec = vecs[0]
            self._backend = "onnx"
            self._model = self._onnx_model
            self._dimension = len(vec)
            logger.info(
                f"Embedding backend: ONNX ({self._onnx_model}, dim={self._dimension}, "
                f"providers={self._onnx_instance.active_providers})"
            )
            return True
        except Exception as e:
            logger.warning(f"ONNX embeddings load failed: {e}")
            if raise_on_fail:
                raise EmbeddingBackendUnavailable(
                    f"ONNX embedding backend failed: {e}"
                ) from e
            return False

    # ── Embedding API ─────────────────────────────────────────────────

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self._backend == "ollama":
            return [self._embed_one_ollama(t) for t in texts]
        if self._backend == "onnx":
            return self._onnx_instance.encode(texts)
        # sentence_transformers + chromadb: must return List[List[float]].
        # Previously this used convert_to_numpy=False + list(v), which leaks
        # PyTorch tensor objects into the embeddings list and breaks Chroma's
        # add() with: "got [[tensor(0.04…), tensor(-0.02…)]]". convert_to_numpy=True
        # returns np.ndarray rows; .tolist() flattens them to native floats.
        embeddings = self._st_instance.encode(texts, convert_to_numpy=True)
        return [row.tolist() for row in embeddings]

    def _embed_one_ollama(self, text: str) -> List[float]:
        resp = requests.post(
            f"{self._ollama.host}/api/embeddings",
            json={"model": self._ollama_model, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        embedding = resp.json().get("embedding")
        if not embedding:
            raise RuntimeError(
                f"Ollama returned empty embedding for text: {text[:60]}..."
            )
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

    def runtime_info(self) -> dict:
        """describe() plus runtime-only fields (active ONNX providers).

        Kept SEPARATE from describe() because describe() feeds Chroma's
        collection-identity metadata — adding providers there would break the
        rebind guard for existing collections.
        """
        info = self.describe()
        if self._backend == "onnx" and self._onnx_instance is not None:
            info["providers"] = self._onnx_instance.active_providers
        return info
