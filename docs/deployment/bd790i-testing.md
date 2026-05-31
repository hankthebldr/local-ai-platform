# Testing on the BD790i

**Status:** v1 — pairs the 1.3.0 MCP & Skills work (PRs #116–127) with the
flagship's actual hardware. Use this as the bring-up checklist when the
container is the next thing you start.

The BD790i is the **flagship** in the Enclave fleet:

| Spec | Value |
|---|---|
| CPU | AMD Ryzen 9 7945HX (16 cores / 32 threads) |
| GPU | NVIDIA RTX 4000 Blackwell, 24 GB VRAM |
| RAM | 96 GB DDR5 |
| OS / deployment | Linux + Docker (`docker-compose.yml`) |
| Role | research / 70B-class workflows |

It's the only host in the fleet that can actually exercise the full
co-scheduler (Phase 2b) — `effective_memory_gb()` lands near 76 GB after
the 20% headroom, large enough to contend with 70B-class models +
multi-GB MCP RSS at the same time. Everything else (Mac M4 Pro 48 GB,
MS-01 64 GB) hits contention earlier and you can't see the
recommendation grammar exercise its full priority chain.

## Bring-up checklist

### 1. Pre-flight on the host

```bash
# CUDA + driver sanity
nvidia-smi              # expect: RTX 4000 Blackwell, driver >= 550, CUDA >= 12.4
docker --version        # expect: 24.x or newer
docker compose version  # expect: v2.20+ (compose v2)

# Verify the host can see a Linux cgroup memory ceiling — the container
# deployment uses cgroup memory.max as effective_memory_gb when set.
cat /sys/fs/cgroup/memory.max 2>/dev/null || echo "cgroup v1 host"
```

### 2. Start the stack

```bash
git pull && docker compose pull && docker compose up -d
docker compose logs -f api ollama
```

First run will write a master API key to `data/config/first-run-key.txt`;
grep it from the logs (`docker compose logs api | grep FIRST-RUN`) or
read the file (it's chmod 0600 inside the container).

### 3. Verify the Phase 7 hardening landed

```bash
# Phase 7.2 — Linux capabilities should be empty in the api container.
docker exec local-ai-api capsh --print | grep "Current:"
# expect: Current:           — (i.e. no bounded caps)

# Phase 7.2 — privilege escalation blocked.
docker inspect local-ai-api | jq '.[0].HostConfig.SecurityOpt'
# expect: ["no-new-privileges:true", ...]

# Phase 7.2 — /tmp is the bounded tmpfs (not the container root FS).
docker exec local-ai-api findmnt /tmp
# expect: tmpfs, size=128M
```

### 4. Verify the deployment + arch detection

```bash
curl -s http://localhost:8000/api/system/architecture | jq
# expect:
#   .arch.name = "gpu_nvidia_single"   (single 24 GB GPU)
#   .deployment.mode = "container"
#   .deployment.effective_memory_gb ≈ 76 GB  (96 × 0.8 host headroom)
#   .deployment.mcp_overhead_gb = 0.0  (no runners yet)
```

The 76 GB effective figure is the **Phase 6** integration showing up — as
soon as a workflow spawns a warm MCP runner, this number drops by the
runner's live RSS.

### 5. Verify the extensions overview surfaces the user layer

```bash
curl -s http://localhost:8000/api/system/extensions | jq
# expect:
#   .deployment = "container"
#   .plugin_paths.system = "/app/plugins"           (system layer, RO)
#   .plugin_paths.user = "/app/data/plugins"        (user layer, RW)
#   .plugin_paths.user_writable = true
#   .mcp.registry_path = "/app/data/mcp/servers.json"  (Phase 1.3)
#   .mcp.binaries_dir = "/app/data/mcp/binaries"
#   .mcp.pool.active_runners = 0
```

The `/app/data/*` paths are the bind-mounted volume — they survive
`docker compose down && up --force-recreate`. Verify by installing a
test plugin and recreating the container.

## What to actually run

### Bench 1: a 70B workflow without MCPs (cold-load baseline)

```yaml
# bench-baseline.yaml
id: bench-70b-baseline
name: 70B Baseline
defaults: {role: reasoning}
steps:
  - id: think
    name: think
    model: llama3.3:70b
    est_size_gb: 40.0
    system_prompt: "Reason out loud about this prompt."
    inputs: [seed.task]
    outputs: [thoughts]
```

```bash
ollama pull llama3.3:70b   # one-time
curl -s -H "Authorization: Bearer $KEY" \
  -X POST http://localhost:8000/api/workflows/run-async \
  -H "Content-Type: application/json" \
  -d '{"definition_yaml": $(cat bench-baseline.yaml), "seed": {"task": "Explain BVH traversal"}}'
```

Watch `/api/system/pressure` while it runs — VRAM should saturate during
load, then steady at ~22 GB resident. Throughput target: ~5 tok/s (matches
the README's 70B figure).

### Bench 2: 70B + filesystem-MCP (Phase 2 warm pool)

Register a filesystem MCP first:

```bash
curl -s -X POST -H "Authorization: Bearer $KEY" \
  http://localhost:8000/api/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{"id":"filesystem-local","name":"FS","transport":"stdio",
       "command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","/tmp"]}'
```

Then declare a workflow with the MCP tool invoker:

```yaml
# bench-mcp.yaml
id: bench-70b-with-mcp
name: 70B + MCP
defaults: {required_mcps: [filesystem-local]}
steps:
  - id: read
    name: read
    model: llama3.3:70b
    est_size_gb: 40.0
    system_prompt: "Summarize {{ s1.file_contents }}"
    inputs: [s1.file_contents]
    outputs: [summary]
    hooks:
      before_step:
        - name: mcp_tool_invoker
          config:
            server_id: filesystem-local
            tool_name: read_file
            store_as: file_contents
            params_from: {path: "seed.target"}
```

After a run, hit `/api/workflows/runs/{run_id}`:

```bash
curl -s -H "Authorization: Bearer $KEY" http://localhost:8000/api/workflows/runs/$RUN_ID | jq '{
  total_overhead: .extension_overhead_seconds,
  mcp_calls: .mcp_invocations_total,
  servers_used: .mcp_servers_used,
  runners: [.mcp_runners[] | {server_id, requests_handled, peak_rss_mb, avg_response_ms}]
}'
```

Expectations:
- `mcp_invocations_total ≥ 1` (the `mcp_tool_invoker` hook ran once)
- `mcp_servers_used = ["filesystem-local"]`
- `runners[0].requests_handled ≥ 1` and `peak_rss_mb` reported as a number
- `runners[0].avg_response_ms < 50` (warm pool — no per-call handshake)

### Bench 3: co-scheduler contention trip

Drop a deliberately too-large model size and watch the recommendation fire:

```yaml
# bench-contention.yaml
defaults: {co_scheduling_policy: recommend}
steps:
  - id: hog
    name: hog
    model: oversized:999b
    est_size_gb: 80.0           # > 76 × 0.85 ≈ 65 GB threshold → contention
    role: coding
    archetype: bash_script
    system_prompt: "..."
    outputs: [out]
```

```bash
curl -s -X POST -H "Authorization: Bearer $KEY" \
  http://localhost:8000/api/workflows/validate \
  -H "Content-Type: application/json" \
  -d '{"definition": '"$(yq -o json . bench-contention.yaml)"'}'
```

Expect a 200 with `optimization_recommendations[]` populated; the action
should be `recommend_smaller_model` (in-archetype) when ROLE_PATTERNS
includes a smaller coding option, else `recommend_split_step` or `block_with_error`.

Bump `co_scheduling_policy` to `reject` and re-run — should return 422.

### Bench 4: circuit breaker (Phase 3) under a misbehaving MCP

Use the fake server fixture from the test suite (`tests/mocks/mcp/fake_server.py`)
with the `FAKE_MCP_CRASH_ON_REQUEST` env var to force crashes:

```bash
curl -s -X POST -H "Authorization: Bearer $KEY" \
  http://localhost:8000/api/mcp/servers \
  -d '{"id":"crashy","name":"Crashy","transport":"stdio",
       "command":"python","args":["/app/tests/mocks/mcp/fake_server.py"],
       "env":{"FAKE_MCP_CRASH_ON_REQUEST":"1"}}'
```

Drive 4 tool calls through it. The breaker should open on the 3rd
consecutive failure; the 4th call should fast-fail with
`MCPCircuitBreakerOpenError` without touching the wire. The runner stats
on the eventual run record will show `circuit_breaker_tripped: true` and
`health_check_failures` if a monitor was active.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `effective_memory_gb` is suspiciously low | Container has a tight cgroup `memory.max`; raise it in compose or your Docker Desktop settings |
| `mcp_overhead_gb > 0` after no workflow ran | A previous run leaked — `docker compose restart api`; the engine's `_safe_drain_mcp_pool` should prevent this so file a repro if it persists |
| 70B model OOMs at load | `est_size_gb` lying — bump it or pull the Q3_K_M quant instead of Q4_K_M (the README's quant guidance) |
| Plugin install endpoint 500s | `/app/data/plugins` not writable from inside the container — verify the bind-mount in `docker-compose.yml` and `chmod 0700 ./data` on the host |
| `/api/system/extensions` returns 503 | `detect_deployment()` didn't run at startup — check `api/main.py` startup logs; usually means container detection failed (check `/.dockerenv`) |

## Related

- [Container security defaults](../../docker-compose.yml) (Phase 7.2 comment block)
- [DMG security posture](dmg-mcp-security.md) (Phase 7.3)
- [MCP & Skills implementation plan](../plans/2026-05-19-mcp-skills-instrumentation-implementation.md) — status table maps every PR to its phase
- [Architecture-aware orchestration](../plans/2026-05-19-architecture-aware-orchestration-design.md) — the foundation Phase 6 builds on
