import numpy as np

from api.services.onnx.encoder import OnnxTextEncoder, mean_pool, l2_normalize


def test_mean_pool_respects_attention_mask():
    # 1 sample, 2 tokens, hidden=2. Second token masked out -> equals first token.
    last_hidden = np.array([[[1.0, 1.0], [9.0, 9.0]]], dtype=np.float32)
    attention_mask = np.array([[1, 0]], dtype=np.int64)
    pooled = mean_pool(last_hidden, attention_mask)
    assert np.allclose(pooled, np.array([[1.0, 1.0]]))


def test_l2_normalize_unit_length():
    vecs = np.array([[3.0, 4.0]], dtype=np.float32)
    out = l2_normalize(vecs)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)


class _FakeInput:
    def __init__(self, name):
        self.name = name


class _FakeSession:
    def get_inputs(self):
        return [_FakeInput("input_ids"), _FakeInput("attention_mask")]

    def run(self, output_names, feed):
        batch = feed["input_ids"].shape[0]
        return [np.ones((batch, 1, 384), dtype=np.float32)]


class _FakeEncoding:
    def __init__(self):
        self.ids = [101, 102]
        self.attention_mask = [1, 1]
        self.type_ids = [0, 0]


class _FakeTokenizer:
    def encode_batch(self, texts):
        return [_FakeEncoding() for _ in texts]


def test_encoder_encode_returns_normalized_vectors():
    encoder = OnnxTextEncoder(
        "all-MiniLM-L6-v2",
        _session=_FakeSession(),
        _tokenizer=_FakeTokenizer(),
        _dimension=384,
        _active_providers=["CPUExecutionProvider"],
    )
    out = encoder.encode(["hello", "world"])
    assert len(out) == 2
    assert len(out[0]) == 384
    assert np.allclose(np.linalg.norm(out[0]), 1.0, atol=1e-5)
    assert encoder.dimension == 384
    assert encoder.active_providers == ["CPUExecutionProvider"]
