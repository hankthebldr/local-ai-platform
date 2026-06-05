# GPU Runner Abstraction — vLLM Backend for Blackwell Workstation

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Use `workflow-engine-expert` subagent for any task touching `api/services/workflow_engine.py`, `step_executor.py`, `workflow_compiler.py`, `eviction_policy.py`, or `prompt_composer.py`.

**Builds on:** [2026-05-19-architecture-aware-orchestration-design.md](2026-05-19-architecture-aware-orchestration-design.md) (the arch×deployment matrix) and [2026-05-19-architecture-aware-orchestration-implementation.md](2026-05-19-architecture-aware-orchestration-implementation.md) (Phases 1–5, shipped in 1.3.0). Read those first for the existing capability registry.

**Goal:** Add a **third orthogonal axis** — `Runner` — alongside `Architecture` and `Deployment`, so Enclave can dispatch to the best inference backend for each host. The first new runner is **vLLM with NVFP4** on `gpu_nvidia_single`; the existing Ollama runner remains the default everywhere else. The architecture impl recommends a runner at startup; the model registry records which runner serves which model; the workflow engine routes through the runner abstraction without caring which backend answered.

**Motivating use case:** A Linux workstation with an **NVIDIA RTX PRO 4000 Blackwell** (24 GB GDDR7, 5th-gen Tensor Cores, native NVFP4) joins the fleet as the dedicated agentic-coding box. Running Ollama on this card leaves ≥3× decode throughput on the table because Ollama cannot exploit NVFP4 or continuous batching. vLLM with `--quantization nvfp4` lets a 30B-class MoE coder (Qwen3-Coder-30B-A3B at ~17 GB) coexist with a 7B FP8 latency companion (~7 GB) inside the 24 GB ceiling, serving multi-file refactor jobs and IDE completions from one box.

**Non-goals:** Multi-GPU runner orchestration (handled in a follow-on for `gpu_nvidia_multi`); fine-tuning workflows; TensorRT-LLM engine builds; replacing Ollama on Apple Silicon, `cpu_x86`, or any deployment where it currently works.

**Pinned baselines:**
- Ollama `0.23.4` (unchanged — see `docs/deployment/ollama-version.md`)
- vLLM `>=0.7.0` (first stable release with NVFP4 + Blackwell SM_120 kernels)
- CUDA `>=12.8` (NVFP4 requires Blackwell `sm_120`); CUDA `13.x` recommended
- NVIDIA driver `>=575` (Blackwell-supporting branch)

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, existing `pynvml` + `psutil`, new optional dep `httpx` for vLLM's OpenAI-compatible client (already present transitively), pytest with new `MockVllmRunner` fixture parallel to existing `MockOllamaService`.

---

## Design Overview

### The third axis

Today Enclave has two orthogonal axes detected at startup, each with a Protocol and a singleton:

```
Architecture     ── apple_unified | cpu_x86 | gpu_nvidia_single | gpu_nvidia_multi
Deployment       ── dmg_native    | container | host_native
```

The Runner becomes the third:

```
Runner           ── ollama | vllm | (future: llama_cpp, tensorrt_llm, sglang)
```

These three combine into an N-way matrix. Not every combination is valid; we maintain an explicit `INVALID_COMBOS` set (mirrors `architecture._check_invalid_combo`). Recommended defaults per architecture:

| Architecture | Default runner | Alternative runners | Why |
|---|---|---|---|
| `apple_unified` | `ollama` | (none for now; `llama_cpp` later) | Ollama Metal path is already well-tuned; no GPU runner ecosystem yet |
| `cpu_x86` | `ollama` | (none) | Ollama CPU GGUF path is the right tool |
| `gpu_nvidia_single` | **`vllm`** (NVFP4 path) | `ollama` (fallback) | NVFP4 + continuous batching ≫ Ollama on Blackwell |
| `gpu_nvidia_multi` | `vllm` (tensor-parallel) | `ollama` | vLLM TP across GPUs; Ollama lacks first-class TP |

**Architecture detection is the authoritative signal for runner selection.** No operator config is required in production — `Architecture.detect()` runs, the impl returns its `recommended_runner()`, the registry picks it up. The `ENCLAVE_PREFERRED_RUNNER=ollama|vllm` env var exists as a development/testing escape hatch only (force-pin a runner to A/B compare, validate fallback paths, etc.). The runtime banner makes the source of the choice explicit: `Runner: vllm@0.7.2 (selected by gpu_nvidia_single; ENCLAVE_PREFERRED_RUNNER unset)`.

**Ollama is the universal fallback.** It is the only runner guaranteed to exist on every supported host (Mac, Linux CPU, Linux+NVIDIA). If the architecture's recommended runner fails its startup `health()` probe — vLLM not installed, port unreachable, NVFP4 weights missing — the runtime degrades silently to Ollama and surfaces a structured warning at `/api/system/health`. Workflows whose required models can be served by Ollama keep running; workflows whose models are vLLM-only refuse to start with a clear validate-time error. This makes the failure mode predictable: **vLLM might not be there, Ollama always is.**

### Runner Protocol

```python
@runtime_checkable
class Runner(Protocol):
    """The capability interface every inference backend satisfies.

    Detected/configured at startup; accessed via Runner.current().
    Multiple Runners can coexist (e.g. ollama on :11434 + vllm on :8001);
    the active one is selected per-model via the registry. Runner.current()
    returns the *preferred* runner for the host; per-step dispatch uses
    RunnerRegistry.for_model(model_id) to pick the right one.
    """

    # ── identity / capabilities ───
    name: RunnerKind                   # "ollama" | "vllm" | ...
    base_url: str                      # OpenAI-compatible endpoint
    supports_keep_alive: bool          # Ollama: True, vLLM: False
    supports_hot_swap: bool            # can we evict-and-load mid-workflow?
    supports_continuous_batching: bool # vLLM/SGLang: True, Ollama: False
    supports_quantizations: list[Quant]  # ["nvfp4", "fp8", "awq_int4", "gguf_q4_k_m", ...]
    version: str

    # ── runtime methods ───
    def list_models(self) -> list[ModelInfo]: ...
    def list_loaded(self) -> list[LoadedModel]: ...
    def generate(self, req: GenerateRequest) -> GenerateResponse: ...
    def generate_stream(self, req: GenerateRequest) -> Iterator[GenerateChunk]: ...
    def load(self, model_id: str) -> LoadResult: ...
    def unload(self, model_id: str) -> UnloadResult: ...
    def health(self) -> RunnerHealth: ...
```

`Ollama` and `vLLM` differ on `load`/`unload` semantics — see "keep_alive reconciliation" below. Both expose the same `generate()` shape; both speak OpenAI-compatible chat completions, so adapters are thin.

### Per-model runner metadata

`MODEL_REGISTRY` in `models/download.py` gains two optional fields per entry:

```python
"qwen3-coder-30b-a3b-nvfp4": {
    "ollama": None,                                # not served by Ollama on this host
    "hf_repo": "nvidia/Qwen3-Coder-30B-A3B-NVFP4", # vLLM pulls from HF
    "runner": "vllm",                              # required runner (or "any")
    "quant": "nvfp4",
    "vram_gb": 17.2,                               # for the feasibility check
    "context_window": 262144,
    "purpose": "Agentic multi-file coding flagship (Blackwell)",
    "tier": "blackwell_workstation",
    # ... existing fields (size_gb, purpose, etc.)
},
```

Backwards compat: every existing entry implicitly has `runner: "ollama"` (the resolver fills it in). No registry entries break.

### keep_alive reconciliation

This is the hardest semantic mismatch and is solved in `eviction_policy.py`, not at every call site.

| | Ollama | vLLM |
|---|---|---|
| Model load trigger | First generate request (auto) | Server start (`vllm serve …`) |
| `keep_alive` granularity | Per-request TTL | None — pinned for server lifetime |
| Unload | `keep_alive: "0"` or `/api/ps` delete | Stop the server process |
| Concurrent models | Up to `OLLAMA_MAX_LOADED_MODELS` | One per server process; multiple servers on different ports OK |

**Resolution:** the existing `eviction_policy.resolve_keep_alive(step, next_step, defaults)` becomes runner-aware:

```python
def resolve_keep_alive(step, next_step, defaults, runner: Runner) -> str | None:
    if not runner.supports_keep_alive:
        return None  # vLLM: server lifetime; engine logs the no-op
    # ... existing logic returns "0", "5m", "auto", etc. for Ollama
```

For vLLM, eviction is achieved by `Runner.unload(model_id)` which the impl maps to "stop the server process for this model" (mode A) or "no-op + log" (mode B — pinned-server mode). The default is **mode B** for vLLM on a single-card workstation: the operator declares which models to serve at startup, the workflow engine validates that all referenced models are reachable, and `keep_alive` becomes advisory. Mode A (managed lifecycle) is a Phase 5 toggle.

### Dispatch topology after the change

```
architecture.py + deployment.py + runner.py   (3 singletons detected at startup)
        ↓                                  ↓
arch_impl/...     deployment_impl/...   runner_impl/ollama.py · runner_impl/vllm.py
        ↓                                  ↓
        └──────────────┬───────────────────┘
                       ↓
        eviction_policy.py (runner-aware)
        scheduler.py
        error_handlers.py
        config_validator.py
                       ↓
        runner_registry.py (model_id → Runner)
                       ↓
        ollama_service.py (now: ollama Runner impl)
        vllm_service.py   (new: vllm  Runner impl)
                       ↓
        step_executor.py · workflow_engine.py (unchanged call-site shape)
```

`OllamaService` is **not removed**. It's adapted to satisfy the `Runner` protocol (Phase 1) — same code, conformant interface. The new `VllmRunner` lives next to it. `ModelResolver` becomes a `RunnerRegistry`-aware shell: given a model id, it returns `(Runner, resolved_model_name)`.

### Phase summary

| Phase | Title | Gate criteria |
|---|---|---|
| 1 | Runner protocol + Ollama adaptation | `Runner` Protocol defined; `OllamaRunner` adapter passes existing tests; no behavior change for current hosts |
| 2 | vLLM runner impl + registry schema | `VllmRunner.generate()` round-trips against a real vLLM server (NVFP4 model); registry entries with `runner: "vllm"` validated |
| 3 | Architecture.recommended_runner() + auto-selection | `gpu_nvidia_single` returns `"vllm"`; CPU/Apple return `"ollama"`; `GET /api/system/runner` returns active runner; env override honored |
| 4 | Runner-aware eviction + scheduling | `eviction_policy.resolve_keep_alive` runner-aware; vLLM steps log `keep_alive: noop`; scheduler respects per-runner concurrency caps; cold-load timing recorded |
| 5 | Pre-warm on vLLM + managed-lifecycle mode | Pre-warm strategy for vLLM (HTTP warm-up vs Ollama's no-op generate); optional managed-lifecycle (spawn/stop server per model) behind `VLLM_MANAGED_LIFECYCLE=true` |
| 6 | Config validator + UI surfacing | `validate_config(arch)` checks vLLM version, NVFP4 driver, weight cache path; Memory tab card surfaces runner + version alongside arch/deployment |

---

## Phase 1: Runner Protocol + Ollama Adaptation

### Task 1.1: Define the `Runner` Protocol

**Files:**
- Create: `api/services/runner.py`
- Create: `tests/test_runner_protocol.py`

**Step 1 — Tests:**

```python
# tests/test_runner_protocol.py
from api.services.runner import (
    RunnerKind, Runner, GenerateRequest, GenerateResponse,
    LoadResult, UnloadResult, RunnerHealth, Quant,
)

def test_runner_kind_enum():
    assert RunnerKind.OLLAMA.value == "ollama"
    assert RunnerKind.VLLM.value == "vllm"

def test_generate_request_shape():
    req = GenerateRequest(model="qwen3", messages=[{"role":"user","content":"hi"}])
    assert req.model == "qwen3"
    assert req.stream is False  # default

def test_runner_protocol_attrs_present():
    # Verifies the Protocol surface — any concrete impl must satisfy these names
    expected = {"name","base_url","supports_keep_alive","supports_hot_swap",
                "supports_continuous_batching","supports_quantizations","version"}
    assert expected <= set(Runner.__annotations__.keys())
```

**Step 2 — Implement:**

`api/services/runner.py` defines: `RunnerKind` enum, `Quant` enum (nvfp4|fp8|awq_int4|gguf_q4_k_m|gguf_q5_k_m|fp16|bf16), `GenerateRequest`/`Response`/`Chunk` Pydantic models matching OpenAI chat completions shape, `LoadResult`/`UnloadResult`/`RunnerHealth`, `LoadedModel` (id, vram_gb, loaded_at), `ModelInfo` (id, family, quant, context_window, size_gb), `Runner` Protocol with attrs + methods listed above, singleton accessor `Runner.current()` parallel to `Architecture.current()` and `Deployment.current()`.

**Step 3 — Verify:**

```bash
pytest tests/test_runner_protocol.py -v
```

---

### Task 1.2: Adapt `OllamaService` to satisfy `Runner`

**Files:**
- Edit: `api/services/ollama_service.py`
- Create: `api/services/runner_impl/__init__.py`
- Create: `api/services/runner_impl/ollama.py`
- Create: `tests/test_ollama_runner_adapter.py`

**Step 1 — Tests:**

`OllamaRunner` wraps the existing `OllamaService`; tests verify the Runner surface (`.name == OLLAMA`, `.supports_keep_alive is True`, `.supports_continuous_batching is False`, `generate()` translates request shape, `unload()` calls the existing `/api/ps` delete path).

**Step 2 — Implement:**

Adapter pattern — `OllamaRunner.__init__(self, service: OllamaService)`. No behavior change in `OllamaService` itself; the adapter exposes the Runner surface and forwards calls. `list_models()` returns the existing `ollama.list_models()` reshaped to `ModelInfo`. `supports_quantizations = [Quant.GGUF_Q4_K_M, Quant.GGUF_Q5_K_M, Quant.GGUF_Q3_K_M]`.

**Step 3 — Verify:**

```bash
pytest tests/test_ollama_runner_adapter.py tests/test_ollama_service.py -v
```

All existing `test_ollama_service.py` tests must still pass.

---

### Task 1.3: Runner registry + ModelResolver migration

**Files:**
- Create: `api/services/runner_registry.py`
- Edit: `api/services/model_resolver.py`
- Edit: `models/download.py` (add `runner` field handling; default to `"ollama"`)
- Create: `tests/test_runner_registry.py`

**Step 1 — Tests:**

Given a registry with `qwen2.5-coder-7b` (runner=ollama) and `qwen3-coder-30b-nvfp4` (runner=vllm), `RunnerRegistry.for_model("qwen2.5-coder-7b")` returns the `OllamaRunner`; `for_model("qwen3-coder-30b-nvfp4")` returns the `VllmRunner`. Missing-runner raises `RunnerNotConfigured`.

**Step 2 — Implement:**

`RunnerRegistry` holds `dict[RunnerKind, Runner]`. `ModelResolver.resolve()` now returns `(Runner, model_name)` instead of `str`. `ROLE_PATTERNS` unchanged. Call sites in `step_executor.py` updated to unpack the tuple. `models/download.py` validation: any entry whose `runner` field is not in the registry → startup warning.

**Step 3 — Verify:**

```bash
pytest tests/test_runner_registry.py tests/test_model_resolver.py -v
```

---

### Phase 1 Gate

Run the full suite on a Mac host with Ollama only:

```bash
source venv/bin/activate
pytest tests/ --ignore=tests/e2e --ignore=tests/playwright -q
```

All currently-passing tests still pass. No new runners configured; `OllamaRunner` is the only `Runner` instance; the abstraction is invisible to existing workflows.

---

## Phase 2: vLLM Runner Implementation

### Task 2.1: `VllmRunner` implementation

**Files:**
- Create: `api/services/runner_impl/vllm.py`
- Create: `tests/test_vllm_runner.py`
- Create: `tests/mocks/mock_vllm_server.py` (FastAPI app mimicking vLLM's OpenAI endpoints)

**Step 1 — Tests (against mock):**

- `list_models()` returns the model the mock advertises at `/v1/models`.
- `generate()` POSTs to `/v1/chat/completions`, parses the response into `GenerateResponse`.
- `generate_stream()` consumes SSE chunks.
- `unload()` in pinned-server mode → returns `UnloadResult(actual="noop", reason="vllm_pinned_server")`.
- `health()` returns `version`, `loaded_models`, `gpu_memory_pct`.

**Step 2 — Implement:**

`VllmRunner(base_url="http://127.0.0.1:8001", model_id="…")`. One Runner instance per vLLM server process. `supports_keep_alive = False`, `supports_continuous_batching = True`, `supports_quantizations = [NVFP4, FP8, AWQ_INT4, FP16, BF16]`. Uses `httpx.AsyncClient` for transport. The server process itself is started outside the engine (operator-managed) in this phase — managed lifecycle is Phase 5.

**Step 3 — Verify:**

```bash
pytest tests/test_vllm_runner.py -v
```

Manual smoke (operator runs on the Blackwell host):

```bash
vllm serve nvidia/Qwen3-Coder-30B-A3B-NVFP4 \
  --quantization nvfp4 \
  --max-model-len 131072 \
  --port 8001 \
  --gpu-memory-utilization 0.78 &

python -c "
from api.services.runner_impl.vllm import VllmRunner
r = VllmRunner(base_url='http://127.0.0.1:8001')
print(r.health())
print(r.generate_sync(model='qwen3-coder-30b-a3b-nvfp4',
                     messages=[{'role':'user','content':'def fib(n):'}]))
"
```

---

### Task 2.2: Blackwell tier in `MODELS.md` + registry

**Files:**
- Edit: `MODELS.md` (new section: "Blackwell Workstation — GPU Tier")
- Edit: `models/download.py` (`MODEL_REGISTRY` entries)

**Step 1 — Doc:**

New section in `MODELS.md` parallel to existing Mac/MS-01/BD790i sections:

```markdown
### Blackwell Workstation (RTX PRO 4000, 24 GB) — Coding Tier

Always-on agentic-coding box. Two models resident: 30B-class MoE coder + 7B
latency companion. Served by vLLM on ports 8001/8002.

| Model ID | HF repo | Quant | VRAM | Port | Purpose |
|---|---|---|---|---|---|
| qwen3-coder-30b-a3b-nvfp4 ⭐ | nvidia/Qwen3-Coder-30B-A3B-NVFP4 | nvfp4 | ~17 GB | 8001 | Flagship: multi-file refactor, agentic loops |
| qwen2.5-coder-7b-fp8 | Qwen/Qwen2.5-Coder-7B-Instruct-FP8 | fp8 | ~7 GB | 8002 | IDE FIM, single-file edits, fast iterations |

Optional swap-in (replaces flagship for reasoning tasks):
| deepseek-r1-distill-qwen-32b-awq | TheBloke/DeepSeek-R1-Distill-Qwen-32B-AWQ | awq_int4 | ~18 GB | 8001 | Design / debugging / spec→code |
```

**Step 2 — Registry entries:**

Add the three entries above to `MODEL_REGISTRY` with the new fields. Include `tier: "blackwell_workstation"` so existing `list-models --tier` CLI filters work.

**Step 3 — Verify:**

```bash
python -m models.download list --tier blackwell_workstation
```

Returns the three new entries; pre-existing tiers unchanged.

---

### Phase 2 Gate

On the Blackwell workstation:
1. `vllm serve` running the NVFP4 flagship on :8001.
2. `python -c "from api.services.runner_impl.vllm import VllmRunner; ..."` returns a real generation.
3. `pytest tests/test_vllm_runner.py -v` green against the mock on any host.

---

## Phase 3: Architecture-Aware Runner Selection

### Task 3.1: Add `recommended_runner()` to Architecture Protocol

**Files:**
- Edit: `api/services/architecture.py` (extend Protocol)
- Edit: `api/services/arch_impl/unified.py` → returns `RunnerKind.OLLAMA`
- Edit: `api/services/arch_impl/nvidia_single.py` → returns `RunnerKind.VLLM` (with `RunnerKind.OLLAMA` as fallback)
- Edit: `api/services/arch_impl/nvidia_multi.py` → returns `RunnerKind.VLLM`
- Edit: `tests/test_architecture_protocol.py`

**Step 1 — Tests:**

```python
def test_apple_unified_recommends_ollama():
    arch = UnifiedArchitecture.detect()  # darwin path
    assert arch.recommended_runner() == RunnerKind.OLLAMA

def test_nvidia_single_recommends_vllm(monkeypatch):
    # mocked nvml fixture
    arch = NvidiaSingleArchitecture.detect()
    assert arch.recommended_runner() == RunnerKind.VLLM
    assert RunnerKind.OLLAMA in arch.fallback_runners()
```

**Step 2 — Implement:**

Each impl returns its `RunnerKind` preference + a `fallback_runners()` list (degraded but still functional). `NvidiaSingleArchitecture.recommended_runner()` returns `VLLM` only if NVFP4 weights for the configured flagship are present in the HF cache; else returns `OLLAMA` with a startup warning ("Blackwell detected but vLLM NVFP4 weights not cached; falling back to Ollama. See docs/blackwell-quickstart.md").

**Step 3 — Verify:**

```bash
pytest tests/test_architecture_protocol.py tests/test_nvidia_single.py -v
```

---

### Task 3.2: Wire runner detection into `api/main.py` startup

**Files:**
- Edit: `api/main.py` (startup sequence)
- Edit: `api/routers/system.py` (new `GET /api/system/runner`)
- Edit: `api/services/runner.py` (`detect_runners()` top-level)
- Edit: `tests/test_system_router.py`

**Step 1 — Tests:**

`GET /api/system/runner` returns `{"active": "vllm", "available": ["vllm", "ollama"], "version": "0.7.2", "base_urls": {...}}`. Env override `ENCLAVE_PREFERRED_RUNNER=ollama` flips `active` to ollama if installed.

**Step 2 — Implement:**

Startup order (after existing `detect_deployment()` / `detect_architecture()`):
1. `detect_runners()` — probe each potentially-available runner's `health()`. Ollama is always probed (universal fallback). vLLM is probed only on architectures whose `recommended_runner()` or `fallback_runners()` includes it (i.e. NVIDIA hosts) AND when `ENCLAVE_VLLM_BASE_URLS` is set (autodiscovery list). Build a `RunnerRegistry` of healthy runners.
2. **Choose active runner — architecture detection is authoritative:**
   - If `ENCLAVE_PREFERRED_RUNNER` is set (escape hatch): use it if present in registry, else hard-fail with a clear error. Log: `Runner: <kind> (FORCED via ENCLAVE_PREFERRED_RUNNER; architecture-recommended was <kind>)`.
   - Else: pick `Architecture.current().recommended_runner()`. If unhealthy/missing, walk `fallback_runners()` in order. If all fail, install Ollama (the universal fallback) and surface a `degraded_runner` warning at `/api/system/health`.
3. Install singleton via `Runner._set_current(active)`.
4. Log banner: `Runner: vllm@0.7.2 (selected by gpu_nvidia_single; ollama also available)` — banner makes the source of the choice explicit so a stuck-on-Ollama operator can immediately see why.

Config keys (env): `ENCLAVE_VLLM_BASE_URLS="http://127.0.0.1:8001,http://127.0.0.1:8002"` enables multi-port vLLM autodiscovery. Absent on a Blackwell host means "vLLM is installed but no servers running yet" — startup logs a hint: `gpu_nvidia_single detected; recommended runner is vllm but ENCLAVE_VLLM_BASE_URLS unset. Falling back to ollama. See docs/blackwell-quickstart.md`.

**Step 3 — Verify:**

```bash
# On Blackwell box with vLLM serving on 8001:
ENCLAVE_VLLM_BASE_URLS=http://127.0.0.1:8001 python api/main.py &
curl -s http://localhost:8000/api/system/runner | jq
# On Mac:
python api/main.py &
curl -s http://localhost:8000/api/system/runner | jq  # {"active":"ollama",...}
```

---

### Phase 3 Gate

- `GET /api/system/runner` returns correct runner on all three host types (Mac, Linux CPU, Linux+Blackwell).
- Env override `ENCLAVE_PREFERRED_RUNNER` honored.
- Startup banner shows runner + version next to arch + deployment.

---

## Phase 4: Runner-Aware Eviction + Scheduling

### Task 4.1: Make `eviction_policy.resolve_keep_alive` runner-aware

**Files:**
- Edit: `api/services/eviction_policy.py`
- Edit: `tests/test_eviction_policy.py`

**Step 1 — Tests:**

- `resolve_keep_alive(step, next_step, defaults, runner=OllamaRunner(...))` returns `"0"` / `"5m"` / etc. (unchanged).
- `resolve_keep_alive(..., runner=VllmRunner(...))` returns `None`.
- Step result records `keep_alive_resolved: null, keep_alive_applied: "noop", reason: "vllm_pinned_server"`.

**Step 2 — Implement:**

Signature change: `resolve_keep_alive(step, next_step, defaults, runner: Runner)`. Early-return `None` if `not runner.supports_keep_alive`. All call sites in `step_executor.py` updated.

**Step 3 — Verify:**

```bash
pytest tests/test_eviction_policy.py tests/test_step_executor.py -v
```

---

### Task 4.2: Scheduler respects runner concurrency caps

**Files:**
- Edit: `api/services/scheduler.py`
- Edit: `tests/test_scheduler.py`

**Step 1 — Tests:**

vLLM Runner exposes `max_concurrent_requests` from server health (`/v1/models` + `health()`). Scheduler defers steps beyond this cap on a single Runner; with continuous batching, this is high (≥128) so the cap rarely bites — test that the cap is respected when artificially set to 2.

**Step 2 — Implement:**

Schedule loop reads `runner.max_concurrent_requests` per dispatch tick; if active in-flight count would exceed, defer with `defer_reason="runner_concurrency_cap"`. Ollama Runner reports `max_concurrent_requests = 1` for legacy behavior (matches today). vLLM Runner reports `≥128` by default (continuous batching).

**Step 3 — Verify:**

```bash
pytest tests/test_scheduler.py -v
```

---

### Task 4.3: Cold-load timing across runners

**Files:**
- Edit: `api/services/step_executor.py` (already records `model_load_seconds`; just generalize)
- Edit: `tests/test_step_executor.py`

vLLM has no per-request load (model is server-pinned), so `model_load_seconds = 0.0` and `was_cold_load = False` always after server warmup. Test asserts this and confirms `runner_kind` is captured on the step result.

---

### Phase 4 Gate

- Run a known workflow on Blackwell box; step results show `runner: "vllm"`, `keep_alive_applied: "noop"`.
- Same workflow on Mac: `runner: "ollama"`, `keep_alive_applied: "0"` (existing behavior).
- Scheduler defers correctly when artificial concurrency cap is exceeded.

---

## Phase 5: Pre-warm on vLLM + Managed Lifecycle (opt-in)

### Task 5.1: vLLM pre-warm strategy

**Files:**
- Edit: `api/services/prewarm.py` (existing — Phase 5b/5c of arch-aware plan)
- Edit: `tests/test_prewarm.py`

For Ollama, pre-warm fires a no-op generate to trigger model load during the previous step. For vLLM in pinned-server mode, the model is already loaded — pre-warm becomes a **lightweight HTTP warm-up** (a single 1-token generate to warm the KV-cache / kernel selection path). This is still measurable as `pre_warm_seconds` in the run record; success criterion: ≤200 ms cost, observable speedup on subsequent first request.

In managed-lifecycle mode (Task 5.2), pre-warm spawns the next model's server *during* current step inference — far more expensive, but hides ~15-30 s cold start.

---

### Task 5.2: Optional managed lifecycle (`VLLM_MANAGED_LIFECYCLE=true`)

**Files:**
- Create: `api/services/runner_impl/vllm_lifecycle.py`
- Edit: `api/services/runner_impl/vllm.py`
- Create: `tests/test_vllm_lifecycle.py`

**Step 1 — Tests:**

In managed mode, `VllmRunner.load(model_id)` spawns a `vllm serve` subprocess with arguments from the registry entry, waits for `/health` to return 200, registers the port. `unload(model_id)` SIGTERMs the process. Tests use a fake subprocess (`unittest.mock.patch("subprocess.Popen")`) and a stubbed health endpoint.

**Step 2 — Implement:**

`VllmLifecycleManager` owns a `dict[model_id → subprocess.Popen + port]`. Port allocation from a pool (8001-8099). On `load()`: pick free port, spawn `vllm serve … --port <p>`, poll `/health` for up to 60 s. On `unload()`: SIGTERM, wait 30 s, SIGKILL fallback. Default off — workflows that pre-declare models work fine in pinned mode; only enable for operators who want Ollama-like hot-swap dynamics.

**Step 3 — Verify:**

```bash
pytest tests/test_vllm_lifecycle.py -v
VLLM_MANAGED_LIFECYCLE=true python api/main.py
# Trigger a workflow that uses two different vLLM models;
# observe spawn/stop in logs.
```

---

### Phase 5 Gate

- Pinned-server mode: warm-up shaves ≥100 ms off first request.
- Managed-lifecycle mode (opt-in): workflow with two different vLLM models runs end-to-end; spawn + stop logs visible; second model's server is up before first model's last step completes (pre-warm success).

---

## Phase 6: Config Validator + UI Surfacing

### Task 6.1: Extend `validate_config(arch)` for vLLM

**Files:**
- Edit: `api/services/config_validator.py`
- Edit: `api/services/deployment_impl/host_native.py` (`recommended_env` adds vLLM keys)
- Edit: `tests/test_config_validator.py`

**Step 1 — Tests:**

On `gpu_nvidia_single + host_native + vllm`, validator checks:
- `nvidia-smi` reports driver ≥ 575
- `vllm --version` ≥ 0.7.0
- `HF_HOME` set (else weights cache balloons in `~/.cache`)
- `VLLM_CACHE_ROOT` aligned with `user_storage_root` from Deployment
- `OLLAMA_*` env vars absent or warned (avoid confusion when both runners live on box)

Each missing/wrong setting → `ConfigIssue` with severity `warning` (most) or `error` (driver below floor).

**Step 2 — Implement:**

New `vllm_recommended_env(arch)` function in `host_native.py`. Validator imports it when active runner is vLLM. Reuses the existing `ConfigIssue` / `ConfigValidationResult` shape — no new types.

**Step 3 — Verify:**

```bash
pytest tests/test_config_validator.py -v
curl -s http://localhost:8000/api/system/health | jq '.config_validation'
```

---

### Task 6.2: Memory tab UI — Runner card

**Files:**
- Edit: `api/static/index.html` (Memory tab; existing Architecture & Deployment card)
- Edit: `tests/playwright/test_memory_tab.py`

Add a third row to the existing card: **Runner: vllm 0.7.2 — supports nvfp4, fp8, awq_int4 — continuous batching: yes — base URL: http://127.0.0.1:8001**. Click-through reveals the loaded models with VRAM usage (from `runner.list_loaded()`). Style matches the existing arch/deployment chips.

---

### Phase 6 Gate

- `/api/system/health` returns a clean validation on a properly-configured Blackwell box.
- Memory tab displays runner alongside arch + deployment.
- A misconfigured box (e.g. driver 555) surfaces a clear error in the UI and at `/api/system/health`.

---

## Out of scope (deliberate)

- **Multi-GPU runner orchestration.** The `gpu_nvidia_multi` arch impl gets `recommended_runner = VLLM` in Phase 3 but full tensor-parallel scheduling across GPUs is a follow-on plan (`2026-Q3-multi-gpu-runner.md`).
- **TensorRT-LLM backend.** Adds 8–13% throughput at the cost of per-model engine builds; revisit when one model is pinned long-term in production.
- **SGLang backend.** Best for shared-prefix workloads (RAG over the Obsidian vault); separate plan when RAG throughput becomes the bottleneck.
- **llama.cpp backend.** Worth considering for Apple Silicon when MLX matures, but Ollama's Metal path remains the default for now.
- **Fine-tuning workflows.** This plan is inference-only.

---

## Operator decisions (resolved 2026-05-23)

1. **Lifecycle mode:** Ship **pinned** as the default. Managed lifecycle exposed as Phase 5 opt-in (`VLLM_MANAGED_LIFECYCLE=true`). The Blackwell box is small enough that 2-3 always-on servers cover the realistic coding working set; pinned mode is simpler, more reliable, and matches production vLLM deployment patterns. Managed is there when an operator's workflow set outgrows the resident-model budget.

2. **Registry shape:** Single `runner:` value per `MODEL_REGISTRY` entry. Shared-name models (e.g. `qwen2.5-coder-7b` served by either runner depending on host) get a top-level `runner_aliases:` block in the registry — a `runner` → `[model_ids]` map that the resolver consults when the same logical model is available via multiple backends.

3. **Co-location + architecture-driven selection:** Both runners installed on hosts that can support them. **The architecture detection is the sole signal for runner selection** — not a separate env-driven choice. The decision tree:

   ```
   Architecture.detect() →
     ├─ apple_unified         → Runner.OLLAMA  (only viable runner; vLLM has no Metal path)
     ├─ cpu_x86               → Runner.OLLAMA  (CPU GGUF is what Ollama is for)
     ├─ gpu_nvidia_single     → Runner.VLLM    (NVFP4 path) — Ollama present as fallback
     └─ gpu_nvidia_multi      → Runner.VLLM    (tensor parallel) — Ollama present as fallback
   ```

   **Ollama is the universal fallback** — self-contained, always installable, always works. If architecture detection lands in `unknown`, or if the recommended runner fails its `health()` probe at startup, the runtime degrades to Ollama silently and surfaces a structured warning in `/api/system/health`. This makes the platform's failure mode predictable: "vLLM might not be there, Ollama always is."

   The `ENCLAVE_PREFERRED_RUNNER` env var becomes an **escape hatch for development/testing only** (e.g. force-pin Ollama on a Blackwell box to compare backends). Production behavior is fully driven by architecture detection. Documented as such in `docs/deployment/runner-selection.md`.

4. **Per-step `runner:` override in workflow YAML:** **Deferred** — see "Ideation" section below for the product-shaped reasoning. Short version: a per-step override is almost always redundant when `model:` → runner mapping in the registry is sound. Add only when a real workflow demonstrates the need.

---

## Ideation — runner selection as a product surface

The deferred question (#4) is really "how does the user *think* about which model serves which step?" — a product question, not just a configuration one. Three layers exist in Enclave today; the goal is for each layer to do its job and no other:

| Layer | What it says | Who writes it | Runner-awareness |
|---|---|---|---|
| Workflow YAML step | "use the coding role" or "use `qwen3-coder-30b-a3b-nvfp4`" | Workflow author (human or skill) | **None** — should be backend-agnostic |
| `ModelResolver` | role → concrete model id, given the host | Engine | **Full** — knows active runner, available models, role patterns |
| Registry entry | `model_id → (runner, quant, vram, hf_repo)` | Operator (via `MODELS.md` + `MODEL_REGISTRY`) | **Full** — declares which runner serves this model on this host |

The product principle: **workflow YAML stays portable across hosts.** A workflow that says `role: coding` runs on:
- Mac dev box → resolver picks `qwen2.5-coder-7b-abliterate` via Ollama
- Blackwell workstation → resolver picks `qwen3-coder-30b-a3b-nvfp4` via vLLM
- MS-01 fallback → resolver picks `qwen2.5-coder-7b-abliterate` via Ollama (smaller VRAM)

No YAML changes. The author thinks in capability ("I need a coder"), the registry encodes deployment reality ("on this host that means *this* model via *this* runner"), the resolver bridges them.

### When per-step `runner:` would actually be useful

Three plausible scenarios — none compelling enough to ship in Phase 1:

1. **Mixed-latency workflows.** A long-form research step (Qwen3-Coder-30B via vLLM, 30 s) followed by a one-token classification step. If the classifier is also a vLLM-served model, vLLM is fine. If you want sub-50ms latency for the classifier and the model fits in spare CPU RAM, you might pin that step to Ollama. **Counter:** put the classifier in the registry as an Ollama-served model. The step says `model: classifier-tiny` and the registry routes it.

2. **A/B benchmarking of runners on the same model.** "Run this prompt against `qwen2.5-coder-7b` via Ollama AND via vLLM-fp8, compare." This is a benchmark scenario, not a production workflow. **Counter:** build a `benchmark_runner` step kind (mirrors existing `parallel`/`loop` composite kinds) rather than a YAML field.

3. **Forced-failover for resilience.** "If vLLM is unhealthy, run this step on Ollama instead." **Counter:** this is what the universal-fallback degradation path already provides at the runner singleton level. A workflow-level retry annotation (`on_runner_failure: degrade`) is a cleaner expression than per-step pinning.

### What the product should expose instead

If, after a quarter of running both runners, real workflows want runner control, the right surfaces (in priority order) are:

1. **Quality-of-service hint at the workflow level**: `defaults.qos: low_latency | high_throughput | reasoning` — the resolver maps QoS class to runner preference. Authors say "I want low latency"; the platform decides Ollama-tiny vs vLLM-batched.
2. **Step-kind composites for benchmarks**: `kind: ab_runner` analogous to existing `kind: parallel` / `kind: loop`. Explicit, structured, observable in the Runs UI.
3. **Workflow-level `on_runner_failure:` annotation**: degrade vs abort. Surfaces the resilience question once, not per-step.

Per-step `runner:` is a last resort — adds a third dimension to YAML when the existing model/role axis already encodes the intent. **Decision: do not add unless a real workflow demands it; if it's added, document it as "for benchmarking and migrations, not production routing."**

---

## Rollback story

Every phase is independently revertable. If vLLM regresses on a host:

1. `unset ENCLAVE_VLLM_BASE_URLS` → vLLM Runner not detected → architecture's `fallback_runners()` kicks in → Ollama becomes active.
2. `ENCLAVE_PREFERRED_RUNNER=ollama` → explicit pin to Ollama regardless of detection.
3. All `MODEL_REGISTRY` entries with `runner: "vllm"` become unresolvable until vLLM returns; existing Ollama entries unaffected.

Workflows referencing only Ollama-served models survive vLLM downtime without modification. The arch-aware DAG validator (Phase 4 of the original plan) refuses to start workflows whose required models have no available runner — surfaces clearly before any step runs.
