# Architecture-Aware Workflow Orchestration — Design Document

**Status:** Draft v1 · **Author:** Henry Reed · **Date:** 2026-05-19 · **Target release:** 1.3.0 → 1.4.0
**Paired implementation plan:** [2026-05-19-architecture-aware-orchestration-implementation.md](2026-05-19-architecture-aware-orchestration-implementation.md)

---

## Executive summary

Enclave ships on two memory architectures (Apple Silicon unified, Linux + NVIDIA discrete VRAM) and through two deployment surfaces (DMG via py2app, container via docker-compose). The workflow engine today treats them identically — same code path, same eviction defaults, same configuration assumptions. They aren't the same. This design introduces an `Architecture` abstraction (memory model) and an orthogonal `Deployment` abstraction (process and resource model). Detection happens once at startup. Every memory-aware decision dispatches through the abstractions. The default eviction policy is **kill the model after each task completes** — favoring context freshness over residency optimization — and arch-aware logic moves into pre-warming the next step's model in parallel with the current step's inference, so cold-load cost is hidden rather than avoided. Ollama 0.23.4 is the pinned baseline; the implementation surfaces every Ollama-side extensibility hook (keep_alive control, `/api/ps`, `OLLAMA_SCHED_SPREAD`, `options.main_gpu`, `/api/show` for size introspection) without requiring Ollama changes. Net result: predictable behavior across DMG-on-Mac, container-on-Linux-CPU, container-on-Linux-GPU, container-on-Linux-multi-GPU; deployment-appropriate failure handling; observability that distinguishes load cost from inference cost; and an explicit configuration validator that refuses to start under unsafe combinations.

---

## Execution model: sequential by default

**Workflows execute as a sequential chain.** Per operator policy (Henry, 2026-05-19), the composer visualization presents workflows as a chain and the engine treats them that way. Existing DAG schema (`depends_on` arrays) continues to work — the compiler topologically orders into a sequence — but no new optimization or scheduling logic targets parallel execution.

What this means for the architecture-aware design:
- **No concurrency island analysis.** The Phase 4 DAG scheduler reduces to a per-step capacity check; no concurrent-step memory budgeting.
- **At any moment at most one model is loading or resident.** The freshness-default policy combined with sequential execution gives this invariant cleanly.
- **`OLLAMA_SCHED_SPREAD` is no longer required** even on multi-GPU hosts (its purpose was parallel placement). Multi-GPU still helps for warm re-load avoidance via pool-across-cards, but it isn't a parallelism enabler in this design.
- **Phase 5 pre-warm becomes more impactful, not less.** With sequential execution and per-step model eviction, hiding the next-step load behind the current-step inference is the only way to maintain throughput. Pre-warm has nothing competing with it on a multi-GPU host.

## Core design principle: freshness by default

Every task ends with the model evicted. The defaults block sets `keep_alive: "0"` for every step, every workflow, every architecture, every deployment. This is the policy commitment.

**Rationale:**

- **Predictable state.** Every step starts with a fresh runner subprocess. No carryover of allocator state, no risk of subtle KV cache reuse across logically-distinct tasks even on the same model, no debugging "why does this work in isolation but not in sequence."
- **Memory hygiene.** Runners can't accumulate. A 5-step workflow using 5 different models doesn't leave 5 runners resident for 5 minutes after the workflow ends.
- **Observable cost.** When every step pays an explicit cold-load tax, that cost is visible in metrics and can be optimized against. When eviction is opportunistic, the cost is implicit and operators can't see what they're paying.
- **Security-adjacent.** For workflows that handle sensitive context (XSIAM detections, customer artifacts, regulated data), each step starting clean reduces the surface for cross-task state leakage. This isn't a security primitive — it's a posture.

**The cost we're committing to:**

| Deployment × Architecture | Cold load per step | Mitigation |
|---|---|---|
| DMG × `apple_unified` | Sub-second after first load (page cache) | mmap is free; no action needed |
| Container × `cpu_x86` | ~1-2 s for 7-13B models, 10s+ for 70B | Pre-warm during prior step's inference |
| Container × `gpu_nvidia_single` | ~2-3 s PCIe upload per step | Pre-warm on alternate process slot |
| Container × `gpu_nvidia_multi` | Effectively 0 with placement | Pre-warm on free GPU during prior step |

The mitigation strategy makes the default viable on every deployment: pre-warm aggressively so the next step's model is loaded by the time the current step ends. Phase 5 in the implementation plan is no longer "an optimization" — it's the reason the default policy doesn't crater performance.

**Override path:** explicit `keep_alive: "5m"` (or any duration) in step YAML or `defaults` block opts back into residency. Reserved for workflows that genuinely benefit from keeping the same model warm across many short steps (e.g. an interactive multi-turn agent). The default is freshness; performance optimization is opt-in.

---

## Problem statement

Five structural gaps when the same code runs on four deployment-architecture combinations:

1. **No architecture abstraction.** [model_resolver.py](../../api/services/model_resolver.py), [step_executor.py](../../api/services/step_executor.py), [ollama_service.py](../../api/services/ollama_service.py) write a single code path. There's no dispatch layer to say "this arch handles eviction cheaply, that one doesn't."
2. **No deployment abstraction.** The DMG and the container appear identical to the engine. They aren't — different resource visibility (psutil vs cgroup-aware), different storage paths, different Ollama integration shape, different failure modes.
3. **No per-deployment configuration management.** The container relies on docker-compose env vars; the DMG relies on shell env + app preferences. Neither validates that the Ollama daemon environment matches the architecture.
4. **No deliberate eviction.** [ollama_service.py:320](../../api/services/ollama_service.py:320) never sends `keep_alive`. Every step inherits the daemon's 5-minute idle default. Runners accumulate.
5. **No per-context error semantics.** CUDA OOM on NVIDIA, swap-thrash on Mac, OOM-killer on Linux CPU, cgroup OOM in container — same generic exception. The engine retries blindly against the same overloaded daemon.

---

## Goals

- Detect host **architecture** (memory model) at startup.
- Detect host **deployment mode** (DMG / container / host-native) at startup.
- Implement default `keep_alive: "0"` policy with explicit override path.
- Implement per-architecture pre-warming to hide cold-load cost.
- Implement per-architecture DAG scheduling (per-pool budgeting).
- Implement per-deployment configuration validation and storage path resolution.
- Pin Ollama to a specific version (`0.23.4`) and document the feature surface required.
- Make architecture, deployment, and Ollama version first-class in every workflow run record.

## Non-goals

- Cross-architecture failover or workflow migration.
- Custom Ollama builds or fork maintenance.
- Multi-host scheduling (single host only, defers to 2.x).
- Heterogeneous fleet management from a single Enclave instance.
- vLLM, TGI, llama.cpp-direct, or any non-Ollama backend integration.
- Custom CUDA streams, Metal shader work, or memory-page manipulation.

---

## Memory architectures

The four classes the engine recognizes:

| Class | Memory model | Failure mode | Warm re-load class | Placement | Detection signal |
|---|---|---|---|---|---|
| `apple_unified` | Single pool (CPU+GPU share DRAM via Metal) | Swap-thrash (soft degradation) | cheap (sub-second via page cache) | none | `sys.platform == "darwin"` + Apple Silicon CPU |
| `cpu_x86` | Single pool, CPU only | OOM-killer (subprocess kill) | cheap (sub-second via page cache) | none | Linux + no NVML devices |
| `gpu_nvidia_single` | Two pools, one VRAM | CUDA OOM (hard error) | expensive (~2.5 s PCIe) | none | NVML reports 1 GPU |
| `gpu_nvidia_multi` | Two pools, N× VRAM | CUDA OOM per GPU | expensive per GPU | per-GPU affinity + spread | NVML reports N>1 GPUs |

Fallback: `unknown` if detection fails entirely; engine runs in degraded mode (no scheduling, no budgeting, basic eviction).

---

## Deployment architectures

The three modes the engine recognizes — orthogonal to the architecture dimension above:

| Mode | Process model | Resource visibility | Storage root | Ollama reach | Detection signal |
|---|---|---|---|---|---|
| `dmg_native` | py2app bundle on macOS | `psutil` + `vm_stat`; no cgroup; no NVML | `~/Library/Application Support/Enclave/` | `127.0.0.1:11434` (host or bundled) | `sys.frozen == True` AND `sys.platform == "darwin"` |
| `container` | Docker/Podman with sibling Ollama service | cgroup-aware `/sys/fs/cgroup`; NVML if Container Toolkit present | `/app/data/` (bind-mounted volume) | service-name (`http://ollama:11434`) on docker bridge network | `/.dockerenv` exists OR `/proc/1/cgroup` references docker/podman/containerd |
| `host_native` | `python api/main.py` directly on Linux or Mac | full host `psutil`; NVML if available | `./data/` (cwd-relative) | `127.0.0.1:11434` | None of the above |

Why this matters: every memory-aware decision the engine makes depends on **which** memory it can see and **how** it's enforced. A container with a 32 GB cgroup limit on an 96 GB host has access to 32 GB, not 96 — the architecture detector must read cgroup limits, not host totals. A DMG on a 48 GB Mac sees 48 GB and gets squeezed when the OS hands memory to other apps. Bare host_native sees raw hardware.

---

## Architecture × Deployment matrix

| | `dmg_native` | `container` | `host_native` |
|---|---|---|---|
| `apple_unified` | ✅ primary Mac deployment | ⚠️ Docker Desktop on Mac uses Linux VM, unified memory model degrades to cpu_x86 inside the VM | ✅ supported (`python api/main.py` on Mac) |
| `cpu_x86` | ❌ py2app is Mac-only | ✅ primary Linux deployment (current BD790i, MS-01) | ✅ bare-metal Linux |
| `gpu_nvidia_single` | ❌ no NVIDIA on Mac | ✅ container with `--gpus all` + Container Toolkit | ✅ bare-metal Linux + GPU |
| `gpu_nvidia_multi` | ❌ | ✅ container with multi-GPU passthrough | ✅ bare-metal multi-GPU |

The engine **detects** all 6 valid combinations at startup. It **optimizes** for the four primary ones (top-left, container × cpu_x86, container × gpu_*). `host_native` is supported but receives less testing.

Three combinations explicitly **rejected at startup with a clear error**:
- `dmg_native` × `cpu_x86`: impossible (py2app builds Mac binaries).
- `dmg_native` × `gpu_nvidia_*`: impossible (no NVIDIA on Mac).
- `container` × `apple_unified`: Docker Desktop on Mac uses a Linux VM internally, so the container sees `cpu_x86` from inside — log this clearly so operators understand they're not getting unified memory inside containers.

---

## The `Architecture` abstraction

```python
class Architecture(Protocol):
    name: ArchClass
    memory_model: Literal["unified", "discrete"]
    pool_count: int                                 # 1 for unified/cpu/single-gpu; N for multi-gpu
    total_memory_gb: float                          # effective, post-cgroup if container
    per_pool_gb: list[float]                        # per-GPU for nvidia_multi, [total] otherwise
    warm_reload_cost_class: Literal["cheap", "expensive"]
    failure_class: Literal["soft_degradation", "hard_oom", "subprocess_kill"]
    supports_placement: bool
    bandwidth_estimate_gbps: float                  # for load-time estimation

    def snapshot(self) -> PressureSnapshot: ...
    def schedule_ready(self, ready_steps: list[Step]) -> list[ScheduleDecision]: ...
    def feasible(self, island: list[Step]) -> Feasibility: ...
    def classify_error(self, exc: Exception) -> ClassifiedError: ...
    def transition_plan(self, prev_step, next_step) -> TransitionPlan: ...
```

`transition_plan` is the central per-arch behavior under the freshness-by-default policy. It answers: "given that we're going to evict prev_step's model anyway, what should we do to make next_step fast?"

Per-arch implementations differ on **pre-warm strategy**:

- `apple_unified` / `cpu_x86`: pre-warm via no-op generate against next model during current step's inference. Page cache means even an "evicted" model re-mmaps cheaply, so pre-warm is nearly free. Always recommend pre-warm.
- `gpu_nvidia_single`: pre-warm only if next-model load time is estimated to fit inside remaining current-step inference. Measured bandwidth contention — if pre-warm degrades inference throughput >10%, auto-disable.
- `gpu_nvidia_multi`: pre-warm on a free GPU during current step's inference. No contention. Best-case scenario; transitions effectively free.

---

## The `Deployment` abstraction

```python
class Deployment(Protocol):
    mode: DeploymentMode
    storage_root: Path
    ollama_url: str
    ollama_reachable: bool
    resource_limits: ResourceLimits     # cgroup-aware in container, OS-given otherwise
    config_sources: list[ConfigSource]  # where env vars come from

    def effective_memory_gb(self) -> float:           # respects cgroup limits if any
        ...
    def daemon_env(self) -> dict[str, str]:
        ...
    def recommended_env(self, arch: Architecture) -> dict[str, str]:
        ...
    def validate_config(self, arch: Architecture) -> ConfigValidationResult:
        ...
```

Three concrete impls:

- `DmgDeployment` — reads `~/Library/Application Support/Enclave/`, talks to Ollama on `127.0.0.1:11434`, validates against macOS-app config conventions.
- `ContainerDeployment` — reads `/sys/fs/cgroup/memory.max` for effective limit, talks to Ollama at the configured `OLLAMA_HOST` (typically `http://ollama:11434`), validates docker-compose env.
- `HostNativeDeployment` — reads host directly, talks to localhost Ollama, validates whatever env is in the shell.

The interaction: `Architecture` and `Deployment` are detected independently. `Deployment.effective_memory_gb()` informs `Architecture.total_memory_gb` (container cgroup limits trump raw host RAM). The scheduler operates on the effective number.

---

## Dispatch topology

```
                              ┌────────────────────────────────────────────────┐
                              │  api/services/architecture.py                   │
                              │  - detect_architecture() at startup             │
                              │  - 1 Hz PressureSnapshot poller                 │
                              │  - singleton: Architecture.current()            │
                              └──────────────────┬──────────────────────────────┘
                                                 │
                              ┌──────────────────┴──────────────────┐
                              │                                     │
                              ▼                                     ▼
              api/services/deployment.py             api/services/arch_impl/
              - detect_deployment() at startup       ├── unified.py (apple + cpu)
              - singleton: Deployment.current()      ├── nvidia_single.py
              - storage paths, ollama url            └── nvidia_multi.py
              - cgroup-aware limits
                              │                                     │
                              └──────────────┬──────────────────────┘
                                             │
                                             ▼
                       ┌──────────────┬──────┴────────┬──────────────────┐
                       │              │               │                  │
                       ▼              ▼               ▼                  ▼
        eviction_policy.py   scheduler.py   error_handlers.py    config_validator.py
        (default: evict)     (arch-aware    (per-arch +          (per-arch ×
                              per-pool)     per-deployment)       per-deployment)
                       │              │               │                  │
                       └──────────────┴───────┬───────┴──────────────────┘
                                              │
                                              ▼
                                  ollama_service.py · step_executor.py
                                  (arch + deployment plumbing)
```

Two new abstraction services, two new dispatch services, two extended plumbing services. The dispatch services contain no `if mac: ... elif nvidia: ...` — they always go through the abstractions.

---

## Eviction policy

The auto-resolution at workflow compile time:

```python
def resolve_keep_alive(step, next_step, defaults):
    # 1. Explicit step override wins
    if step.keep_alive is not None:
        return step.keep_alive

    # 2. Workflow defaults override the global default
    if defaults.keep_alive is not None and defaults.keep_alive != "auto":
        return defaults.keep_alive

    # 3. The global default. Freshness first.
    return "0"
```

The `"auto"` keyword in `defaults.keep_alive` (or step) is preserved as an opt-in to the older arch-aware cost-optimizing policy, for operators who explicitly want residency optimization. It is no longer the default behavior.

```yaml
defaults:
  keep_alive: "0"              # the new default; same as omitting it entirely
  # keep_alive: "auto"         # opt-in to cost-optimizing policy (deprecated)
  # keep_alive: "5m"           # opt-in to daemon-default residency

steps:
  - id: chatty_agent
    model: qwen2.5:1.5b
    keep_alive: "5m"           # this agent runs many short steps; opt out of evict
```

---

## Pre-warm strategy (the policy's enabler)

Without pre-warm, the freshness default makes every step pay full cold-load cost. Pre-warm hides it.

**Decision tree per step boundary (executed by `arch.transition_plan(prev, next)`):**

```
1. If next_step is None (workflow ends): no pre-warm needed.

2. If prev_step's runtime estimate < next_step's load time estimate:
   No useful overlap possible. Skip pre-warm.

3. If arch == apple_unified or cpu_x86:
   Pre-warm via no-op generate(next_model, prompt="", keep_alive="0").
   Page cache makes it nearly free.

4. If arch == gpu_nvidia_multi:
   Find a GPU with free VRAM for next_model.
   If found, pre-warm on that GPU. No bandwidth contention with prev_step.
   If no free GPU, fall back to single-GPU logic.

5. If arch == gpu_nvidia_single:
   Estimate: would loading next_model during prev_step's inference degrade
   inference throughput?
   If degradation history shows >10% slowdown, skip pre-warm; pay cold load
   at step boundary instead.
   Otherwise pre-warm.
```

**The no-op pre-warm call:**

```python
ollama.generate(
    model=next_model,
    prompt="",                  # empty — Ollama still loads weights
    keep_alive="0",             # match the freshness default
    stream=False,
)
```

This loads the model and immediately schedules eviction at the response. The model is resident for ~milliseconds; that's enough — page cache (Mac/CPU) or VRAM allocator (NVIDIA) keeps the bytes warm-enough for the real call moments later.

**Empirical guard:** `step_executor` measures `eval_count / total_duration` per step per model. If a step that runs concurrent with a pre-warm shows that ratio drop >10% vs. the cached baseline for that model, increment a regression counter. After 3 consecutive regressions for the same arch class, set a runtime flag `disable_predictive_warm: true` and log a telemetry alert.

---

## Per-architecture × per-deployment configuration

The configuration validator at startup checks the Ollama daemon environment against per-architecture-and-deployment recommendations:

### `dmg_native` × `apple_unified`

| Setting | Source | Recommended | Notes |
|---|---|---|---|
| `OLLAMA_HOST` | App preferences | `127.0.0.1:11434` | localhost only |
| `OLLAMA_MAX_LOADED_MODELS` | Ollama Mac app preferences | `3` | with freshness default, this rarely matters |
| `OLLAMA_NUM_PARALLEL` | Ollama Mac app preferences | `1-2` | unified pool, conservative |
| `OLLAMA_KEEP_ALIVE` | Ollama Mac app preferences | `"5m"` (Ollama default) | engine overrides per-step |
| `CUDA_VISIBLE_DEVICES` | n/a | should NOT be set | mismatch error if present |
| `OLLAMA_FLASH_ATTENTION` | optional | `"1"` if Apple Silicon ≥ M2 | inference speedup |
| Storage path | `~/Library/Application Support/Enclave/` | n/a | created at first run |

### `container` × `cpu_x86`

| Setting | Source | Recommended | Notes |
|---|---|---|---|
| `OLLAMA_HOST` | docker-compose env | `http://ollama:11434` | service name |
| `OLLAMA_MAX_LOADED_MODELS` | docker-compose env | `1` | small effective memory likely, big models |
| `OLLAMA_NUM_PARALLEL` | docker-compose env | `1` | conservative on CPU inference |
| `OLLAMA_NUM_THREAD` | docker-compose env | = physical core count | recommended for throughput |
| `OLLAMA_KEEP_ALIVE` | docker-compose env | `"5m"` | engine overrides per-step |
| cgroup memory limit | docker-compose `deploy.resources.limits.memory` | document explicitly | engine reads `/sys/fs/cgroup/memory.max` |
| Volume mount | `/app/data` | bind-mounted | persistence |

### `container` × `gpu_nvidia_single`

| Setting | Source | Recommended | Notes |
|---|---|---|---|
| `OLLAMA_HOST` | docker-compose env | `http://ollama:11434` | |
| `OLLAMA_MAX_LOADED_MODELS` | docker-compose env | `2` | small headroom |
| `OLLAMA_NUM_PARALLEL` | docker-compose env | `1` | KV cache competes with weights in VRAM |
| `CUDA_VISIBLE_DEVICES` | docker-compose env | `"0"` or as desired | |
| `OLLAMA_KEEP_ALIVE` | docker-compose env | `"5m"` | engine overrides |
| Container runtime | docker-compose `runtime: nvidia` | required | for Container Toolkit |
| `--gpus all` flag | docker-compose `deploy.resources.reservations.devices` | required | GPU passthrough |
| `nvidia-smi` from inside container | sanity check | must work | validator checks at startup |

### `container` × `gpu_nvidia_multi`

| Setting | Source | Recommended | Notes |
|---|---|---|---|
| `OLLAMA_SCHED_SPREAD` | docker-compose env | `"1"` | **required for parallelism** |
| `OLLAMA_MAX_LOADED_MODELS` | docker-compose env | `3 × gpu_count` | |
| `OLLAMA_NUM_PARALLEL` | docker-compose env | `1` | let DAG drive parallelism |
| `CUDA_VISIBLE_DEVICES` | docker-compose env | enumerate desired GPUs | e.g. `"0,1"` |
| NVLink | NVML topology detection | informational | engine prefers NVLink-paired GPUs for `same_as` |

### `host_native` × *

Recommendations match the matching container variant, but settings come from shell env / systemd unit / launchd plist instead of docker-compose. Validator surfaces any missing recommended setting as a warning.

---

## Ollama version requirements (pinned: 0.23.4)

The implementation requires every feature below. All present in 0.23.4 (verified by reading `/api/version` from the running container).

| Feature | Used by | Endpoint / parameter | Confirmed in 0.23.4 |
|---|---|---|---|
| Per-request `keep_alive` | Phase 3 eviction policy | `/api/generate` payload `keep_alive` | ✅ |
| Loaded-model listing | Phase 2 observability | `GET /api/ps` | ✅ |
| Model size introspection | Phase 1 pre-warm size cache | `GET /api/show` | ✅ |
| Multi-GPU spread | Phase 5 multi-GPU | `OLLAMA_SCHED_SPREAD=1` env | ✅ |
| Per-request GPU pinning | Phase 5 affinity | `options.main_gpu` per generate | ✅ (best-effort) |
| Max-loaded-models cap | Phase 6 config | `OLLAMA_MAX_LOADED_MODELS` env | ✅ |
| Per-runner concurrency | Phase 6 config | `OLLAMA_NUM_PARALLEL` env | ✅ |
| Load duration in response | Phase 2 observability | `load_duration` field in generate response | ✅ |
| Server version | Phase 1 detector | `GET /api/version` | ✅ |

**Pinning recommendation:** [docker-compose.yml:14](../../docker-compose.yml:14) currently uses `ollama/ollama:latest`. Change to `ollama/ollama:0.23.4` for the implementation plan baseline. Document upgrade procedure separately. Operators running other versions:
- < 0.20: refuse to start (missing `/api/ps`, missing daemon-level features).
- 0.20–0.22: start with warning; some Phase 5 features may degrade.
- 0.23.4+: full feature set supported.
- 0.24+: best-effort forward compat; warn if `/api/version` reports an unknown major.

---

## Error handling philosophy

Each error class has a per-arch detection signature and a per-arch recovery action. The engine classifies first (via `arch.classify_error(exc)`), then dispatches recovery.

**Classification:**

```python
class ClassifiedError(BaseModel):
    error_class: Literal["hardware", "daemon", "memory", "runner", "scheduler", "dag", "config"]
    error_code: str          # snake_case enum like "vram_oom", "unified_swap_thrash"
    arch: str
    deployment: str
    recoverable: bool
    suggested_action: Literal["retry", "evict_and_retry", "abort_step", "abort_workflow"]
    human_message: str
```

**Recovery rules — three levels:**

1. **Engine-level retry** (transient failures): up to `retries` (default 1) for `daemon_timeout`, `ollama_unreachable`, with exponential backoff. Beyond the retry budget, classify as terminal.
2. **Arch-level recovery** (capacity failures): on `vram_oom` (NVIDIA only), evict the LRU non-current model, retry once. On `unified_swap_thrash` (Mac/CPU), pause dispatch for 2 s and re-poll. On `host_oom_killer` (CPU container/host), fail-fast (runner is dead; retrying loads will OOM the same way).
3. **DAG-level policy** (terminal failures): `branch_failure_policy` controls whether one failed step aborts the whole workflow, aborts the branch only, or continues with best-effort propagation of `null` to downstream steps.

The full error matrix is reproduced in the implementation plan; what matters at design level is that **every error carries arch + deployment** so post-mortem analysis can correlate.

---

## Observability surface

Per step (extended `StepResult`):

```
arch: gpu_nvidia_multi
deployment: container
model_load_seconds: 2.34
was_cold_load: true
ollama_version: "0.23.4"
pre_step_pressure: { level: "ok", per_pool: [...] }
post_step_pressure: { level: "warning", per_pool: [...] }
residency_before: { pool_count: 2, pools: [{gpu_id: 0, vram_used: ...}, ...] }
residency_after: { ... }
placement_decision: { gpu_assigned: 1, affinity_requested: "spread" }
pre_warm_fired: true
pre_warm_target_gpu: 0
pre_warm_succeeded: true
errors_encountered: []
```

Per run (extended `WorkflowRun`):

```
arch: gpu_nvidia_multi
deployment: container
ollama_version: "0.23.4"
effective_memory_gb: 160.0
transition_cost_seconds: 0.4         # near-zero on multi-GPU pre-warm
parallelism_efficiency: 1.83          # observed speedup over serial baseline
pressure_events: [
  { timestamp, pool, level, action_taken }
]
config_warnings: []                   # captured at startup, replayed in run
```

Operator-facing: `GET /api/workflows/runs/{id}` returns the full record; UI surfaces transition cost separately from total duration so the distinction between load and inference is visible.

---

## Architecture detection algorithm

```
1. Detect deployment mode:
   if /.dockerenv exists OR /proc/1/cgroup mentions docker/podman/containerd:
     deployment = container
   elif sys.frozen and sys.platform == "darwin":
     deployment = dmg_native
   else:
     deployment = host_native

2. Detect architecture:
   if sys.platform == "darwin":
     if deployment == container:
       # Docker Desktop Linux VM — log a warning, fall through to NVML check
       log("Docker on Mac runs Linux VM; not seeing unified memory")
     else:
       arch = apple_unified
       goto 3
   try:
     pynvml.nvmlInit()
     count = pynvml.nvmlDeviceGetCount()
     if count == 0:
       arch = cpu_x86
     elif count == 1:
       arch = gpu_nvidia_single
     else:
       arch = gpu_nvidia_multi
   except:
     arch = cpu_x86

3. Read effective memory:
   if deployment == container:
     try cgroup v2: /sys/fs/cgroup/memory.max
     try cgroup v1: /sys/fs/cgroup/memory/memory.limit_in_bytes
     fallback: /proc/meminfo
   else:
     psutil.virtual_memory()

4. Validate combination:
   if (arch, deployment) in INVALID_COMBINATIONS:
     log error, refuse to start (STRICT) or degrade (else)

5. Detect Ollama:
   GET /api/version → version string
   if version < 0.20: refuse to start
   if version in [0.20, 0.23): warn about degraded Phase 5
   if version >= 0.23.4: ok

6. Capture daemon env (best-effort):
   if deployment == container:
     read docker inspect on ollama container (if accessible) for env
   else:
     parse OLLAMA_* from os.environ
   for variables Ollama doesn't expose, mark as "unknown"

7. Run config validator:
   compare daemon_env against recommendations[arch][deployment]
   produce warnings + errors
   in STRICT mode, errors halt startup
```

This runs once at startup. Pressure poller runs at 1 Hz thereafter, updating `Architecture.snapshot()`.

---

## Resource accounting per deployment

The number the scheduler uses for "available memory" is **effective**, not raw:

- **DMG / host_native:** `psutil.virtual_memory().total` minus a configurable headroom (default 20% reserved for OS and other apps).
- **Container with cgroup v2:** `min(cgroup memory.max, host total)` minus configurable headroom (default 10% inside container; the cgroup is already the budget).
- **Container without cgroup limit:** falls back to host total minus 10% (Ollama and the app must share; reserve for OS).

The headroom is configurable via `RESOURCE_HEADROOM_PCT` env var or `defaults.resource_headroom_pct` in the workflow YAML. Operator can tune.

GPU VRAM accounting always uses NVML; no headroom adjustment (NVML reports `free` accurately and Ollama itself adds its own internal headroom).

---

## Storage paths per deployment

| Resource | DMG | Container | Host native |
|---|---|---|---|
| Workflow runs | `~/Library/Application Support/Enclave/data/workflows/<run_id>/` | `/app/data/workflows/<run_id>/` | `./data/workflows/<run_id>/` |
| Models | Ollama defaults (`~/.ollama/`) | volume `ollama_data:/root/.ollama` | `~/.ollama/` |
| API keys | `~/Library/Application Support/Enclave/data/config/api_keys.yaml` | `/app/data/config/api_keys.yaml` | `./data/config/api_keys.yaml` |
| Logs | `~/Library/Logs/Enclave/` | stdout (captured by Docker) | stdout / file via config |
| Cache (architecture detection, model sizes) | `~/Library/Caches/Enclave/` | `/app/data/cache/` | `./data/cache/` |

`Deployment.storage_root` exposes the base; subdirectories are derived consistently.

---

## Open questions

1. **`keep_alive: "0"` semantics on Ollama 0.23.4.** Does it evict at response completion (atomic with response write) or at next idle-check tick? Spec assumes atomic; verify in Phase 3 test suite. If non-atomic, the post-step `/api/ps` snapshot will catch the discrepancy and trigger an explicit unload call as a fallback.
2. **Pre-warm regression detection threshold.** 10% slowdown chosen by intuition; needs calibration against real workloads. Make configurable.
3. **Container memory limit detection in podman.** Podman uses cgroup v2 but sometimes via different paths. Phase 1 test should cover.
4. **MIG mode on NVIDIA.** A100/H100 with MIG enabled — engine should see slices as separate GPUs. NVML reports them that way; verify on real hardware in Phase 5 acceptance.
5. **`dmg_native` × Apple Silicon GPU count.** M-series chips have multiple GPU cores but expose one Metal device. Engine treats as `pool_count=1`. Document.
6. **Heterogeneous multi-GPU.** 1× H100 + 1× A100 — scheduler treats uniformly. Defer model-size-aware placement preference to 1.4.x.
7. **Docker Desktop on Mac.** A real edge case (`container × apple_unified` collapses to `container × cpu_x86` inside the VM). Phase 1 logs a warning; should it refuse?

---

## Future work (deferred from 1.3.0)

- **Cross-host scheduling.** Single Enclave instance managing a fleet of Mac and Linux hosts. Requires distributed state and a leader/follower model. → 2.x enterprise track.
- **NVLink-aware placement.** `same_as` affinity preferring NVLink-paired GPUs. Detection exists in Phase 1; scheduler doesn't act on it yet.
- **Heterogeneous-GPU placement.** Prefer bigger GPU for bigger model.
- **Dynamic quantization downgrade.** On unavoidable OOM, fall back from Q4 to Q3 of the same model — requires a model-size catalog and Ollama variant resolution.
- **vLLM/TGI backend.** A different inference engine fundamentally changes the residency/eviction model. Out of scope here; possible architectural extension.

---

## Acceptance criteria (cross-cutting)

The design is "shipped" when:

1. `GET /api/system/architecture` returns the correct `(arch, deployment, ollama_version)` triple on:
   - Dev Mac (apple_unified, dmg_native or host_native, 0.23.4)
   - Container on Linux CPU (cpu_x86, container, 0.23.4)
   - Container on Linux + 1 GPU (gpu_nvidia_single, container, 0.23.4)
   - Container on Linux + N GPUs (gpu_nvidia_multi, container, 0.23.4)
2. Reference workflow `workflows/arch-aware-demo.yaml` runs on all four with deployment-appropriate transition cost, GPU placement (where applicable), and clean error recovery on injected failures.
3. Default `keep_alive: "0"` policy is in effect; every step's post-snapshot shows the model evicted.
4. Pre-warm is fired on every step boundary with a different next-model, and `pre_warm_succeeded` is true ≥80% of the time on each architecture.
5. Configuration validator surfaces misconfigurations at startup with arch- and deployment-appropriate guidance.

These map 1:1 to phase gates in the implementation plan.
