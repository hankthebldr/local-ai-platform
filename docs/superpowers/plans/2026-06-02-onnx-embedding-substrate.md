# ONNX Execution Substrate + Embeddings Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ONNX Runtime as a hardware-portable execution substrate for Enclave's encoder tier, and prove it by wiring an ONNX embeddings backend into the RAG pipeline (torch-free, arch-aware provider selection).

**Architecture:** A new `api/services/onnx/` package (session factory + model cache + text encoder + model registry) selects an ONNX execution provider per host from the existing `Architecture` abstraction via a new `recommended_onnx_providers()` Protocol method. `EmbeddingService` gains a third backend arm that consumes the encoder. ONNX is a substrate *beside* `Runner`, not a new Runner — the LLM hot path is untouched.

**Tech Stack:** Python 3.12+, `onnxruntime>=1.17`, `tokenizers>=0.15`, `numpy`, `huggingface-hub` (already core), pytest. No `torch` on the ONNX path.

**Source spec:** [docs/superpowers/specs/2026-06-02-onnx-embedding-substrate-design.md](../specs/2026-06-02-onnx-embedding-substrate-design.md)

---

## File Structure

**Created:**
- `api/services/onnx/__init__.py` — package marker
- `api/services/onnx/models.py` — `ONNX_EMBEDDING_MODELS` registry + `DEFAULT_ONNX_EMBEDDING_MODEL` (pure data, no onnxruntime import)
- `api/services/onnx/model_cache.py` — `LocalModelPaths` + `ensure_model()` (HF download + quant-variant pick)
- `api/services/onnx/session.py` — `build_session()` (arch→providers + CPU-floor fallback)
- `api/services/onnx/encoder.py` — `OnnxTextEncoder` + pure pooling functions
- `setup/requirements-onnx.txt` — onnxruntime/tokenizers/numpy
- `tests/test_architecture_onnx_providers.py`
- `tests/test_onnx_model_cache.py`
- `tests/test_onnx_session.py`
- `tests/test_onnx_encoder.py`

**Modified:**
- `api/services/architecture.py` — add `OnnxExecutionPlan` model + `recommended_onnx_providers()` on the `Architecture` Protocol and on `UnknownArchitecture`
- `api/services/arch_impl/unified.py` — `recommended_onnx_providers()` (apple/cpu_x86 branch)
- `api/services/arch_impl/nvidia_single.py` — `recommended_onnx_providers()`
- `api/services/arch_impl/nvidia_multi.py` — `recommended_onnx_providers()`
- `api/services/embedding_service.py` — `normalized_family()`, `collection_compatible()`, `_bind_onnx()`, `_load_onnx_encoder()`, `_select_backend()` wiring, `embed()` branch, `runtime_info()`
- `api/services/document_service.py` — use `collection_compatible()` in `_init_chroma()`
- `setup/requirements-rag.txt` — reference `requirements-onnx.txt`

---

## Phase 0 — The substrate

### Task 0.1: `OnnxExecutionPlan` + Protocol method + `UnknownArchitecture` impl

**Files:**
- Modify: `api/services/architecture.py`
- Test: `tests/test_architecture_onnx_providers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_architecture_onnx_providers.py`:

```python
from api.services.architecture import (
    OnnxExecutionPlan,
    UnknownArchitecture,
)


def test_onnx_execution_plan_shape():
    plan = OnnxExecutionPlan(
        providers=["CPUExecutionProvider"], quant="int8", provider_options=[{}]
    )
    assert plan.providers == ["CPUExecutionProvider"]
    assert plan.quant == "int8"
    assert plan.provider_options == [{}]


def test_unknown_arch_recommends_cpu_int8():
    plan = UnknownArchitecture().recommended_onnx_providers()
    assert plan.providers == ["CPUExecutionProvider"]
    assert plan.quant == "int8"
    # CPU is always the floor
    assert plan.providers[-1] == "CPUExecutionProvider"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_architecture_onnx_providers.py -v`
Expected: FAIL — `ImportError: cannot import name 'OnnxExecutionPlan'`

- [ ] **Step 3: Add the model + Protocol method**

In `api/services/architecture.py`, after the `TransitionPlan` class (around line 159), add:

```python
class OnnxExecutionPlan(BaseModel):
    """Per-architecture ONNX Runtime execution recipe.

    providers is ordered by preference; CPUExecutionProvider is ALWAYS the
    final entry (the universal floor). provider_options is parallel to
    providers — one options dict per provider (empty dict = defaults).
    """

    providers: List[str]
    quant: Literal["int8", "fp16", "fp32"]
    provider_options: List[dict]
```

In the `Architecture` Protocol body, after `default_keep_alive` (around line 223), add:

```python
    def recommended_onnx_providers(self) -> "OnnxExecutionPlan":
        """Ordered ONNX Runtime execution providers + quant for this host.

        The ONNX substrate (api/services/onnx/) calls this to configure
        encoder sessions (embeddings, rerankers, classifiers). CPU is always
        the floor — a missing accelerator wheel degrades, never fails.
        """
        ...
```

- [ ] **Step 4: Implement on `UnknownArchitecture`**

In `UnknownArchitecture` (around line 262), add a method (place it after `default_keep_alive`):

```python
    def recommended_onnx_providers(self) -> "OnnxExecutionPlan":
        # Degraded mode: the universal floor, conservatively quantized.
        return OnnxExecutionPlan(
            providers=["CPUExecutionProvider"], quant="int8", provider_options=[{}]
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_architecture_onnx_providers.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add api/services/architecture.py tests/test_architecture_onnx_providers.py
git commit -m "feat(onnx): OnnxExecutionPlan + recommended_onnx_providers protocol"
```

---

### Task 0.2: `recommended_onnx_providers()` on `UnifiedArchitecture`

**Files:**
- Modify: `api/services/arch_impl/unified.py`
- Test: `tests/test_architecture_onnx_providers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_architecture_onnx_providers.py`:

```python
from api.services.architecture import ArchClass
from api.services.arch_impl.unified import UnifiedArchitecture


def _unified(arch_class):
    # Construct directly — bypass detect() so the test runs on any host.
    return UnifiedArchitecture(
        arch_class=arch_class, total_memory_gb=48.0, bandwidth_gbps=273.0
    )


def test_apple_unified_recommends_coreml_fp16():
    plan = _unified(ArchClass.APPLE_UNIFIED).recommended_onnx_providers()
    assert plan.providers == ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    assert plan.quant == "fp16"
    assert len(plan.provider_options) == len(plan.providers)


def test_cpu_x86_recommends_cpu_int8_amd_first():
    # AMD-first: cpu_x86 maps to plain CPU EP + int8. No vendor probe in Phase 1.
    plan = _unified(ArchClass.CPU_X86).recommended_onnx_providers()
    assert plan.providers == ["CPUExecutionProvider"]
    assert plan.quant == "int8"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_architecture_onnx_providers.py -k unified_recommends -v`
Expected: FAIL — `AttributeError: 'UnifiedArchitecture' object has no attribute 'recommended_onnx_providers'`

- [ ] **Step 3: Implement the method**

In `api/services/arch_impl/unified.py`, add `OnnxExecutionPlan` to the import block from `..architecture` (around line 25):

```python
from ..architecture import (
    ArchClass,
    ClassifiedError,
    Feasibility,
    OnnxExecutionPlan,
    PressureSnapshot,
    ScheduleDecision,
    TransitionPlan,
)
```

Then add the method to `UnifiedArchitecture` (after `default_keep_alive`, around line 355):

```python
    def recommended_onnx_providers(self) -> OnnxExecutionPlan:
        """Apple Silicon → CoreML (ANE/GPU) + CPU floor, fp16.
        cpu_x86 → plain CPU EP, int8 (AMD-first; Zen4 AVX-512 runs int8 well).

        The Intel OpenVINO branch is a deferred optimization (needs a CPU-vendor
        probe in detect()); cpu_x86 here is optimal for AMD and a correct floor
        for Intel.
        """
        if self.name == ArchClass.APPLE_UNIFIED:
            return OnnxExecutionPlan(
                providers=["CoreMLExecutionProvider", "CPUExecutionProvider"],
                quant="fp16",
                provider_options=[{}, {}],
            )
        return OnnxExecutionPlan(
            providers=["CPUExecutionProvider"],
            quant="int8",
            provider_options=[{}],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_architecture_onnx_providers.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/arch_impl/unified.py tests/test_architecture_onnx_providers.py
git commit -m "feat(onnx): UnifiedArchitecture onnx providers (CoreML/CPU, AMD-first)"
```

---

### Task 0.3: `recommended_onnx_providers()` on NVIDIA architectures

**Files:**
- Modify: `api/services/arch_impl/nvidia_single.py`
- Modify: `api/services/arch_impl/nvidia_multi.py`
- Test: `tests/test_architecture_onnx_providers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_architecture_onnx_providers.py`:

```python
from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture
from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture

_FAKE_GPU = {"name": "RTX PRO 4000", "vram_total_gb": 24.0}


def test_nvidia_single_recommends_cuda_fp16():
    arch = NvidiaSingleArchitecture(gpu_meta=_FAKE_GPU, driver_version="575")
    plan = arch.recommended_onnx_providers()
    assert plan.providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert plan.quant == "fp16"


def test_nvidia_multi_recommends_cuda_fp16():
    arch = NvidiaMultiArchitecture(
        gpus=[_FAKE_GPU, _FAKE_GPU], nvlink_topology=[], driver_version="575"
    )
    plan = arch.recommended_onnx_providers()
    assert plan.providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert plan.quant == "fp16"
```

Note: `NvidiaSingleArchitecture.__init__` calls `_nvml.estimate_bandwidth_gbps(gpu_meta["name"])`, which works without a real GPU (it is a name→number lookup). If it raises in CI, wrap construction in the test with `monkeypatch.setattr("api.services.arch_impl._nvml.estimate_bandwidth_gbps", lambda n: 600.0)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_architecture_onnx_providers.py -k nvidia -v`
Expected: FAIL — `AttributeError: ... has no attribute 'recommended_onnx_providers'`

- [ ] **Step 3: Implement on `NvidiaSingleArchitecture`**

In `api/services/arch_impl/nvidia_single.py`, add `OnnxExecutionPlan` to the `..architecture` import block (around line 17), then add the method to the class (after its `default_keep_alive`, or at the end of the runtime methods):

```python
    def recommended_onnx_providers(self) -> OnnxExecutionPlan:
        """Single NVIDIA GPU → CUDA EP + CPU floor, fp16. (TensorRT EP is a
        later opportunistic optimization.)"""
        return OnnxExecutionPlan(
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            quant="fp16",
            provider_options=[{}, {}],
        )
```

- [ ] **Step 4: Implement on `NvidiaMultiArchitecture`**

In `api/services/arch_impl/nvidia_multi.py`, add `OnnxExecutionPlan` to the `..architecture` import block (around line 21), then add the identical method to the class:

```python
    def recommended_onnx_providers(self) -> OnnxExecutionPlan:
        """Multi-GPU → CUDA EP + CPU floor, fp16. Encoder workloads are small;
        they run on one GPU (placement of encoders across GPUs is out of scope)."""
        return OnnxExecutionPlan(
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            quant="fp16",
            provider_options=[{}, {}],
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_architecture_onnx_providers.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add api/services/arch_impl/nvidia_single.py api/services/arch_impl/nvidia_multi.py tests/test_architecture_onnx_providers.py
git commit -m "feat(onnx): NVIDIA architectures onnx providers (CUDA/CPU, fp16)"
```

---

### Task 0.4: ONNX embedding model registry

**Files:**
- Create: `api/services/onnx/__init__.py`
- Create: `api/services/onnx/models.py`
- Test: `tests/test_onnx_model_cache.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_onnx_model_cache.py`:

```python
from api.services.onnx.models import (
    ONNX_EMBEDDING_MODELS,
    DEFAULT_ONNX_EMBEDDING_MODEL,
)


def test_default_model_is_registered():
    assert DEFAULT_ONNX_EMBEDDING_MODEL in ONNX_EMBEDDING_MODELS


def test_default_model_is_minilm():
    # Phase 1 default = the exact model the sentence-transformers path uses.
    assert DEFAULT_ONNX_EMBEDDING_MODEL == "all-MiniLM-L6-v2"
    entry = ONNX_EMBEDDING_MODELS["all-MiniLM-L6-v2"]
    assert entry["dimension"] == 384
    assert entry["pooling"] == "mean"
    assert "fp32" in entry["files"] and "int8" in entry["files"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_onnx_model_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.onnx'`

- [ ] **Step 3: Create the package + registry**

Create `api/services/onnx/__init__.py`:

```python
"""ONNX Runtime execution substrate for Enclave's encoder tier.

Hardware-portable embeddings / rerankers / classifiers. Selects execution
providers per host from api.services.architecture. Sits beside the Runner
axis (LLM generation) — it is NOT a Runner.
"""
```

Create `api/services/onnx/models.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_onnx_model_cache.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/onnx/__init__.py api/services/onnx/models.py tests/test_onnx_model_cache.py
git commit -m "feat(onnx): encoder model registry (MiniLM default, BGE upgrade)"
```

---

### Task 0.5: Model cache — `ensure_model()`

**Files:**
- Create: `api/services/onnx/model_cache.py`
- Test: `tests/test_onnx_model_cache.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_onnx_model_cache.py`:

```python
import api.services.onnx.model_cache as mc


def test_ensure_model_picks_int8_variant(monkeypatch):
    calls = []

    def fake_download(repo_id, filename, cache_dir=None):
        calls.append((repo_id, filename))
        return f"/cache/{repo_id}/{filename}"

    monkeypatch.setattr(mc, "hf_hub_download", fake_download)
    paths = mc.ensure_model("all-MiniLM-L6-v2", quant="int8")
    assert paths.onnx_path.endswith("onnx/model_quantized.onnx")
    assert paths.tokenizer_path.endswith("tokenizer.json")
    assert ("sentence-transformers/all-MiniLM-L6-v2", "onnx/model_quantized.onnx") in calls


def test_ensure_model_falls_back_to_fp32_when_quant_absent(monkeypatch):
    monkeypatch.setattr(
        mc, "hf_hub_download", lambda repo_id, filename, cache_dir=None: f"/c/{filename}"
    )
    # fp16 variant isn't registered for MiniLM → falls back to fp32
    paths = mc.ensure_model("all-MiniLM-L6-v2", quant="fp16")
    assert paths.onnx_path.endswith("onnx/model.onnx")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_onnx_model_cache.py -k ensure_model -v`
Expected: FAIL — `AttributeError: module 'api.services.onnx.model_cache' has no attribute 'hf_hub_download'`

- [ ] **Step 3: Implement**

Create `api/services/onnx/model_cache.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_onnx_model_cache.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/onnx/model_cache.py tests/test_onnx_model_cache.py
git commit -m "feat(onnx): model cache with quant-variant resolution"
```

---

### Task 0.6: Session factory — `build_session()` with CPU-floor fallback

**Files:**
- Create: `api/services/onnx/session.py`
- Test: `tests/test_onnx_session.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_onnx_session.py`:

```python
import api.services.onnx.session as sess_mod
from api.services.architecture import ArchClass
from api.services.arch_impl.unified import UnifiedArchitecture


class _FakeSession:
    """Mimics ORT: silently drops providers not in `available`."""

    available = {"CPUExecutionProvider"}

    def __init__(self, path, providers=None, provider_options=None):
        self.path = path
        self._providers = [p for p in (providers or []) if p in self.available]

    def get_providers(self):
        return self._providers or ["CPUExecutionProvider"]


class _FakeOrt:
    InferenceSession = _FakeSession


def _apple():
    return UnifiedArchitecture(
        arch_class=ArchClass.APPLE_UNIFIED, total_memory_gb=48.0, bandwidth_gbps=273.0
    )


def test_build_session_appends_cpu_floor(monkeypatch):
    monkeypatch.setattr(sess_mod, "ort", _FakeOrt)
    # cpu_x86 plan is already CPU-only; assert the session builds and reports CPU.
    cpu_arch = UnifiedArchitecture(
        arch_class=ArchClass.CPU_X86, total_memory_gb=96.0, bandwidth_gbps=89.0
    )
    session, active = sess_mod.build_session("/fake/model.onnx", arch=cpu_arch)
    assert active == ["CPUExecutionProvider"]


def test_build_session_degrades_when_accelerator_unavailable(monkeypatch, caplog):
    # CoreML requested (apple plan) but only CPU available → falls back to CPU, warns.
    monkeypatch.setattr(sess_mod, "ort", _FakeOrt)
    session, active = sess_mod.build_session("/fake/model.onnx", arch=_apple())
    assert active == ["CPUExecutionProvider"]
    assert any("CoreMLExecutionProvider" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_onnx_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.onnx.session'`

- [ ] **Step 3: Implement**

Create `api/services/onnx/session.py`:

```python
"""Build ONNX Runtime InferenceSessions using the host architecture's
recommended execution providers, with a guaranteed CPU floor."""

from __future__ import annotations

from typing import List, Optional, Tuple

import onnxruntime as ort  # module-level so tests can monkeypatch `ort`

from ..architecture import Architecture, _get_current
from ...logging_config import logger


def build_session(
    model_path: str, arch: Optional[Architecture] = None
) -> Tuple["ort.InferenceSession", List[str]]:
    """Construct an InferenceSession for `model_path`.

    Reads the architecture's recommended_onnx_providers(), guarantees
    CPUExecutionProvider is present as the floor, and reports which providers
    actually activated. A requested provider that the installed wheel can't
    supply is logged and dropped — the session still builds on CPU.
    Returns (session, active_providers).
    """
    arch = arch or _get_current()
    plan = arch.recommended_onnx_providers()

    requested = list(plan.providers)
    options = list(plan.provider_options)
    if "CPUExecutionProvider" not in requested:
        requested.append("CPUExecutionProvider")
        options.append({})
    # Pad options to match providers length.
    if len(options) < len(requested):
        options += [{}] * (len(requested) - len(options))

    try:
        session = ort.InferenceSession(
            model_path, providers=requested, provider_options=options
        )
    except Exception as e:  # accelerator EP construction can raise on some wheels
        logger.warning(
            f"ONNX session with providers {requested} failed ({e}); "
            f"retrying CPU-only"
        )
        session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )

    active = session.get_providers()
    dropped = [p for p in requested if p not in active]
    if dropped:
        logger.warning(
            f"ONNX providers requested but unavailable, fell back: {dropped}; "
            f"active={active}. Install the matching onnxruntime wheel "
            f"(onnxruntime-gpu / onnxruntime-openvino) to enable them."
        )
    return session, active
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_onnx_session.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/onnx/session.py tests/test_onnx_session.py
git commit -m "feat(onnx): arch-aware session factory with CPU-floor fallback"
```

---

### Task 0.7: Text encoder — `OnnxTextEncoder` + pooling

**Files:**
- Create: `api/services/onnx/encoder.py`
- Test: `tests/test_onnx_encoder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_onnx_encoder.py`:

```python
import numpy as np

import api.services.onnx.encoder as enc_mod
from api.services.onnx.encoder import OnnxTextEncoder, mean_pool, l2_normalize


def test_mean_pool_respects_attention_mask():
    # 1 sample, 2 tokens, hidden=2. Second token masked out → equals first token.
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
        # Return [batch, 1, 384] all-ones hidden states.
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
    # all-ones hidden → mean-pool all-ones → L2-normalized to 1/sqrt(384)
    assert np.allclose(np.linalg.norm(out[0]), 1.0, atol=1e-5)
    assert encoder.dimension == 384
    assert encoder.active_providers == ["CPUExecutionProvider"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_onnx_encoder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.onnx.encoder'`

- [ ] **Step 3: Implement**

Create `api/services/onnx/encoder.py`:

```python
"""OnnxTextEncoder — text → normalized vectors via ONNX Runtime.

The pooling/normalization pipeline is owned here (no torch). Construction
either resolves+loads the model (production) or accepts injected session +
tokenizer (tests), mirroring EmbeddingService._load_sentence_transformer
isolation.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from ..architecture import Architecture, _get_current
from .models import ONNX_EMBEDDING_MODELS
from .model_cache import ensure_model
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
            self._session, self._active_providers = build_session(
                paths.onnx_path, arch
            )
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_onnx_encoder.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/onnx/encoder.py tests/test_onnx_encoder.py
git commit -m "feat(onnx): OnnxTextEncoder with mean/cls pooling + L2 norm"
```

---

### Task 0.8: Dependency files

**Files:**
- Create: `setup/requirements-onnx.txt`
- Modify: `setup/requirements-rag.txt`

- [ ] **Step 1: Create `setup/requirements-onnx.txt`**

```
# ONNX Runtime encoder substrate — torch-free embeddings / rerankers / classifiers.
# Base onnxruntime wheel carries CoreML (macOS) + universal CPU. Accelerator
# wheels (onnxruntime-gpu, onnxruntime-openvino) are installed per-arch by
# install.sh and are mutually exclusive with the base wheel.
-r requirements-core.txt
onnxruntime>=1.17
tokenizers>=0.15
numpy>=1.26.2
```

- [ ] **Step 2: Reference it from `setup/requirements-rag.txt`**

Add this line under the `-r requirements-core.txt` line in `setup/requirements-rag.txt`:

```
-r requirements-onnx.txt
```

- [ ] **Step 3: Verify install resolves**

Run: `pip install -r setup/requirements-onnx.txt`
Expected: onnxruntime, tokenizers, numpy install with no conflict.

- [ ] **Step 4: Commit**

```bash
git add setup/requirements-onnx.txt setup/requirements-rag.txt
git commit -m "build(onnx): add requirements-onnx, reference from rag extras"
```

---

## Phase 1 — Embeddings consumer

### Task 1.1: Rebind-compatibility helpers

**Files:**
- Modify: `api/services/embedding_service.py`
- Test: `tests/test_embedding_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_embedding_service.py`:

```python
from api.services.embedding_service import normalized_family, collection_compatible


def test_normalized_family_strips_qualifiers():
    assert normalized_family("all-MiniLM-L6-v2") == "all-minilm-l6-v2"
    assert normalized_family("sentence-transformers/all-MiniLM-L6-v2") == "all-minilm-l6-v2"
    assert normalized_family("nomic-embed-text:latest") == "nomic-embed-text"


def test_collection_compatible_exact_match():
    meta = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ok, warning = collection_compatible(meta, dict(meta))
    assert ok is True and warning is None


def test_collection_compatible_strict_default_refuses_backend_switch():
    existing = {"backend": "sentence_transformers", "model": "all-MiniLM-L6-v2", "dimension": 384}
    active = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ok, warning = collection_compatible(existing, active)
    assert ok is False


def test_collection_compatible_lenient_allows_same_family(monkeypatch):
    monkeypatch.setenv("ENCLAVE_EMBEDDING_ALLOW_REBIND", "true")
    existing = {"backend": "sentence_transformers", "model": "all-MiniLM-L6-v2", "dimension": 384}
    active = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ok, warning = collection_compatible(existing, active)
    assert ok is True
    assert warning and "quality" in warning.lower()


def test_collection_compatible_lenient_still_refuses_dimension_change(monkeypatch):
    monkeypatch.setenv("ENCLAVE_EMBEDDING_ALLOW_REBIND", "true")
    existing = {"backend": "ollama", "model": "nomic-embed-text", "dimension": 768}
    active = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ok, warning = collection_compatible(existing, active)
    assert ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embedding_service.py -k "normalized_family or collection_compatible" -v`
Expected: FAIL — `ImportError: cannot import name 'normalized_family'`

- [ ] **Step 3: Implement the helpers**

In `api/services/embedding_service.py`, add module-level functions after the imports (before the exception classes, around line 19):

```python
from typing import Optional, Tuple


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
```

(`os` is already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embedding_service.py -k "normalized_family or collection_compatible" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/embedding_service.py tests/test_embedding_service.py
git commit -m "feat(embeddings): rebind-compatibility helpers (strict default + escape)"
```

---

### Task 1.2: ONNX embedding backend arm

**Files:**
- Modify: `api/services/embedding_service.py`
- Test: `tests/test_embedding_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_embedding_service.py`. These tests stub the encoder so no real model downloads:

```python
from unittest.mock import MagicMock
from api.services.embedding_service import EmbeddingService


def _service_with_stubbed_onnx(monkeypatch, ollama_up=False):
    """Build an EmbeddingService in auto mode with Ollama down and ONNX stubbed."""
    fake_encoder = MagicMock()
    fake_encoder.encode.return_value = [[0.1] * 384]
    fake_encoder.active_providers = ["CPUExecutionProvider"]

    # Patch the isolated loader so no real onnxruntime/model is touched.
    monkeypatch.setattr(
        EmbeddingService,
        "_load_onnx_encoder",
        lambda self: setattr(self, "_onnx_instance", fake_encoder),
    )
    ollama = MagicMock()
    ollama.host = "http://127.0.0.1:11434"
    svc = EmbeddingService.__new__(EmbeddingService)  # bypass __init__ probing
    return svc, fake_encoder, ollama


def test_bind_onnx_sets_backend_and_dimension(monkeypatch):
    svc, fake_encoder, ollama = _service_with_stubbed_onnx(monkeypatch)
    svc._ollama = ollama
    svc._onnx_model = "all-MiniLM-L6-v2"
    svc._onnx_instance = None
    ok = svc._bind_onnx(raise_on_fail=True)
    assert ok is True
    assert svc.get_backend() == "onnx"
    assert svc.get_dimension() == 384
    assert svc.embed(["x"]) == [[0.1] * 384]


def test_runtime_info_includes_providers(monkeypatch):
    svc, fake_encoder, ollama = _service_with_stubbed_onnx(monkeypatch)
    svc._ollama = ollama
    svc._onnx_model = "all-MiniLM-L6-v2"
    svc._onnx_instance = None
    svc._bind_onnx(raise_on_fail=True)
    info = svc.runtime_info()
    assert info["providers"] == ["CPUExecutionProvider"]
    # describe() stays pure (collection identity) — no providers key
    assert "providers" not in svc.describe()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embedding_service.py -k "bind_onnx or runtime_info" -v`
Expected: FAIL — `AttributeError: 'EmbeddingService' object has no attribute '_bind_onnx'`

- [ ] **Step 3: Implement the backend arm**

In `api/services/embedding_service.py`:

(a) Add the default-model import near the top (after the existing imports):

```python
from .onnx.models import DEFAULT_ONNX_EMBEDDING_MODEL
```

(b) In `__init__`, add the ONNX model + instance fields (after the `self._st_model` assignment, around line 45):

```python
        self._onnx_model = onnx_model or os.getenv(
            "ONNX_EMBEDDING_MODEL", DEFAULT_ONNX_EMBEDDING_MODEL
        )
        self._onnx_instance = None
```

And add `onnx_model: Optional[str] = None` to the `__init__` signature (after `st_model`).

(c) Add the loader + binder (after `_bind_sentence_transformers`, around line 116):

```python
    def _load_onnx_encoder(self) -> None:
        """Import and instantiate the ONNX encoder. Isolated for test patching."""
        from .onnx.encoder import OnnxTextEncoder

        self._onnx_instance = OnnxTextEncoder(self._onnx_model)

    def _bind_onnx(self, raise_on_fail: bool) -> bool:
        try:
            self._load_onnx_encoder()
            vec = self._onnx_instance.encode(["probe"])[0]
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
```

(d) Add the `onnx` branch to `embed()` (after the `if self._backend == "ollama":` block, around line 129):

```python
        if self._backend == "onnx":
            return self._onnx_instance.encode(texts)
```

(e) Add `runtime_info()` after `describe()` (around line 171):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embedding_service.py -k "bind_onnx or runtime_info" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/embedding_service.py tests/test_embedding_service.py
git commit -m "feat(embeddings): ONNX backend arm + runtime_info provider surfacing"
```

---

### Task 1.3: Wire ONNX into `auto` backend selection

**Files:**
- Modify: `api/services/embedding_service.py`
- Test: `tests/test_embedding_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_embedding_service.py`:

```python
def test_auto_order_prefers_onnx_over_st_when_ollama_down(monkeypatch):
    svc, fake_encoder, ollama = _service_with_stubbed_onnx(monkeypatch)
    svc._ollama = ollama
    svc._onnx_model = "all-MiniLM-L6-v2"
    svc._onnx_instance = None
    svc._st_model = "all-MiniLM-L6-v2"
    svc._backend_choice = "auto"
    svc._backend = None
    svc._model = None
    svc._dimension = None
    svc._st_instance = None

    # Ollama probe fails; sentence-transformers must NOT be reached.
    monkeypatch.setattr(svc, "_bind_ollama", lambda raise_on_fail: False)
    st_called = {"hit": False}

    def _st_should_not_run(raise_on_fail):
        st_called["hit"] = True
        return False

    monkeypatch.setattr(svc, "_bind_sentence_transformers", _st_should_not_run)

    svc._select_backend()
    assert svc.get_backend() == "onnx"
    assert st_called["hit"] is False  # ONNX bound first → ST never tried


def test_explicit_onnx_backend_binds(monkeypatch):
    svc, fake_encoder, ollama = _service_with_stubbed_onnx(monkeypatch)
    svc._ollama = ollama
    svc._onnx_model = "all-MiniLM-L6-v2"
    svc._onnx_instance = None
    svc._backend_choice = "onnx"
    svc._backend = None
    svc._select_backend()
    assert svc.get_backend() == "onnx"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embedding_service.py -k "auto_order_prefers_onnx or explicit_onnx" -v`
Expected: FAIL — `auto` order still falls straight to ST (backend != "onnx"), and explicit `"onnx"` is unhandled.

- [ ] **Step 3: Update `_select_backend()`**

In `api/services/embedding_service.py`, replace the body of `_select_backend()` (around lines 57-68) with:

```python
    def _select_backend(self) -> None:
        if self._backend_choice == "ollama":
            self._bind_ollama(raise_on_fail=True)
        elif self._backend_choice == "onnx":
            self._bind_onnx(raise_on_fail=True)
        elif self._backend_choice == "sentence_transformers":
            self._bind_sentence_transformers(raise_on_fail=True)
        else:  # auto: Ollama → ONNX → sentence-transformers (ST is the failsafe)
            if not self._bind_ollama(raise_on_fail=False):
                if not self._bind_onnx(raise_on_fail=False):
                    if not self._bind_sentence_transformers(raise_on_fail=False):
                        raise EmbeddingBackendUnavailable(
                            f"No embedding backend available. Tried Ollama model "
                            f"'{self._ollama_model}', ONNX model '{self._onnx_model}', "
                            f"and sentence-transformers model '{self._st_model}'."
                        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embedding_service.py -k "auto_order_prefers_onnx or explicit_onnx" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full embedding suite to confirm no regression**

Run: `pytest tests/test_embedding_service.py -v`
Expected: PASS (all — existing Ollama/ST tests unaffected; auto order now has ONNX in the middle)

- [ ] **Step 6: Commit**

```bash
git add api/services/embedding_service.py tests/test_embedding_service.py
git commit -m "feat(embeddings): auto backend order Ollama->ONNX->sentence-transformers"
```

---

### Task 1.4: Rebind-aware collection guard in `document_service`

**Files:**
- Modify: `api/services/document_service.py`
- Test: `tests/test_document_service.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_document_service.py` (create the file if it does not exist; use this import-safe unit test that exercises only the guard logic via a fake collection):

```python
import pytest
from unittest.mock import MagicMock


def _make_doc_service_with_existing(monkeypatch, existing_meta, active_desc):
    """Stand up a DocumentService whose Chroma client returns a collection
    tagged `existing_meta`, with an EmbeddingService reporting `active_desc`."""
    import api.services.document_service as ds

    embed = MagicMock()
    embed.describe.return_value = active_desc

    existing_collection = MagicMock()
    existing_collection.metadata = existing_meta

    client = MagicMock()
    client.get_collection.return_value = existing_collection

    # _init_chroma (after Step 3) reuses self._client when already set, so we
    # inject the fake client directly — no need to patch PersistentClient.
    svc = ds.DocumentService.__new__(ds.DocumentService)
    svc._embed = embed
    svc._chroma_dir = "/tmp/fake-chroma"
    svc._client = client
    svc._collection = None
    return ds, svc, client


def test_init_chroma_strict_refuses_backend_switch(monkeypatch):
    from api.services.embedding_service import EmbeddingBackendMismatch

    existing = {"backend": "sentence_transformers", "model": "all-MiniLM-L6-v2", "dimension": 384}
    active = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ds, svc, client = _make_doc_service_with_existing(monkeypatch, existing, active)
    with pytest.raises(EmbeddingBackendMismatch):
        svc._init_chroma()


def test_init_chroma_lenient_reuses_same_family(monkeypatch):
    monkeypatch.setenv("ENCLAVE_EMBEDDING_ALLOW_REBIND", "true")
    existing = {"backend": "sentence_transformers", "model": "all-MiniLM-L6-v2", "dimension": 384}
    active = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ds, svc, client = _make_doc_service_with_existing(monkeypatch, existing, active)
    svc._init_chroma()
    assert svc._collection is client.get_collection.return_value
```

Note: `_init_chroma` constructs its own `chromadb.PersistentClient`. Refactor (Step 3) makes it reuse `self._client` if already set, so the test's injected client is honored.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_document_service.py -v`
Expected: FAIL — current `_init_chroma` uses exact `existing.metadata != desc` (raises in the lenient case too) and rebuilds its own client.

- [ ] **Step 3: Update `_init_chroma()`**

In `api/services/document_service.py`, update the import (line 22) and `_init_chroma` (lines 96-117):

```python
from .embedding_service import (
    EmbeddingService,
    EmbeddingBackendMismatch,
    collection_compatible,
)
```

```python
    def _init_chroma(self) -> None:
        import chromadb

        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self._chroma_dir))
        desc = self._embed.describe()
        try:
            existing = self._client.get_collection(name=COLLECTION_NAME)
            compatible, warning = collection_compatible(existing.metadata, desc)
            if not compatible:
                raise EmbeddingBackendMismatch(
                    f"Collection '{COLLECTION_NAME}' was created with {existing.metadata}, "
                    f"but EmbeddingService reports {desc}. Restore the original backend, "
                    f"set ENCLAVE_EMBEDDING_ALLOW_REBIND=true to reuse a same-family "
                    f"collection, or delete {self._chroma_dir} to re-ingest."
                )
            if warning:
                logger.warning(warning)
            self._collection = existing
        except Exception as e:
            if isinstance(e, EmbeddingBackendMismatch):
                raise
            self._collection = self._client.create_collection(
                name=COLLECTION_NAME,
                metadata=desc,
            )
            logger.info(
                f"Created ChromaDB collection '{COLLECTION_NAME}' with metadata {desc}"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_document_service.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/document_service.py tests/test_document_service.py
git commit -m "feat(embeddings): rebind-aware collection guard (strict default + escape)"
```

---

### Task 1.5: Phase-1 integration gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full non-e2e suite**

Run: `source venv/bin/activate && pytest tests/ --ignore=tests/e2e --ignore=tests/playwright -q`
Expected: all green. The ONNX substrate is invisible to existing workflows; no prior test regresses.

- [ ] **Step 2: Smoke-test the real encoder (host with internet + onnxruntime)**

Run:
```bash
python -c "
from api.services.architecture import detect_architecture
detect_architecture()
from api.services.onnx.encoder import OnnxTextEncoder
e = OnnxTextEncoder('all-MiniLM-L6-v2')
v = e.encode(['hello world'])
print('dim', len(v[0]), 'providers', e.active_providers)
assert abs(sum(x*x for x in v[0]) ** 0.5 - 1.0) < 1e-4  # unit length
print('OK')
"
```
Expected: prints `dim 384 providers [...]` and `OK`. On Mac, providers include `CoreMLExecutionProvider`; on the AMD box, `['CPUExecutionProvider']`.

- [ ] **Step 3: Commit (if any smoke-fix needed; otherwise skip)**

No code change expected. If the smoke test surfaces a real model-file path mismatch (HF repo layout differs), fix `ONNX_EMBEDDING_MODELS[...]["files"]` and re-run.

---

## Self-Review

**Spec coverage:**
- §2 keystone (`recommended_onnx_providers`) → Tasks 0.1–0.3 ✓
- §3.1 session + CPU-floor fallback → Task 0.6 ✓
- §3.2 model cache + quant-variant pick → Task 0.5 ✓
- §3.3 encoder (pool + normalize) → Task 0.7 ✓
- §3.4 model registry + MiniLM default → Task 0.4 ✓
- §4 consumer (`_bind_onnx`, auto order, `embed`) → Tasks 1.2–1.3 ✓ (note: §4's `describe()`+providers refined to `runtime_info()` — Task 1.2 — to protect collection identity)
- §5 Decision 1 rebind (strict default + escape) → Tasks 1.1, 1.4 ✓
- §5 Decision 2 AMD-first / no vendor probe → Task 0.2 ✓
- §6 error handling (EP fallback, download miss, mismatch) → Tasks 0.5, 0.6, 1.2, 1.4 ✓
- §7 dependencies → Task 0.8 ✓
- §8 testing strategy → tests in every task ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command shows expected output. ✓

**Type consistency:** `OnnxExecutionPlan(providers, quant, provider_options)` consistent across 0.1/0.2/0.3/0.6. `LocalModelPaths(onnx_path, tokenizer_path)` consistent 0.5/0.7. `OnnxTextEncoder(model_name, arch, *, _session, _tokenizer, _dimension, _active_providers)` + `.encode()/.dimension/.active_providers` consistent 0.7/1.2. `collection_compatible(existing, active) -> (bool, Optional[str])` consistent 1.1/1.4. `build_session(model_path, arch) -> (session, active)` consistent 0.6/0.7. ✓

**Deferred (not in this plan, per spec §9):** Intel OpenVINO + CPU-vendor probe; reranker; PII-NER classifier; `/api/system` provider UI; sentence-transformers removal.
