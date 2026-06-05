"""Resolve ONNX encoder models to local files, downloading from the HF Hub on miss."""

from __future__ import annotations

import os
from typing import Optional

from huggingface_hub import hf_hub_download
from pydantic import BaseModel

from .models import ONNX_EMBEDDING_MODELS


class LocalModelPaths(BaseModel):
    onnx_path: str
    tokenizer_path: str


def _cache_dir() -> Optional[str]:
    # Prefer an Enclave-specific cache, then HF_HOME, else hf_hub's default (None).
    return os.getenv("ENCLAVE_ONNX_CACHE") or os.getenv("HF_HOME") or None


def ensure_model(name: str, quant: str) -> LocalModelPaths:
    """Resolve `name` to local .onnx + tokenizer files for the given quant.

    Picks the quant-appropriate weight variant from the registry entry's
    `files` map, falling back to fp32, then to any registered variant.
    """
    entry = ONNX_EMBEDDING_MODELS[name]  # KeyError on unknown name is intentional
    files = entry["files"]
    onnx_file = files.get(quant) or files.get("fp32") or next(iter(files.values()))

    onnx_path = hf_hub_download(
        repo_id=entry["repo"], filename=onnx_file, cache_dir=_cache_dir()
    )
    tokenizer_path = hf_hub_download(
        repo_id=entry["repo"], filename="tokenizer.json", cache_dir=_cache_dir()
    )
    return LocalModelPaths(onnx_path=onnx_path, tokenizer_path=tokenizer_path)
