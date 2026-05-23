# Per-Architecture Deployment Configuration

Reference for matching Ollama daemon settings to the architecture and
deployment surface Enclave detects on a given host. Same recommendations
the runtime validator at [`api/services/config_validator.py`](../../api/services/config_validator.py)
checks against; this doc is the prose form for operators.

## Confirming which arch the app detects

```bash
curl -s http://localhost:8000/api/system/architecture | jq .arch.name
curl -s http://localhost:8000/api/system/health      | jq .
```

The two values reported by `/api/system/health` are the dispatch keys:

| Field        | Value                                           |
|--------------|-------------------------------------------------|
| `arch`       | `apple_unified` / `cpu_x86` / `gpu_nvidia_single` / `gpu_nvidia_multi` / `unknown` |
| `deployment` | `dmg_native` / `host_native` / `container`      |

Recommendations are keyed by the `(arch, deployment)` pair. The same arch
under different deployments gets different "right answers."

## Detection matrix

| Arch                | Detection signal                                        |
|---------------------|---------------------------------------------------------|
| `apple_unified`     | `sys.platform == "darwin"` + `arm64`                    |
| `cpu_x86`           | Linux + NVML init fails (`Shared Library Not Found`)    |
| `gpu_nvidia_single` | Linux + `pynvml.nvmlInit()` succeeds + `device_count == 1` |
| `gpu_nvidia_multi`  | Linux + `pynvml.nvmlInit()` succeeds + `device_count >= 2` |
| `unknown`           | All probes failed; engine runs in degraded mode         |

| Deployment    | Detection signal                                      |
|---------------|-------------------------------------------------------|
| `dmg_native`  | macOS + bundle is `Enclave.app` (py2app)              |
| `container`   | `/.dockerenv` exists OR `/proc/1/cgroup` mentions docker/podman/containerd |
| `host_native` | Default — neither bundle nor container marker present |

## Apple unified × DMG / host native

| Env var                    | Recommended       | Why |
|----------------------------|-------------------|---|
| `OLLAMA_HOST`              | `127.0.0.1:11434` | Loopback; the DMG bundles its own daemon |
| `OLLAMA_MAX_LOADED_MODELS` | `3`               | Unified RAM is plentiful (typically 32-128 GB) |
| `OLLAMA_NUM_PARALLEL`      | `1`               | KV-cache locality matters more than concurrency |
| `CUDA_VISIBLE_DEVICES`     | **must not be set** | No NVIDIA hardware; setting these is `arch_env_mismatch` |
| `NVIDIA_VISIBLE_DEVICES`   | **must not be set** | Same |

### Known pitfall

`docker compose up` with Ollama on an Apple Silicon Mac runs the daemon
inside a Linux VM. The daemon sees no Metal/MPS; it falls back to CPU.
Use the DMG build for Apple Silicon performance, OR accept the CPU
penalty if you specifically need containerised deployment.

The validator emits `docker_desktop_mac_vm` warning for this case.

## x86 CPU × container / host native

| Env var                    | Recommended | Why |
|----------------------------|-------------|---|
| `OLLAMA_HOST`              | `http://ollama:11434` (container) / `127.0.0.1:11434` (host) | Daemon service name vs loopback |
| `OLLAMA_MAX_LOADED_MODELS` | `1`         | CPU prefill cost dominates; only one resident model is sensible |
| `OLLAMA_NUM_PARALLEL`      | `1`         | Same — no surplus capacity for concurrent generations |
| `OLLAMA_NUM_THREAD`        | physical-core count | Logical cores hurt CPU inference; pin to physical (typically `nproc --all / 2` with SMT enabled) |
| `CUDA_VISIBLE_DEVICES`     | **must not be set** | No GPU |

### Verification

```bash
docker exec -it enclave-ollama ollama ps   # confirms running models
nproc --all                                # confirm CPU thread count
```

## NVIDIA single GPU × container / host native

| Env var                    | Recommended | Why |
|----------------------------|-------------|---|
| `OLLAMA_HOST`              | `http://ollama:11434` (container) / `127.0.0.1:11434` (host) | |
| `OLLAMA_MAX_LOADED_MODELS` | `2`         | KV cache competes with weights in a single VRAM pool |
| `OLLAMA_NUM_PARALLEL`      | `1`         | Same — concurrent generations starve KV cache |
| `OLLAMA_FLASH_ATTENTION`   | `1`         | Faster prefill; supported on Ampere+ |
| `OLLAMA_GPU_LAYERS`        | `-1`        | Offload all layers (the GPU layer count, not VRAM bytes) |

### Container pitfall

Container with NVIDIA arch but missing `--gpus all` / `runtime: nvidia`
in compose → the daemon runs but `nvidia-smi` is unreachable. The
validator runs `nvidia-smi -L` and emits `gpu_passthrough_misconfigured`
error when this is the case.

### Verification

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

## NVIDIA multi-GPU × container / host native

| Env var                    | Recommended       | Severity | Why |
|----------------------------|-------------------|----------|---|
| `OLLAMA_SCHED_SPREAD`      | `1`               | **error** | Without this Ollama serializes loads onto GPU 0 |
| `OLLAMA_HOST`              | `http://ollama:11434` (container) / `127.0.0.1:11434` (host) | warn | |
| `OLLAMA_MAX_LOADED_MODELS` | `3 × gpu_count`   | warn | Conservative starting point — measure VRAM pressure |
| `OLLAMA_NUM_PARALLEL`      | `1`               | warn | Let the DAG drive parallelism, not per-runner |
| `OLLAMA_FLASH_ATTENTION`   | `1`               | warn | |

### The SCHED_SPREAD pitfall

The single most common multi-GPU misconfiguration: Ollama defaults to
loading every model on GPU 0 until it fills, then spilling. With
`OLLAMA_SCHED_SPREAD=1` it distributes models across GPUs. **The
validator treats this as `severity=error`**, not warn.

### Verification

```bash
ollama ps        # should show models spread across GPU indices, not all 0
nvidia-smi       # should show usage on multiple GPUs
```

## Strict mode

Set `STRICT_CONFIG_VALIDATION=true` to abort startup on any
`severity=error` recommendation. Useful for ops handoff: a fresh
deployment that hits `missing_sched_spread` will exit cleanly rather
than launch and silently degrade.

Without the flag, errors are logged at startup and surfaced on
`/api/system/health` for the operator to address at their pace.

## See also

- [`api/services/config_validator.py`](../../api/services/config_validator.py) — recommendation matrix, source of truth
- [`templates/`](./templates/) — parameterised docker-compose snippets per arch
- [`ollama-version.md`](./ollama-version.md) — Ollama 0.23.4 pinning rationale
- `docs/BD790I_MIGRATION.md` — concrete BD790i (NVIDIA RTX 4000 Blackwell) runbook
