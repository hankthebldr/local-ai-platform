# ONNX Execution Substrate + Embeddings Consumer — Design

> **For Claude:** This is a *design* spec. The task-by-task implementation plan is produced
> separately via `superpowers:writing-plans` and lands in `docs/plans/`. Do not begin
> implementation from this document alone.

**Status:** Approved design (2026-06-02). Awaiting implementation plan.

**Goal:** Introduce **ONNX Runtime as a hardware-portable execution substrate** for Enclave's
encoder/auxiliary model tier, and prove it by adding an **ONNX embeddings backend** to the RAG
pipeline. The substrate selects an execution provider per host from the existing `Architecture`
abstraction, so the same logical model runs optimally on Apple Silicon (CoreML), AMD/x86 CPU
(CPU EP), and — later — NVIDIA (CUDA) and Intel (OpenVINO).

**Non-goals (this design):**
- ONNX as an **LLM generation backend.** Text generation stays on the `Runner` axis
  (Ollama / planned vLLM). This substrate is for *encoder* workloads only — different I/O
  contract (text→vector, pair→score, text→spans), not chat generation.
- The reranker (Phase 2) and PII-NER classifier (Phase 3) consumers. This design ships the
  substrate + embeddings only.
- Removing `sentence-transformers` / `torch`. They are demoted to a last-resort fallback here;
  deletion is a later cleanup once ONNX is proven in the field.
- Intel `OpenVINOExecutionProvider` and the CPU-vendor probe it needs — deferred optimization
  for the secondary MS-01 host (see "Deferred").

**Builds on:**
- [2026-05-19-architecture-aware-orchestration-design.md](../../plans/2026-05-19-architecture-aware-orchestration-design.md)
  — the `Architecture` capability registry this design extends.
- [2026-05-23-gpu-runner-abstraction.md](../../plans/2026-05-23-gpu-runner-abstraction.md)
  — the `Runner` axis. This design deliberately sits *beside* it, not inside it.
- [2026-04-19-rag-pipeline-design.md](2026-04-19-rag-pipeline-design.md) — the
  `EmbeddingService` backend-binding model the new consumer plugs into.

**Tech stack:** Python 3.12+, `onnxruntime>=1.17`, `tokenizers>=0.15`, `numpy`,
`huggingface-hub` (already core). No `torch` at runtime on the ONNX path.

---

## 1. Where this sits — a fourth concept, beside Runner

Enclave detects three orthogonal axes at startup, each a Protocol + singleton:

```
Architecture  ── apple_unified | cpu_x86 | gpu_nvidia_single | gpu_nvidia_multi   (memory model)
Deployment    ── dmg_native | container | host_native                            (process/packaging)
Runner        ── ollama | vllm                                                    (LLM generation backend)
```

The ONNX substrate is **not** a fourth `Runner`. The `Runner` Protocol is shaped entirely around
text generation (`generate`, `generate_stream`, chat messages). Embeddings, reranking and NER are
encoder workloads with a fundamentally different contract. Forcing them through `Runner` would
corrupt an abstraction the gpu-runner design deliberately kept narrow.

Instead, ONNX is an **execution substrate** that encoder *services* consume. It reuses
`Architecture.current()` to choose its execution provider, but lives in its own package and is
invisible to the LLM hot path (`Runner`, `step_executor`, `workflow_engine` are untouched).

```
                    Architecture.current()                       ← existing singleton
                            │
                  recommended_onnx_providers()  ← NEW Protocol method
                            │  OnnxExecutionPlan(providers[], quant, provider_options[])
                            ▼
api/services/onnx/                                               ← NEW package (the substrate)
  session.py     build_session(model_path, arch) → InferenceSession    (EP selection + CPU-floor fallback)
  model_cache.py ensure_model(name) → LocalModelPaths                  (HF download, quant-variant pick)
  encoder.py     OnnxTextEncoder.encode(texts) → List[List[float]]     (tokenize→run→pool→normalize)
  models.py      ONNX_EMBEDDING_MODELS registry                        (name → repo, files, dim, pooling)
                            │
                            ▼
api/services/embedding_service.py   _bind_onnx()                        ← Phase 1 consumer
        auto bind order:  Ollama → ONNX → sentence-transformers
```

---

## 2. The keystone — `recommended_onnx_providers()` on `Architecture`

A new method on the `Architecture` Protocol ([api/services/architecture.py](../../../api/services/architecture.py)),
mirroring the existing `default_keep_alive()` / `transition_plan()` style and the
`recommended_runner()` method the gpu-runner plan adds. This is the single source of
hardware truth for #3 (max ROI per host) and #4 (model/hardware alignment).

```python
class OnnxExecutionPlan(BaseModel):
    """Per-architecture ONNX Runtime execution recipe."""
    providers: List[str]            # ordered preference, e.g. ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    quant: Literal["int8", "fp16", "fp32"]
    provider_options: List[dict]    # parallel to `providers`; per-EP flags (CoreML compute units, etc.)


@runtime_checkable
class Architecture(Protocol):
    ...
    def recommended_onnx_providers(self) -> OnnxExecutionPlan:
        """Ordered ONNX Runtime execution providers + quant for this host.

        CPUExecutionProvider is ALWAYS the final entry — the universal floor.
        The substrate verifies which providers actually activated and logs
        any that fell back (e.g. an accelerator wheel isn't installed)."""
        ...
```

### Provider map (Phase 1 scope)

`cpu_x86` is served by the same `UnifiedArchitecture` class as `apple_unified`
([detect_architecture()](../../../api/services/architecture.py) routes both macOS and Linux-no-NVIDIA
to `UnifiedArchitecture.detect()`), so the impl branches on `self.name`.

| Impl | Branch | `providers` | `quant` | Phase |
|---|---|---|---|---|
| `UnifiedArchitecture` | `name == apple_unified` (M4 Pro) | `[CoreMLExecutionProvider, CPUExecutionProvider]` | `fp16` | **1** |
| `UnifiedArchitecture` | `name == cpu_x86` (**AMD-first** — BD790i) | `[CPUExecutionProvider]` | `int8` | **1** |
| `NvidiaSingleArchitecture` / `NvidiaMultiArchitecture` | — | `[CUDAExecutionProvider, CPUExecutionProvider]` | `fp16` | 1 (code lands; unverified until a GPU host exists) |
| `UnknownArchitecture` | degraded | `[CPUExecutionProvider]` | `int8` | **1** |

**AMD-first rationale:** the BD790i (Ryzen 9 7945HX, 96 GB) is the primary `cpu_x86` target. AMD
has no worthwhile ONNX accelerator EP — `OpenVINOExecutionProvider` is Intel-only, and ROCm-on-ORT
for that iGPU isn't worth the dependency. The plain `CPUExecutionProvider` with int8 quantization
runs fast on Zen4's AVX-512. This is optimal for AMD and a correct floor for Intel, so **Phase 1
needs no CPU-vendor probe.**

---

## 3. Substrate component contracts

### 3.1 `api/services/onnx/session.py`

```python
def build_session(model_path: str, arch: Architecture | None = None) -> tuple[InferenceSession, list[str]]:
    """Build an ORT InferenceSession using the architecture's recommended providers.

    Reads `arch or Architecture.current()`, calls recommended_onnx_providers(),
    and constructs the session. Returns (session, active_providers).

    Resilience: if a requested provider is unavailable in the installed wheel,
    ORT silently drops it. We compare requested vs session.get_providers() and
    log a structured warning naming the EP that fell back. CPUExecutionProvider
    is guaranteed present, so a session ALWAYS builds — a missing accelerator
    wheel degrades to CPU, never fatal.
    """
```

This function is what makes the mutually-exclusive-wheel problem
(`onnxruntime` vs `onnxruntime-gpu` vs `onnxruntime-openvino`) safe: the base `onnxruntime` wheel
already carries CoreML (macOS) + universal CPU, and any richer EP is opportunistic.

### 3.2 `api/services/onnx/model_cache.py`

```python
class LocalModelPaths(BaseModel):
    onnx_path: str        # resolved .onnx weight file (quant-appropriate variant)
    tokenizer_path: str   # tokenizer.json

def ensure_model(name: str, quant: str) -> LocalModelPaths:
    """Resolve an ONNX_EMBEDDING_MODELS entry to local files, downloading on miss.

    Uses huggingface_hub.hf_hub_download into a cache dir (ENCLAVE_ONNX_CACHE,
    else HF_HOME, else platform default). When a repo ships multiple quant
    variants (model.onnx / model_int8.onnx / model_quantized.onnx), picks the
    one matching `quant` from the registry entry's `files` map, falling back to
    fp32 if the requested quant variant is absent.
    """
```

### 3.3 `api/services/onnx/encoder.py`

```python
class OnnxTextEncoder:
    """Text → vector via ONNX Runtime. The ~150–250 lines of owned pipeline."""

    def __init__(self, model_name: str, arch: Architecture | None = None): ...
        # ensure_model → build_session → Tokenizer.from_file
        # records: dimension, model_name, active_providers, pooling strategy

    def encode(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        # tokenize (enable_padding + enable_truncation)
        #   → numpy input_ids / attention_mask [/ token_type_ids if model expects it]
        #   → session.run()
        #   → POOL: mean over tokens × attention_mask  (CLS-pool when the registry entry declares it)
        #   → L2 normalize
        #   → .tolist()

    @property
    def dimension(self) -> int: ...
    @property
    def active_providers(self) -> list[str]: ...
```

### 3.4 `api/services/onnx/models.py` — embedding model registry

ONNX embedding models are referenced here (they are encoders, not the LLM `MODEL_REGISTRY`).

```python
ONNX_EMBEDDING_MODELS = {
    "all-MiniLM-L6-v2": {           # Phase 1 DEFAULT
        "repo": "sentence-transformers/all-MiniLM-L6-v2",
        "files": {"fp32": "onnx/model.onnx", "int8": "onnx/model_quantized.onnx"},
        "dimension": 384,
        "pooling": "mean",
        "query_prefix": None,
    },
    "bge-small-en-v1.5": {          # documented quality-upgrade path (NOT default)
        "repo": "BAAI/bge-small-en-v1.5",
        "files": {"fp32": "onnx/model.onnx", "int8": "onnx/model_quantized.onnx"},
        "dimension": 384,
        "pooling": "cls",
        "query_prefix": "Represent this sentence for searching relevant passages: ",
    },
}
DEFAULT_ONNX_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
```

**Default = `all-MiniLM-L6-v2`.** It is the *exact model* the `sentence-transformers` fallback
already uses, so the ONNX backend is a true drop-in for the torch path being retired:
near-identical vectors, same 384-dim. ST-built collections remain reusable **under the
lenient-rebind escape** (§5) — same model family + dimension; under the strict default a
backend switch still re-indexes. Phase 1 swaps the *runtime*, holding the *model* constant.
Upgrading retrieval quality (→ BGE) is a separate, independently-validated change — never ride a
quality change on a plumbing change.

---

## 4. Phase 1 consumer — `embedding_service.py`

The existing [EmbeddingService](../../../api/services/embedding_service.py) binds one backend at
init (`ollama` | `sentence_transformers` | `auto`). Add a third arm:

```python
def _bind_onnx(self, raise_on_fail: bool) -> bool:
    """Instantiate OnnxTextEncoder, probe with encode(["probe"]), bind on success.
    Sets self._backend = "onnx", self._model, self._dimension, self._onnx_encoder."""
    # self._onnx_model from ONNX_EMBEDDING_MODEL env, default DEFAULT_ONNX_EMBEDDING_MODEL
```

Wiring:
- explicit `backend == "onnx"` → `_bind_onnx(raise_on_fail=True)`
- `auto` order → **Ollama → ONNX → sentence-transformers** (ST is now the failsafe only)
- `embed()` gains an `onnx` branch → `self._onnx_encoder.encode(texts)`
- `describe()` gains an `active_providers` field — surfaces #3/#4 through the existing metadata path

With the default model = MiniLM, ONNX binds before ST in `auto` mode and serves the *same* model
torch-free, so the ST path becomes effectively dead unless `onnxruntime` itself fails to import.

---

## 5. Resolved decisions

### Decision 1 — collection rebind semantics: **strict by default**

Chroma collections are tagged `{backend, model, dimension}` and guarded by the existing
`EmbeddingBackendMismatch`.

- **Default (no env):** active service must match the collection's `{backend, model, dimension}`
  exactly, else raise `EmbeddingBackendMismatch` with an actionable message (re-index instructions).
  This preserves today's behavior.
- **`ENCLAVE_EMBEDDING_ALLOW_REBIND=true`:** match leniently on `{normalized_model_family, dimension}`
  and log a quality-risk warning. *Normalized model family* = the model id stripped of its backend
  and quant qualifiers, so `sentence_transformers/all-MiniLM-L6-v2` and `onnx/all-MiniLM-L6-v2`
  both reduce to `all-MiniLM-L6-v2`. A mismatched **dimension always raises** regardless (hard
  incompatibility).

Rationale: a lenient default risks silent retrieval degradation when query vectors (ONNX) probe
document vectors embedded by a different backend — drawn from slightly different distributions,
miserable to debug. On a single-operator appliance with a local, modest corpus, a one-time
re-index is cheap; silently-worse RAG is not. The lenient escape exists precisely for the
low-risk `sentence_transformers/all-MiniLM-L6-v2/384` → `onnx/all-MiniLM-L6-v2/384` swap (same
model family + dimension, near-identical vectors).

### Decision 2 — Intel/AMD detection: **AMD-first, vendor probe deferred**

`cpu_x86` maps to `[CPUExecutionProvider]/int8` in Phase 1 — optimal for the primary AMD target
(BD790i) and a correct floor for Intel. The Intel `OpenVINOExecutionProvider` branch, and the
`/proc/cpuinfo` `vendor_id` probe it requires inside `UnifiedArchitecture.detect()`, are deferred
to a later phase as a pure optimization for the secondary MS-01.

---

## 6. Error handling

| Condition | Behavior |
|---|---|
| Accelerator wheel absent (`-openvino`/`-gpu` not installed) | `build_session` logs requested-vs-active providers, runs on CPU floor. Non-fatal. |
| Model download failure | `auto` mode → fall through to sentence-transformers; explicit `onnx` mode → raise `EmbeddingBackendUnavailable`. |
| Collection identity/dimension mismatch | Reuse `EmbeddingBackendMismatch` per Decision 1 (strict default, lenient via env). |
| `onnxruntime` import fails entirely | `auto` mode → fall through to ST; explicit → raise. |

---

## 7. Dependencies & packaging

- New `setup/requirements-onnx.txt`: `onnxruntime>=1.17`, `tokenizers>=0.15`, `numpy`.
- `setup/requirements-rag.txt` references it. `sentence-transformers` stays (demoted), so Phase 1
  is fully reversible.
- Accelerator wheels (`onnxruntime-gpu`, `onnxruntime-openvino`) are **opt-in per detected arch**
  via `install.sh`; the base wheel already covers Mac CoreML + universal CPU. The substrate
  degrades to CPU when an accelerator wheel is absent (§6), so a missing wheel is a soft miss.

---

## 8. Testing strategy

Mirrors the existing `_load_*` patch seams (e.g. `_load_sentence_transformer`), so tests run on
any host without real accelerators:

- `tests/test_onnx_session.py` — mock `ort.InferenceSession`; assert the provider plan per mocked
  arch (apple→CoreML, cpu_x86→CPU, nvidia→CUDA, unknown→CPU); assert CPU-floor fallback + warning
  when a requested provider is reported unavailable.
- `tests/test_onnx_encoder.py` — mock `session.run` with a known tensor; assert mean-pool ×
  attention-mask and L2-normalization math; assert `dimension` reporting.
- `tests/test_embedding_service.py` (extend) — `_bind_onnx` binds and reports dim; `auto` order
  picks ONNX before ST when Ollama is down; `EmbeddingBackendMismatch` strict default vs
  `ENCLAVE_EMBEDDING_ALLOW_REBIND` lenient path.

No new heavy CI deps beyond `onnxruntime` + `tokenizers` (both wheels, no torch) — keeps the RAG
suite's "heavy to install" concern from regressing.

---

## 9. Deferred / future phases

| Item | Phase |
|---|---|
| CPU-vendor probe + Intel `OpenVINOExecutionProvider` for MS-01 | 1.x optimization |
| Reranker consumer (CPU cross-encoder, net-new RAG capability) | 2 |
| PII-NER classifier consumer (powers triage redaction) | 3 |
| `/api/system` surfacing of active ONNX providers (Memory tab card) | with Phase 2 |
| Remove `sentence-transformers` / `torch` from the appliance (the dep-shed payoff) | after ONNX proven in field |
| TensorRT EP on NVIDIA; embedding-quality upgrade to BGE | opportunistic |

---

## 10. Rollback story

- `EMBEDDING_BACKEND=ollama` or `=sentence_transformers` → ONNX backend never binds; current
  behavior restored.
- Uninstalling `onnxruntime` → `auto` mode falls through to ST; no code change needed.
- No existing collection is rewritten by adding the backend (strict default refuses to mix), so
  enabling ONNX is non-destructive to existing RAG data.
