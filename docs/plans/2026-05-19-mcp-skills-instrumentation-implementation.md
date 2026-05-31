# MCP & Skills Instrumentation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Use `workflow-engine-expert` subagent for any task touching `api/services/workflow_engine.py`, `step_executor.py`, `workflow_compiler.py`.

**Paired design doc:** [2026-05-19-mcp-skills-instrumentation-design.md](2026-05-19-mcp-skills-instrumentation-design.md)
**Depends on:** [2026-05-19-architecture-aware-orchestration-implementation.md](2026-05-19-architecture-aware-orchestration-implementation.md) Phase 1 (Deployment abstraction). Do not start this plan's Phase 1 until that lands.

**Goal:** Add deployment-aware storage layering, **step-scoped MCP runners with compiler-promoted region-scoping**, per-step skill + MCP instrumentation, a **resource-maximization compiler pass** that flags MCP/heavy-model contention, declarative pre-flight validation, and resource accounting that integrates with the arch scheduler — extending the existing plugin / skills / MCP infrastructure ([api/routers/plugins.py](../../api/routers/plugins.py), [api/routers/skills.py](../../api/routers/skills.py), [api/routers/mcp.py](../../api/routers/mcp.py), [api/services/plugin_service.py](../../api/services/plugin_service.py), [api/services/mcp_service.py](../../api/services/mcp_service.py)).

**Architecture summary:** PluginService and MCPService gain a two-tier path resolver (system / user, dispatched through `Deployment.current()`). MCPService gains a `MCPRunnerPool` keyed by `(workflow_run_id, server_id)`. step_executor wraps every step with skill-activation + MCP-call telemetry capture. workflow_compiler extends validate with extension reachability checks. The arch scheduler consumes a new `MCPService.total_runner_overhead_mb()` to adjust effective memory budget.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, psutil (RSS sampling), existing PluginService + MCPService + step_executor, pytest with deployment mock fixtures from the arch plan.

### Phase summary

| Phase | Title | Gate criteria |
|---|---|---|
| 1 | Deployment-aware storage layering | PluginService and MCPService discover from system + user layers; user-layer plugins persist across DMG reinstall and container rebuild; API responses include `origin` |
| 2 | Step-scoped MCP runners + compiler region promotion | Default: spawn-per-step, evict at step end. Compiler emits `MCPLifecycleDirective` per step; contiguous same-MCP runs without heavy-model intervening get promoted to region. Zero zombies. Zero MCP residency when a heavy-model step is loading. |
| 2b | Resource-maximization compiler pass | Compiler computes per-step `combined_pressure_gb`; emits `optimization_recommendations` per the `co_scheduling_policy`; `STRICT_OPTIMIZATION` blocks compile on unresolved contention. |
| 3 | MCP health monitoring + circuit breaker | Dead/hung MCPs detected within 30 s; circuit breaker after 3× failure; failed health doesn't crash workflow |
| 4 | Per-step skill + MCP instrumentation | StepResult carries `skills_activated`, `mcp_calls`, `plugin_tools_called`; WorkflowRun aggregates surface correctly |
| 5 | Declarative pre-flight validation | `required_plugins` / `required_mcps` honored at validate; workflow refuses to run if errors |
| 6 | Resource accounting + arch integration | MCP RSS sampled at 1 Hz; arch scheduler's `effective_memory_gb` reduced by MCP overhead during workflow runs |
| 7 | Deployment-specific security defaults + extensions endpoint | Container `cap_drop`, DMG entitlements documented; `/api/system/extensions` returns deployment-correct paths |

---

## Status & execution-flow reconciliation (updated 2026-05-29)

This plan was drafted 2026-05-19, before the multi-agent workflow taxonomy
landed. Two things changed under it; the remaining phases must build on the
*shipped* shape, not the draft's assumptions.

**1. The step model is now `kind`-discriminated, not a single `AgentStep` path.**
Steps carry a `kind` discriminator (`llm`, `parallel`, `loop`, `a2a`,
`orchestrator`, `consolidate`, `ralph`) and dispatch through lazily-imported
per-kind modules under `api/services/engine_executors/`. Consequences for the
unstarted phases:

- **Phase 4 (instrumentation)** attaches `skills_activated` / `mcp_calls` /
  `plugin_tools_called` to the `StepResult` that *every* kind already returns;
  capture lives in `step_executor` (the `kind: llm` leaf path) and is
  aggregated up by `workflow_engine` regardless of kind. Composite kinds
  (`parallel`, `loop`) roll up their children's extension stats the same way
  they already roll up token counts.
- **Phase 5 (tool/skill refs)** — `tools[]` / `skills[]` / `archetype` are
  fields on the `kind: llm` leaf step. Pre-flight validation walks every
  leaf step regardless of nesting (parallel branches, loop bodies).
- **Phase 2/2b/2c** — the runner pool keys on `(workflow_run_id, server_id)`,
  which is kind-agnostic. The co-scheduler's pressure walk iterates the
  flattened leaf-step order the compiler already produces.

**2. Execution is sequential by default — already the shipped contract.**
The arch-aware orchestration work (PRs #88–#103) made sequential execution the
default with freshness-by-default eviction. The design's "execution model:
sequential by default" section and the removal of `force_serialize` are
therefore already satisfied; no engine change is needed to honor them.

**Phase-by-phase status:**

| Phase / Task | Status | Notes |
|---|---|---|
| 1.1 Deployment storage roots | ✅ shipped | `system_storage_root` / `user_storage_root` / `ensure_user_storage()` landed with the deployment abstraction (arch work) |
| 1.2 PluginService two-layer discovery | ✅ shipped | `scan_plugins()` walks system→user, emits `origin` + `overrides_system` |
| 1.3 MCPService user-layer storage + migration | ✅ this PR | registry → `user_storage_root/mcp/servers.json`; `binaries_dir`; one-time legacy `data/config` migration; `has_server` / `has_tool` / `is_reachable` pre-flight helpers |
| 1.4 Install/uninstall endpoints + origin | ✅ PR #116 | `POST /api/plugins/install` (tarball→user layer, traversal-guarded), `DELETE /api/plugins/{id}` (system-layer protected, 403), `origin` surfaced; router now resolves both layers from the deployment |
| 2.1 `MCPRunnerPool` service | ✅ this PR | Warm stdio runner + HTTP session, keyed on `(run_id, server_id)`; `acquire` / `release_server` (step-scope) / `release_workflow` (workflow-scope); `total_runner_overhead_mb` for the Phase 6 arch hook; module singleton via `get_mcp_runner_pool()` |
| 2.2 Wire pool into MCPService | ✅ PR #117 | `MCPService.invoke_tool(run_id=…, scope=…)` routes through the pool; legacy run_id-less callers (the direct router endpoint) still use the cold path |
| 2 engine-side wiring | ⬜ deferred to Phase 5 | Today no step kind invokes MCPs directly — there's no `tools[]` field on `AgentStep` yet. When Phase 5 lands that schema, `step_executor` passes `workflow_run.run_id` to `invoke_tool` and `workflow_engine` calls `pool.release_workflow` in a `finally` block; the pool is already shaped for that integration |
| 2b Compiler region promotion | ⬜ not started | Default ships as workflow-scope; promotion needs the leaf-step pressure walk from Phase 2b |
| 3.1 Periodic health checks + circuit breaker | ✅ PR #118 | `CircuitBreaker` primitive composed into each runner (trips at N consecutive failures, fast-fails subsequent calls without touching the wire); `runner.health_check()` probes via `tools/list` and resets the breaker on success; opt-in `pool.start_health_monitor(interval_s)` daemon thread sweeps every live runner periodically; `MCPRunnerStats.{health_check_failures,circuit_breaker_tripped}` surface in run summaries |
| 5.1 Schema additions (`tools[]` / `skills[]` / `archetype` on `AgentStep`, `required_plugins` / `required_mcps` / `skill_injection` on `WorkflowDefaults`) | ✅ PR #119 | `ToolRef` Pydantic model (exactly one of `plugin` / `mcp`, dotted form); fields default to empty/None so every pre-Phase-5 workflow validates unchanged |
| 5.2 Validate-time reachability checks | ✅ PR #119 | `api/services/extension_preflight.py` walks every leaf step recursively (top-level + parallel branches + loop body + ralph body + orchestrator workers + gather); missing plugin/MCP/tool → error (refuses run); registered-but-unreachable MCP, missing-skill plugin, malformed skill ref → warning surfaced in the validate response body; `STRICT_VALIDATION=true` promotes warnings to errors |
| 7.1 `/api/system/extensions` endpoint | ✅ this PR | One-stop GET surfaces deployment-resolved plugin paths (system + user, with `user_writable` probe), MCP registry path + binaries dir (from Phase 1.3), live runner-pool state (active count, total RSS overhead, per-runner snapshot from Phase 2), and cache paths; returns 503 when `detect_deployment()` hasn't run yet |
| 4, 6, 7.2 + 7.3 | ⬜ not started | see reconciliation above |

**Mac/Linux form-factor resolution (confirmed):**

| Deployment | system layer | user layer (writable, persists) | MCP registry |
|---|---|---|---|
| `dmg_native` (Mac) | `Enclave.app/Contents/Resources` | `~/Library/Application Support/Enclave` | `…/Enclave/mcp/servers.json` |
| `container` (Linux) | `/app` | `/app/data` (bind-mount) | `/app/data/mcp/servers.json` |
| `host_native` (Mac/Linux dev) | cwd | `~/.enclave` | `~/.enclave/mcp/servers.json` |

---

## Phase 1: Deployment-Aware Storage Layering

### Task 1.1: Extend `Deployment` Protocol with system and user storage roots

**Files:**
- Edit: `api/services/deployment.py`
- Edit: `api/services/deployment_impl/dmg.py`
- Edit: `api/services/deployment_impl/container.py`
- Edit: `api/services/deployment_impl/host_native.py`
- Edit: `tests/test_deployment_impls.py`

**Step 1: Write the failing tests**

```python
def test_dmg_storage_layers():
    with patch_dmg(home="/Users/test"):
        from api.services.deployment_impl.dmg import DmgDeployment
        d = DmgDeployment.detect()
        assert d.system_storage_root.as_posix().endswith("Enclave.app/Contents/Resources")
        assert d.user_storage_root.as_posix() == "/Users/test/Library/Application Support/Enclave"

def test_container_storage_layers():
    with patch_container():
        from api.services.deployment_impl.container import ContainerDeployment
        d = ContainerDeployment.detect()
        assert d.system_storage_root.as_posix() == "/app"
        assert d.user_storage_root.as_posix() == "/app/data"

def test_host_native_storage_layers():
    with patch_host_native(cwd="/home/test/enclave"):
        from api.services.deployment_impl.host_native import HostNativeDeployment
        d = HostNativeDeployment.detect()
        assert d.system_storage_root.as_posix() == "/home/test/enclave"
        assert d.user_storage_root.as_posix() == str(Path.home() / ".enclave")

def test_user_storage_root_created_on_first_access():
    with patch_dmg(home="/Users/test"):
        d = DmgDeployment.detect()
        # First access should create the directory
        plugins_dir = d.user_storage_root / "plugins"
        d.ensure_user_storage()
        assert plugins_dir.exists()
        assert plugins_dir.stat().st_mode & 0o700  # at least user-rwx
```

**Step 2: Implement**

In `deployment.py` Protocol:

```python
class Deployment(Protocol):
    # ... existing fields ...
    system_storage_root: Path     # read-only, ships with app/image
    user_storage_root: Path       # writable, persists across updates

    def ensure_user_storage(self) -> None:
        """Create user_storage_root/{plugins,mcp/binaries,cache} with 0700 if missing."""
        ...
```

Per-impl:
- `DmgDeployment.system_storage_root = Path(sys._MEIPASS) / "Resources"` (py2app) or app bundle Resources path.
- `DmgDeployment.user_storage_root = Path.home() / "Library/Application Support/Enclave"`.
- `ContainerDeployment.system_storage_root = Path("/app")`.
- `ContainerDeployment.user_storage_root = Path("/app/data")`.
- `HostNativeDeployment.system_storage_root = Path.cwd()`.
- `HostNativeDeployment.user_storage_root = Path.home() / ".enclave"`.
- `ensure_user_storage()` creates `plugins/`, `mcp/binaries/`, `cache/` with `mkdir(parents=True, exist_ok=True, mode=0o700)`.

**Step 3: Verify**

```bash
pytest tests/test_deployment_impls.py -v -k storage
```

---

### Task 1.2: PluginService discovers from both layers

**Files:**
- Edit: `api/services/plugin_service.py`
- Edit: `tests/test_plugin_service.py` (new tests)

**Step 1: Write the failing tests**

```python
def test_plugin_discovery_walks_both_layers(tmp_path):
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"
    system.mkdir(parents=True)
    user.mkdir(parents=True)

    # System ships "ootb-plugin"
    (system / "ootb-plugin").mkdir()
    (system / "ootb-plugin" / "plugin.yaml").write_text("id: ootb-plugin\nname: OOTB\nversion: 1.0\nskills: []\ntools: []\n")

    # User installs "my-plugin"
    (user / "my-plugin").mkdir()
    (user / "my-plugin" / "plugin.yaml").write_text("id: my-plugin\nname: Mine\nversion: 1.0\nskills: []\ntools: []\n")

    service = PluginService(system_dir=system, user_dir=user)
    plugins = service.scan_plugins()
    ids = {p["id"]: p for p in plugins}
    assert "ootb-plugin" in ids
    assert "my-plugin" in ids
    assert ids["ootb-plugin"]["origin"] == "system"
    assert ids["my-plugin"]["origin"] == "user"

def test_user_plugin_overrides_system_on_same_id(tmp_path):
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"
    (system / "shared").mkdir(parents=True)
    (system / "shared" / "plugin.yaml").write_text("id: shared\nname: SystemShared\nversion: 1.0\nskills: []\ntools: []\n")
    (user / "shared").mkdir(parents=True)
    (user / "shared" / "plugin.yaml").write_text("id: shared\nname: UserShared\nversion: 2.0\nskills: []\ntools: []\n")

    service = PluginService(system_dir=system, user_dir=user)
    plugins = {p["id"]: p for p in service.scan_plugins()}
    assert plugins["shared"]["name"] == "UserShared"
    assert plugins["shared"]["origin"] == "user"
    assert plugins["shared"]["overrides_system"] is True
```

**Step 2: Implement**

```python
class PluginService:
    def __init__(
        self,
        system_dir: Optional[Path] = None,
        user_dir: Optional[Path] = None,
    ):
        # Default to deployment-resolved paths
        if system_dir is None or user_dir is None:
            from .deployment import Deployment
            d = Deployment.current()
            system_dir = system_dir or (d.system_storage_root / "plugins")
            user_dir = user_dir or (d.user_storage_root / "plugins")
        self._system_dir = system_dir
        self._user_dir = user_dir
        self._plugins: dict = {}
        self._tools: dict = {}

    def scan_plugins(self) -> list:
        self._plugins.clear()
        self._tools.clear()
        # Walk system first, then user; user overrides on id collision
        for layer, base in [("system", self._system_dir), ("user", self._user_dir)]:
            if not base.exists():
                continue
            for plugin_dir in base.iterdir():
                if not plugin_dir.is_dir():
                    continue
                manifest_path = plugin_dir / "plugin.yaml"
                if not manifest_path.exists():
                    continue
                manifest = yaml.safe_load(manifest_path.read_text())
                pid = manifest["id"]
                overrides_system = pid in self._plugins
                self._plugins[pid] = {
                    **manifest,
                    "origin": layer,
                    "overrides_system": overrides_system if layer == "user" else False,
                    "_path": str(plugin_dir),
                }
                # Load tools from the winning layer only
                self._load_tools(plugin_dir, pid)
        return list(self._plugins.values())
```

**Step 3: Verify**

```bash
pytest tests/test_plugin_service.py -v -k discovery
```

---

### Task 1.3: MCPService persists registry to user layer; binaries dir resolution

**Files:**
- Edit: `api/services/mcp_service.py`
- Edit: `tests/test_mcp_service.py`

**Step 1: Write the failing tests**

```python
def test_mcp_registry_at_user_storage(tmp_path):
    with patch_container_storage_layers(user=tmp_path / "data"):
        service = MCPService()
        assert service.storage_path == tmp_path / "data" / "mcp" / "servers.json"

def test_mcp_binaries_dir_under_user_storage(tmp_path):
    with patch_container_storage_layers(user=tmp_path / "data"):
        service = MCPService()
        assert service.binaries_dir == tmp_path / "data" / "mcp" / "binaries"
        assert service.binaries_dir.exists()  # created on first access

def test_mcp_registry_migrates_from_legacy_path(tmp_path):
    """If data/config/mcp_servers.json exists (legacy), migrate to user layer."""
    legacy = tmp_path / "data" / "config" / "mcp_servers.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('[{"id": "test", "transport": "stdio", "command": "echo"}]')

    user = tmp_path / "user_data"
    with patch_container_storage_layers(user=user), patch("os.getcwd", return_value=str(tmp_path)):
        service = MCPService()
        # Legacy file migrated
        assert (user / "mcp" / "servers.json").exists()
        # Service loaded the entries
        servers = service.list_servers()
        assert len(servers) == 1
```

**Step 2: Implement**

In `mcp_service.py`:

```python
def _storage_path(self) -> Path:
    from .deployment import Deployment
    return Deployment.current().user_storage_root / "mcp" / "servers.json"

def _binaries_dir(self) -> Path:
    from .deployment import Deployment
    d = Deployment.current().user_storage_root / "mcp" / "binaries"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d

def _migrate_legacy(self):
    """One-time migration from data/config/mcp_servers.json to user layer."""
    legacy = Path(os.getcwd()) / "data" / "config" / "mcp_servers.json"
    new = self.storage_path
    if legacy.exists() and not new.exists():
        new.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        new.write_text(legacy.read_text())
        new.chmod(0o600)
        logger.info(f"Migrated MCP registry: {legacy} → {new}")
```

Call `_migrate_legacy()` in `__init__` before `_load()`.

**Step 3: Verify**

```bash
pytest tests/test_mcp_service.py -v -k storage
```

---

### Task 1.4: Install / uninstall endpoints + origin in responses

**Files:**
- Edit: `api/routers/plugins.py`
- Edit: `api/routers/skills.py`
- Edit: `tests/test_plugin_router.py`

**Step 1: Write the failing tests**

```python
def test_plugin_list_includes_origin():
    client = TestClient(app)
    r = client.get("/api/plugins", headers={"Authorization": f"Bearer {MASTER_KEY}"})
    body = r.json()
    for p in body:
        assert "origin" in p
        assert p["origin"] in ("system", "user")

def test_plugin_install_writes_to_user_layer(tmp_path):
    plugin_tarball = make_test_plugin_tarball(tmp_path, id="my-test-plugin")
    client = TestClient(app)
    r = client.post(
        "/api/plugins/install",
        headers={"Authorization": f"Bearer {MASTER_KEY}"},
        files={"plugin": open(plugin_tarball, "rb")},
    )
    assert r.status_code == 200
    deployment = Deployment.current()
    assert (deployment.user_storage_root / "plugins" / "my-test-plugin").exists()

def test_plugin_delete_protects_system_layer():
    client = TestClient(app)
    # ootb plugin from system layer
    r = client.delete("/api/plugins/general-skills",
                      headers={"Authorization": f"Bearer {MASTER_KEY}"})
    assert r.status_code == 403
    body = r.json()
    assert "system-layer plugin cannot be deleted" in body["detail"]
```

**Step 2: Implement**

- `POST /api/plugins/install`: accepts a tarball (or zip), validates manifest, extracts to `user_storage_root / "plugins/" / <id>`. Validate signature stub (defer real check).
- `DELETE /api/plugins/{id}`: only removes from user layer; 403 if id only exists in system layer.
- All GET responses include `origin` field.

**Step 3: Verify**

```bash
pytest tests/test_plugin_router.py -v
```

---

### Phase 1 Gate

```bash
pytest tests/test_deployment_impls.py tests/test_plugin_service.py tests/test_mcp_service.py tests/test_plugin_router.py -v
```

Manual: container deployment — bind-mount `./data` to `/app/data`, install a plugin, `docker-compose down && up --force-recreate`, plugin still discovered.
DMG: build, install user plugin, upgrade DMG (re-run installer), user plugin still discovered.

---

## Phase 2: Step-Scoped MCP Runners + Compiler Region Promotion

**Phase intent:** Default is spawn-MCP-at-step-start, evict-at-step-end. Compiler walks the DAG and promotes contiguous same-MCP runs to region-scope **only when no heavy-model step intervenes**. The principle: at no moment when a model is loading should an MCP runner exist that the current step doesn't strictly require.

### Task 2.1: `MCPRunnerPool` service (step-scoped default)

**Files:**
- Create: `api/services/mcp_runner_pool.py`
- Create: `tests/test_mcp_runner_pool.py`

**Step 1: Write the failing tests**

```python
def test_pool_spawns_one_runner_per_server_per_workflow(mocked_stdio_mcp):
    pool = MCPRunnerPool()
    run_id = "run-123"
    pool.acquire(run_id, "filesystem-local")  # spawn
    pool.acquire(run_id, "filesystem-local")  # reuse
    pool.acquire(run_id, "filesystem-local")  # reuse
    assert mocked_stdio_mcp.spawn_count == 1

def test_pool_spawns_separate_runners_per_workflow(mocked_stdio_mcp):
    pool = MCPRunnerPool()
    pool.acquire("run-A", "filesystem-local")
    pool.acquire("run-B", "filesystem-local")
    assert mocked_stdio_mcp.spawn_count == 2

def test_pool_evicts_at_workflow_end(mocked_stdio_mcp):
    pool = MCPRunnerPool()
    pool.acquire("run-123", "filesystem-local")
    pool.release_workflow("run-123")
    # Give cleanup a moment
    import time; time.sleep(0.1)
    assert mocked_stdio_mcp.alive_count == 0

def test_pool_handles_runner_crash(mocked_stdio_mcp):
    pool = MCPRunnerPool()
    runner = pool.acquire("run-123", "filesystem-local")
    mocked_stdio_mcp.simulate_crash(runner.pid)
    # Next acquire should respawn
    runner2 = pool.acquire("run-123", "filesystem-local")
    assert runner2.pid != runner.pid
    assert mocked_stdio_mcp.spawn_count == 2

def test_pool_records_stats():
    pool = MCPRunnerPool()
    runner = pool.acquire("run-123", "filesystem-local")
    runner.call_tool("read_file", {"path": "/tmp/test"})
    runner.call_tool("read_file", {"path": "/tmp/test2"})
    pool.release_workflow("run-123")
    stats = pool.get_run_stats("run-123")
    assert stats[0].server_id == "filesystem-local"
    assert stats[0].requests_handled == 2
    assert stats[0].peak_rss_mb > 0
```

**Step 2: Implement**

```python
class MCPRunnerPool:
    def __init__(self):
        self._runners: dict[tuple[str, str], MCPRunner] = {}
        self._lock = threading.RLock()
        self._stats: dict[str, list[MCPRunnerStats]] = defaultdict(list)
        self._rss_sampler = RSSamplerThread(self)
        self._rss_sampler.start()

    def acquire(self, run_id: str, server_id: str) -> MCPRunner:
        with self._lock:
            key = (run_id, server_id)
            runner = self._runners.get(key)
            if runner is None or not runner.is_alive():
                runner = self._spawn(run_id, server_id, replacing=runner)
                self._runners[key] = runner
            return runner

    def release_workflow(self, run_id: str) -> None:
        with self._lock:
            to_close = [(k, r) for k, r in self._runners.items() if k[0] == run_id]
            for key, runner in to_close:
                stats = runner.close()
                self._stats[run_id].append(stats)
                del self._runners[key]

    def _spawn(self, run_id, server_id, replacing=None) -> "MCPRunner":
        config = MCPService.get_server(server_id)
        if config.transport == "stdio":
            return StdioMCPRunner.spawn(config, run_id)
        elif config.transport == "http":
            return HttpMCPSession.open(config, run_id)
        else:
            raise ValueError(f"Unknown transport: {config.transport}")

    def total_runner_overhead_mb(self) -> float:
        with self._lock:
            return sum(r.current_rss_mb() for r in self._runners.values())
```

`MCPRunner` is an abstract base. `StdioMCPRunner` keeps stdin/stdout pipes open, sends initialize once, reuses for subsequent tool calls. `HttpMCPSession` keeps an `httpx.Client` session.

**Step 3: Verify**

```bash
pytest tests/test_mcp_runner_pool.py -v
```

---

### Task 2.2: Wire pool into MCPService and step_executor

**Files:**
- Edit: `api/services/mcp_service.py`
- Edit: `api/services/step_executor.py`
- Edit: `api/services/workflow_engine.py`
- Edit: `tests/test_workflow_engine.py`

**Step 1: Write the failing test**

```python
def test_workflow_uses_pooled_runners(mocked_stdio_mcp):
    workflow = WorkflowDefinition(
        steps=[
            AgentStep(id="s1", tools=[{"mcp": "filesystem-local.read_file"}], ...),
            AgentStep(id="s2", tools=[{"mcp": "filesystem-local.list_dir"}], ...),
            AgentStep(id="s3", tools=[{"mcp": "filesystem-local.read_file"}], ...),
        ],
    )
    run = execute_workflow(workflow)
    assert mocked_stdio_mcp.spawn_count == 1   # one spawn for the workflow
    assert run.mcp_runners[0].server_id == "filesystem-local"
    assert run.mcp_runners[0].requests_handled == 3
    assert run.mcp_runners[0].closed_at is not None   # released at workflow end
```

**Step 2: Implement**

- `MCPService.invoke(server_id, tool, args, run_id=None)`: if `run_id` provided, route through `MCPRunnerPool.acquire(run_id, server_id)`; if not, fall back to the current spawn-per-call behavior (preserves API behavior for direct invocations).
- `step_executor`: pass `workflow_run.run_id` to every MCP invocation.
- `workflow_engine`: at run start, instantiate `MCPRunnerPool`; at run end (success or failure), call `pool.release_workflow(run_id)` and attach stats to `WorkflowRun.mcp_runners`.

**Step 3: Verify**

```bash
pytest tests/test_workflow_engine.py -v -k pool
```

---

### Phase 2 Gate

```bash
pytest tests/test_mcp_runner_pool.py tests/test_workflow_engine.py -v -k mcp
```

Manual: run a workflow with 5 MCP tool calls to the same server; `ps aux | grep <mcp-binary>` mid-run shows 1 process; after workflow completes, 0 processes.

---

## Phase 2b: Resource-Maximization Compiler Pass

### Task 2b.1: Per-step pressure computation

**Files:**
- Edit: `api/services/workflow_compiler.py`
- Create: `api/services/co_scheduler.py`
- Create: `tests/test_co_scheduler.py`

**Step 1: Write the failing test**

```python
def test_pressure_computation_per_step(mocked_unified_arch_96gb, mocked_mcp_sizes):
    mocked_mcp_sizes["filesystem-local"] = 12.0   # 12 GB RSS estimate
    workflow = WorkflowDefinition(steps=[
        AgentStep(id="s1", model="qwen2.5:1.5b", est_size_gb=2.0,
                  tools=[{"mcp": "filesystem-local.read_file"}]),
        AgentStep(id="s2", model="llama3.3:70b", est_size_gb=40.0),
    ])
    pressures = compute_pressures(workflow)
    # s1: 2 GB model + 12 GB MCP * 1.15 KV headroom = 16.3
    assert pressures["s1"].combined_pressure_gb == pytest.approx(16.3, abs=0.5)
    # s2: 40 GB model only (no MCPs declared); KV adds 15%
    assert pressures["s2"].combined_pressure_gb == pytest.approx(46.0, abs=1.0)
```

**Step 2: Implement**

```python
# api/services/co_scheduler.py
class StepPressure(BaseModel):
    step_id: str
    model_footprint_gb: float
    mcp_servers_in_use: list[str]
    mcp_peak_rss_gb_estimate: float
    combined_pressure_gb: float
    effective_budget_gb: float
    is_contention: bool


def compute_pressures(workflow: WorkflowDefinition) -> dict[str, StepPressure]:
    arch = Architecture.current()
    budget = arch.effective_memory_gb() * 0.85
    mcp_service = MCPService.current()
    pressures = {}
    for step in workflow.steps:
        model_gb = (step.est_size_gb or _lookup_model_size(step.model)) * 1.15  # KV headroom
        mcp_servers = [t.mcp.split(".")[0] for t in step.tools if t.mcp]
        mcp_gb = sum(mcp_service.peak_rss_gb_estimate(s) for s in mcp_servers)
        combined = model_gb + mcp_gb
        pressures[step.id] = StepPressure(
            step_id=step.id,
            model_footprint_gb=model_gb,
            mcp_servers_in_use=mcp_servers,
            mcp_peak_rss_gb_estimate=mcp_gb,
            combined_pressure_gb=combined,
            effective_budget_gb=budget,
            is_contention=combined > budget,
        )
    return pressures
```

**Step 3: Verify**

```bash
pytest tests/test_co_scheduler.py -v -k pressure
```

---

### Task 2b.2: Co-scheduling policy engine

**Files:**
- Edit: `api/services/co_scheduler.py`
- Edit: `tests/test_co_scheduler.py`

This task contains the **policy decision Henry shapes** (see request below the tests).

**Step 1: Write the failing tests**

```python
def test_policy_off_emits_nothing():
    pressures = {"s1": _contention_pressure()}
    recs = apply_co_scheduling_policy(pressures, policy="off", workflow=...)
    assert recs == []

def test_policy_recommend_emits_recommendations():
    pressures = {"s1": _contention_pressure(model="llama3.3:70b", mcps=["fs"])}
    recs = apply_co_scheduling_policy(pressures, policy="recommend", workflow=...)
    assert len(recs) >= 1
    assert recs[0].action in ("recommend_smaller_model", "recommend_split_step",
                              "recommend_reorder", "force_serialize")

def test_policy_reject_blocks_compile():
    pressures = {"s1": _contention_pressure()}
    with pytest.raises(CompilationError, match="co_scheduling_reject"):
        apply_co_scheduling_policy(pressures, policy="reject", workflow=...)

def test_policy_auto_substitute_replaces_model():
    pressures = {"s1": _contention_pressure(model="llama3.3:70b", mcps=["fs"])}
    workflow = _workflow_with_step_using("llama3.3:70b", role="reasoning")
    recs, rewrites = apply_co_scheduling_policy(
        pressures, policy="auto_substitute", workflow=workflow,
    )
    # Should pick a smaller "reasoning" role model that fits alongside fs
    assert any(r.type == "model_substitution" for r in rewrites)
    assert rewrites[0].new_model != "llama3.3:70b"
```

**Step 2: Implement**

Per operator policy (Henry, 2026-05-19): workflows execute sequentially; archetypes drive substitution; the action priority order is **archetype-aware substitute → split → reorder → block**. `force_serialize` is removed (sequential is the contract).

```python
class OptimizationRecommendation(BaseModel):
    step_id: str
    contention_pressure_gb: float
    available_budget_gb: float
    action: Literal[
        "recommend_smaller_model",
        "recommend_split_step",
        "recommend_reorder",
        "block_with_error",
    ]
    rationale: str
    suggested_substitution: Optional[str] = None       # smaller model name (in same archetype)
    suggested_split: Optional[dict] = None             # how to split the step
    suggested_reorder_position: Optional[int] = None   # new index in the chain
    archetype: Optional[str] = None                    # inferred or declared


def choose_action(
    pressure: StepPressure,
    step: AgentStep,
    workflow: WorkflowDefinition,
    arch: Architecture,
) -> OptimizationRecommendation:
    """
    Pick the right action when this step is in contention.

    Operator policy (Henry, 2026-05-19):
    - Workflows are sequential — no parallel concurrency to resolve.
    - Substitute within archetype before splitting.
    - Split before reorder, because reorder requires DAG slack which
      a sequential chain rarely has.
    - Never substitute across archetypes (a bash_script step stays a
      coding step; we shrink the coding model, we don't swap to a
      writing model).
    - Never split a step that has multiple declared tools — operator
      grouped them on purpose.
    - Block only when no in-archetype substitution fits AND step has
      bundled tools.
    """
    archetype = infer_archetype(step)   # may be None

    # 1. Archetype-aware substitution.
    if archetype is not None:
        smaller = pick_smaller_in_archetype(step.model, archetype, arch, pressure)
        if smaller is not None:
            return OptimizationRecommendation(
                step_id=step.id, action="recommend_smaller_model",
                contention_pressure_gb=pressure.combined_pressure_gb,
                available_budget_gb=pressure.effective_budget_gb,
                rationale=f"Archetype '{archetype}' has a smaller-in-role option that fits.",
                suggested_substitution=smaller, archetype=archetype,
            )

    # 2. Split, unless tools were grouped explicitly.
    if step.model and any(t.mcp for t in step.tools) and len(step.tools) == 1:
        return OptimizationRecommendation(
            step_id=step.id, action="recommend_split_step",
            contention_pressure_gb=pressure.combined_pressure_gb,
            available_budget_gb=pressure.effective_budget_gb,
            rationale="MCP + heavy model in one step; split into MCP-bound + model-bound steps.",
            suggested_split={
                "mcp_step": {"role": "lightweight", "tools": [t.dict() for t in step.tools]},
                "model_step": {"model": step.model, "tools": []},
            },
            archetype=archetype,
        )

    # 3. Reorder if chain has slack (heavy step can move to an MCP-free slot).
    new_pos = find_chain_slack(step, workflow, pressure)
    if new_pos is not None:
        return OptimizationRecommendation(
            step_id=step.id, action="recommend_reorder",
            contention_pressure_gb=pressure.combined_pressure_gb,
            available_budget_gb=pressure.effective_budget_gb,
            rationale=f"Chain has slack at position {new_pos} where MCPs are inactive.",
            suggested_reorder_position=new_pos, archetype=archetype,
        )

    # 4. Block — operator must rewrite.
    return OptimizationRecommendation(
        step_id=step.id, action="block_with_error",
        contention_pressure_gb=pressure.combined_pressure_gb,
        available_budget_gb=pressure.effective_budget_gb,
        rationale=(
            f"Step exceeds budget; no in-archetype substitute fits, "
            f"step has bundled tools (cannot split safely), chain has no slack."
        ),
        archetype=archetype,
    )
```

Three helper functions defined in this task:

- `infer_archetype(step)` — match step's (model_role, declared_tools, declared_skills) against `ARCHETYPES` registry; return archetype id or None.
- `pick_smaller_in_archetype(current_model, archetype, arch, pressure)` — walk the archetype's role pattern list in [model_resolver.py:19](../../api/services/model_resolver.py:19), pick the largest available model whose footprint < `pressure.effective_budget_gb - pressure.mcp_peak_rss_gb_estimate`. Return None if nothing fits.
- `find_chain_slack(step, workflow, pressure)` — walk the sequential chain; return earliest index where the step's heavy model could fit without any MCPs being active (because step-scoped MCPs would be evicted at the boundary). Return None if no such position.

**Step 3: Verify**

```bash
pytest tests/test_co_scheduler.py -v -k policy
```

---

## Phase 2c: `lightweight` role + step archetype registry

**Phase intent:** Provide the building blocks the co-scheduler policy relies on — a `lightweight` role pattern that resolves to small general-purpose models, and a step-archetype registry that codifies the (role + MCPs + skills) pairings.

### Task 2c.1: Add `lightweight` role to model resolver

**Files:**
- Edit: `api/services/model_resolver.py`
- Edit: `tests/test_model_resolver.py`

**Step 1: Write the failing tests**

```python
def test_lightweight_role_resolves_to_small_model(mocked_ollama_inventory):
    mocked_ollama_inventory.return_value = [
        {"name": "llama3.3:70b"},
        {"name": "qwen2.5:1.5b"},
        {"name": "phi:2.7b"},
    ]
    resolver = ModelResolver(...)
    assert resolver.resolve(role="lightweight") in ("qwen2.5:1.5b", "phi:2.7b")

def test_lightweight_falls_back_to_general_if_none_match():
    mocked_ollama_inventory.return_value = [{"name": "llama3.3:70b"}]
    resolver = ModelResolver(...)
    # No 1.5-3B model installed; lightweight falls back to general's match
    result = resolver.resolve(role="lightweight")
    assert result == "llama3.3:70b"  # only available

def test_step_without_model_defaults_to_lightweight_when_tool_bound():
    """A step with declared tools but no model declares 'lightweight' implicitly."""
    step = AgentStep(id="s1", system_prompt="...", inputs=[], outputs=[],
                     tools=[{"mcp": "fs.read_file"}], model=None, role=None)
    resolved = resolve_step_model(step, defaults=WorkflowDefaults())
    assert resolved == "lightweight" or _is_small_model(resolved)
```

**Step 2: Implement**

In [api/services/model_resolver.py:19](../../api/services/model_resolver.py:19), add to `ROLE_PATTERNS`:

```python
ROLE_PATTERNS: Dict[str, List[str]] = {
    "reasoning": ["deepseek-r1", "qwen3", "qwen2.5-coder", "nous-hermes"],
    "fast": ["dolphin3:8b", "mistral", "phi"],
    "coding": ["qwen3.5", "qwen2.5-coder", "deepseek-coder", "codellama", "dolphin"],
    "uncensored": ["dolphin", "uncensored", "abliterated", "nous-hermes"],
    "general": ["dolphin", "qwen", "mistral", "llama"],
    "lightweight": [               # NEW
        "qwen2.5:1.5b",
        "qwen2.5-coder:1.5b",
        "phi:2.7b",
        "phi",                     # any phi variant
        "llama3.2:3b",
        "gemma:2b",
        "qwen2.5:0.5b",
    ],
}
```

In `step_executor.py` (or wherever model resolution happens), add inference for tool-bound steps without a declared model:

```python
def resolve_step_model(step, defaults):
    if step.model:
        return resolver.resolve(model=step.model)
    if step.role:
        return resolver.resolve(role=step.role)
    if any(t.mcp or t.plugin for t in step.tools):
        # Tool-bound step with no model declared → lightweight
        return resolver.resolve(role="lightweight")
    if defaults.role:
        return resolver.resolve(role=defaults.role)
    return resolver.resolve(role="general")
```

**Step 3: Verify**

```bash
pytest tests/test_model_resolver.py -v -k lightweight
```

---

### Task 2c.2: Step archetype registry

**Files:**
- Create: `api/services/archetypes.py`
- Create: `tests/test_archetypes.py`

**Step 1: Write the failing tests**

```python
def test_archetype_inference_from_declared_tools():
    step = AgentStep(id="s1", role="coding", tools=[{"mcp": "bash-mcp.run"}], ...)
    assert infer_archetype(step) == "bash_script"

def test_archetype_inference_from_skills():
    step = AgentStep(id="s1", role="reasoning", tools=[],
                     skills=["xdm-toolkit.xdm-rule-writer"], ...)
    assert infer_archetype(step) == "xsiam_analysis"

def test_archetype_explicit_declaration_wins():
    step = AgentStep(id="s1", model="x", tools=[],
                     skills=[], archetype="documentation", ...)
    assert infer_archetype(step) == "documentation"

def test_archetype_companions_lookup():
    arch = get_archetype("bash_script")
    assert arch["default_role"] == "coding"
    assert "bash-mcp" in arch["companion_mcps"]
    assert "coder" in arch["companion_skills"]

def test_archetype_returns_none_for_unknown_pattern():
    step = AgentStep(id="s1", model="x", role=None, tools=[], skills=[], ...)
    assert infer_archetype(step) is None
```

**Step 2: Implement**

```python
# api/services/archetypes.py
from typing import Optional
from ..models.workflow_models import AgentStep

ARCHETYPES: dict[str, dict] = {
    "bash_script": {
        "default_role": "coding",
        "companion_mcps": ["bash-mcp", "filesystem-local"],
        "companion_skills": ["coder"],
        "trigger_mcps": ["bash-mcp"],         # any of these in tools → match
        "trigger_skills": [],
        "description": "Generate and execute shell scripts",
    },
    "code_review": {
        "default_role": "coding",
        "companion_mcps": [],
        "companion_skills": ["coder", "reviewer"],
        "trigger_mcps": [],
        "trigger_skills": ["reviewer"],
        "description": "Review diffs or PRs",
    },
    "documentation": {
        "default_role": "reasoning",
        "companion_mcps": ["web-search", "filesystem-local"],
        "companion_skills": ["research", "concise-writer"],
        "trigger_mcps": ["web-search"],
        "trigger_skills": ["research"],
        "description": "Write documentation from sources",
    },
    "research_brief": {
        "default_role": "reasoning",
        "companion_mcps": ["web-search"],
        "companion_skills": ["research"],
        "trigger_mcps": ["web-search"],
        "trigger_skills": ["research"],
        "description": "Topic investigation",
    },
    "extraction": {
        "default_role": "lightweight",
        "companion_mcps": [],
        "companion_skills": ["concise-writer"],
        "trigger_mcps": [],
        "trigger_skills": ["concise-writer"],   # ambiguous; needs more
        "description": "Pull structured data from text",
    },
    "synthesis": {
        "default_role": "reasoning",
        "companion_mcps": [],
        "companion_skills": ["concise-writer"],
        "trigger_mcps": [],
        "trigger_skills": [],                    # inferred only by step name patterns
        "description": "Combine prior outputs",
    },
    "data_lookup": {
        "default_role": "lightweight",
        "companion_mcps": ["filesystem-local", "rag"],
        "companion_skills": [],
        "trigger_mcps": ["filesystem-local", "rag"],
        "trigger_skills": [],
        "description": "Read a file or search a vector store",
    },
    "xsiam_analysis": {
        "default_role": "reasoning",
        "companion_mcps": [],
        "companion_skills": ["xdm-rule-writer", "xql-validator", "rag-query-crafter"],
        "trigger_mcps": [],
        "trigger_skills": ["xdm-rule-writer", "xql-validator"],
        "description": "XSIAM detection-engineering",
    },
    "triage": {
        "default_role": "lightweight",
        "companion_mcps": [],
        "companion_skills": ["concise-writer"],
        "trigger_mcps": [],
        "trigger_skills": [],
        "description": "First-pass classification",
    },
}


def infer_archetype(step: AgentStep) -> Optional[str]:
    """Match step against ARCHETYPES. Explicit declaration wins."""
    if step.archetype:
        return step.archetype if step.archetype in ARCHETYPES else None

    declared_mcps = {t.mcp.split(".")[0] for t in step.tools if t.mcp}
    declared_skills = {s.split(".")[-1] for s in step.skills}

    # Score each archetype by trigger overlap
    best, best_score = None, 0
    for name, spec in ARCHETYPES.items():
        score = (
            len(declared_mcps & set(spec["trigger_mcps"])) * 2 +
            len(declared_skills & set(spec["trigger_skills"]))
        )
        if step.role == spec["default_role"]:
            score += 1
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 2 else None


def get_archetype(name: str) -> dict:
    return ARCHETYPES.get(name, {})


def extend_archetypes(plugin_archetypes: dict[str, dict]) -> None:
    """Plugins can register archetypes via plugins/<id>/archetypes.yaml."""
    for name, spec in plugin_archetypes.items():
        if name in ARCHETYPES:
            logger.warning(f"Archetype '{name}' already registered; skipping override")
            continue
        ARCHETYPES[name] = spec
```

`AgentStep` gets an optional `archetype: Optional[str] = None` field (schema add).

**Step 3: Verify**

```bash
pytest tests/test_archetypes.py -v
```

---

### Task 2c.3: Composer-assist endpoint for archetype companions

**Files:**
- Edit: `api/routers/workflows.py`
- Create: `tests/test_workflow_composer_assist.py`

**Step 1: Write the failing tests**

```python
def test_composer_assist_suggests_companions_from_partial_step():
    """User declares an MCP; assist suggests the role + skills that complete the archetype."""
    partial = {"id": "s1", "tools": [{"mcp": "bash-mcp.run"}]}
    client = TestClient(app)
    r = client.post("/api/workflows/composer/assist", json=partial,
                    headers={"Authorization": f"Bearer {KEY}"})
    body = r.json()
    assert body["inferred_archetype"] == "bash_script"
    assert "coding" in body["suggested_role"]
    assert "coder" in body["suggested_skills"]

def test_composer_assist_warns_on_archetype_mismatch():
    """User declares role + tools that don't match any archetype well."""
    partial = {"id": "s1", "role": "coding", "tools": [{"mcp": "web-search.query"}]}
    r = client.post("/api/workflows/composer/assist", json=partial,
                    headers={"Authorization": f"Bearer {KEY}"})
    body = r.json()
    assert "archetype_mismatch" in [w["code"] for w in body["warnings"]]
```

**Step 2: Implement**

New endpoint `POST /api/workflows/composer/assist` accepts a partial `AgentStep` (any subset of fields) and returns:

```python
{
    "inferred_archetype": "bash_script" | None,
    "suggested_role": "coding",
    "suggested_mcps": ["bash-mcp"],          # not already declared
    "suggested_skills": ["coder"],           # not already declared
    "warnings": [{"code": "archetype_mismatch", "message": "..."}],
}
```

The composer UI calls this on every field edit to surface "logical companion" suggestions inline.

**Step 3: Verify**

```bash
pytest tests/test_workflow_composer_assist.py -v
```

---

### Phase 2c Gate

```bash
pytest tests/test_model_resolver.py tests/test_archetypes.py tests/test_workflow_composer_assist.py -v
```

Manual: in the composer UI (when shipped), declare a step with only `bash-mcp` as a tool; the UI should suggest `coding` role and `coder` skill as companions.

---

## Phase 3: MCP Health Monitoring + Circuit Breaker

### Task 3.1: Periodic health checks

**Files:**
- Edit: `api/services/mcp_runner_pool.py`
- Edit: `tests/test_mcp_runner_pool.py`

**Step 1: Write the failing tests**

```python
def test_health_check_fires_periodically(mocked_stdio_mcp):
    pool = MCPRunnerPool(health_check_interval_s=0.5)
    runner = pool.acquire("run-123", "filesystem-local")
    time.sleep(1.5)   # ~3 health checks
    assert mocked_stdio_mcp.tools_list_count >= 2

def test_circuit_breaker_after_three_failures(mocked_stdio_mcp):
    pool = MCPRunnerPool()
    mocked_stdio_mcp.fail_next_n_calls(3)
    runner = pool.acquire("run-123", "filesystem-local")
    for _ in range(3):
        runner.call_tool("read_file", {})   # all fail
    # 4th call: circuit broken, fast-fail without spawning
    with pytest.raises(MCPCircuitBreakerOpenError):
        runner.call_tool("read_file", {})
```

**Step 2: Implement**

- `MCPRunner.health_check()`: sends `tools/list` with short timeout. On failure, increments `health_check_failures`.
- Background `HealthCheckThread` runs every `health_check_interval_s` (default 30 s) — iterates pool runners, runs health check on each.
- `MCPRunner.call_tool()`: before sending, check `consecutive_errors >= 3`; if so, raise `MCPCircuitBreakerOpenError`.
- Health check success resets `consecutive_errors` to 0.

**Step 3: Verify**

```bash
pytest tests/test_mcp_runner_pool.py -v -k "health or circuit"
```

---

### Phase 3 Gate

```bash
pytest tests/test_mcp_runner_pool.py -v -k "health or circuit or timeout"
```

Manual: configure an MCP server pointing to a script that sleeps forever; verify timeout fires within `mcp_request_timeout_s`; circuit breaker opens after 3 timeouts.

---

## Phase 4: Per-Step Instrumentation

### Task 4.1: Extend `StepResult` and `WorkflowRun` schemas

**Files:**
- Edit: `api/models/workflow_models.py`
- Edit: `tests/test_workflow_models.py`

**Step 1: Write the failing tests**

```python
def test_step_result_instrumentation_fields():
    result = StepResult(
        step_id="s1",
        status="completed",
        skills_activated=[
            {"plugin_id": "general-skills", "skill_id": "concise-writer",
             "trigger": "keyword", "trigger_match": "concise",
             "injected_into": "system", "injected_chars": 524}
        ],
        mcp_calls=[
            {"server_id": "fs", "tool_name": "read_file",
             "duration_ms": 142.5, "status": "ok",
             "request_size_bytes": 50, "response_size_bytes": 1024}
        ],
        plugin_tools_called=[],
        extension_overhead_ms=142.5,
    )
    assert result.skills_activated[0].plugin_id == "general-skills"
    assert result.mcp_calls[0].duration_ms == 142.5

def test_workflow_run_aggregates():
    run = WorkflowRun(
        run_id="r1",
        workflow_id="w1",
        skills_activated_total=4,
        mcp_invocations_total=12,
        mcp_servers_used=["fs", "web-search"],
        extension_overhead_seconds=8.7,
    )
    assert run.skills_activated_total == 4
```

**Step 2: Implement**

Add Pydantic models per the design doc's instrumentation section (`SkillActivation`, `MCPCall`, `PluginToolCall`, `MCPRunnerStats`). Extend `StepResult` and `WorkflowRun` with the new fields, all defaulted to empty.

**Step 3: Verify**

```bash
pytest tests/test_workflow_models.py -v -k "instrumentation or activation"
```

---

### Task 4.2: Capture skill activations in step_executor

**Files:**
- Edit: `api/services/step_executor.py`
- Edit: `api/services/plugin_service.py`
- Edit: `tests/test_step_executor.py`

**Step 1: Write the failing test**

```python
def test_step_records_skill_activations(mocked_skill_match):
    mocked_skill_match.return_value = [
        ("general-skills", "concise-writer", "keyword", "concise", 524),
    ]
    step = AgentStep(id="s1", model="m", system_prompt="be concise", ...)
    result = step_executor.execute_step(step, context)
    assert len(result.skills_activated) == 1
    assert result.skills_activated[0].plugin_id == "general-skills"
    assert result.skills_activated[0].skill_id == "concise-writer"
    assert result.skills_activated[0].injected_chars == 524
```

**Step 2: Implement**

In `step_executor.py`:

```python
def execute_step(self, step, context):
    # ... existing prompt assembly ...

    # Skill activation phase
    activations = []
    if context.workflow.skill_injection != "off":
        matches = self.plugin_service.match_skills(
            text=prompt,
            allow_list=step.skills,                  # explicit step list, if any
            mode=step.skill_injection or context.workflow.skill_injection,
        )
        for m in matches:
            prompt = self._inject_skill(prompt, m.body, m.inject_position)
            activations.append(SkillActivation(
                plugin_id=m.plugin_id,
                skill_id=m.skill_id,
                trigger=m.trigger_type,
                trigger_match=m.trigger_match,
                injected_into=m.inject_position,
                injected_chars=len(m.body),
            ))

    # ... call ollama ...

    result.skills_activated = activations
    return result
```

`PluginService.match_skills(text, allow_list, mode)` returns SkillMatch objects given the configured mode (`auto` = keyword triggers; `manual` = no auto-injection; `explicit` = only matches from allow_list).

**Step 3: Verify**

```bash
pytest tests/test_step_executor.py -v -k skill
```

---

### Task 4.3: Capture MCP and plugin tool calls

**Files:**
- Edit: `api/services/mcp_service.py`
- Edit: `api/services/plugin_service.py`
- Edit: `api/services/step_executor.py`
- Edit: `tests/test_step_executor.py`

**Step 1: Write the failing test**

```python
def test_step_records_mcp_calls(mocked_mcp_pool):
    step = AgentStep(id="s1", tools=[{"mcp": "fs.read_file"}], ...)
    mocked_mcp_pool.simulate_tool_call("fs", "read_file", duration_ms=200, status="ok")
    result = step_executor.execute_step(step, context)
    assert len(result.mcp_calls) == 1
    call = result.mcp_calls[0]
    assert call.server_id == "fs"
    assert call.tool_name == "read_file"
    assert call.duration_ms == 200
    assert call.status == "ok"

def test_step_records_extension_overhead():
    # 200 ms skill + 800 ms mcp = 1000 ms overhead
    result = StepResult(...)
    result.skills_activated = [...]   # 200 ms inject time
    result.mcp_calls = [{"duration_ms": 800, ...}]
    # extension_overhead_ms computed from sum
    assert result.extension_overhead_ms == 1000
```

**Step 2: Implement**

- Wrap every MCP invocation and plugin tool invocation in a stopwatch + try/except.
- On success: append `MCPCall(status="ok", duration_ms=...)` or `PluginToolCall(status="ok", ...)`.
- On error: append with `status="error"` and the error_code; do not raise (return error to the prompt context as the tool result).
- Compute `extension_overhead_ms` as sum of all skill activation render time + MCP call durations + plugin tool durations.

**Step 3: Verify**

```bash
pytest tests/test_step_executor.py -v -k "mcp_call or plugin_tool or overhead"
```

---

### Task 4.4: Aggregate at run-level

**Files:**
- Edit: `api/services/workflow_engine.py`
- Edit: `tests/test_workflow_engine.py`

**Step 1: Write the failing test**

```python
def test_run_aggregates_extension_stats():
    workflow = WorkflowDefinition(steps=[...])   # 3 steps each with skill + mcp activity
    run = execute_workflow(workflow)
    assert run.skills_activated_total == sum(len(s.skills_activated) for s in run.step_results)
    assert run.mcp_invocations_total == sum(len(s.mcp_calls) for s in run.step_results)
    assert set(run.mcp_servers_used) == {s.server_id for sr in run.step_results for s in sr.mcp_calls}
    assert run.extension_overhead_seconds == pytest.approx(
        sum(s.extension_overhead_ms for s in run.step_results) / 1000
    )
```

**Step 2: Implement**

After workflow completes in `workflow_engine.py`:

```python
run.skills_activated_total = sum(len(s.skills_activated) for s in run.step_results)
run.mcp_invocations_total = sum(len(s.mcp_calls) for s in run.step_results)
run.plugin_tools_invoked_total = sum(len(s.plugin_tools_called) for s in run.step_results)
run.mcp_servers_used = sorted({
    c.server_id for s in run.step_results for c in s.mcp_calls
})
run.extension_overhead_seconds = sum(
    s.extension_overhead_ms for s in run.step_results
) / 1000.0
# mcp_runners populated by MCPRunnerPool.release_workflow(run_id) (Phase 2)
```

**Step 3: Verify**

```bash
pytest tests/test_workflow_engine.py -v -k aggregate
```

---

### Phase 4 Gate

```bash
pytest tests/test_workflow_models.py tests/test_step_executor.py tests/test_workflow_engine.py -v -k "skill or mcp or extension"
```

Manual: run a workflow that uses general-skills + an MCP server; inspect `/api/workflows/runs/{id}` response — should show non-zero `skills_activated_total` and `extension_overhead_seconds`.

---

## Phase 5: Declarative Pre-flight Validation

### Task 5.1: Schema additions for `required_plugins`, `required_mcps`, step-level `tools`/`skills`

**Files:**
- Edit: `api/models/workflow_models.py`
- Edit: `tests/test_workflow_models.py`

**Step 1: Write the failing tests**

```python
def test_workflow_required_plugins_field():
    workflow = WorkflowDefinition(
        defaults=WorkflowDefaults(required_plugins=["xdm-toolkit"], required_mcps=["fs"]),
        steps=[],
    )
    assert workflow.defaults.required_plugins == ["xdm-toolkit"]

def test_step_tools_field_accepts_plugin_and_mcp_refs():
    step = AgentStep(
        id="s1", model="m", system_prompt="...", inputs=[], outputs=[],
        tools=[
            {"plugin": "xdm-toolkit.lookup_xdm_path"},
            {"mcp": "fs.read_file"},
        ],
        skills=["xdm-toolkit.xdm-rule-writer"],
    )
    assert len(step.tools) == 2
    assert step.tools[0].plugin == "xdm-toolkit.lookup_xdm_path"
    assert step.tools[1].mcp == "fs.read_file"
```

**Step 2: Implement**

Add `WorkflowDefaults.required_plugins: list[str]`, `required_mcps: list[str]`, `mcp_request_timeout_s: int = 30`, `mcp_warmup_at_run_start: bool = True`.

Add to `AgentStep`:

```python
class ToolRef(BaseModel):
    plugin: Optional[str] = None     # "<plugin_id>.<tool_id>"
    mcp: Optional[str] = None        # "<server_id>.<tool_name>"

class AgentStep(BaseModel):
    # ... existing ...
    tools: list[ToolRef] = []
    skills: list[str] = []           # "<plugin_id>.<skill_id>"
    skill_injection: Optional[Literal["auto", "manual", "explicit", "off"]] = None
```

**Step 3: Verify**

```bash
pytest tests/test_workflow_models.py -v -k "required or tools or skills"
```

---

### Task 5.2: Validate-time reachability checks

**Files:**
- Edit: `api/services/workflow_compiler.py`
- Edit: `api/routers/workflows.py`
- Edit: `tests/test_workflow_compiler.py`

**Step 1: Write the failing tests**

```python
def test_validate_flags_missing_required_plugin():
    workflow = WorkflowDefinition(
        defaults=WorkflowDefaults(required_plugins=["does-not-exist"]),
        steps=[],
    )
    result = validate_workflow(workflow)
    assert any(e["code"] == "plugin_missing" for e in result.plugin_errors)

def test_validate_flags_unreachable_required_mcp(mocked_mcp_service):
    mocked_mcp_service.simulate_unreachable("fs")
    workflow = WorkflowDefinition(
        defaults=WorkflowDefaults(required_mcps=["fs"]),
        steps=[],
    )
    result = validate_workflow(workflow)
    assert any(e["code"] == "mcp_unreachable" for e in result.mcp_errors)

def test_validate_flags_unknown_tool_ref():
    workflow = WorkflowDefinition(
        steps=[AgentStep(
            id="s1", model="m", system_prompt="...", inputs=[], outputs=[],
            tools=[{"plugin": "xdm-toolkit.no_such_tool"}],
        )],
    )
    result = validate_workflow(workflow)
    assert any(e["code"] == "plugin_tool_not_found" for e in result.plugin_errors)

def test_strict_validation_promotes_warnings_to_errors():
    with patch.dict(os.environ, {"STRICT_VALIDATION": "true"}):
        # mcp_warnings normally; in STRICT they become errors and refuse run
        workflow = WorkflowDefinition(
            defaults=WorkflowDefaults(required_mcps=["unreachable"]),
            steps=[],
        )
        result = validate_workflow(workflow)
        assert result.has_errors
```

**Step 2: Implement**

In `workflow_compiler.py`, after structural validation:

```python
def validate_extensions(workflow: WorkflowDefinition) -> ExtensionValidationResult:
    plugin_service = PluginService()
    mcp_service = MCPService()

    plugin_errors, plugin_warnings = [], []
    mcp_errors, mcp_warnings = [], []
    skill_warnings = []

    # required_plugins
    available = {p["id"] for p in plugin_service.scan_plugins()}
    for pid in workflow.defaults.required_plugins:
        if pid not in available:
            plugin_errors.append({"code": "plugin_missing", "plugin_id": pid})

    # required_mcps
    for mid in workflow.defaults.required_mcps:
        if not mcp_service.has_server(mid):
            mcp_errors.append({"code": "mcp_not_registered", "server_id": mid})
        elif not mcp_service.is_reachable(mid):
            mcp_warnings.append({"code": "mcp_unreachable", "server_id": mid})

    # step-level tool refs
    for step in workflow.steps:
        for tool in step.tools:
            if tool.plugin:
                pid, tname = tool.plugin.split(".", 1)
                if not plugin_service.has_tool(pid, tname):
                    plugin_errors.append({"code": "plugin_tool_not_found",
                                          "plugin_id": pid, "tool": tname,
                                          "step_id": step.id})
            if tool.mcp:
                sid, tname = tool.mcp.split(".", 1)
                if not mcp_service.has_tool(sid, tname):
                    mcp_errors.append({"code": "mcp_tool_not_found",
                                       "server_id": sid, "tool": tname,
                                       "step_id": step.id})

        for skill_ref in step.skills:
            pid, sid = skill_ref.split(".", 1)
            if not plugin_service.has_skill(pid, sid):
                skill_warnings.append({"code": "skill_not_found",
                                       "plugin_id": pid, "skill_id": sid,
                                       "step_id": step.id})

    return ExtensionValidationResult(
        plugin_errors=plugin_errors, plugin_warnings=plugin_warnings,
        mcp_errors=mcp_errors, mcp_warnings=mcp_warnings,
        skill_warnings=skill_warnings,
    )
```

In `routers/workflows.py`, merge `ExtensionValidationResult` into the main `ValidationResult`. Honor `STRICT_VALIDATION` env: promote warnings to errors.

**Step 3: Verify**

```bash
pytest tests/test_workflow_compiler.py -v -k "extension or plugin_missing or mcp"
```

---

### Phase 5 Gate

```bash
pytest tests/test_workflow_compiler.py tests/test_workflows_router.py -v -k "validate"
```

Manual: create a workflow with `required_mcps: [nonexistent]`, POST to `/api/workflows/validate`, see `mcp_errors` populated.

---

## Phase 6: Resource Accounting + Arch Integration

### Task 6.1: RSS sampling for stdio MCP runners

**Files:**
- Edit: `api/services/mcp_runner_pool.py`
- Edit: `tests/test_mcp_runner_pool.py`

**Step 1: Write the failing test**

```python
def test_rss_sampler_updates_runner_stats(mocked_stdio_mcp):
    pool = MCPRunnerPool(rss_sample_interval_s=0.5)
    runner = pool.acquire("run-123", "fs")
    mocked_stdio_mcp.set_rss_mb(runner.pid, 142.5)
    time.sleep(1.0)
    assert runner.peak_rss_mb >= 142.0
    assert runner.current_rss_mb() == pytest.approx(142.5, abs=2.0)
```

**Step 2: Implement**

`RSSSamplerThread` runs in background:

```python
class RSSSamplerThread(threading.Thread):
    def __init__(self, pool: MCPRunnerPool, interval_s: float = 1.0):
        super().__init__(daemon=True)
        self.pool = pool
        self.interval = interval_s

    def run(self):
        while True:
            for runner in self.pool.all_runners():
                try:
                    p = psutil.Process(runner.pid)
                    rss_mb = p.memory_info().rss / 1024 / 1024
                    runner.peak_rss_mb = max(runner.peak_rss_mb or 0, rss_mb)
                    runner._current_rss_mb = rss_mb
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            time.sleep(self.interval)
```

**Step 3: Verify**

```bash
pytest tests/test_mcp_runner_pool.py -v -k rss
```

---

### Task 6.2: Arch scheduler consumes MCP overhead

**Files:**
- Edit: `api/services/architecture.py`
- Edit: `api/services/deployment.py`
- Edit: `api/services/scheduler.py`
- Edit: `tests/test_scheduler.py`

**Step 1: Write the failing test**

```python
def test_scheduler_subtracts_mcp_overhead(mocked_unified_arch_96gb, mocked_mcp_pool):
    mocked_mcp_pool.total_runner_overhead_mb.return_value = 8 * 1024   # 8 GB of MCP RSS
    scheduler = Scheduler(arch=mocked_unified_arch_96gb)
    # Effective budget should be 96 - 8 = 88 GB
    decisions = scheduler.schedule_ready([Step(model="m", est_size_gb=80)])
    # 80 GB fits in 88, but at the 85% headroom check (88 * 0.85 = 74.8), it doesn't
    assert decisions[0].deferred is True
    assert "mcp_overhead" in decisions[0].defer_reason
```

**Step 2: Implement**

In `Deployment.effective_memory_gb()`:

```python
def effective_memory_gb(self) -> float:
    base = self._raw_effective_memory_gb()
    # Subtract MCP overhead if pool is active
    try:
        from .mcp_runner_pool import MCPRunnerPool
        pool = MCPRunnerPool.current()
        mcp_overhead_gb = pool.total_runner_overhead_mb() / 1024.0
        return max(0, base - mcp_overhead_gb)
    except ImportError:
        return base
```

In `Scheduler.schedule_ready()`, log `defer_reason` to include MCP overhead when relevant.

**Step 3: Verify**

```bash
pytest tests/test_scheduler.py -v -k "mcp_overhead or extension"
```

---

### Phase 6 Gate

```bash
pytest tests/test_mcp_runner_pool.py tests/test_scheduler.py -v -k "rss or overhead"
```

Manual: start a workflow that spawns an MCP using >1 GB RSS; observe `/api/system/architecture` `effective_memory_gb` decreases by that amount while the workflow is active; returns to baseline after workflow ends.

---

## Phase 7: Security Defaults + Extensions Endpoint

### Task 7.1: `/api/system/extensions` endpoint

**Files:**
- Edit: `api/routers/system.py`
- Edit: `tests/test_system_router.py`

**Step 1: Write the failing test**

```python
def test_system_extensions_endpoint():
    client = TestClient(app)
    r = client.get("/api/system/extensions")
    body = r.json()
    assert "plugin_paths" in body
    assert "system" in body["plugin_paths"]
    assert "user" in body["plugin_paths"]
    assert "mcp" in body
    assert "registry_path" in body["mcp"]
    assert "binaries_dir" in body["mcp"]
    assert "active_runners" in body["mcp"]
    assert "deployment" in body
    assert body["deployment"] in ("dmg_native", "container", "host_native")
```

**Step 2: Implement**

```python
@router.get("/api/system/extensions")
def get_extensions():
    d = Deployment.current()
    return {
        "deployment": d.mode.value,
        "plugin_paths": {
            "system": str(d.system_storage_root / "plugins"),
            "user": str(d.user_storage_root / "plugins"),
            "user_writable": os.access(d.user_storage_root / "plugins", os.W_OK),
        },
        "mcp": {
            "registry_path": str(MCPService.current()._path),
            "binaries_dir": str(d.user_storage_root / "mcp" / "binaries"),
            "active_runners": MCPRunnerPool.current().runner_count(),
            "overhead_mb": MCPRunnerPool.current().total_runner_overhead_mb(),
        },
        "cache": {
            "plugins_cache": str(d.user_storage_root / "cache" / "plugins.cache.json"),
        },
    }
```

**Step 3: Verify**

```bash
pytest tests/test_system_router.py -v -k extensions
```

---

### Task 7.2: Container security defaults

**Files:**
- Edit: `docker-compose.yml`
- Edit: `docs/deployment/templates/docker-compose.gpu_nvidia_*.yml`
- Edit: `docs/deployment/per-architecture-config.md`

**Step 1:** No test (config change).

**Step 2: Implement**

Update `docker-compose.yml` api service:

```yaml
api:
  # ... existing ...
  cap_drop:
    - ALL
  security_opt:
    - no-new-privileges:true
  read_only: false   # default false for v1; document opt-in
  tmpfs:
    - /tmp
  volumes:
    - ./data:/app/data    # user layer persists
    # ... existing ...
```

Document in per-architecture-config.md the opt-in for `read_only: true` with `/app/data` and `/tmp` as the only writable surfaces.

**Step 3: Verify**

```bash
docker-compose config   # validates without error
docker-compose up -d
docker exec local-ai-api capsh --print   # should show stripped capabilities
```

---

### Task 7.3: DMG entitlements documentation

**Files:**
- Edit: `desktop/entitlements.plist`
- Create: `docs/deployment/dmg-mcp-security.md`

**Step 1:** No test.

**Step 2: Implement**

Review `desktop/entitlements.plist`. Add explicit entitlements:

```xml
<key>com.apple.security.app-sandbox</key>
<false/>   <!-- v1: not sandboxed; document path to sandboxed build -->

<key>com.apple.security.cs.allow-jit</key>
<true/>

<key>com.apple.security.cs.allow-unsigned-executable-memory</key>
<true/>

<key>com.apple.security.network.client</key>
<true/>
```

Document in `dmg-mcp-security.md`:
- DMG MCP subprocesses inherit these entitlements.
- Path to a sandboxed build for App Store distribution (out of scope for v1).
- User-installed MCP binaries placed at `~/Library/Application Support/Enclave/mcp/binaries/` must be executable AND on the user's allow path.

**Step 3: Verify**

Build DMG, smoke-test that an OOTB MCP (filesystem-style) can spawn.

---

### Phase 7 Gate

```bash
pytest tests/test_system_router.py -v -k extensions
docker-compose config && docker-compose up -d
```

Manual: visit `/api/system/extensions` on both deployments; paths look correct.

---

## Cross-cutting concerns

### Error-handling reference

| error_class | error_code | Detection | Response |
|---|---|---|---|
| `extension` | `plugin_missing` | scan_plugins | validate-time error; refuse run |
| `extension` | `plugin_tool_not_found` | tool lookup | validate-time error; refuse run |
| `extension` | `mcp_not_registered` | registry lookup | validate-time error; refuse run |
| `extension` | `mcp_unreachable` | handshake test | validate-time warning (error in STRICT) |
| `extension` | `mcp_tool_not_found` | post-handshake tools/list check | validate-time error |
| `extension` | `skill_not_found` | scan_skills | validate-time warning |
| `runtime` | `mcp_runner_crashed` | psutil poll | 1 respawn, then fail step with `mcp_runner_crashed` |
| `runtime` | `mcp_timeout` | request timeout | abort step with `mcp_timeout` |
| `runtime` | `mcp_circuit_breaker_open` | 3× consecutive failures | fast-fail subsequent calls until next health check passes |
| `runtime` | `plugin_tool_error` | plugin tool raised exception | record on step, surface to prompt as tool error result |

### YAML schema additions (cumulative)

```yaml
defaults:
  required_plugins: []                # workflow refuses if any missing
  required_mcps: []                   # workflow refuses if any unreachable (STRICT) or unregistered
  skill_injection: "auto"             # "auto" | "manual" | "explicit" | "off"
  mcp_request_timeout_s: 30
  mcp_warmup_at_run_start: true       # spawn runners before step 1
  max_mcp_runners_per_workflow: 8

steps:
  - id: <id>
    model: <name>
    tools:
      - plugin: "<plugin_id>.<tool_id>"
      - mcp: "<server_id>.<tool_name>"
    skills:
      - "<plugin_id>.<skill_id>"
    skill_injection: "explicit"       # overrides defaults for this step
```

### API surface additions

| Endpoint | Method | Phase |
|---|---|---|
| `/api/plugins/install` | POST | 1 |
| `/api/plugins/{id}` | DELETE | 1 |
| `/api/skills/{id}/preview` | GET | 4 |
| `/api/mcp/servers/{id}/runners` | GET | 2 |
| `/api/mcp/runners` | GET | 2 |
| `/api/system/extensions` | GET | 7 |
| `/api/workflows/validate` | POST (extended) | 5 |
| `/api/workflows/runs/{id}` | GET (extended) | 4 |

### Files touched

| File | Phases | Change type |
|---|---|---|
| `api/services/mcp_runner_pool.py` | 2, 3, 6 | New |
| `docs/deployment/dmg-mcp-security.md` | 7 | New |
| `tests/mocks/mcp/*` | 2, 3 | New |
| `api/services/plugin_service.py` | 1, 4 | Modified — system+user layer discovery, skill matching |
| `api/services/mcp_service.py` | 1, 2 | Modified — user-layer storage, route to pool |
| `api/services/step_executor.py` | 4 | Modified — capture skill/mcp/tool activations |
| `api/services/workflow_engine.py` | 2, 4 | Modified — instantiate pool per run, aggregate stats |
| `api/services/workflow_compiler.py` | 5 | Modified — extension reachability validation |
| `api/services/deployment.py` | 1 | Modified — system_storage_root, user_storage_root, ensure_user_storage |
| `api/services/deployment_impl/dmg.py` | 1, 7 | Modified — bundle Resources path |
| `api/services/deployment_impl/container.py` | 1 | Modified — /app and /app/data paths |
| `api/services/deployment_impl/host_native.py` | 1 | Modified — cwd and ~/.enclave |
| `api/services/scheduler.py` | 6 | Modified — consume mcp overhead |
| `api/services/architecture.py` | 6 | Modified — effective_memory accounts for mcp |
| `api/models/workflow_models.py` | 4, 5 | Modified — StepResult + WorkflowRun + AgentStep extensions |
| `api/routers/plugins.py` | 1 | Modified — install/delete, origin field |
| `api/routers/skills.py` | 4 | Modified — preview endpoint |
| `api/routers/mcp.py` | 2 | Modified — runners endpoints |
| `api/routers/system.py` | 7 | Modified — /extensions endpoint |
| `api/routers/workflows.py` | 5 | Modified — extension validation in validate response |
| `docker-compose.yml` | 7 | Modified — cap_drop, security_opt, /app/data volume |
| `docs/deployment/per-architecture-config.md` | 7 | Modified — document security defaults |
| `desktop/entitlements.plist` | 7 | Modified — explicit entitlements |
| `desktop/setup_app.py` | 1 | Modified — bundle Resources/plugins |

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Existing workflows break under stricter validation | medium | high | Default to lenient mode; STRICT is opt-in; warn loudly before error in lenient |
| MCP runner pool leaks subprocesses on workflow crash | medium | high | `release_workflow` in `finally` block of workflow_engine.execute; on app shutdown, drain all pools |
| Stdio MCP handshake state diverges from per-call model | low | medium | Keep stdio runner stateless beyond `initialize`; verify in Phase 2 tests |
| User-layer plugin contains malicious tool code | low | high | Document trust boundary; `trusted: bool` field stub in Phase 1; signing deferred to 2.x |
| RSS sampling overhead noticeable | low | low | 1 Hz sampling per runner; psutil is cheap |
| Bind-mount permissions wrong on container restart | medium | medium | Document `chmod 0700 ./data` in deployment guide; validator warns if dir not writable |
| DMG plugin update collides with system layer | low | medium | User layer always wins; validator flags id collisions explicitly |
| MCP server binaries depend on host runtimes not in container | high | medium | Document required runtimes (Node, Python, Bun) in per-arch-config; bake into image |
| Pool leaks across STRICT validation refusal | low | low | Refused workflows never instantiate a pool; verify in Phase 5 tests |

---

## Rollout plan

Each phase merges to master via PR after gate closes. Phases 2 and 4 can parallelize after Phase 1 lands.

| Phase | Branch | Merge target | Tag |
|---|---|---|---|
| 1 | `feature/extension-storage-layering` | `master` | `1.3.0-alpha.4` |
| 2 + 3 (combined) | `feature/mcp-warm-pool` | `master` | `1.3.0-alpha.5` |
| 4 | `feature/extension-instrumentation` | `master` | `1.3.0-alpha.6` |
| 5 | `feature/extension-pre-flight` | `master` | `1.3.0-beta.3` |
| 6 | `feature/mcp-arch-integration` | `master` | `1.3.0-beta.4` |
| 7 | `feature/extension-security-defaults` | `master` | `1.3.0` |

Per-deployment release verification before tagging `1.3.0`:

| Deployment | Verification |
|---|---|
| DMG on M-series Mac | Install user plugin to `~/Library/Application Support/Enclave/plugins/`; survives DMG reinstall; OOTB plugins still discoverable |
| Container on Linux CPU | Install user plugin via `/api/plugins/install`; survives `docker-compose down && up --force-recreate`; bind-mount works |
| Container on Linux + GPU | Above + MCP that uses RAM (e.g. local vector-store MCP) shows non-zero `mcp_overhead_mb` in run record |

---

## Open questions

1. **Migration safety for existing `data/config/mcp_servers.json`** — design says one-time migrate to user layer. What if both files exist (operator manually placed)? Spec: log warning, prefer user-layer file, leave legacy alone. Verify behavior in Phase 1 tests.
2. **Plugin install format** — tarball, zip, or directory upload? Spec doesn't pick. Phase 1 task 1.4 chooses tarball (most portable); document alternatives.
3. **MCP runner pool lifetime under workflow resume** — resumed workflows have a stale `run_id` from before the restart. Should pool key on `(run_id, server_id)` or `(resumed_run_id, server_id)`? Spec: resumed workflows always cold-start MCPs. Document.
4. **Skill injection collision** — two skills triggered on the same keyword. Today's plugin_service injects all. Should the engine cap (max 3 skills per step)? Recommend cap in defaults; surface via `skill_injection_capped: bool` on StepResult.
5. **HTTP MCP authentication refresh** — long-lived HTTP sessions may need token refresh. Out of scope for v1; document hook.
6. **Pool eviction order under memory pressure** — if pressure poller flags critical mid-workflow, should the engine evict MCP runners before model runners? MCPs are cheaper to re-spawn but more disruptive. Recommend: evict model runners first (matches arch design); document.
7. **OOTB plugin signing** — do shipped plugins get signed by Enclave? Not in v1; document in trust-boundary section.
