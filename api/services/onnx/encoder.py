"""OnnxTextEncoder — text -> normalized vectors via ONNX Runtime.

The pooling/normalization pipeline is owned here (no torch). Construction
either resolves+loads the model (production) or accepts injected session +
tokenizer (tests), mirroring EmbeddingService._load_sentence_transformer
isolation.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from ..architecture import Architecture, _get_current
from .model_cache import ensure_model
from .models import ONNX_EMBEDDING_MODELS
from .session import build_session


def mean_pool(last_hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Mean over tokens, weighted by attention mask. [B,T,H],[B,T] -> [B,H]."""
    mask = attention_mask[..., None].astype(np.float32)
    summed = (last_hidden * mask).sum(axis=1)
    counts = np.clip(mask.sum(axis=1), 1e-9, None)
    return summed / counts


def cls_pool(last_hidden: np.ndarray) -> np.ndarray:
    """Take the [CLS] token (position 0). [B,T,H] -> [B,H]."""
    return last_hidden[:, 0]


def l2_normalize(vecs: np.ndarray) -> np.ndarray:
    norms = np.clip(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12, None)
    return vecs / norms


class OnnxTextEncoder:
    def __init__(
        self,
        model_name: str,
        arch: Optional[Architecture] = None,
        *,
        _session=None,
        _tokenizer=None,
        _dimension: Optional[int] = None,
        _active_providers: Optional[List[str]] = None,
    ):
        entry = ONNX_EMBEDDING_MODELS[model_name]
        # NOTE: entry["query_prefix"] is intentionally NOT applied here. For the
        # Phase-1 default (all-MiniLM-L6-v2) the prefix is None, so this is a
        # no-op. bge-small-en-v1.5 declares a query prefix, but applying it
        # correctly needs a query-vs-document distinction the encode() interface
        # doesn't carry yet — deferred to the reranker/Phase-2 work. A future
        # bge user must wire prefixing before relying on asymmetric retrieval.
        self.model_name = model_name
        self._pooling = entry["pooling"]
        self._max_length = entry.get("max_length", 512)

        if _session is not None:
            # Injected (test) path.
            self._session = _session
            self._tokenizer = _tokenizer
            self._dimension = _dimension or entry["dimension"]
            self._active_providers = _active_providers or ["CPUExecutionProvider"]
        else:
            arch = arch or _get_current()
            quant = arch.recommended_onnx_providers().quant
            paths = ensure_model(model_name, quant)
            self._session, self._active_providers = build_session(paths.onnx_path, arch)
            from tokenizers import Tokenizer

            self._tokenizer = Tokenizer.from_file(paths.tokenizer_path)
            self._tokenizer.enable_truncation(max_length=self._max_length)
            self._tokenizer.enable_padding()
            self._dimension = entry["dimension"]

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def active_providers(self) -> List[str]:
        return self._active_providers

    def encode(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        if not texts:
            return []
        input_names = {i.name for i in self._session.get_inputs()}
        out: List[List[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            encs = self._tokenizer.encode_batch(batch)
            input_ids = np.array([e.ids for e in encs], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
            feed = {"input_ids": input_ids, "attention_mask": attention_mask}
            if "token_type_ids" in input_names:
                feed["token_type_ids"] = np.array(
                    [e.type_ids for e in encs], dtype=np.int64
                )
            outputs = self._session.run(None, feed)
            last_hidden = outputs[0]
            if self._pooling == "cls":
                pooled = cls_pool(last_hidden)
            else:
                pooled = mean_pool(last_hidden, attention_mask)
            out.extend(l2_normalize(pooled).tolist())
        return out
