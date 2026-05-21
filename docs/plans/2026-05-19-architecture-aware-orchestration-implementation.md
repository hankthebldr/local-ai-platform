# Architecture-Aware Workflow Orchestration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Use `workflow-engine-expert` subagent for any task touching `api/services/workflow_engine.py`, `step_executor.py`, `workflow_compiler.py`, or `model_adapters.py`.

**Paired design doc:** [2026-05-19-architecture-aware-orchestration-design.md](2026-05-19-architecture-aware-orchestration-design.md) — read first for the architectural reasoning and full per-arch × per-deployment matrices.

**Goal:** Make Enclave first-class on its two memory architectures (Apple Silicon unified, Linux + NVIDIA discrete VRAM) **and** its two deployment surfaces (DMG via py2app, container via docker-compose), through orthogonal `Architecture` and `Deployment` abstractions. Default eviction policy is **kill the model after every task** ("freshness by default"); arch-aware logic moves to pre-warming the next model in parallel with the current step's inference, so cold-load cost is hidden rather than avoided.

**Architecture summary:** Two new abstraction services (`architecture.py`, `deployment.py`) detected at startup. Three arch impls (`unified.py`, `nvidia_single.py`, `nvidia_multi.py`). Three deployment impls (`DmgDeployment`, `ContainerDeployment`, `HostNativeDeployment`). Two new dispatch services (`eviction_policy.py`, `scheduler.py`, `error_handlers.py`, `config_validator.py`). Existing services (`ollama_service`, `step_executor`, `workflow_engine`, `workflow_compiler`) extended to dispatch through the abstractions.

**Pinned baseline:** Ollama `0.23.4` (verified by `GET /api/version` against running container). All required features present: per-request `keep_alive`, `/api/ps`, `/api/show`, `OLLAMA_SCHED_SPREAD`, `options.main_gpu`, `OLLAMA_MAX_LOADED_MODELS`, `load_duration` in generate responses. [docker-compose.yml:14](../../docker-compose.yml:14) to be updated from `:latest` to `:0.23.4`.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, `pynvml` (NVIDIA), `psutil`, existing OllamaService, existing inventory router, pytest with arch + deployment mock fixtures.

---

## Design Overview

For the full reasoning, read the [paired design doc](2026-05-19-architecture-aware-orchestration-design.md). What's repeated here is the operational surface the implementation needs to satisfy.

### Memory architecture classes

| Class | Memory model | Failure mode | Warm re-load | Placement |
|---|---|---|---|---|
| `apple_unified` | Single pool (CPU+GPU share DRAM via Metal) | Swap-thrash (soft degradation) | Sub-second (page cache) | N/A |
| `cpu_x86` | Single pool, CPU only | OOM-killer (subprocess kill) | Sub-second (page cache) | N/A |
| `gpu_nvidia_single` | Two pools, one VRAM | CUDA OOM (hard error) | ~2.5 s (PCIe) | N/A |
| `gpu_nvidia_multi` | Two pools, N× VRAM | CUDA OOM per GPU | ~2.5 s per GPU | Per-GPU affinity, spread |

### Deployment modes

| Mode | Process model | Resource visibility | Storage root | Ollama reach |
|---|---|---|---|---|
| `dmg_native` | py2app bundle (macOS) | psutil + vm_stat; no cgroup; no NVML | `~/Library/Application Support/Enclave/` | `127.0.0.1:11434` |
| `container` | Docker/Podman with sibling Ollama | cgroup-aware; NVML if Container Toolkit | `/app/data/` (bind-mount) | `http://ollama:11434` (compose service name) |
| `host_native` | `python api/main.py` directly | full host psutil; NVML if present | `./data/` (cwd-relative) | `127.0.0.1:11434` |

### Default eviction policy

**Global default: `keep_alive: "0"` on every step.** Model evicted at step completion. Implemented in `eviction_policy.resolve_keep_alive()`:

```python
def resolve_keep_alive(step, next_step, defaults):
    if step.keep_alive is not None: return step.keep_alive
    if defaults.keep_alive is not None and defaults.keep_alive != "auto":
        return defaults.keep_alive
    return "0"   # the new default — freshness wins
```

Override path: workflow-level `defaults.keep_alive: "5m"` or step-level `keep_alive: "5m"`. `"auto"` is preserved as an opt-in to the old cost-optimizing policy, but is no longer the default.

### Capability interfaces

```python
class Architecture(Protocol):
    name: ArchClass
    memory_model: Literal["unified", "discrete"]
    pool_count: int
    total_memory_gb: float                    # effective, post-cgroup
    per_pool_gb: list[float]
    warm_reload_cost_class: Literal["cheap", "expensive"]
    failure_class: Literal["soft_degradation", "hard_oom", "subprocess_kill"]
    supports_placement: bool
    bandwidth_estimate_gbps: float

    def snapshot(self) -> PressureSnapshot: ...
    def schedule_ready(self, ready: list[Step]) -> list[ScheduleDecision]: ...
    def feasible(self, island: list[Step]) -> Feasibility: ...
    def classify_error(self, exc: Exception) -> ClassifiedError: ...
    def transition_plan(self, prev_step, next_step) -> TransitionPlan: ...

class Deployment(Protocol):
    mode: DeploymentMode
    storage_root: Path
    ollama_url: str
    ollama_reachable: bool

    def effective_memory_gb(self) -> float: ...          # cgroup-aware
    def daemon_env(self) -> dict[str, str]: ...
    def recommended_env(self, arch) -> dict[str, str]: ...
    def validate_config(self, arch) -> ConfigValidationResult: ...
```

### Dispatch topology

```
architecture.py + deployment.py  (detected at startup, singletons)
                ↓
   arch_impl/unified.py · arch_impl/nvidia_single.py · arch_impl/nvidia_multi.py
   deployment_impl/dmg.py · deployment_impl/container.py · deployment_impl/host.py
                ↓
   eviction_policy.py · scheduler.py · error_handlers.py · config_validator.py
                ↓
   ollama_service.py (plumbing) · step_executor.py (plumbing) · workflow_engine.py
```

### Phase summary

| Phase | Title | Gate criteria |
|---|---|---|
| 1 | Architecture + deployment detection | `GET /api/system/architecture` returns correct `(arch, deployment, ollama_version)` triple on all 4 supported combinations; invalid combinations rejected with clear errors |
| 2 | Architecture-aware observability | Step results carry `arch`, `deployment`, `model_load_seconds`, `was_cold_load`, `pre_warm_*`, arch-specific residency; run summary carries `transition_cost_seconds` |
| 3 | Default-evict policy + per-step `keep_alive` | Default `"0"` applied; explicit overrides honored; post-step `/api/ps` confirms eviction; fallback to explicit unload if Ollama version disagrees on semantics |
| 4 | Architecture-aware DAG scheduling | Multi-GPU workflow parallelizes; single-GPU workflow serializes; cgroup-aware effective memory respected in container; validate-time warnings per arch+deployment |
| 5 | Pre-warm strategies (the policy enabler) | Pre-warm fires at every step boundary with different next-model; ≥80% success rate; bandwidth guard auto-disables on regression; transitions hidden behind inference |
| 6 | Deployment-aware config validator | Per-arch × per-deployment recommendations checked at startup; misconfigurations surface clearly; STRICT mode refuses unsafe combinations; Ollama version validated against `0.23.4+` floor |

---

## Phase 1: Architecture + Deployment Detection

### Task 1.0: Pin Ollama version

**Files:**
- Edit: `docker-compose.yml`
- Edit: `Dockerfile` (if Ollama is referenced)
- Edit: `docs/deployment/ollama-version.md` (new)

**Step 1:** No test (config change).

**Step 2: Implement**

- [docker-compose.yml:14](../../docker-compose.yml:14): change `image: ollama/ollama:latest` → `image: ollama/ollama:0.23.4`.
- Document the pinning rationale in `docs/deployment/ollama-version.md`: lists the required features (per-request `keep_alive`, `/api/ps`, `/api/show`, `OLLAMA_SCHED_SPREAD`, `options.main_gpu`, `OLLAMA_MAX_LOADED_MODELS`, `load_duration` in response, `/api/version`) and the version floor for each.
- Document the upgrade procedure: stop stack, change tag, `docker-compose pull ollama`, `docker-compose up -d`, verify with `/api/version`.

**Step 3: Verify**

```bash
docker-compose pull ollama
docker-compose up -d ollama
curl -s http://localhost:11434/api/version  # should report 0.23.4
```

---

### Task 1.1: Define the `Architecture` and `Deployment` protocols

**Files:**
- Create: `api/services/architecture.py`
- Create: `api/services/deployment.py`
- Create: `tests/test_architecture_protocol.py`
- Create: `tests/test_deployment_protocol.py`

**Step 1: Write the failing tests**

```python
# tests/test_architecture_protocol.py
from api.services.architecture import ArchClass, PressureSnapshot

def test_arch_class_enum_values():
    assert ArchClass.APPLE_UNIFIED.value == "apple_unified"
    assert ArchClass.CPU_X86.value == "cpu_x86"
    assert ArchClass.GPU_NVIDIA_SINGLE.value == "gpu_nvidia_single"
    assert ArchClass.GPU_NVIDIA_MULTI.value == "gpu_nvidia_multi"
    assert ArchClass.UNKNOWN.value == "unknown"

def test_pressure_snapshot_shape():
    snap = PressureSnapshot(
        level="ok",
        per_pool=[{"pool_id": 0, "free_gb": 50.0, "used_gb": 30.0}],
        timestamp=1234567890.0,
    )
    assert snap.level in ("ok", "warning", "critical")
    assert snap.timestamp > 0


# tests/test_deployment_protocol.py
from api.services.deployment import DeploymentMode, ConfigValidationResult

def test_deployment_mode_enum():
    assert DeploymentMode.DMG_NATIVE.value == "dmg_native"
    assert DeploymentMode.CONTAINER.value == "container"
    assert DeploymentMode.HOST_NATIVE.value == "host_native"

def test_config_validation_result_shape():
    result = ConfigValidationResult(
        warnings=[{"code": "missing_env", "message": "..."}],
        errors=[],
    )
    assert result.is_clean is False
    assert result.has_errors is False
```

**Step 2: Implement**

- `api/services/architecture.py`: `ArchClass`, `PressureLevel`, `PressureSnapshot`, `Architecture` Protocol, `ScheduleDecision`, `Feasibility`, `ClassifiedError`, `TransitionPlan` (Pydantic).
- `api/services/deployment.py`: `DeploymentMode` enum, `Deployment` Protocol, `ResourceLimits`, `ConfigSource`, `ConfigValidationResult` (Pydantic). `ConfigValidationResult.is_clean` returns `not warnings and not errors`.

**Step 3: Verify**

```bash
pytest tests/test_architecture_protocol.py tests/test_deployment_protocol.py -v
```

---

### Task 1.2: Implement `unified.py` (Mac + CPU)

**Files:**
- Create: `api/services/arch_impl/__init__.py`
- Create: `api/services/arch_impl/unified.py`
- Create: `tests/mocks/arch/mock_apple_unified.py`
- Create: `tests/mocks/arch/mock_cpu_x86.py`
- Create: `tests/test_arch_unified.py`

**Step 1: Write the failing tests**

```python
# tests/test_arch_unified.py
from tests.mocks.arch.mock_apple_unified import patch_apple_unified
from tests.mocks.arch.mock_cpu_x86 import patch_cpu_x86
from api.services.arch_impl.unified import UnifiedArchitecture

class TestAppleUnified:
    def test_capabilities(self):
        with patch_apple_unified(total_gb=96.0):
            arch = UnifiedArchitecture.detect()
            assert arch.name.value == "apple_unified"
            assert arch.memory_model == "unified"
            assert arch.pool_count == 1
            assert arch.total_memory_gb == 96.0
            assert arch.warm_reload_cost_class == "cheap"
            assert arch.failure_class == "soft_degradation"
            assert arch.supports_placement is False

    def test_snapshot_under_pressure(self):
        with patch_apple_unified(total_gb=96.0, used_gb=88.0, swap_active=True):
            arch = UnifiedArchitecture.detect()
            snap = arch.snapshot()
            assert snap.level == "critical"

class TestCpuX86:
    def test_capabilities_from_proc_meminfo(self):
        with patch_cpu_x86(total_gb=96.0):
            arch = UnifiedArchitecture.detect()
            assert arch.name.value == "cpu_x86"
            assert arch.memory_model == "unified"
            assert arch.failure_class == "subprocess_kill"
```

**Step 2: Implement**

- `UnifiedArchitecture` class implementing the Protocol.
- `detect()` classmethod: checks `sys.platform == "darwin"` to differentiate apple vs cpu; reads `/proc/meminfo` on Linux, `psutil.virtual_memory()` on Mac with `vm_stat` swap supplement.
- `snapshot()`: returns `PressureSnapshot` with level computed per the table in design (pages >90% AND swap activity → critical for apple; MemAvailable <10% for cpu).
- Stub methods `should_evict`, `schedule_ready`, `feasible`, `classify_error`, `recommended_config`, `optimize_transition` raising `NotImplementedError` (filled in later phases).

**Mock layer (`tests/mocks/arch/mock_apple_unified.py`):**

```python
import contextlib
from unittest.mock import patch

@contextlib.contextmanager
def patch_apple_unified(total_gb: float, used_gb: float = 10.0, swap_active: bool = False):
    """Patch sys.platform + psutil + subprocess(vm_stat) to simulate apple_unified."""
    with patch("sys.platform", "darwin"):
        with patch("api.services.arch_impl.unified._read_psutil_memory") as mem:
            mem.return_value = (total_gb * 1024**3, used_gb * 1024**3)
            with patch("api.services.arch_impl.unified._read_vm_stat_swap") as swap:
                swap.return_value = swap_active
                yield
```

(Similar pattern for `mock_cpu_x86.py` patching `/proc/meminfo` reads.)

**Step 3: Verify**

```bash
pytest tests/test_arch_unified.py -v
```

---

### Task 1.3: Implement `nvidia_single.py` and `nvidia_multi.py`

**Files:**
- Create: `api/services/arch_impl/nvidia_single.py`
- Create: `api/services/arch_impl/nvidia_multi.py`
- Create: `tests/mocks/arch/mock_nvidia_single.py`
- Create: `tests/mocks/arch/mock_nvidia_multi.py`
- Create: `tests/test_arch_nvidia.py`

**Step 1: Write the failing tests**

```python
# tests/test_arch_nvidia.py
from tests.mocks.arch.mock_nvidia_single import patch_nvidia_single
from tests.mocks.arch.mock_nvidia_multi import patch_nvidia_multi
from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture
from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture

class TestNvidiaSingle:
    def test_a100_80gb(self):
        with patch_nvidia_single(vram_gb=80.0, name="NVIDIA A100 80GB"):
            arch = NvidiaSingleArchitecture.detect()
            assert arch.name.value == "gpu_nvidia_single"
            assert arch.memory_model == "discrete"
            assert arch.pool_count == 1
            assert arch.total_memory_gb == 80.0
            assert arch.warm_reload_cost_class == "expensive"
            assert arch.failure_class == "hard_oom"
            assert arch.supports_placement is False

    def test_cuda_oom_classification(self):
        with patch_nvidia_single(vram_gb=80.0):
            arch = NvidiaSingleArchitecture.detect()
            err = arch.classify_error(RuntimeError("CUDA out of memory"))
            assert err.error_code == "vram_oom"
            assert err.recoverable is True

class TestNvidiaMulti:
    def test_h100_dual_topology(self):
        with patch_nvidia_multi(
            gpus=[{"vram_gb": 80.0, "name": "H100"}, {"vram_gb": 80.0, "name": "H100"}],
            nvlink_pairs=[(0, 1)],
        ):
            arch = NvidiaMultiArchitecture.detect()
            assert arch.name.value == "gpu_nvidia_multi"
            assert arch.pool_count == 2
            assert arch.total_memory_gb == 160.0
            assert arch.supports_placement is True
            assert (0, 1) in arch.nvlink_topology
```

**Step 2: Implement**

- `NvidiaSingleArchitecture` and `NvidiaMultiArchitecture` classes.
- `detect()` uses `pynvml.nvmlInit()`; `nvmlDeviceGetCount()` differentiates single vs multi.
- For each GPU collect: `name`, `vram_total`, `vram_free`, `pcie_gen`, `compute_capability`, `mig_mode`.
- Multi-GPU additionally collects NVLink adjacency via `nvmlDeviceGetNvLinkState`.
- `snapshot()`: NVML `nvmlDeviceGetMemoryInfo` for each GPU; level = critical if any GPU <10% free.
- `classify_error`: pattern-match Ollama error responses for "CUDA out of memory", "cudaErrorMemoryAllocation", driver disconnect, etc.
- Stub remaining methods.

**Step 3: Verify**

```bash
pytest tests/test_arch_nvidia.py -v
```

---

### Task 1.4: Top-level detection + singleton accessor

**Files:**
- Edit: `api/services/architecture.py`
- Create: `tests/test_architecture_detection.py`

**Step 1: Write the failing test**

```python
# tests/test_architecture_detection.py
from api.services.architecture import detect_architecture, Architecture
from tests.mocks.arch.mock_apple_unified import patch_apple_unified
from tests.mocks.arch.mock_nvidia_multi import patch_nvidia_multi
from tests.mocks.arch.mock_nvidia_unavailable import patch_no_nvidia

def test_detection_apple():
    with patch_apple_unified(total_gb=48.0):
        arch = detect_architecture()
        assert arch.name.value == "apple_unified"

def test_detection_nvidia_multi():
    with patch_nvidia_multi(gpus=[{"vram_gb": 80.0}, {"vram_gb": 80.0}]):
        arch = detect_architecture()
        assert arch.name.value == "gpu_nvidia_multi"

def test_detection_no_nvidia_falls_back_to_cpu():
    with patch_no_nvidia():
        arch = detect_architecture()
        assert arch.name.value == "cpu_x86"

def test_singleton_accessor():
    arch1 = Architecture.current()
    arch2 = Architecture.current()
    assert arch1 is arch2
```

**Step 2: Implement**

- `detect_architecture()` function with the decision tree from the design overview.
- `Architecture.current()` classmethod backed by a module-level singleton populated at first call (or explicit `set_current` for tests).
- Module-level `_pressure_poller_task` that runs `arch.snapshot()` at 1 Hz when the FastAPI app is alive (use FastAPI startup/shutdown lifecycle).

**Step 3: Verify**

```bash
pytest tests/test_architecture_detection.py -v
```

---

### Task 1.4b: Implement deployment impls (DMG, Container, HostNative)

**Files:**
- Create: `api/services/deployment_impl/__init__.py`
- Create: `api/services/deployment_impl/dmg.py`
- Create: `api/services/deployment_impl/container.py`
- Create: `api/services/deployment_impl/host_native.py`
- Create: `tests/mocks/deployment/mock_dmg.py`
- Create: `tests/mocks/deployment/mock_container.py`
- Create: `tests/mocks/deployment/mock_host_native.py`
- Create: `tests/test_deployment_impls.py`

**Step 1: Write the failing tests**

```python
# tests/test_deployment_impls.py
from tests.mocks.deployment.mock_dmg import patch_dmg
from tests.mocks.deployment.mock_container import patch_container
from tests.mocks.deployment.mock_host_native import patch_host_native

class TestDmgDeployment:
    def test_capabilities(self):
        with patch_dmg(home="/Users/test"):
            from api.services.deployment_impl.dmg import DmgDeployment
            d = DmgDeployment.detect()
            assert d.mode.value == "dmg_native"
            assert str(d.storage_root) == "/Users/test/Library/Application Support/Enclave"
            assert d.ollama_url == "http://127.0.0.1:11434"
            assert d.effective_memory_gb() > 0   # via psutil

    def test_dmg_recommended_env_no_cuda(self):
        from api.services.architecture import ArchClass
        from tests.mocks.arch.mock_apple_unified import patch_apple_unified
        with patch_dmg(), patch_apple_unified(total_gb=48.0):
            from api.services.deployment_impl.dmg import DmgDeployment
            from api.services.arch_impl.unified import UnifiedArchitecture
            d = DmgDeployment.detect()
            arch = UnifiedArchitecture.detect()
            env = d.recommended_env(arch)
            assert "CUDA_VISIBLE_DEVICES" not in env or env["CUDA_VISIBLE_DEVICES"] is None
            assert env["OLLAMA_HOST"] == "127.0.0.1:11434"

class TestContainerDeployment:
    def test_capabilities_with_cgroup_v2(self):
        # cgroup memory.max = 32 GB on a 96 GB host
        with patch_container(cgroup_memory_max=32 * 1024**3, host_memory=96 * 1024**3):
            from api.services.deployment_impl.container import ContainerDeployment
            d = ContainerDeployment.detect()
            assert d.mode.value == "container"
            assert d.effective_memory_gb() == 32.0   # cgroup wins
            assert d.storage_root.as_posix() == "/app/data"
            assert "ollama" in d.ollama_url

    def test_container_without_cgroup_limit_falls_back_to_host(self):
        with patch_container(cgroup_memory_max=None, host_memory=96 * 1024**3):
            from api.services.deployment_impl.container import ContainerDeployment
            d = ContainerDeployment.detect()
            # 10% headroom inside container, so 86.4 GB
            assert d.effective_memory_gb() == pytest.approx(86.4, abs=0.1)

class TestHostNativeDeployment:
    def test_host_native_uses_cwd_storage(self):
        with patch_host_native(cwd="/home/test/enclave"):
            from api.services.deployment_impl.host_native import HostNativeDeployment
            d = HostNativeDeployment.detect()
            assert d.mode.value == "host_native"
            assert d.storage_root.as_posix() == "/home/test/enclave/data"
```

**Step 2: Implement**

- `DmgDeployment.detect()`:
  - `mode = dmg_native`
  - `storage_root = Path.home() / "Library/Application Support/Enclave"` (creates if missing)
  - `ollama_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")`
  - `effective_memory_gb()`: `psutil.virtual_memory().total / 1024**3 * 0.80` (20% headroom for OS)
  - `daemon_env()`: parse `OLLAMA_*` from `os.environ`
  - `recommended_env(arch)`: per-arch dict; never sets `CUDA_VISIBLE_DEVICES`
- `ContainerDeployment.detect()`:
  - `mode = container`
  - `storage_root = Path("/app/data")`
  - `ollama_url = os.environ.get("OLLAMA_HOST", "http://ollama:11434")`
  - `effective_memory_gb()`:
    - read `/sys/fs/cgroup/memory.max` (cgroup v2) — if `"max"`, use host fallback
    - read `/sys/fs/cgroup/memory/memory.limit_in_bytes` (cgroup v1) — if max-int, use host fallback
    - else use cgroup value
    - apply 10% headroom (cgroup is already a constraint)
  - `daemon_env()`: try `/api/show` introspection first, fall back to `os.environ`
- `HostNativeDeployment.detect()`:
  - `mode = host_native`
  - `storage_root = Path.cwd() / "data"`
  - `ollama_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")`
  - `effective_memory_gb()`: psutil with 20% headroom

**Mock layers:**

```python
# tests/mocks/deployment/mock_container.py
import contextlib
from unittest.mock import patch, mock_open

@contextlib.contextmanager
def patch_container(cgroup_memory_max=None, host_memory=32*1024**3):
    """Patch /proc + /sys + /.dockerenv to simulate container."""
    with patch("os.path.exists") as p_exists:
        p_exists.side_effect = lambda p: p == "/.dockerenv" or p.startswith("/sys/fs/cgroup")
        with patch("api.services.deployment_impl.container._read_cgroup_memory_max") as r:
            r.return_value = cgroup_memory_max
            with patch("psutil.virtual_memory") as vm:
                vm.return_value.total = host_memory
                yield
```

**Step 3: Verify**

```bash
pytest tests/test_deployment_impls.py -v
```

---

### Task 1.4c: Top-level deployment detection + invalid-combo guards

**Files:**
- Edit: `api/services/deployment.py`
- Edit: `api/services/architecture.py`
- Edit: `tests/test_architecture_detection.py`

**Step 1: Write the failing tests**

```python
def test_detect_deployment_container_via_dockerenv():
    with patch("os.path.exists", lambda p: p == "/.dockerenv"):
        from api.services.deployment import detect_deployment
        d = detect_deployment()
        assert d.mode.value == "container"

def test_detect_deployment_dmg_via_sys_frozen():
    with patch("sys.frozen", True, create=True), patch("sys.platform", "darwin"):
        with patch("os.path.exists", return_value=False):
            from api.services.deployment import detect_deployment
            d = detect_deployment()
            assert d.mode.value == "dmg_native"

def test_invalid_combo_dmg_with_nvidia_rejected():
    # Mac + NVIDIA = impossible; refuse
    from api.services.architecture import detect_architecture
    with patch_dmg(), patch_nvidia_single(vram_gb=80.0):
        with pytest.raises(RuntimeError, match="invalid arch×deployment"):
            detect_architecture(strict=True)

def test_docker_desktop_on_mac_logs_warning(caplog):
    # container on Mac sees Linux VM → cpu_x86; should warn loudly
    with patch_container(), patch("sys.platform", "darwin"):
        from api.services.architecture import detect_architecture
        arch = detect_architecture()
        assert arch.name.value == "cpu_x86"
        assert "Docker on Mac" in caplog.text
```

**Step 2: Implement**

In `deployment.py`:

```python
def detect_deployment() -> Deployment:
    if os.path.exists("/.dockerenv") or _is_in_container_cgroup():
        return ContainerDeployment.detect()
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        return DmgDeployment.detect()
    return HostNativeDeployment.detect()

def _is_in_container_cgroup() -> bool:
    try:
        with open("/proc/1/cgroup") as f:
            content = f.read()
        return any(x in content for x in ("docker", "podman", "containerd"))
    except (FileNotFoundError, PermissionError):
        return False
```

In `architecture.py`, add validation:

```python
INVALID_COMBOS = {
    (ArchClass.GPU_NVIDIA_SINGLE, DeploymentMode.DMG_NATIVE),
    (ArchClass.GPU_NVIDIA_MULTI, DeploymentMode.DMG_NATIVE),
    (ArchClass.CPU_X86, DeploymentMode.DMG_NATIVE),  # py2app is mac-only
}

def detect_architecture(strict: bool = False) -> Architecture:
    deployment = Deployment.current()
    # Apple-platform short-circuit, BUT respect container-on-mac
    if sys.platform == "darwin" and deployment.mode != DeploymentMode.CONTAINER:
        return UnifiedArchitecture.detect(deployment)
    if sys.platform == "darwin" and deployment.mode == DeploymentMode.CONTAINER:
        logger.warning("Docker on Mac runs Linux VM; not seeing unified memory")
        # fall through to NVML / cpu_x86 detection
    # ... rest of the decision tree
    arch = _decide_arch_from_nvml()
    if (arch.name, deployment.mode) in INVALID_COMBOS:
        msg = f"invalid arch×deployment: {arch.name.value} × {deployment.mode.value}"
        if strict:
            raise RuntimeError(msg)
        logger.error(msg)
        return UnknownArchitecture()
    return arch
```

**Step 3: Verify**

```bash
pytest tests/test_architecture_detection.py -v -k "deployment or invalid_combo or docker"
```

---

### Task 1.4d: Ollama version probe

**Files:**
- Edit: `api/services/ollama_service.py`
- Edit: `api/services/architecture.py`
- Edit: `tests/test_ollama_service.py`

**Step 1: Write the failing test**

```python
def test_ollama_version_probe():
    with patch("requests.get") as g:
        g.return_value.json.return_value = {"version": "0.23.4"}
        g.return_value.raise_for_status = lambda: None
        from api.services.ollama_service import OllamaService
        v = OllamaService().get_version()
        assert v == "0.23.4"

def test_arch_detection_rejects_old_ollama():
    with patch("api.services.ollama_service.OllamaService.get_version", return_value="0.15.0"):
        with pytest.raises(RuntimeError, match="Ollama version 0.15.0 below floor"):
            detect_architecture(strict=True)

def test_arch_detection_warns_on_intermediate_ollama(caplog):
    with patch("api.services.ollama_service.OllamaService.get_version", return_value="0.21.0"):
        arch = detect_architecture()
        assert "Phase 5 features may degrade" in caplog.text
```

**Step 2: Implement**

- `OllamaService.get_version()` → `GET /api/version`, returns version string or `None` on failure.
- In `detect_architecture()`, call `OllamaService(deployment.ollama_url).get_version()`:
  - `None` (unreachable): warn, mark `ollama_reachable: false` on the deployment.
  - `< "0.20"`: refuse to start (STRICT) or run in degraded mode.
  - `[0.20, 0.23.4)`: warn about Phase 5 degradation.
  - `>= "0.23.4"`: ok.
  - `>= "1.0"` or unknown major: warn forward-compat unknown.

**Step 3: Verify**

```bash
pytest tests/test_ollama_service.py -v -k version
pytest tests/test_architecture_detection.py -v -k ollama
```

---

### Task 1.5: Wire detection into app startup + add system router

**Files:**
- Edit: `api/main.py`
- Create: `api/routers/system.py`
- Create: `tests/test_system_router.py`

**Step 1: Write the failing test**

```python
# tests/test_system_router.py
from fastapi.testclient import TestClient
from api.main import app
from tests.mocks.arch.mock_nvidia_multi import patch_nvidia_multi
from tests.mocks.deployment.mock_container import patch_container

def test_get_architecture_returns_triple():
    with patch_container(), patch_nvidia_multi(gpus=[{"vram_gb": 80.0}, {"vram_gb": 80.0}]):
        client = TestClient(app)
        r = client.get("/api/system/architecture")
        assert r.status_code == 200
        body = r.json()
        assert body["arch"]["name"] == "gpu_nvidia_multi"
        assert body["arch"]["pool_count"] == 2
        assert body["deployment"]["mode"] == "container"
        assert body["ollama"]["version"] == "0.23.4"
        assert body["ollama"]["reachable"] is True

def test_get_pressure():
    client = TestClient(app)
    r = client.get("/api/system/pressure")
    assert r.status_code == 200
    body = r.json()
    assert body["level"] in ("ok", "warning", "critical")
    assert "per_pool" in body

def test_get_deployment_specific():
    client = TestClient(app)
    r = client.get("/api/system/deployment")
    body = r.json()
    assert "mode" in body
    assert "storage_root" in body
    assert "effective_memory_gb" in body

def test_post_refresh():
    client = TestClient(app)
    r = client.post("/api/system/architecture/refresh")
    assert r.status_code == 200
```

**Step 2: Implement**

- `api/routers/system.py`:
  - `GET /api/system/architecture` → returns combined `{arch, deployment, ollama}` triple.
  - `GET /api/system/deployment` → deployment-only details (storage paths, ollama_url, effective memory).
  - `GET /api/system/pressure` → most recent pressure snapshot.
  - `POST /api/system/architecture/refresh` → re-runs detection + restarts pressure poller.
- `api/main.py`:
  - On startup: call `detect_deployment()` then `detect_architecture()`, log banner like:
    ```
    🖥️  Deployment: container (cgroup-limited to 96 GB)
    🧠 Architecture: gpu_nvidia_multi (2× H100 80GB, NVLink)
    🦙 Ollama: 0.23.4 (reachable at http://ollama:11434)
    ```
  - If `(arch, deployment)` is in INVALID_COMBOS and `STRICT_ARCH_DETECTION=true`: SystemExit.
  - Otherwise log error and continue in degraded mode.
  - Register the system router.
  - Start pressure poller as a background task.

**Step 3: Verify**

```bash
pytest tests/test_system_router.py -v
python api/main.py &
curl -s http://localhost:8000/api/system/architecture | python3 -m json.tool
kill %1
```

---

### Phase 1 Gate

```bash
pytest tests/test_architecture_*.py tests/test_arch_*.py tests/test_deployment_*.py tests/test_system_router.py -v
```

Expected: all green. Manual verification:

**On dev Mac (`host_native` × `apple_unified`):**
```bash
python api/main.py &
curl -s http://localhost:8000/api/system/architecture | jq
# expect: arch.name=apple_unified, deployment.mode=host_native, ollama.version=0.23.4
kill %1
```

**In running container (`container` × `cpu_x86`):**
```bash
docker-compose up -d
KEY="sk-first-run-master-..."
curl -s -H "Authorization: Bearer $KEY" http://localhost:8000/api/system/architecture | jq
# expect: arch.name=cpu_x86, deployment.mode=container, deployment.effective_memory_gb=<cgroup-limited value>
```

**Invalid-combo rejection:**
```bash
# Simulate: build DMG, run on a hypothetical Mac with mocked nvidia → must refuse to start
STRICT_ARCH_DETECTION=true python api/main.py
# expect: SystemExit with "invalid arch×deployment" message
```

---

## Phase 2: Architecture-Aware Observability

### Task 2.1: Extend StepResult schema with arch-specific fields

**Files:**
- Edit: `api/models/workflow_models.py`
- Edit: `tests/test_workflow_models.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_workflow_models.py
def test_step_result_arch_observability_fields():
    result = StepResult(
        step_id="extract",
        status="completed",
        model_used="llama3.3:70b",
        duration_seconds=12.5,
        token_count={"total_tokens": 1500},
        model_load_seconds=2.3,
        was_cold_load=True,
        arch="gpu_nvidia_single",
        residency_before={"pool_count": 1, "pools": [{"vram_used_gb": 0.0}]},
        residency_after={"pool_count": 1, "pools": [{"vram_used_gb": 42.0}]},
        placement_decision={"gpu_assigned": 0},
        pre_step_pressure={"level": "ok"},
        post_step_pressure={"level": "warning"},
    )
    assert result.was_cold_load is True
    assert result.model_load_seconds == 2.3
```

**Step 2: Implement**

Add fields to `StepResult`:

```python
model_load_seconds: Optional[float] = None
was_cold_load: Optional[bool] = None
arch: Optional[str] = None
residency_before: Optional[dict] = None
residency_after: Optional[dict] = None
placement_decision: Optional[dict] = None
pre_step_pressure: Optional[dict] = None
post_step_pressure: Optional[dict] = None
errors_encountered: list[dict] = Field(default_factory=list)
```

Add to `WorkflowRun`:

```python
arch: Optional[str] = None
transition_cost_seconds: Optional[float] = None
parallelism_efficiency: Optional[float] = None
pressure_events: list[dict] = Field(default_factory=list)
```

**Step 3: Verify**

```bash
pytest tests/test_workflow_models.py -v
```

---

### Task 2.2: Capture `load_duration` from Ollama response

**Files:**
- Edit: `api/services/ollama_service.py`
- Edit: `tests/test_ollama_service.py`

**Step 1: Write the failing test**

```python
def test_generate_returns_load_duration():
    # Mock Ollama response with load_duration field
    mock_response = {
        "response": "hello",
        "total_duration": 2_500_000_000,    # ns
        "load_duration": 1_800_000_000,
        "eval_count": 50,
        "prompt_eval_count": 20,
    }
    with patch("requests.post") as p:
        p.return_value.json.return_value = mock_response
        p.return_value.raise_for_status = lambda: None
        result = OllamaService().generate("llama3.3:70b", "test prompt")
        assert result["load_duration_seconds"] == pytest.approx(1.8, abs=0.01)
        assert result["was_cold_load"] is True   # load_duration > 0.5s

def test_generate_warm_load():
    mock_response = {
        "response": "hello",
        "total_duration": 500_000_000,
        "load_duration": 0,           # warm
        "eval_count": 50,
        "prompt_eval_count": 20,
    }
    with patch("requests.post") as p:
        p.return_value.json.return_value = mock_response
        p.return_value.raise_for_status = lambda: None
        result = OllamaService().generate("llama3.3:70b", "test prompt")
        assert result["load_duration_seconds"] == 0
        assert result["was_cold_load"] is False
```

**Step 2: Implement**

In [api/services/ollama_service.py:336](api/services/ollama_service.py:336), after `result = response.json()`:

```python
load_ns = result.get("load_duration", 0)
result["load_duration_seconds"] = load_ns / 1_000_000_000
result["was_cold_load"] = result["load_duration_seconds"] > 0.5
```

Apply to both `generate()` and `chat()` paths.

**Step 3: Verify**

```bash
pytest tests/test_ollama_service.py::test_generate_returns_load_duration -v
pytest tests/test_ollama_service.py::test_generate_warm_load -v
```

---

### Task 2.3: Snapshot residency before/after each step

**Files:**
- Edit: `api/services/step_executor.py`
- Edit: `tests/test_step_executor.py`

**Step 1: Write the failing test**

```python
def test_step_executor_captures_residency_and_pressure(mocked_arch):
    """Mock the architecture's snapshot() and verify it gets called before+after."""
    mocked_arch.snapshot.side_effect = [
        PressureSnapshot(level="ok", per_pool=[...], timestamp=1.0),
        PressureSnapshot(level="warning", per_pool=[...], timestamp=2.0),
    ]
    executor = StepExecutor(...)
    result = executor.execute_step(step, context)
    assert result.pre_step_pressure["level"] == "ok"
    assert result.post_step_pressure["level"] == "warning"
    assert result.arch is not None
    assert mocked_arch.snapshot.call_count == 2
```

**Step 2: Implement**

In `step_executor.py`, before calling `ollama_service.generate(...)`:

```python
arch = Architecture.current()
pre_snapshot = arch.snapshot()
pre_ps_call = ollama_service.get_loaded_models()  # /api/ps wrapper
```

After generate completes:

```python
post_snapshot = arch.snapshot()
post_ps_call = ollama_service.get_loaded_models()
step_result.pre_step_pressure = pre_snapshot.dict()
step_result.post_step_pressure = post_snapshot.dict()
step_result.residency_before = _format_residency(pre_ps_call, arch)
step_result.residency_after = _format_residency(post_ps_call, arch)
step_result.arch = arch.name.value
step_result.model_load_seconds = generate_result["load_duration_seconds"]
step_result.was_cold_load = generate_result["was_cold_load"]
```

Wrap snapshot calls in try/except — failures are logged but don't fail the step.

**Step 3: Verify**

```bash
pytest tests/test_step_executor.py::test_step_executor_captures_residency_and_pressure -v
```

---

### Task 2.4: Run-level transition cost aggregation

**Files:**
- Edit: `api/services/workflow_engine.py`
- Edit: `tests/test_workflow_engine.py`

**Step 1: Write the failing test**

```python
def test_workflow_run_computes_transition_cost():
    # 3-step workflow with model changes between steps
    run = execute_test_workflow(...)
    # step1 cold-loads model A (load=2.3s)
    # step2 cold-loads model B (load=2.1s)
    # step3 reuses model B (load=0)
    assert run.transition_cost_seconds == pytest.approx(4.4, abs=0.1)
```

**Step 2: Implement**

After all steps complete, in `workflow_engine.py`:

```python
transition_cost = sum(
    s.model_load_seconds or 0
    for s in run.step_results
    if s.was_cold_load
)
run.transition_cost_seconds = transition_cost
run.arch = Architecture.current().name.value
```

**Step 3: Verify**

```bash
pytest tests/test_workflow_engine.py::test_workflow_run_computes_transition_cost -v
```

---

### Phase 2 Gate

```bash
pytest tests/test_workflow_models.py tests/test_ollama_service.py tests/test_step_executor.py tests/test_workflow_engine.py -v
```

Manual verification: re-run the `multi-model-handoff` workflow against the live container; inspect `/app/data/workflows/<run_id>/run.json` and confirm `transition_cost_seconds`, `was_cold_load`, and `arch` are populated. Re-run within 5 min; confirm `was_cold_load=false` on the warm run.

---

## Phase 3: Default-Evict Policy + Per-Step `keep_alive`

**Phase intent:** Implement the freshness-by-default policy. Every step evicts at completion unless explicitly overridden. The "arch-aware cost-optimizing" policy is preserved as the `"auto"` opt-in but is no longer the default.

### Task 3.1: Add `keep_alive` to the schema with `"0"` default

**Files:**
- Edit: `api/models/workflow_models.py`
- Edit: `tests/test_workflow_models.py`

**Step 1: Write the failing test**

```python
def test_default_keep_alive_is_zero():
    """The new default: freshness wins."""
    defaults = WorkflowDefaults()
    assert defaults.keep_alive == "0"   # not "auto"

def test_step_keep_alive_override():
    step = AgentStep(
        id="chatty",
        name="Chatty",
        model="qwen2.5:1.5b",
        system_prompt="...",
        inputs=[], outputs=[],
        keep_alive="5m",        # opt back into residency
    )
    assert step.keep_alive == "5m"

def test_keep_alive_auto_opts_into_arch_aware_policy():
    """auto preserved for operators who want the old cost-optimizing behavior."""
    defaults = WorkflowDefaults(keep_alive="auto")
    assert defaults.keep_alive == "auto"

def test_keep_alive_invalid_value_rejected():
    with pytest.raises(ValueError):
        AgentStep(..., keep_alive="not_a_duration")
```

**Step 2: Implement**

Add to `AgentStep`:

```python
keep_alive: Optional[str] = None  # "auto" | "0" | "5m" | "1h" | "-1" — None means use defaults

@field_validator("keep_alive")
def _validate_keep_alive(cls, v):
    if v is None or v in ("auto", "-1", "0"):
        return v
    if re.match(r"^\d+[smh]$", v):
        return v
    raise ValueError(f"invalid keep_alive: {v}")
```

Add to `WorkflowDefaults`:

```python
keep_alive: str = "0"   # ← the new default: freshness by default
eviction_policy: Literal["engine", "off"] = "engine"
```

**Step 3: Verify**

```bash
pytest tests/test_workflow_models.py -v -k keep_alive
```

---

### Task 3.2: Per-arch `should_evict` implementation

**Files:**
- Edit: `api/services/arch_impl/unified.py`
- Edit: `api/services/arch_impl/nvidia_single.py`
- Edit: `api/services/arch_impl/nvidia_multi.py`
- Edit: `tests/test_arch_unified.py`
- Edit: `tests/test_arch_nvidia.py`

**Step 1: Write the failing tests**

```python
# unified
def test_unified_keeps_resident_when_fits():
    arch = UnifiedArchitecture(total_memory_gb=96.0)
    pressure = PressureSnapshot(level="ok", ...)
    assert arch.should_evict(
        current_step=Step(model="a", est_size_gb=30),
        next_step=Step(model="b", est_size_gb=30),
        pressure=pressure,
    ) is False  # 60 GB total, fits in 96 GB pool

def test_unified_evicts_when_doesnt_fit():
    arch = UnifiedArchitecture(total_memory_gb=96.0)
    assert arch.should_evict(
        current_step=Step(model="a", est_size_gb=60),
        next_step=Step(model="b", est_size_gb=50),
        pressure=ok_pressure,
    ) is True  # 110 GB > 96 GB

def test_unified_terminal_step_evicts():
    arch = UnifiedArchitecture(total_memory_gb=96.0)
    assert arch.should_evict(
        current_step=Step(model="a", est_size_gb=10),
        next_step=None,
        pressure=ok_pressure,
    ) is True  # terminal

# nvidia_multi
def test_nvidia_multi_keeps_when_spread_possible():
    arch = NvidiaMultiArchitecture(pools=[80.0, 80.0])
    assert arch.should_evict(
        current_step=Step(model="a", est_size_gb=50),
        next_step=Step(model="b", est_size_gb=40),
        pressure=ok_pressure,
    ) is False  # each fits on its own GPU
```

**Step 2: Implement**

Per design overview decision tables. Helpers:

```python
def _combined_footprint_gb(a: Step, b: Step) -> float:
    return a.est_size_gb + b.est_size_gb * 1.15  # 15% headroom for KV
```

**Step 3: Verify**

```bash
pytest tests/test_arch_*.py -v -k should_evict
```

---

### Task 3.3: Plumb `keep_alive` through Ollama service

**Files:**
- Edit: `api/services/ollama_service.py`
- Edit: `tests/test_ollama_service.py`

**Step 1: Write the failing test**

```python
def test_generate_passes_keep_alive():
    with patch("requests.post") as p:
        p.return_value.json.return_value = {"response": "x", "load_duration": 0}
        p.return_value.raise_for_status = lambda: None
        OllamaService().generate("model", "prompt", keep_alive="0")
        payload = p.call_args.kwargs["json"]
        assert payload["keep_alive"] == "0"

def test_generate_omits_keep_alive_when_none():
    with patch("requests.post") as p:
        p.return_value.json.return_value = {"response": "x", "load_duration": 0}
        p.return_value.raise_for_status = lambda: None
        OllamaService().generate("model", "prompt")
        payload = p.call_args.kwargs["json"]
        assert "keep_alive" not in payload
```

**Step 2: Implement**

Add `keep_alive: Optional[str] = None` arg to `generate()` and `chat()`. Include in payload only when not None.

**Step 3: Verify**

```bash
pytest tests/test_ollama_service.py -v -k keep_alive
```

---

### Task 3.4: Compile-time `keep_alive` resolution (default `"0"`)

**Files:**
- Edit: `api/services/workflow_compiler.py`
- Create: `api/services/eviction_policy.py`
- Edit: `tests/test_workflow_compiler.py`

**Step 1: Write the failing tests**

```python
def test_default_workflow_evicts_every_step():
    """Bare workflow with no keep_alive overrides → every step evicts."""
    workflow = WorkflowDefinition(
        defaults=WorkflowDefaults(),   # defaults to keep_alive="0"
        steps=[
            AgentStep(id="s1", model="a", ...),
            AgentStep(id="s2", model="b", ...),
            AgentStep(id="s3", model="a", ...),   # same as s1, still evicts
        ],
    )
    compiled = compile_workflow(workflow)
    assert all(s._resolved_keep_alive == "0" for s in compiled.steps)

def test_step_override_wins_over_defaults():
    workflow = WorkflowDefinition(
        defaults=WorkflowDefaults(keep_alive="0"),
        steps=[
            AgentStep(id="s1", model="a", keep_alive="5m", ...),   # override
            AgentStep(id="s2", model="b", ...),                    # uses default
        ],
    )
    compiled = compile_workflow(workflow)
    assert compiled.steps[0]._resolved_keep_alive == "5m"
    assert compiled.steps[1]._resolved_keep_alive == "0"

def test_workflow_defaults_override_global_default():
    workflow = WorkflowDefinition(
        defaults=WorkflowDefaults(keep_alive="5m"),
        steps=[AgentStep(id="s1", model="a", ...)],
    )
    compiled = compile_workflow(workflow)
    assert compiled.steps[0]._resolved_keep_alive == "5m"

def test_auto_opts_into_arch_aware_cost_policy(mocked_unified_arch_96gb):
    """auto preserves old behavior: keep resident when fits, evict on overflow."""
    workflow = WorkflowDefinition(
        defaults=WorkflowDefaults(keep_alive="auto"),
        steps=[
            AgentStep(id="s1", model="a", est_size_gb=30, ...),
            AgentStep(id="s2", model="b", est_size_gb=30, ...),  # 60GB fits in 96GB
        ],
    )
    compiled = compile_workflow(workflow)
    assert compiled.steps[0]._resolved_keep_alive == "5m"   # cost-optimizing: keep

def test_auto_evicts_when_overflow(mocked_unified_arch_96gb):
    workflow = WorkflowDefinition(
        defaults=WorkflowDefaults(keep_alive="auto"),
        steps=[
            AgentStep(id="s1", model="a", est_size_gb=60, ...),
            AgentStep(id="s2", model="b", est_size_gb=50, ...),  # 110>96
        ],
    )
    compiled = compile_workflow(workflow)
    assert compiled.steps[0]._resolved_keep_alive == "0"
```

**Step 2: Implement**

`api/services/eviction_policy.py`:

```python
def resolve_keep_alive(
    step: AgentStep,
    next_step: Optional[AgentStep],
    defaults: WorkflowDefaults,
) -> str:
    # 1. Explicit step-level override wins.
    if step.keep_alive is not None:
        return step.keep_alive

    # 2. Workflow defaults override the global default.
    resolved_default = defaults.keep_alive

    # 3. "auto" opts into the arch-aware cost-optimizing policy.
    if resolved_default == "auto":
        return _arch_aware_auto(step, next_step)

    # 4. Otherwise honor the defaults value (default: "0").
    return resolved_default


def _arch_aware_auto(step: AgentStep, next_step: Optional[AgentStep]) -> str:
    """The opt-in cost-optimizing policy. Preserved but no longer the default."""
    if next_step is None:
        return "0"                              # terminal always evicts
    if next_step.model == step.model:
        return "5m"                             # reuse, keep resident
    arch = Architecture.current()
    pressure = arch.snapshot()
    combined = (step.est_size_gb or 0) + (next_step.est_size_gb or 0) * 1.15
    if combined > arch.total_memory_gb * 0.85:
        return "0"                              # won't fit
    return "5m"
```

In `workflow_compiler.py`, after DAG ordering walk pairs (step, immediate_next_step_in_topological_order) and set `step._resolved_keep_alive = resolve_keep_alive(...)`.

**Step 3: Verify**

```bash
pytest tests/test_workflow_compiler.py -v -k keep_alive
```

---

### Task 3.5: Pass resolved `keep_alive` in step execution

**Files:**
- Edit: `api/services/step_executor.py`
- Edit: `tests/test_step_executor.py`

**Step 1: Write the failing test**

```python
def test_step_executor_passes_resolved_keep_alive(mocked_ollama, mocked_arch):
    step = AgentStep(id="s1", model="a", ...)
    step._resolved_keep_alive = "0"
    executor = StepExecutor(...)
    executor.execute_step(step, context)
    assert mocked_ollama.generate.call_args.kwargs["keep_alive"] == "0"
```

**Step 2: Implement**

In `step_executor.py`:

```python
ollama_service.generate(
    model=step.model,
    prompt=composed_prompt,
    keep_alive=getattr(step, "_resolved_keep_alive", None),
    ...
)
```

After step completes, snapshot `/api/ps`. If `keep_alive=="0"` was requested but the model is still resident, log `eviction_fallback=true` and explicitly call `ollama_service.unload(model)`.

**Step 3: Verify**

```bash
pytest tests/test_step_executor.py -v -k keep_alive
```

---

### Phase 3 Gate

```bash
pytest tests/test_arch_*.py tests/test_workflow_compiler.py tests/test_step_executor.py tests/test_ollama_service.py -v
```

Manual verification: build a 2-step workflow with `qwen2.5-coder:1.5b` → `llama3.2:3b`, run against container; `keep_alive="0"` should be in the first step's generate request, verifiable in Ollama daemon logs. Confirm model unloaded by `/api/inventory/memory` snapshot mid-workflow.

---

## Phase 4: Architecture-Aware DAG Scheduling

### Task 4.1: Extract scheduling logic into `scheduler.py`

**Files:**
- Create: `api/services/scheduler.py`
- Edit: `api/services/workflow_engine.py`
- Create: `tests/test_scheduler.py`

**Step 1: Write the failing test**

```python
def test_scheduler_groups_ready_steps(mocked_unified_arch):
    scheduler = Scheduler(arch=mocked_unified_arch)
    ready = [step_a, step_b, step_c]  # all DAG-ready
    decisions = scheduler.schedule_ready(ready)
    assert all(isinstance(d, ScheduleDecision) for d in decisions)
```

**Step 2: Implement**

Extract the current scheduling loop in `workflow_engine.py` into `scheduler.py:Scheduler.schedule_ready(...)`. Initially it just calls `arch.schedule_ready(ready)` and returns the decisions. Keep `workflow_engine.py` as the DAG-walking orchestrator that calls the scheduler each tick.

**Step 3: Verify**

```bash
pytest tests/test_scheduler.py -v
pytest tests/test_workflow_engine.py -v  # ensure no regression
```

---

### Task 4.2: Per-arch `schedule_ready` implementation

**Files:**
- Edit: `api/services/arch_impl/unified.py`
- Edit: `api/services/arch_impl/nvidia_single.py`
- Edit: `api/services/arch_impl/nvidia_multi.py`
- Edit: `tests/test_arch_*.py`

**Step 1: Write the failing tests**

```python
def test_unified_schedules_all_fitting_steps():
    arch = UnifiedArchitecture(total_memory_gb=96.0)
    steps = [Step(est_size_gb=30) for _ in range(2)]
    decisions = arch.schedule_ready(steps)
    assert len(decisions) == 2  # both fit

def test_unified_defers_steps_that_dont_fit():
    arch = UnifiedArchitecture(total_memory_gb=96.0)
    steps = [Step(est_size_gb=50), Step(est_size_gb=50), Step(est_size_gb=50)]
    decisions = arch.schedule_ready(steps)
    assert len(decisions) == 1  # only one fits at 85% budget

def test_nvidia_multi_spreads_across_gpus():
    arch = NvidiaMultiArchitecture(pools=[80.0, 80.0])
    steps = [Step(est_size_gb=50), Step(est_size_gb=50)]
    decisions = arch.schedule_ready(steps)
    assert {d.placement for d in decisions} == {0, 1}  # spread
```

**Step 2: Implement**

Per design overview algorithms. `ScheduleDecision` shape:

```python
class ScheduleDecision(BaseModel):
    step_id: str
    placement: Optional[int] = None    # GPU index, None for unified
    deferred: bool = False
    defer_reason: Optional[str] = None
```

**Step 3: Verify**

```bash
pytest tests/test_arch_*.py -v -k schedule_ready
```

---

### Task 4.3: Validate-time island feasibility analysis

**Files:**
- Edit: `api/services/workflow_compiler.py`
- Edit: `api/routers/workflows.py`
- Edit: `tests/test_workflow_compiler.py`

**Step 1: Write the failing test**

```python
def test_validate_flags_capacity_warning_on_single_gpu(mocked_nvidia_single_80gb):
    workflow = WorkflowDefinition(
        steps=[
            AgentStep(id="s1", model="m1", est_size_gb=50, depends_on=[]),
            AgentStep(id="s2", model="m2", est_size_gb=50, depends_on=[]),  # parallel
        ],
    )
    result = validate_workflow(workflow)
    assert result.capacity_warnings  # 100 GB needed concurrently, 80 GB available
    assert "s1" in result.capacity_warnings[0]["steps"]
    assert "s2" in result.capacity_warnings[0]["steps"]

def test_validate_clean_on_multi_gpu(mocked_nvidia_multi_2x80gb):
    workflow = same_workflow
    result = validate_workflow(workflow)
    assert not result.capacity_warnings  # fits on 2× GPUs

def test_validate_capacity_error_on_unfittable_step(mocked_nvidia_single_80gb):
    workflow = WorkflowDefinition(
        steps=[AgentStep(id="big", model="m", est_size_gb=120, ...)],
    )
    result = validate_workflow(workflow)
    assert result.capacity_errors  # 120 GB doesn't fit anywhere
```

**Step 2: Implement**

`workflow_compiler.py`:

```python
def analyze_capacity(workflow: WorkflowDefinition) -> CapacityAnalysis:
    arch = Architecture.current()
    islands = _walk_concurrency_islands(workflow)
    warnings, errors = [], []
    for island in islands:
        feasibility = arch.feasible(island)
        if feasibility.fits is False:
            (errors if feasibility.fatal else warnings).append({
                "steps": [s.id for s in island],
                "reason": feasibility.reason,
                "arch": arch.name.value,
            })
    return CapacityAnalysis(warnings=warnings, errors=errors)
```

Extend validate response in `workflows.py` to include `capacity_warnings`, `capacity_errors`.

**Step 3: Verify**

```bash
pytest tests/test_workflow_compiler.py -v -k capacity
```

---

### Task 4.4: Runtime starvation handling

**Files:**
- Edit: `api/services/scheduler.py`
- Edit: `api/models/workflow_models.py`
- Edit: `tests/test_scheduler.py`

**Step 1: Write the failing test**

```python
def test_scheduler_aborts_step_on_starvation():
    scheduler = Scheduler(arch=arch_with_no_capacity, max_defer_ticks=3)
    for _ in range(3):
        scheduler.tick([step_too_big])
    decisions = scheduler.tick([step_too_big])
    assert any(d.error_code == "capacity_starvation" for d in decisions)
```

**Step 2: Implement**

Per-step defer counter in scheduler. After `max_defer_ticks` (default 60, configurable via `defaults.max_defer_ticks`), promote to a `ClassifiedError(error_code="capacity_starvation", recoverable=False)` and propagate.

**Step 3: Verify**

```bash
pytest tests/test_scheduler.py -v -k starvation
```

---

### Phase 4 Gate

```bash
pytest tests/test_scheduler.py tests/test_workflow_compiler.py tests/test_arch_*.py -v
```

Manual verification: validate a deliberately-oversized workflow on the dev Mac; confirm `capacity_warnings` populated in `/api/workflows/validate` response.

---

## Phase 5: Pre-Warm Strategies (the freshness-default's enabler)

**Phase intent:** With the freshness-default in place from Phase 3, every step boundary pays a cold load. This phase hides that cost by pre-warming the next step's model in parallel with the current step's inference. Per-arch implementations of `Architecture.transition_plan(prev, next)` decide when pre-warming is safe and beneficial.

**Per-arch pre-warm strategy:**

| Arch | Strategy | Bandwidth contention risk |
|---|---|---|
| `apple_unified` | Always pre-warm during prev step's inference; page cache makes it nearly free | None — page cache is read-side |
| `cpu_x86` | Same as apple_unified | None |
| `gpu_nvidia_single` | Pre-warm only if prev_step remaining inference > expected load time; measure throughput, auto-disable on >10% regression | Real — PCIe shared, VRAM allocator competes |
| `gpu_nvidia_multi` | Pre-warm on a free GPU (no contention) | None when free GPU exists; fall back to single-GPU logic otherwise |

### Task 5.1: Piggybacked eviction (NVIDIA single + multi)

**Files:**
- Edit: `api/services/arch_impl/nvidia_single.py`
- Edit: `api/services/arch_impl/nvidia_multi.py`
- Edit: `api/services/step_executor.py`
- Create: `tests/test_piggyback_eviction.py`

**Step 1: Write the failing test**

```python
def test_nvidia_optimize_transition_piggybacks_eviction(mocked_nvidia_single):
    arch = mocked_nvidia_single
    plan = arch.optimize_transition(
        prev_step=Step(model="A", est_size_gb=60),
        next_step=Step(model="B", est_size_gb=50),  # combined 110 > 80
    )
    assert plan.evict_at_prev_step is True
    assert plan.evict_via_keep_alive_zero is True
```

**Step 2: Implement**

`NvidiaSingleArchitecture.optimize_transition`:

```python
def optimize_transition(self, prev_step, next_step):
    if next_step is None:
        return TransitionPlan(evict_at_prev_step=True, evict_via_keep_alive_zero=True)
    if prev_step.model == next_step.model:
        return TransitionPlan(evict_at_prev_step=False)
    if self._combined_footprint(prev_step, next_step) > self.total_memory_gb * 0.85:
        return TransitionPlan(evict_at_prev_step=True, evict_via_keep_alive_zero=True)
    return TransitionPlan(evict_at_prev_step=False)
```

`step_executor.py`: when `plan.evict_via_keep_alive_zero is True`, pass `keep_alive="0"` on this step's generate (override the resolved policy from Phase 3). Detect post-step that eviction succeeded; if not, fallback to explicit unload.

**Step 3: Verify**

```bash
pytest tests/test_piggyback_eviction.py -v
```

---

### Task 5.2: Pre-warm next-step model (NVIDIA only)

**Files:**
- Edit: `api/services/arch_impl/nvidia_single.py`
- Edit: `api/services/arch_impl/nvidia_multi.py`
- Edit: `api/services/step_executor.py`
- Create: `tests/test_pre_warm.py`

**Step 1: Write the failing test**

```python
async def test_pre_warm_fires_no_op_generate_during_step(mocked_ollama, mocked_nvidia_multi):
    """Pre-warm step N+1 model during step N inference on a free GPU."""
    arch = mocked_nvidia_multi  # 2× 80GB
    plan = arch.optimize_transition(
        prev_step=Step(model="A", est_size_gb=50, gpu_assigned=0),
        next_step=Step(model="B", est_size_gb=40),
    )
    assert plan.pre_warm_next is True
    assert plan.pre_warm_target_gpu == 1

    # Simulating execution
    await executor.execute_step(prev_step, ...)
    # Verify a no-op generate was fired against model B in background
    assert any(
        c for c in mocked_ollama.generate.call_args_list
        if c.kwargs["model"] == "B" and c.kwargs["prompt"] == ""
    )
```

**Step 2: Implement**

- `optimize_transition` on multi-GPU: if a free GPU has room for next step's model, set `pre_warm_next=True`, `pre_warm_target_gpu=<idx>`.
- `optimize_transition` on single-GPU: only pre-warm if remaining current-step inference time > expected load time (estimated from cached load times in Phase 2 data).
- `step_executor`: spawn `asyncio.create_task(self._pre_warm(model, gpu))` at step start; pre-warm calls `ollama_service.generate(model, prompt="", keep_alive="5m")` and ignores errors.

**Bandwidth guard:** measure `eval_count/s` during the step. If >10% drop vs cached baseline for that model, log a regression warning. After 3 consecutive regressions, auto-disable pre-warm via in-memory flag until restart.

**Step 3: Verify**

```bash
pytest tests/test_pre_warm.py -v
```

---

### Task 5.3: GPU affinity (NVIDIA multi)

**Files:**
- Edit: `api/models/workflow_models.py`
- Edit: `api/services/arch_impl/nvidia_multi.py`
- Edit: `api/services/ollama_service.py`
- Create: `tests/test_gpu_affinity.py`

**Step 1: Write the failing tests**

```python
def test_step_gpu_affinity_schema():
    step = AgentStep(..., gpu_affinity="spread")
    assert step.gpu_affinity == "spread"
    step2 = AgentStep(..., gpu_affinity=1)
    assert step2.gpu_affinity == 1

def test_invalid_gpu_index_rejected_at_validate(mocked_nvidia_2gpu):
    workflow = WorkflowDefinition(
        steps=[AgentStep(id="s", model="m", gpu_affinity=5, ...)],
    )
    result = validate_workflow(workflow)
    assert any("gpu_affinity" in e["reason"] for e in result.capacity_errors)

def test_same_as_affinity_colocates(mocked_nvidia_multi_2x80gb):
    arch = mocked_nvidia_multi_2x80gb
    decisions = arch.schedule_ready([
        Step(id="s1", model="a", est_size_gb=30, gpu_affinity="any"),
        Step(id="s2", model="b", est_size_gb=20, gpu_affinity="same_as:s1"),
    ])
    assert decisions[0].placement == decisions[1].placement
```

**Step 2: Implement**

- Add `gpu_affinity: Optional[Union[str, int]] = None` to `AgentStep`. Validator: "spread" | "any" | "same_as:<id>" | int.
- `NvidiaMultiArchitecture.schedule_ready`: honor affinity hints before falling back to spread.
- `ollama_service.generate`: pass `options.main_gpu` to Ollama when affinity is an int. Document as best-effort.

**Step 3: Verify**

```bash
pytest tests/test_gpu_affinity.py -v
```

---

### Task 5.4: Mac page-cache awareness

**Files:**
- Edit: `api/services/arch_impl/unified.py`
- Edit: `api/services/step_executor.py`
- Create: `tests/test_page_cache_aware.py`

**Step 1: Write the failing test**

```python
def test_recently_evicted_model_marked_warm_candidate(mocked_apple_unified):
    arch = mocked_apple_unified
    # Step 1 uses model A, evicted at completion
    # Step 2 uses model B
    # Step 3 reuses model A
    plan_step3 = arch.optimize_transition(
        prev_step=Step(model="B"),
        next_step=Step(model="A"),
        recently_evicted=["A"],
    )
    assert plan_step3.warm_eviction_candidate is True
    assert plan_step3.pre_warm_next is True  # cheap pre-warm via page cache
```

**Step 2: Implement**

- `UnifiedArchitecture.optimize_transition` tracks `recently_evicted` (last 5 min) and marks plans accordingly.
- `step_executor` maintains the recently-evicted list across steps within a run; passes to `optimize_transition`.
- Pre-warm on unified is essentially free (just triggers re-mmap from page cache); always safe to enable.

**Step 3: Verify**

```bash
pytest tests/test_page_cache_aware.py -v
```

---

### Phase 5 Gate

```bash
pytest tests/test_piggyback_eviction.py tests/test_pre_warm.py tests/test_gpu_affinity.py tests/test_page_cache_aware.py -v
```

Manual verification (limited without GPU hardware): exercise the multi-model-handoff workflow on the Mac dev box with three iterations within 5 min; confirm second iteration's `was_cold_load=false` for all steps and total wall-clock <40% of first run.

---

## Phase 6: Deployment-Aware Configuration Validator

**Phase intent:** Validate the supporting environment against per-architecture **and** per-deployment recommendations. The same arch on different deployments has different recommended settings; the validator dispatches through both.

### Task 6.1: Per-arch × per-deployment config validator

**Files:**
- Create: `api/services/config_validator.py`
- Create: `tests/test_config_validator.py`

**Step 1: Write the failing tests**

```python
def test_validator_dmg_apple_unified_clean():
    with patch_dmg(), patch_apple_unified(total_gb=48.0):
        arch, deployment = detect_architecture(), Deployment.current()
        daemon_env = {"OLLAMA_KEEP_ALIVE": "5m", "OLLAMA_MAX_LOADED_MODELS": "3"}
        result = validate_config(arch, deployment, daemon_env)
        assert result.is_clean

def test_validator_container_multi_gpu_requires_sched_spread():
    with patch_container(), patch_nvidia_multi(gpus=[{"vram_gb":80.0},{"vram_gb":80.0}]):
        arch, deployment = detect_architecture(), Deployment.current()
        daemon_env = {}   # OLLAMA_SCHED_SPREAD unset
        result = validate_config(arch, deployment, daemon_env)
        assert any(e.code == "missing_sched_spread" for e in result.errors)

def test_validator_cuda_visible_on_dmg_mismatch():
    """DMG should never have CUDA_VISIBLE_DEVICES; if set, mismatch warning."""
    with patch_dmg(), patch_apple_unified():
        arch, deployment = detect_architecture(), Deployment.current()
        daemon_env = {"CUDA_VISIBLE_DEVICES": "0"}
        result = validate_config(arch, deployment, daemon_env)
        assert any(w.code == "arch_env_mismatch" for w in result.warnings)

def test_validator_container_cpu_warns_no_num_thread():
    with patch_container(), patch_no_nvidia():
        arch, deployment = detect_architecture(), Deployment.current()
        daemon_env = {}
        result = validate_config(arch, deployment, daemon_env)
        assert any(w.code == "missing_num_thread" for w in result.warnings)

def test_validator_strict_mode_exits_on_error():
    with patch_container(), patch_nvidia_multi(gpus=[{"vram_gb":80.0},{"vram_gb":80.0}]):
        daemon_env = {}  # missing SCHED_SPREAD → error
        with patch.dict(os.environ, {"STRICT_CONFIG_VALIDATION": "true"}):
            with pytest.raises(SystemExit):
                validate_config_or_exit(...)

def test_validator_container_on_mac_logs_vm_warning():
    """Docker Desktop on Mac shows as container × cpu_x86; should call this out."""
    with patch_container(), patch("sys.platform", "darwin"):
        result = validate_config(...)
        assert any(w.code == "docker_desktop_mac_vm" for w in result.warnings)
```

**Step 2: Implement**

Recommendations are keyed by `(ArchClass, DeploymentMode)`:

```python
# api/services/config_validator.py
RECOMMENDATIONS: dict[tuple[ArchClass, DeploymentMode], list[Recommendation]] = {

    (ArchClass.APPLE_UNIFIED, DeploymentMode.DMG_NATIVE): [
        Recommendation("OLLAMA_HOST", "127.0.0.1:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "3", severity="warn"),
        Recommendation("OLLAMA_NUM_PARALLEL", "1-2", severity="warn"),
        Recommendation("CUDA_VISIBLE_DEVICES", None, severity="arch_env_mismatch",
                       message="CUDA env vars on macOS DMG are meaningless"),
    ],

    (ArchClass.APPLE_UNIFIED, DeploymentMode.HOST_NATIVE): [
        # same as DMG_NATIVE
    ],

    (ArchClass.CPU_X86, DeploymentMode.CONTAINER): [
        Recommendation("OLLAMA_HOST", "http://ollama:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "1", severity="warn"),
        Recommendation("OLLAMA_NUM_PARALLEL", "1", severity="warn"),
        Recommendation("OLLAMA_NUM_THREAD", "physical-core-count", severity="warn",
                       code="missing_num_thread"),
        Recommendation("CUDA_VISIBLE_DEVICES", None, severity="arch_env_mismatch"),
    ],

    (ArchClass.GPU_NVIDIA_SINGLE, DeploymentMode.CONTAINER): [
        Recommendation("OLLAMA_HOST", "http://ollama:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "2", severity="warn"),
        Recommendation("OLLAMA_NUM_PARALLEL", "1", severity="warn",
                       message="KV cache competes with weights in single VRAM pool"),
        Recommendation("CUDA_VISIBLE_DEVICES", "*", severity="warn"),
        # Special: --gpus all / runtime: nvidia is checked separately
    ],

    (ArchClass.GPU_NVIDIA_MULTI, DeploymentMode.CONTAINER): [
        Recommendation("OLLAMA_SCHED_SPREAD", "1", severity="error",
                       code="missing_sched_spread",
                       message="Required for parallel multi-GPU execution"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "3*gpu_count", severity="warn"),
        Recommendation("OLLAMA_NUM_PARALLEL", "1", severity="warn",
                       message="Let DAG drive parallelism, not per-runner"),
        Recommendation("CUDA_VISIBLE_DEVICES", "enumerate", severity="warn"),
    ],

    # ... host_native variants
}


def validate_config(
    arch: Architecture,
    deployment: Deployment,
    daemon_env: dict[str, str],
) -> ConfigValidationResult:
    key = (arch.name, deployment.mode)
    recs = RECOMMENDATIONS.get(key, [])
    warnings, errors = [], []

    for rec in recs:
        actual = daemon_env.get(rec.key)
        if rec.expected is None:
            # should NOT be set
            if actual is not None:
                warnings.append({"code": rec.code, "message": rec.message, ...})
        else:
            # should be set
            if actual is None:
                (errors if rec.severity == "error" else warnings).append({...})
            elif not _matches(rec.expected, actual):
                warnings.append({...})

    # Deployment-special checks
    if deployment.mode == DeploymentMode.CONTAINER and arch.name.value.startswith("gpu_"):
        if not _gpu_passthrough_works():
            errors.append({"code": "gpu_passthrough_misconfigured", ...})

    if deployment.mode == DeploymentMode.CONTAINER and sys.platform == "darwin":
        warnings.append({"code": "docker_desktop_mac_vm",
                         "message": "Docker on Mac runs Linux VM; not seeing unified memory"})

    return ConfigValidationResult(warnings=warnings, errors=errors)


def validate_config_or_exit(arch, deployment, daemon_env):
    result = validate_config(arch, deployment, daemon_env)
    if result.errors and os.environ.get("STRICT_CONFIG_VALIDATION") == "true":
        for e in result.errors:
            logger.error(f"Config error: {e}")
        raise SystemExit(1)
    return result
```

**Step 3: Verify**

```bash
pytest tests/test_config_validator.py -v
```

**Step 3: Verify**

```bash
pytest tests/test_config_validator.py -v
```

---

### Task 6.2: Probe daemon env at startup

**Files:**
- Edit: `api/services/architecture.py`
- Edit: `api/services/config_validator.py`
- Edit: `tests/test_config_validator.py`

**Step 1: Write the failing test**

```python
def test_probe_daemon_env_returns_known_vars():
    with patch("api.services.ollama_service.OllamaService.get_daemon_env") as g:
        g.return_value = {"OLLAMA_KEEP_ALIVE": "5m", "OLLAMA_NUM_PARALLEL": "2"}
        env = probe_daemon_env()
        assert env["OLLAMA_KEEP_ALIVE"] == "5m"

def test_probe_handles_unsupported_ollama_version():
    with patch("api.services.ollama_service.OllamaService.get_daemon_env") as g:
        g.side_effect = NotImplementedError
        env = probe_daemon_env()
        assert env == {}  # graceful degradation
```

**Step 2: Implement**

`OllamaService.get_daemon_env()` — attempt to read daemon env from `/api/show` (newer Ollama exposes this); fall back to inspecting the container env (if our app shares the container). Last resort: return empty dict.

Call in `architecture.detect()`; pass to config validator.

**Step 3: Verify**

```bash
pytest tests/test_config_validator.py -v -k probe
```

---

### Task 6.3: Health endpoint extension + recommendations endpoint

**Files:**
- Edit: `api/routers/system.py`
- Edit: `tests/test_system_router.py`

**Step 1: Write the failing test**

```python
def test_health_includes_config_warnings(mocked_nvidia_multi_no_sched_spread):
    client = TestClient(app)
    r = client.get("/api/system/health")
    body = r.json()
    assert "config_validation" in body
    assert any(e["code"] == "missing_sched_spread" for e in body["config_validation"]["errors"])

def test_get_config_recommendations(mocked_nvidia_multi):
    client = TestClient(app)
    r = client.get("/api/system/config/recommendations")
    body = r.json()
    assert "OLLAMA_SCHED_SPREAD" in body["recommended_env"]
    assert "docker_compose_snippet" in body
    assert "systemd_snippet" in body
```

**Step 2: Implement**

- Extend `/api/system/health` with `config_validation` block (warnings + errors).
- New endpoint `/api/system/config/recommendations` returns env vars, docker-compose snippet, systemd snippet for the detected arch.
- Generate snippets from templates in `docs/deployment/templates/`.

**Step 3: Verify**

```bash
pytest tests/test_system_router.py -v -k config
```

---

### Task 6.4: Per-architecture deployment doc

**Files:**
- Create: `docs/deployment/per-architecture-config.md`
- Create: `docs/deployment/templates/docker-compose.apple_unified.yml`
- Create: `docs/deployment/templates/docker-compose.gpu_nvidia_single.yml`
- Create: `docs/deployment/templates/docker-compose.gpu_nvidia_multi.yml`
- Create: `docs/deployment/templates/docker-compose.cpu_x86.yml`

**Step 1:** No test (doc + templates).

**Step 2: Write**

`docs/deployment/per-architecture-config.md` covers:
- Detection table (how to confirm which arch the app sees)
- Per-arch required and recommended env vars
- Per-arch docker-compose and systemd examples
- Per-arch known pitfalls (e.g. multi-GPU without SCHED_SPREAD)
- Per-arch verification commands

Templates parameterize Ollama daemon env, GPU passthrough flags (`--gpus all`, `--device=/dev/nvidia*`), and resource limits.

**Step 3: Verify**

Cross-check that running `docker-compose -f docs/deployment/templates/docker-compose.gpu_nvidia_multi.yml config` validates without error (don't actually run; we have no GPU host).

---

### Phase 6 Gate

```bash
pytest tests/test_config_validator.py tests/test_system_router.py -v
```

Manual verification on dev Mac:

```bash
python api/main.py &
curl -s http://localhost:8000/api/system/health | jq '.config_validation'
curl -s http://localhost:8000/api/system/config/recommendations | jq '.recommended_env'
kill %1
```

Expected: clean config validation (Mac has no required-but-missing env vars). Recommendations endpoint returns Mac-appropriate snippet.

---

## Cross-cutting concerns

### Error handling reference

Implemented in `api/services/error_handlers.py`. Every error carries `error_class`, `error_code`, `arch`, `step_id`, `recoverable: bool`, `recovery_action_taken`, `human_message`.

Full matrix is in the v3 spec (chat history); critical entries restated here:

| error_class | error_code | Arch-specific recovery |
|---|---|---|
| `memory` | `vram_oom` | nvidia: evict LRU pool model, retry once, fail if still OOM |
| `memory` | `unified_swap_thrash` | unified: pause 2s, evict LRU, log incident |
| `memory` | `host_oom_killer` | cpu_x86: detect via runner-died, retry once, fail-fast on recurrence |
| `daemon` | `ollama_unreachable` | all: 3× exp backoff, then fail step |
| `hardware` | `gpu_lost_mid_run` | nvidia_multi: reschedule survivors; nvidia_single: abort workflow |
| `scheduler` | `capacity_starvation` | all: abort step per branch policy |
| `config` | `required_setting_missing` | STRICT: refuse start; else degrade |

### Schema (cumulative)

```yaml
defaults:
  keep_alive: "0"                # freshness by default — model killed after every step
  eviction_policy: "engine"      # "engine" | "off"
  branch_failure_policy: "abort_branch"
  oom_retry_policy: "evict"
  affinity_strictness: "advisory"
  max_defer_ticks: 60
  request_timeout_s: 300
  stream_idle_timeout_s: 60
  retries: 1
  runner_crash_retries: 1
  disable_predictive_warm: false  # pre-warm is the cost-hider for the default policy; default ON
  gpu_loss_policy: "reschedule"
  pressure_critical_threshold: 0.90
  resource_headroom_pct: null     # null = deployment default (20% host, 10% container)
  arch_required: null             # e.g. "gpu_nvidia_multi" if workflow needs it
  deployment_required: null       # e.g. "container" if workflow needs cgroup-enforced limits

steps:
  - id: <id>
    model: <name>
    keep_alive: <duration|"auto">    # null = use defaults; "auto" opts into cost-optimizing policy
    gpu_affinity: "spread"|"any"|"same_as:<id>"|<int>
    requires_isolation: false
    timeout_override_s: null
```

The default value `keep_alive: "0"` means **every workflow that doesn't explicitly set otherwise will evict its model at every step boundary**. Pre-warm (Phase 5) hides the cost.

### API surface

| Endpoint | Method | Phase |
|---|---|---|
| `/api/system/architecture` | GET | 1 |
| `/api/system/deployment` | GET | 1 |
| `/api/system/architecture/refresh` | POST | 1 |
| `/api/system/pressure` | GET | 1 |
| `/api/system/health` | GET (extended) | 1, 6 |
| `/api/system/config/recommendations` | GET | 6 |
| `/api/workflows/runs/{id}` | GET (extended) | 2 |
| `/api/workflows/validate` | POST (extended) | 4 |

### Files touched

| File | Phases | Change type |
|---|---|---|
| `api/services/architecture.py` | 1 | New — arch abstraction + Protocol |
| `api/services/deployment.py` | 1 | New — deployment abstraction + Protocol |
| `api/services/arch_impl/unified.py` | 1, 3, 4, 5 | New — Mac + CPU impl |
| `api/services/arch_impl/nvidia_single.py` | 1, 3, 4, 5 | New |
| `api/services/arch_impl/nvidia_multi.py` | 1, 3, 4, 5 | New |
| `api/services/deployment_impl/dmg.py` | 1 | New — DMG / py2app impl |
| `api/services/deployment_impl/container.py` | 1 | New — cgroup-aware container impl |
| `api/services/deployment_impl/host_native.py` | 1 | New — bare-metal Linux/Mac impl |
| `api/services/eviction_policy.py` | 3 | New — freshness-default resolver + `"auto"` opt-in |
| `api/services/scheduler.py` | 4 | New — extracted from workflow_engine; arch+deployment dispatched |
| `api/services/error_handlers.py` | all | New — per-arch × per-deployment recovery |
| `api/services/config_validator.py` | 6 | New — `(arch, deployment)` recommendation matrix |
| `api/routers/system.py` | 1, 6 | New — arch / deployment / pressure / config endpoints |
| `docs/deployment/per-architecture-config.md` | 6 | New — primary deployment guide |
| `docs/deployment/ollama-version.md` | 1 | New — version pin rationale + upgrade procedure |
| `docs/deployment/templates/docker-compose.*.yml` | 6 | New — one template per supported `(arch, deployment)` |
| `workflows/arch-aware-demo.yaml` | gate | New — cross-phase reference workflow |
| `tests/mocks/arch/` | all | New — 4 arch mock fixtures |
| `tests/mocks/deployment/` | all | New — 3 deployment mock fixtures |
| `docker-compose.yml` | 1 | **Modified** — pin `ollama/ollama:0.23.4` |
| `api/services/ollama_service.py` | 1, 2, 3, 5 | Modified — `get_version()`, `keep_alive` param, `load_duration` capture |
| `api/services/step_executor.py` | 2, 3, 5 | Modified — pre/post snapshot, eviction dispatch, pre-warm |
| `api/services/workflow_engine.py` | 4 | Modified — scheduling extracted → `scheduler.py` |
| `api/services/workflow_compiler.py` | 3, 4 | Modified — `keep_alive` resolution + validate-time analysis |
| `api/models/workflow_models.py` | 2, 3, 5 | Modified — schema extensions; `defaults.keep_alive: "0"` |
| `api/main.py` | 1, 6 | Modified — startup detection, banner, STRICT-mode gate |
| `api/routers/workflows.py` | 4 | Modified — surface capacity warnings/errors in validate |
| `api/routers/inventory.py` | 5 | Modified (small) — wire `/unload` as fallback path |
| `desktop/setup_app.py` | 1 | Modified — ensure py2app picks up new modules (`arch_impl`, `deployment_impl`) |

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Ollama `keep_alive: 0` semantics — does it evict at response end or at next idle tick? | high | high | Phase 3 Task 3.5 verifies via post-step `/api/ps`; explicit-unload fallback if response-end semantics not honored |
| Ollama version drift breaks pinned `0.23.4` | medium | medium | Pinned in [docker-compose.yml](../../docker-compose.yml); Phase 1 validates `/api/version` floor; document upgrade procedure |
| Default-evict policy regresses workflow throughput before pre-warm lands | high | medium | Stage delivery: do not ship Phase 3 to operators without Phase 5 also enabled; or make defaults `"5m"` until Phase 5 gate closes (then flip) |
| DMG packaging breaks under new arch/deployment detection | medium | high | Phase 1 Task 1.4b explicitly tests py2app frozen=True path; smoke-test DMG build after each phase |
| Container detection false-negative (rootless podman, k8s pod, LXC) | medium | medium | Phase 1 Task 1.4c tests multiple signals (`/.dockerenv`, cgroup path); fall back to `host_native` rather than crash |
| Cgroup v1 vs v2 path differences across kernel versions | medium | low | Detect both paths in Phase 1; document supported kernels |
| Mac `vm_stat` pressure thresholds need empirical calibration | high | low | Make configurable; ship conservative default; iterate post-1.3 |
| No GPU hardware in current fleet for live testing | high | medium | Mock layers exercise all logic; cloud rental for Phase 5 acceptance pre-tag |
| Pre-warm bandwidth contention on single GPU regresses inference | medium | medium | Auto-disable feature flag based on measured `eval_count/s` regression (Phase 5 Task 5.2) |
| MIG mode breaks GPU-count detection | low | medium | Phase 1 verifies; document MIG as 1.4.x scope if needed |
| Container GPU passthrough misconfigured | medium | high | Phase 6 validator checks `nvidia-smi` from inside container at startup |
| Workflow resume after arch or deployment change | low | low | Phase 1 records both in run; resume validates match |

---

## Rollout plan

**Critical sequencing constraint:** Phase 3 changes the default eviction policy. Without Phase 5 (pre-warm), this regresses throughput on every multi-step workflow. **Either ship Phases 3 + 5 together, or keep `defaults.keep_alive` at `"5m"` (old behavior) until Phase 5 gate closes and then flip in a single release.** Recommended: ship 3 + 5 together as `1.3.0-beta.1`.

| Phase | Branch | Merge target | Tag |
|---|---|---|---|
| 1 (incl. Ollama pin) | `feature/arch-deployment-detection` | `master` | `1.3.0-alpha.1` |
| 2 | `feature/arch-observability` | `master` | `1.3.0-alpha.2` |
| 4 | `feature/arch-scheduling` | `master` | `1.3.0-alpha.3` |
| 3 + 5 (combined) | `feature/freshness-default-and-prewarm` | `master` | `1.3.0-beta.1` |
| 6 | `feature/deployment-aware-config-validator` | `master` | `1.3.0` |

Alpha tags are internal; beta gets external testing on at least dev Mac + container-cpu (BD790i) + container-GPU (cloud rental). 1.4.0 absorbs follow-up refinements (MIG support, NVLink-aware pairing, dynamic quantization downgrade).

### Per-deployment release checklist

Before tagging `1.3.0`:

| Deployment | Verification |
|---|---|
| DMG on M-series Mac | Build via `desktop/build.sh`; install; `arch=apple_unified deployment=dmg_native` reported in `/api/system/architecture`; reference workflow runs |
| Container on Linux CPU (BD790i / MS-01) | `docker-compose up -d` with pinned `ollama:0.23.4`; cgroup-limited memory respected; reference workflow runs |
| Container on Linux + single GPU | Cloud-rented A100 or L4; `--gpus all` + NVIDIA Container Toolkit; multi-model reference workflow runs; transition cost ≤3 s |
| Container on Linux + multi-GPU | Cloud-rented 2× GPU host; `OLLAMA_SCHED_SPREAD=1`; parallel branches land on different GPUs; ≥1.7× speedup vs serial baseline |
| Host-native Linux | Run `python api/main.py` bare on the BD790i; verify same behavior as container minus cgroup limits |

---

## Open questions

1. **Ollama `keep_alive: 0` semantics on `0.23.4`** — evicts at response end (atomic), or at next idle-check tick? Test in Phase 3 Task 3.5. The freshness-default policy *requires* atomic-at-response-end for correctness; if it's not, every step's executor needs an explicit `/api/inventory/unload` follow-up call, adding ~50ms per step. **Resolve before Phase 3 ships.**
2. **DMG bundled Ollama vs system Ollama** — the desktop app today assumes Ollama is reachable at `127.0.0.1:11434` but doesn't bundle it. Should the DMG installer prompt for Ollama install if missing? Out of scope here; flagged for Mac UX track.
3. **Container memory limit detection on rootless podman / k8s pods / LXC** — cgroup paths vary. Phase 1 Task 1.4b tests Docker; later variants need verification.
4. **Daemon env introspection coverage** — Ollama 0.23.4's `/api/show` exposes per-model parameters but not daemon env. Phase 6 falls back to parsing `os.environ` inside the container; for DMG the source is the shell launching the Ollama Mac app, which we can't reliably read.
5. **MIG slices as separate pools or one logical pool?** — Phase 1 assumes separate; verify on a real MIG-enabled card before tagging beta. Likely 1.4 scope.
6. **Heterogeneous multi-GPU (e.g. 1× H100 + 1× A100)** — scheduler treats uniformly; defer model-size-aware placement to 1.4.
7. **Pressure threshold tuning on Mac** — empirical calibration needed; ship with conservative default (90% wired+inactive AND swap rising), make configurable.
8. **Pre-warm regression threshold (10%)** — chosen by intuition. Calibrate against real workloads during Phase 5 beta.
9. **`OLLAMA_KEEP_ALIVE` env var vs per-request `keep_alive`** — when both are set, per-request wins (verified). Document so operators understand the engine's per-step values override any env-set default.
10. **Multi-tenancy global lock** — two concurrent workflows on same host racing on eviction. Per-model lock for now; global lock deferred to a future phase.

---

## Acceptance gate (cross-phase)

A reference workflow at `workflows/arch-aware-demo.yaml` exercises multi-model handoff under the **freshness-default** policy with explicit (arch × deployment) expectations.

**Workflow structure:**
```
step1: extract            (small model, ~2 GB)
step2: analyze            (medium model, ~20 GB)
step3a: synth_A ──┐
                   ├── parallel branch
step3b: synth_B ──┘
step4: judge              (re-uses step1's model — but evicted, must reload)
```

**Default policy in effect:** every step evicts at completion. `step4` cold-loads step1's model even though step1 already used it. Pre-warm fires at every boundary where the next-step model differs.

**Per-(arch × deployment) expected behavior:**

| Combination | Behavior |
|---|---|
| `apple_unified` × `dmg_native` (M-series Mac DMG) | Every step evicts; pre-warm via page cache; step4's warm reload of step1's model is sub-second; total wall-clock close to pure inference time |
| `cpu_x86` × `container` (BD790i cgroup-limited) | Every step evicts; effective memory respects cgroup; pre-warm via page cache; step3a/b serialize |
| `gpu_nvidia_single` × `container` (cloud A100 80GB) | Every step evicts; pre-warm during prev-step inference when estimate allows; step3a/b serialize with piggybacked eviction; transition cost ≤3 s |
| `gpu_nvidia_multi` × `container` (cloud 2× H100) | Every step evicts; pre-warm on alternate GPU; step3a/b parallelize; transition cost effectively 0; wall-clock ≥1.7× vs serial baseline |

**Default-evict verification:** after every step, `/api/inventory/memory` snapshot shows the step's model has been evicted. Verified for every step on every combination.

**Per-arch failure injection (must pass):**

- `apple_unified`: simulated critical swap pressure → engine pauses 2 s, evicts pool, recovers.
- `cpu_x86` × `container`: simulated OOM-killer on runner mid-step → engine detects vanished runner, retries once, fails workflow on recurrence with `host_oom_killer`.
- `gpu_nvidia_single`: injected `cudaErrorMemoryAllocation` on step2 load → engine evicts pool, retries step2, succeeds.
- `gpu_nvidia_multi`: GPU 1 marked offline mid-workflow → step3b reschedules to GPU 0 (serializes), engine continues, no crash.

**Per-deployment configuration verification (must pass):**

- `dmg_native`: launch DMG; `/api/system/architecture` reports correct triple; no daemon-config warnings.
- `container` × `gpu_nvidia_multi` **without** `OLLAMA_SCHED_SPREAD`: startup ERRORS with `missing_sched_spread`; STRICT mode refuses to start.
- `container` on Mac (Docker Desktop): logs Linux-VM warning at startup; runs as `cpu_x86` from inside the VM.
- All deployments: `/api/system/architecture` returns `(arch, deployment, ollama_version)` triple matching the host.

Closing this gate ships the full feature set across all 4 supported (arch × deployment) combinations.

---

## Effort estimate

| Phase | Engineer-days | Notes |
|---|---|---|
| 1 (incl. deployment + Ollama pin) | 7 | Arch + deployment abstractions; cgroup detection; Ollama version probe; py2app frozen path testing |
| 2 | 3 | Schema additions + plumbing |
| 3 (freshness default) | 3 | Default policy + compile-time resolution + `"auto"` opt-in retention |
| 4 | 5 | Scheduler extraction + validate-time per-arch×deployment analysis |
| 5 (pre-warm — critical) | 7 | Pre-warm logic per arch + bandwidth guard + affinity; load-bearing for Phase 3's policy |
| 6 (deployment-aware) | 4 | Validator with (arch × deployment) matrix; per-deployment docs/templates |
| **Total** | **29 days** | ~6 weeks for one engineer; some parallelism possible after Phase 1 |

Phases 2 and 4 can parallelize after Phase 1 lands (disjoint code paths). Phases 3 and 5 must ship together per the rollout plan. Phase 6 ships last. Realistic calendar with one engineer: 7-8 weeks including reviews and gate verification on live hardware where available.
