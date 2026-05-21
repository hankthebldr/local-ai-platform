# Ollama Version Pinning

**Pinned baseline:** `ollama/ollama:0.23.4`

Set in [`docker-compose.yml`](../../docker-compose.yml). All architecture-aware orchestration features (introduced 1.3.0) require this version or newer.

## Why pin

`:latest` drifts. A working production deployment can break overnight when a new Ollama release changes payload shape, response field naming, or scheduler defaults. Pinning is the standard production discipline.

## Feature surface required

Every feature below is consumed by the architecture-aware orchestration code (introduced 1.3.0 per [`docs/plans/2026-05-19-architecture-aware-orchestration-design.md`](../plans/2026-05-19-architecture-aware-orchestration-design.md)).

| Feature | Endpoint / parameter | Floor version | Confirmed in 0.23.4 |
|---|---|---|---|
| Per-request `keep_alive` | `POST /api/generate` payload `keep_alive` field | 0.1.x | ✅ |
| Loaded-model listing | `GET /api/ps` | 0.1.32 | ✅ |
| Model metadata introspection | `GET /api/show` | 0.1.x | ✅ |
| Multi-GPU spread placement | `OLLAMA_SCHED_SPREAD=1` env | 0.1.40 | ✅ |
| Per-request GPU pinning | `options.main_gpu` in generate payload | 0.1.x (best-effort) | ✅ |
| Max-loaded-models cap | `OLLAMA_MAX_LOADED_MODELS` env | 0.1.33 | ✅ |
| Per-runner concurrency cap | `OLLAMA_NUM_PARALLEL` env | 0.1.33 | ✅ |
| Load duration in response | `load_duration` field on generate response | 0.1.x | ✅ |
| Server version probe | `GET /api/version` | 0.1.x | ✅ |

## Detector floor enforcement

The architecture detector in [`api/services/architecture.py`](../../api/services/architecture.py) probes `GET /api/version` at startup and applies these rules:

| Version range | Behavior |
|---|---|
| Unreachable | `deployment.ollama_reachable = false`; logs warning; downstream phases run in degraded mode |
| `< 0.20` | Refuse to start in STRICT mode; in lenient mode warn and disable Phase 5 features |
| `0.20` – `0.23.3` | Warn that Phase 5 (pre-warm, multi-GPU placement) may degrade |
| `>= 0.23.4` | Full feature set supported |
| `>= 1.0` | Forward-compat unknown; log warning, continue |

## Upgrade procedure

```bash
# 1. Stop the stack
docker-compose down

# 2. Bump the pin in docker-compose.yml
#    (edit ollama service's image tag)

# 3. Pull the new tag
docker-compose pull ollama

# 4. Bring the stack back up
docker-compose up -d

# 5. Verify version
curl -s http://localhost:11434/api/version
# expect: {"version":"<new-version>"}

# 6. Run the Enclave system check
KEY="$(cat data/config/first-run-key.txt 2>/dev/null || echo $ENCLAVE_API_KEY)"
curl -s -H "Authorization: Bearer $KEY" http://localhost:8000/api/system/architecture | jq '.ollama'
# expect: {"version":"<new-version>","reachable":true}
```

## What changes when bumping versions

| If you bump to... | Re-verify... |
|---|---|
| 0.23.x patch | Re-run the integration suite (`pytest tests/integration -v`); no schema changes expected |
| 0.24.x minor | Re-verify `keep_alive: "0"` evicts at response end (atomic semantics); check `load_duration` field still present on generate response; check `/api/show` response shape |
| 1.0.x major | Treat as new floor; bump `OLLAMA_VERSION_FLOOR` in the detector code; re-run full Phase 1 gate |

## Operator override

To run a different version intentionally (e.g. for testing a new release):

```bash
export ENCLAVE_OLLAMA_VERSION_FLOOR="0.22.0"  # lower the floor
docker-compose up -d
```

The detector reads `ENCLAVE_OLLAMA_VERSION_FLOOR` from the api container's env. Default is `0.23.4`.
