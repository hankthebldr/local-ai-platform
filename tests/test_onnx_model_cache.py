from api.services.onnx.models import (
    ONNX_EMBEDDING_MODELS,
    DEFAULT_ONNX_EMBEDDING_MODEL,
)


def test_default_model_is_registered():
    assert DEFAULT_ONNX_EMBEDDING_MODEL in ONNX_EMBEDDING_MODELS


def test_default_model_is_minilm():
    assert DEFAULT_ONNX_EMBEDDING_MODEL == "all-MiniLM-L6-v2"
    entry = ONNX_EMBEDDING_MODELS["all-MiniLM-L6-v2"]
    assert entry["dimension"] == 384
    assert entry["pooling"] == "mean"
    # Phase 1 ships fp32 only; ISA-specific int8 is deferred to hardware-tuning.
    assert "fp32" in entry["files"] and "int8" not in entry["files"]


import api.services.onnx.model_cache as mc


def test_ensure_model_selects_fp32(monkeypatch):
    calls = []

    def fake_download(repo_id, filename, cache_dir=None):
        calls.append((repo_id, filename))
        return f"/cache/{repo_id}/{filename}"

    monkeypatch.setattr(mc, "hf_hub_download", fake_download)
    paths = mc.ensure_model("all-MiniLM-L6-v2", quant="fp32")
    assert paths.onnx_path.endswith("onnx/model.onnx")
    assert paths.tokenizer_path.endswith("tokenizer.json")
    assert (
        "sentence-transformers/all-MiniLM-L6-v2",
        "onnx/model.onnx",
    ) in calls


def test_ensure_model_falls_back_to_fp32_when_quant_absent(monkeypatch):
    monkeypatch.setattr(
        mc,
        "hf_hub_download",
        lambda repo_id, filename, cache_dir=None: f"/c/{filename}",
    )
    paths = mc.ensure_model("all-MiniLM-L6-v2", quant="fp16")
    assert paths.onnx_path.endswith("onnx/model.onnx")
