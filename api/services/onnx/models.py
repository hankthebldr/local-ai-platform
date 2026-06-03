"""ONNX encoder model registry. Pure data — no onnxruntime import, so this
module is safe to import anywhere (including from embedding_service at startup).

Phase 1 ships fp32 (`onnx/model.onnx`) only — it exists for every model here and
runs on any CPU architecture. int8 quantization is deferred to the hardware-
tuning phase because the published int8 weights are ISA-specific and there is no
universal int8 file. For reference, sentence-transformers/all-MiniLM-L6-v2
publishes: onnx/model_qint8_arm64.onnx (Apple/ARM), onnx/model_qint8_avx512.onnx
and onnx/model_qint8_avx512_vnni.onnx (x86 AVX-512), onnx/model_quint8_avx2.onnx
(older x86). Selecting among these needs ISA detection (the same CPU-vendor probe
deferred for OpenVINO), so it ships with that work — not before.
"""

from __future__ import annotations

ONNX_EMBEDDING_MODELS = {
    "all-MiniLM-L6-v2": {  # Phase 1 DEFAULT — drop-in for the sentence-transformers path
        "repo": "sentence-transformers/all-MiniLM-L6-v2",
        "files": {"fp32": "onnx/model.onnx"},
        "dimension": 384,
        "pooling": "mean",
        "query_prefix": None,
        "max_length": 256,
    },
    "bge-small-en-v1.5": {  # documented quality-upgrade path — NOT the default
        "repo": "BAAI/bge-small-en-v1.5",
        "files": {"fp32": "onnx/model.onnx"},  # this repo publishes fp32 only
        "dimension": 384,
        "pooling": "cls",
        "query_prefix": "Represent this sentence for searching relevant passages: ",
        "max_length": 512,
    },
}

DEFAULT_ONNX_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
