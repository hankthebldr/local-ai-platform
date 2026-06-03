"""ONNX encoder model registry. Pure data — no onnxruntime import, so this
module is safe to import anywhere (including from embedding_service at startup).
"""

from __future__ import annotations

ONNX_EMBEDDING_MODELS = {
    "all-MiniLM-L6-v2": {  # Phase 1 DEFAULT — drop-in for the sentence-transformers path
        "repo": "sentence-transformers/all-MiniLM-L6-v2",
        "files": {"fp32": "onnx/model.onnx", "int8": "onnx/model_quantized.onnx"},
        "dimension": 384,
        "pooling": "mean",
        "query_prefix": None,
        "max_length": 256,
    },
    "bge-small-en-v1.5": {  # documented quality-upgrade path — NOT the default
        "repo": "BAAI/bge-small-en-v1.5",
        "files": {"fp32": "onnx/model.onnx", "int8": "onnx/model_quantized.onnx"},
        "dimension": 384,
        "pooling": "cls",
        "query_prefix": "Represent this sentence for searching relevant passages: ",
        "max_length": 512,
    },
}

DEFAULT_ONNX_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
