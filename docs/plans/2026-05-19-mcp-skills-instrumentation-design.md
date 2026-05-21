# MCP & Skills Instrumentation in the App's Virtual Compute Space — Design Document

**Status:** Draft v1 · **Author:** Henry Reed · **Date:** 2026-05-19 · **Target release:** 1.3.0 → 1.4.0
**Paired implementation plan:** [2026-05-19-mcp-skills-instrumentation-implementation.md](2026-05-19-mcp-skills-instrumentation-implementation.md)
**Depends on:** [2026-05-19-architecture-aware-orchestration-design.md](2026-05-19-architecture-aware-orchestration-design.md) (deployment abstraction)

---

## Executive summary

Enclave already has working plugin, skills, and MCP infrastructure — [api/routers/plugins.py](../../api/routers/plugins.py), [api/routers/skills.py](../../api/routers/skills.py), [api/routers/mcp.py](../../api/routers/mcp.py), backed by [plugin_service.py](../../api/services/plugin_service.py) and [mcp_service.py](../../api/services/mcp_service.py), with a `plugins/` directory shipping OOTB content (general-skills, xdm-toolkit, rag, example-web-search). What it doesn't have: a coherent story for **where user-installed extensions live across DMG vs container deployments**, **how MCP processes are managed efficiently within the app's compute space**, and **how skill activation and MCP invocations are instrumented into workflow run records**. This design layers two storage tiers (system / user) anchored to the `Deployment` abstraction from the architecture spec, replaces the spawn-per-call stdio MCP model with **step-scoped (default) or region-scoped (compiler-detected) warm runners** so MCP residency aligns with actual need and never competes with large-model loading, adds per-step skill + MCP telemetry, and gives the compiler a **resource-maximization pass** that rewrites or warns about workflows where MCP-active windows overlap with heavy-model steps. No protocol changes, no breaking schema, and the existing OOTB plugins continue to work unchanged.

---

## Current state (what exists today)

A quick anchor on what's already shipped, with file:line references:

**Plugins:**
- Discovery: [api/services/plugin_service.py:42](../../api/services/plugin_service.py) — `PluginService` scans `Path("plugins")` (cwd-relative, hardcoded).
- Manifest: `plugins/<id>/plugin.yaml` declares `id`, `version`, `skills[]`, `tools[]`.
- Tools: `plugins/<id>/tools/*.py` — Python modules loaded dynamically.
- Skills: `plugins/<id>/skills/*.md` — markdown with YAML frontmatter (`name`, `description`, `inject`).
- Router: [api/routers/plugins.py](../../api/routers/plugins.py) — list, get, invoke (3 endpoints, master-key gated).

**Skills:**
- Triggers: keyword-based, declared in `plugin.yaml` per skill.
- Injection: `inject: "system"` adds the skill body to the system prompt of an agent / step when triggered.
- Router: [api/routers/skills.py](../../api/routers/skills.py) — discover, install, create, delete (5 endpoints, master-key gated).
- Skill discovery providers: [api/services/discovery_providers/](../../api/services/discovery_providers/) — stub set, web-search hooks exist.

**MCP:**
- Service: [api/services/mcp_service.py](../../api/services/mcp_service.py) — registry persisted at `data/config/mcp_servers.json` (chmod 0600).
- Transports: stdio (subprocess-per-call) + HTTP/SSE.
- Protocol version: `2024-11-05`.
- Router: [api/routers/mcp.py](../../api/routers/mcp.py) — full CRUD + test + invoke (8 endpoints).

**OOTB plugins shipped today:**
- `general-skills` — 3 writing/reasoning skills, skills-only (no tools).
- `xdm-toolkit` — 4 skills + 7 XQL/XDM tools (Python).
- `rag` — search tool.
- `example-web-search` — search tool + skill.

The infrastructure works. What's missing is the operational scaffolding around it.

---

## Problem statement

Six concrete gaps when this infrastructure runs in real deployments:

1. **Hardcoded plugins path is deployment-hostile.** `PluginService` looks in cwd's `plugins/`. In the container that's `/app/plugins`, baked into the image — user-installed plugins are erased on image rebuild. In the DMG it's bundled in the .app bundle — user-installed plugins are erased on app update. Neither deployment has a writable, persistent user-plugin location.

2. **MCP stdio spawns are wasteful.** Every tool call against an stdio MCP server fires a full subprocess: spawn → initialize handshake → request → teardown. For workflow steps that call the same MCP multiple times (RAG lookup, schema validation), that's N spawn cycles. The handshake alone is ~200-500 ms; for sub-second tool calls, that's overhead-dominated.

3. **MCP processes are invisible to the arch scheduler.** The architecture-aware orchestration design counts memory against models. MCP subprocesses also eat memory — sometimes substantial (a filesystem MCP indexing a large directory; a vector-store MCP). The scheduler doesn't see them, doesn't budget against them, doesn't surface their footprint.

4. **No instrumentation per step.** When a step activates a skill or invokes an MCP tool, none of that lands in the step result. Operators reading `run.json` see model + tokens + duration but not "this step's text was 2× longer because three skills auto-injected" or "this step took 8 s because the filesystem MCP took 6 s to respond."

5. **No pre-flight check.** A workflow that requires `xdm-toolkit` and an MCP filesystem server can start, run two steps, then fail on step three because the MCP isn't installed or isn't reachable. Operators want validate-time errors, not runtime errors.

6. **No deployment-specific security posture.** DMG subprocess MCPs inherit the Mac app's entitlements; container subprocess MCPs run with the container's cap-set. The current MCP service has no awareness of either — it spawns whatever the manifest says with default permissions.

---

## Goals

- Two-tier storage (system / user) per deployment for plugins and MCP configs, with persistent user storage that survives app/container updates.
- **Step-scoped warm MCP runner by default**; **region-scoped** (across a contiguous run of MCP-using steps) when the compiler detects it's safe and beneficial; never workflow-scoped. MCP residency aligns with actual need.
- **Resource-maximization compiler pass** that analyzes the sequential chain for overlap between MCP-active windows and heavy-model steps; emits recommendations (lighter-model substitution within archetype; chain rewrites to separate MCP and heavy-model phases).
- **Step archetype registry** — named patterns of (role + MCPs + skills) covering common step purposes (`bash_script`, `documentation`, `xsiam_analysis`, etc.); used by the compiler for in-archetype substitution and by the composer UI for "logical companion" suggestions.
- **`lightweight` role** — new role pattern matching small models (Qwen 1.5B, Phi, Llama 3.2 3B, Gemma 2B); becomes the default when a step is tool-bound and doesn't declare a model.
- Health monitoring + circuit breaker for MCP runners.
- Memory accounting for MCP runners — visible to the arch scheduler.
- Per-step instrumentation: `skills_activated`, `mcp_calls` arrays on every `StepResult`.
- Per-run aggregate: skill/MCP usage summary on `WorkflowRun`.
- Declarative pre-flight: workflow YAML declares `required_plugins` and `required_mcps`; validate endpoint checks reachability.
- Deployment-specific security defaults (DMG entitlements, container cap-drop).

## Non-goals

- Building a new MCP protocol or non-standard transport. Ollama is already pinned; MCP protocol is `2024-11-05`; this design adds no protocol layer.
- A plugin marketplace / discovery service over the public internet. Skill `discover` stubs exist; this design leaves them as-is.
- Containerizing MCP servers as sibling containers in compose. In-process subprocess management stays the model; sibling-container is deferred to 2.x enterprise scope.
- Persistent KV cache or state between MCP runner lifetimes. Each workflow gets a fresh runner; freshness-by-default applies to MCPs too.
- Cross-workflow MCP runner sharing. Two concurrent workflows each get their own runner of the same MCP. Trade compute for isolation; revisit in 2.x.

---

## Three concepts and how they compose

Three things, three different lifetimes:

| Concept | What it is | Lifetime | Lives at |
|---|---|---|---|
| **Plugin** | Bundle: manifest + skills + tools | Install-time persistent | `plugins/<id>/` directory |
| **Skill** | Markdown with YAML frontmatter that injects into a prompt | Per-step (activated/injected on demand) | `plugins/<id>/skills/*.md` |
| **MCP server** | External process (or HTTP endpoint) exposing tools via JSON-RPC | Per-workflow-run (warm) or per-call (cold) | Registered in `mcp_servers.json`; binary/script anywhere on disk |

How they compose: a **plugin** can ship skills and/or tools. **Skills** affect prompt content (system or message-level injection). **Plugin tools** are Python functions called via the plugins router. **MCP servers** are external — registered separately, invoked through the MCP router or referenced by workflow steps.

Importantly, plugins and MCPs are *complementary not redundant*: plugins are Python-in-process extensions; MCPs are external-process integrations following an open protocol. A vendor would ship plugins for app-specific tooling and MCPs for cross-app/cross-vendor integrations.

---

## Deployment-aware storage layout

Anchored to `Deployment.storage_root` from the architecture design. Two layers per deployment: **system** (read-only, ships with the app/image) and **user** (writable, persists across updates). Discovery walks both; user overrides system by `id`.

### `dmg_native`

```
System (read-only, in app bundle):
  Enclave.app/Contents/Resources/
    plugins/
      general-skills/
      xdm-toolkit/
      rag/
      example-web-search/

User (writable, persists across reinstalls):
  ~/Library/Application Support/Enclave/
    plugins/                              # user-installed plugins
      <plugin-id>/
        plugin.yaml
        skills/*.md
        tools/*.py
    mcp/
      servers.json                        # MCP registry (was data/config/mcp_servers.json)
      binaries/                           # user-installed MCP binaries/scripts
    cache/
      plugins.cache.json                  # discovery cache
      mcp-tools.cache.json                # per-server tools/list cache
```

### `container`

```
System (read-only, baked into image):
  /app/plugins/                           # ships with image
    general-skills/
    xdm-toolkit/
    rag/
    example-web-search/

User (writable, bind-mounted volume):
  /app/data/                              # bind-mounted from host
    plugins/                              # user-installed plugins (survives image rebuild)
      <plugin-id>/...
    mcp/
      servers.json
      binaries/                           # mounted MCP binaries (Node, Python scripts, executables)
    cache/
      plugins.cache.json
      mcp-tools.cache.json
```

The container's `docker-compose.yml` adds a named volume for `/app/data` (bind-mount or named volume) so user-installed content persists across `docker-compose down` and image rebuilds.

### `host_native`

```
System (read-only):
  ./plugins/                              # cwd, ships with the source checkout

User (writable):
  ~/.enclave/
    plugins/                              # user-installed
    mcp/
      servers.json
      binaries/
    cache/
```

### Path resolution

`PluginService` and `MCPService` consult both layers in order:

```
1. Read user layer (Deployment.user_storage_root / "plugins/")
2. Read system layer (Deployment.system_storage_root / "plugins/")
3. Merge: user wins on id collision
4. Mark each discovered plugin with origin: "user" | "system"
```

API responses expose `origin` so operators know whether a plugin is shipped or user-installed. The skills install endpoint writes to the user layer always. The system layer is treated as immutable.

---

## MCP runner lifecycle: step-scoped default, region-scoped on hint

The current model spawns a subprocess per MCP tool call (overhead-heavy). The naïve fix would have been workflow-scoped runners (handshake once, hold for the whole run). That's wrong: MCPs and large models compete for the same memory pool, and holding MCP residency across logically-distinct phases violates the same freshness principle that drove model eviction. The right model is **step-scoped by default, with the compiler promoting to region-scoped where it's safe and cheap.**

### Default: step-scoped

```
step start
  ├── spawn MCP runner (one per server this step uses)
  ├── send initialize handshake
  ├── perform step's tool calls
  └── send shutdown + reap subprocess
step end (model evicted per freshness-default; MCPs evicted too)
```

Cost per step using N MCPs: N × handshake (~200-500 ms each). Memory residency: only during the step's tool-call window.

### Compiler promotion: region-scoped

A **region** is a contiguous DAG segment where:
1. Every step in the region uses the same MCP server S, AND
2. No step in the region invokes a model whose footprint, combined with S's measured RSS, would exceed `Architecture.effective_memory_gb() * 0.85`.

When the compiler detects a region, it emits a directive: hold S warm across the region, evict at region exit. Net effect: pay 1 handshake instead of N for that region, while still respecting the freshness principle at the model-MCP interaction boundary.

```
region_detected({steps: [s1, s2, s3], server: filesystem-local}):
   at s1.start: spawn S, handshake
   between steps: keep S warm
   at s3.end: shutdown S
   model freshness-default still applies: model evicted at every step boundary
```

The compiler **never** promotes a region that contains a heavy-model step. If `s2` loads a 70B model and `filesystem-local` holds a 12 GB index, the region splits at s2: S is evicted before s2's model loads; respawned at s3 if needed.

### Lifecycle

```
workflow compile time:
  ├── walk DAG; for each step record (mcp_servers_used, model_footprint_gb)
  ├── identify candidate regions (contiguous, same-MCP)
  ├── prune regions that contain heavy-model steps
  ├── emit MCPLifecycleDirective per step: SPAWN_NEW | REUSE_FROM_REGION | TERMINATE_AFTER

workflow run time:
  ├── execute each step honoring its directive
  ├── never hold an MCP runner across a step where it's not declared
  └── on step error: terminate any region-warm runners; later steps spawn fresh
```

### Per-runner record (attached to `WorkflowRun.mcp_runners`)

```python
class MCPRunnerStats(BaseModel):
    server_id: str
    transport: Literal["stdio", "http"]
    pid: Optional[int]
    scope: Literal["step", "region"]       # how the runner was lifetimed
    region_step_ids: list[str]              # the steps it served (length 1 for step-scope)
    started_at: datetime
    handshake_duration_ms: int
    requests_handled: int
    errors: int
    peak_rss_mb: Optional[float]            # stdio only; via psutil
    avg_response_ms: float
    closed_at: datetime
    exit_code: Optional[int]
    health_check_failures: int
```

### Failure handling

| Failure | Detection | Response |
|---|---|---|
| Runner subprocess dies | psutil poll fails | Mark unhealthy, attempt 1 respawn with fresh handshake, fail step with `mcp_runner_crashed` on second crash. Region-scope runners that die mid-region collapse the remaining region into step-scope. |
| Runner hangs (no response > `mcp_request_timeout_s`, default 30) | request timeout | SIGTERM the runner, respawn for the current step only, fail current step with `mcp_timeout` |
| Handshake fails | initialize returns error or times out | Mark MCP as `unreachable`, fail any step that requires it, surface in run summary |
| HTTP MCP returns 5xx | HTTP status | Retry with exponential backoff (max 3); circuit-break after 3 consecutive failures |
| Health check fails 3× | periodic `tools/list` ping every 30 s during a region | Terminate region early; subsequent steps spawn fresh per step-scope default |

### Why step-scoped by default (not call-scoped, not process-wide, not workflow-wide)

- **Call-scoped (current):** every call pays handshake. Slow.
- **Process-wide:** runners live forever; state accumulates across unrelated workflows. Violates freshness principle.
- **Workflow-scoped:** MCP residency overlaps with the entire workflow even when only one step uses it; competes with large-model loading; same freshness violation at the workflow boundary.
- **Step-scoped (this design):** MCP exists only during the step that needs it. Maximum freshness; minimum contention with model memory budget. Cost: handshake per use. Compiler promotes to region-scope where the savings are clean.
- **Region-scoped (compiler-detected):** the speed of workflow-scoping for the cases where it's safe; the cleanliness of step-scoping everywhere else.

### Resource accounting

Each warm runner's RSS is sampled at 1 Hz via psutil (stdio MCPs only; HTTP MCPs are external). The `Deployment.effective_memory_gb()` calculation subtracts current MCP overhead. With step-scoping the default, MCP overhead is typically zero between steps — the arch scheduler from the prior design sees nearly the full pool when loading models. Region-scope adds overhead only across the region's active steps.

This is the design's central memory invariant: **at any moment when a model is loading, no MCP runner exists that isn't strictly required by the step about to execute.** The scheduler can plan against full memory minus only the strictly-necessary MCP overhead.

---

## Execution model: sequential by default

**Workflows execute as a sequential chain.** The composer visualization reinforces this — users see a chain of steps, not a graph. The engine still permits the DAG schema for backward compatibility, but the new lifecycle logic, co-scheduling pass, and observability are built around sequential execution.

Why this matters here:
- No two models are resident simultaneously (the engine doesn't try to overlap them).
- No two heavy MCPs are active simultaneously across parallel branches (no parallel branches by default).
- Co-scheduling reduces to: for each step, can its model + its MCPs fit alongside each other? Memory budget is fully reclaimed between steps by the freshness-default policy.
- The `force_serialize` action is removed from the recommendation menu — sequential is already the case.

Existing workflows declared with `depends_on` arrays continue to work; the compiler topologically orders them and runs them serially.

## Resource-maximization compiler pass

The compiler's job grows beyond validation. It also analyzes the sequential chain for cross-resource contention and emits recommendations or rewrites. The principle: **MCP-active windows and heavy-model steps should not overlap; when they must on a single step, the smaller model in the same archetype wins; if no rearrangement fits, the operator is asked to rewrite.**

### What the pass computes

For each step:
- `mcp_servers_in_use: list[str]` — declared MCPs.
- `mcp_peak_rss_gb_estimate: float` — sum of cached RSS observations per server (from prior runs); fallback to a conservative 1 GB/server default.
- `model_footprint_gb: float` — from `/api/show` cached size, plus KV headroom (15% by default).
- `combined_pressure_gb: float = mcp_peak_rss_gb_estimate + model_footprint_gb`.
- `effective_budget_gb: float` — from `Architecture.effective_memory_gb()`.

Then it walks the topological order and flags every step where `combined_pressure_gb > effective_budget_gb * 0.85`. These are **contention steps**.

### What the pass emits

For each contention step, the compiler chooses from a fixed action menu:

| Action | When applied | What it does |
|---|---|---|
| `recommend_smaller_model` | Heavy model + MCP both needed in this step | Suggest a lighter model in the **same archetype** (e.g. `coding` heavy → `lightweight` coding; never substitutes across archetypes) |
| `recommend_split_step` | One step is doing too much — mixes lookup with reasoning | Suggest splitting into two steps: one MCP-bound (lightweight model), one model-bound (heavy model, no MCP) |
| `recommend_reorder` | The chain has slack — heavy step could move earlier/later | Suggest sequential rewrite that preserves dependencies |
| `block_with_error` | Step's combined footprint exceeds effective budget regardless of arrangement | Refuse to compile; operator must rewrite |

Recommendations are emitted in the validate response under `optimization_recommendations`. They're informational by default; `STRICT_OPTIMIZATION=true` promotes them to errors that block run.

### The `lightweight` role — a new default

The action menu's `recommend_smaller_model` needs a concrete target. Today's `ROLE_PATTERNS` in [api/services/model_resolver.py:19](../../api/services/model_resolver.py:19) has `reasoning`, `fast`, `coding`, `uncensored`, `general` — none of which guarantee a sub-3B model. We add a new role:

```python
"lightweight": [
    "qwen2.5:1.5b",
    "qwen2.5-coder:1.5b",
    "phi",
    "llama3.2:3b",
    "gemma:2b",
],
```

`lightweight` is the role the engine assumes when:

1. A step declares MCPs/plugins but no model — the engine infers "this step is tool-mediated, the model just needs to drive the tools."
2. The compiler is auto-substituting for fit on a contention step within the matching archetype.
3. A workflow's `defaults.role` is not set and a step has no explicit `model` or `role`.

This makes "tool-bound, lightweight by default" a recognized pattern. Operators can still pin a heavy model when they want reasoning depth; the engine just doesn't assume they want it.

### Step archetypes — logical companions

Step purpose dictates a natural pairing of (model role + MCPs + skills). The compiler recognizes these pairings and uses them for:

- Validation (warn if declared MCPs don't match the inferred archetype).
- Auto-substitution (when shrinking a model, stay in-archetype).
- Composer assist (suggest companions when an operator declares only part of a pattern).

Initial registry (extensible via `plugins/<id>/archetypes.yaml`):

| Archetype | Default role | Companion MCPs | Companion skills | Typical use |
|---|---|---|---|---|
| `bash_script` | `coding` | `bash-mcp`, `filesystem-local` | `coder` | Generate + execute shell scripts |
| `code_review` | `coding` | none required | `coder`, `reviewer` | Review diff/PR |
| `documentation` | `reasoning` | `web-search`, `filesystem-local` | `research`, `concise-writer` | Write docs from sources |
| `research_brief` | `reasoning` | `web-search` | `research` | Topic investigation |
| `extraction` | `lightweight` | none | `concise-writer` | Pull structured data from text |
| `synthesis` | `reasoning` | none | `concise-writer` | Combine prior step outputs into a brief |
| `data_lookup` | `lightweight` | `filesystem-local` or `rag` | none | Read a file / search a vector store |
| `xsiam_analysis` | `reasoning` | `xdm-toolkit` (plugin), optional `web-search` | `xdm-rule-writer`, `xql-validator` | XSIAM detection-engineering |
| `triage` | `lightweight` | none | `concise-writer` | First-pass classification |

A step's archetype can be:

- **Declared** in YAML: `archetype: bash_script`.
- **Inferred** by the compiler from declared `tools` and `model`/`role`. If a step has `bash-mcp` + `coding` role, the compiler infers `bash_script` even without the declaration.
- **Unknown** if no match — the compiler treats it as a generic step (no archetype-driven recommendations).

**v1 scope (decided 2026-05-19):** ship with the 9 archetypes above. No additional archetypes added during the 1.3.0 release. Plugin authors register custom archetypes via `plugins/<id>/archetypes.yaml`, picked up by `extend_archetypes()` at plugin scan time. Likely 1.4.x additions: `slack_message`, `email_draft`, `meeting_summary`, `xql_authoring`, `vendor_pack_generation` — deferred until plugin authors signal demand or the OOTB workflows reveal a missing pattern.

**Default `co_scheduling_policy` for 1.3.0 (decided 2026-05-19):** `"recommend"`. The compiler emits recommendations in the validate response; workflows run as written. Operators inspect recommendations and decide whether to apply them. Stricter modes (`warn_strict`, `auto_substitute`) ship in 1.4.x once the recommendation logic has operator trust.

When the compiler emits `recommend_smaller_model`, it picks within the archetype's role family. A `bash_script` step's "smaller model" is a smaller *coding* model, not an arbitrary lightweight model. This preserves the step's competence.

### The decision boundary the compiler can't make

The compiler *can* compute the contention. What it *can't* do without operator policy is pick between the actions above when more than one applies. A contention step where both a smaller model AND a step split would work — which does Enclave prefer? That's the policy hook this design exposes for operator control.

See `co_scheduling_policy` in the schema additions below. Default policy is conservative (`recommend` everything, never auto-apply).

### Concrete example

Workflow:

```
step1 (small extractor, 2 GB) ──► step2 (RAG search via MCP, 12 GB MCP + 30B model = 30 GB) ──► step3 (synthesis, 70B model, 40 GB)
```

On the BD790i (96 GB effective):
- step1: 2 GB. No contention.
- step2: 30 GB (MCP+model). No contention against 96 GB budget alone.
- step3: 40 GB model. But MCP from step2 — if region-scoped — would still be resident: 12 + 40 = 52 GB. Doesn't violate budget, but does compete during step3's cold load.

Compiler emits:
- `region_promotion_denied(step2→step3, reason=heavy_model_in_next_step)` — keep step2 step-scoped; force MCP eviction before step3 starts.
- `optimization_recommendation(step=step2, type=region_safe)` — step2 alone could be region-scoped if it had multiple MCP calls.

On an A100 80 GB:
- step3 model alone: 40 GB. No contention with anything.
- step2 model+MCP: 30 GB. Fine.
- No recommendations emitted.

On a 48 GB Mac M4 Pro:
- step3 model: 40 GB. Already 83% of pool before KV. Tight.
- step2 model+MCP: 30 GB. Fine.
- Compiler emits: `optimization_recommendation(step=step3, type=recommend_smaller_model, reason="70B model leaves <8 GB headroom on apple_unified 48GB")`.

The recommendation is informational; operator decides whether to substitute or accept the risk.

---

## Per-step instrumentation

`StepResult` gains four new fields:

```python
class StepResult(BaseModel):
    # ... existing fields ...

    skills_activated: list[SkillActivation] = []
    mcp_calls: list[MCPCall] = []
    plugin_tools_called: list[PluginToolCall] = []
    extension_overhead_ms: float = 0.0   # cumulative skill injection + MCP call time


class SkillActivation(BaseModel):
    plugin_id: str
    skill_id: str
    trigger: Literal["keyword", "manual", "explicit"]
    trigger_match: Optional[str]            # the keyword or trigger that fired
    injected_into: Literal["system", "messages"]
    injected_chars: int                     # length of skill body added to prompt


class MCPCall(BaseModel):
    server_id: str
    tool_name: str
    duration_ms: float
    status: Literal["ok", "error", "timeout"]
    request_size_bytes: int
    response_size_bytes: int
    error_code: Optional[str]
    error_message: Optional[str]


class PluginToolCall(BaseModel):
    plugin_id: str
    tool_id: str
    duration_ms: float
    status: Literal["ok", "error"]
    error_class: Optional[str]
```

`WorkflowRun` gains aggregate fields:

```python
class WorkflowRun(BaseModel):
    # ... existing fields ...

    skills_activated_total: int = 0
    mcp_invocations_total: int = 0
    plugin_tools_invoked_total: int = 0
    mcp_servers_used: list[str] = []
    mcp_runners: list[MCPRunnerStats] = []
    extension_overhead_seconds: float = 0.0
```

Why this matters: today's `transition_cost_seconds` (from the arch design) tells you load cost. With these fields you can also tell extension cost, and ratio them against pure inference. A workflow where 40% of wall-clock is MCP calls is a different optimization target than one where 40% is cold-loads.

---

## Pre-flight declaration and validation

Workflows declare extension dependencies; validate-time checks reachability.

### Schema additions

```yaml
defaults:
  required_plugins: ["xdm-toolkit"]         # workflow refuses to run if missing
  required_mcps: ["filesystem-local"]       # workflow refuses if MCP unreachable
  skill_injection: "auto"                   # "auto" (keyword triggers) | "manual" | "off"
  mcp_request_timeout_s: 30
  mcp_lifecycle: "step"                     # "step" | "region" | "explicit"
                                            # step: spawn-per-step (max freshness)
                                            # region: compiler may promote to region-scope
                                            # explicit: only honor per-step mcp_lifetime overrides

  co_scheduling_policy: "recommend"         # see policy section below

steps:
  - id: lookup
    model: deepseek-r1:32b
    tools:
      - plugin: "xdm-toolkit.lookup_xdm_path"
      - mcp: "filesystem-local.read_file"
    skills:                                  # skills explicitly active for this step
      - "xdm-toolkit.xdm-rule-writer"
    skill_injection: "explicit"              # override defaults — only listed skills inject
    mcp_lifetime: "step"                     # per-step override of defaults.mcp_lifecycle
```

### `co_scheduling_policy` values

Defines how the compiler responds when it detects MCP / heavy-model contention. **This is the most consequential operator-facing decision in the design** — see the design-decision request after this section.

| Value | Behavior |
|---|---|
| `"off"` | Compiler doesn't analyze contention. Step-scoping still applies. |
| `"recommend"` (default) | Compiler emits `optimization_recommendations` in validate response. Workflow runs as written. |
| `"warn_strict"` | Recommendations promoted to warnings; workflow still runs but each run record carries `optimization_warnings`. |
| `"reject"` | Any unresolved contention step blocks compile. Operator must rewrite. |
| `"auto_substitute"` | Compiler applies `recommend_smaller_model` automatically when a smaller model in the same role is available. Other recommendations still surfaced. |

### Validation behavior

The `POST /api/workflows/validate` endpoint extends with:

1. For each `required_plugins[id]`: confirm plugin discovered (user or system layer).
2. For each `required_mcps[id]`: confirm server in registry; optionally `test_handshake: true` to actually spawn and ping.
3. For each step's `tools[].plugin`: confirm plugin tool exists.
4. For each step's `tools[].mcp`: confirm server registered AND tool exists in its handshake-cache (or refresh cache).
5. For each step's `skills[]`: confirm skill discovered.

Validation result extended:

```python
class ValidationResult(BaseModel):
    # ... existing fields ...

    plugin_warnings: list[dict] = []        # missing-but-optional plugins
    plugin_errors: list[dict] = []          # missing required plugins
    mcp_warnings: list[dict] = []           # registered but unreachable
    mcp_errors: list[dict] = []             # required but not registered, or test failed
    skill_warnings: list[dict] = []         # referenced but not discovered
```

`STRICT_VALIDATION=true` mode treats warnings as errors. Default is lenient — warn but allow run.

---

## Deployment-specific security

### `dmg_native`

- All MCP subprocesses inherit the Mac app's entitlements (declared in `desktop/entitlements.plist`). User-installed MCP binaries gain whatever the app has — usually network + user-directory file access.
- Recommended entitlements addition: `com.apple.security.app-sandbox` set to `false` for the demo build, `true` for App Store distribution with explicit user-selected file scopes.
- DMG installer creates `~/Library/Application Support/Enclave/mcp/binaries/` on first run with `chmod 700` (user-only). MCP binaries placed here can be executed but not by other users.
- A new optional `desktop/entitlements.mcp.plist` can be referenced by users who want stricter sandboxing per MCP — out of scope for v1, hook documented.

### `container`

- Default `docker-compose.yml` runs the api service with no special caps. MCP subprocesses inherit. Recommended additions for production:
  - `cap_drop: [ALL]` and `cap_add: [...]` only as needed (currently nothing is needed beyond default).
  - `read_only: true` on the api service with `tmpfs: [/tmp]` for scratch; mount `/app/data` as the only writable surface.
  - `security_opt: [no-new-privileges:true]`.
- MCP binaries in `/app/data/mcp/binaries/` are executed from a bind-mount; host SELinux/AppArmor policies apply.
- Network policy: by default the api container can reach the ollama container; MCP subprocesses inherit this. For MCPs that need outbound internet (web-search, API integrations), document that the container needs unrestricted egress, or use a per-MCP egress proxy.

### Both deployments

- MCP registry (`servers.json`) is `chmod 0600` (already enforced by mcp_service.py); secrets in headers/env are stored cleartext but masked in API responses (already done).
- Skill markdown is treated as data, not code — injection into a prompt is the most that happens; no skill body is `exec`'d.
- Plugin tool Python modules ARE code — the plugin scanner needs an explicit allowlist for user-layer plugins. Default behavior: load only signed plugins or plugins from a `trusted: true` manifest. Document this trust boundary.

---

## API surface

| Endpoint | Method | Phase | Purpose |
|---|---|---|---|
| `/api/plugins` | GET | existing | List plugins (extended with `origin: user|system`) |
| `/api/plugins/{id}` | GET | existing | Plugin details (extended) |
| `/api/plugins/{id}/tools/{tool_id}` | POST | existing | Invoke a plugin tool (instrumented) |
| `/api/plugins/install` | POST | new | Install plugin to user layer |
| `/api/plugins/{id}` | DELETE | new | Remove from user layer (system plugins protected) |
| `/api/skills` | GET | existing | List skills (extended) |
| `/api/skills/{id}/preview` | GET | new | Preview the rendered skill body before injection |
| `/api/mcp/servers` | GET | existing | List registered MCP servers |
| `/api/mcp/servers/{id}/runners` | GET | new | List active warm runners for this server |
| `/api/mcp/runners` | GET | new | List all active warm runners (debug) |
| `/api/workflows/validate` | POST | extended | Adds plugin/mcp/skill pre-flight |
| `/api/workflows/runs/{id}` | GET | extended | Adds `skills_activated_total`, `mcp_invocations_total`, etc. |
| `/api/system/extensions` | GET | new | One-stop deployment-aware view: where plugins live, MCP binaries dir, cache status |

---

## Integration with the architecture-aware orchestration design

This design depends on the deployment abstraction from the architecture spec. Specific integration points:

1. **`Deployment.system_storage_root` and `Deployment.user_storage_root`** — new properties on the `Deployment` Protocol, populated per impl (dmg / container / host_native). PluginService and MCPService consume these instead of cwd-relative paths.

2. **`Deployment.effective_memory_gb()`** — updated to subtract `MCPService.total_runner_overhead_mb()` from its returned value. The arch scheduler sees the post-extension budget.

3. **Workflow run record** — `arch`, `deployment`, `ollama_version` (from arch design) sit alongside `skills_activated_total`, `mcp_invocations_total` (from this design). Single run.json contains both views.

4. **Config validator (Phase 6 in arch impl plan)** — extended to also check:
   - User-layer plugin dir exists and is writable.
   - MCP binaries dir exists and binaries are executable.
   - Required Node/Python runtimes are present for declared stdio MCPs.

5. **Per-deployment docker-compose templates** — extended to include `/app/data` volume mount and Node.js + Bun runtimes for MCP stdio transport.

---

## Observability story end-to-end

For a single workflow run, the operator-facing dashboard surfaces:

```
Workflow run: <run_id>
  arch: gpu_nvidia_multi
  deployment: container
  ollama: 0.23.4

  Wall-clock:        45.2 s
  ├── Inference:     30.1 s  (67%)
  ├── Model load:     5.3 s  (12%, cold loads from default-evict)
  ├── MCP calls:      8.4 s  (19%, 12 invocations across 2 servers)
  └── Skill inject:   1.4 s  (3%, 6 activations)

  MCP runners:
    filesystem-local:  spawn 1×, 8 calls, peak RSS 142 MB, avg 0.6 s/call
    web-search:        spawn 1×, 4 calls, peak RSS 28 MB, avg 1.1 s/call

  Skills activated:
    xdm-toolkit/xdm-rule-writer:    4× (steps: extract, analyze, judge, synthesize)
    general-skills/concise-writer:  2× (steps: synthesize, judge)
```

This is the picture the run record needs to support. Every line above is derivable from fields added in this design + the arch design.

---

## Open questions

1. **MCP runner sharing across concurrent workflows on the same host.** Spec says no sharing — each workflow gets its own runner. For RAG-heavy fleets, this might double-allocate vector indexes. Revisit in 2.x with explicit opt-in sharing.

2. **Plugin signing.** A first step toward user-layer plugin trust. Out of scope here; design hook exposed via `plugin.yaml.trusted: bool` and `plugin.yaml.signature` fields, validator stub only.

3. **MCP tool result caching.** Repeated tool calls with identical inputs within a workflow could return cached results. Not in v1; surface a hook in the MCPCall record for future cache instrumentation.

4. **Container Node/Bun runtime requirement.** Many MCP servers are Node-based (anthropic-ai mcp-server-* family). Container image must include `node` and `npx`; bumps image size by ~150 MB. Worth it for ecosystem compatibility.

5. **DMG plugin auto-update.** OOTB plugins ship with the .app bundle; on update they replace. User-layer plugins persist. What about user plugins that depended on a now-removed OOTB plugin? Validate-time error; document.

6. **MCP runner pool size limit per workflow.** A workflow could declare 20 MCPs. Each spawns a process. Resource ceiling needed; recommend `max_mcp_runners_per_workflow: 8` as default, configurable.

7. **HTTP MCPs and load timing.** Can't measure RSS (external). Can measure handshake duration and per-call latency. Report partial metrics with `transport: "http"` in the runner stats and mark RSS as `null`.

8. **Hot-pool across workflow runs (Phase 7 idea from arch spec).** Specifically: should the *same* MCP runner persist if the next workflow declares it? Aligns with arch's hot-pool concept. Defer to 2.x; per-workflow scoping for now.

---

## Future work (deferred from 1.3.0)

- **Sibling-container MCPs.** Run MCPs as separate Docker services in compose, network-reach them. Better isolation, more orchestration overhead. 2.x.
- **MCP marketplace.** Discovery from a known registry. Currently stubs exist; needs a real catalog. Out of scope.
- **Plugin signing + trusted plugin store.** Sigstore-style or simple PGP signing. Needs a key-management story.
- **MCP result cache.** Per-workflow KV cache for idempotent tool calls (e.g. schema lookups). Concrete pattern but unproven need.
- **Distributed MCP runners.** Cross-host MCP execution for fleet deployments. Couples with cross-host scheduling — both 2.x.

---

## Acceptance criteria (cross-cutting)

The design ships when:

1. **Storage layout.** OOTB plugins are read from system layer; user-installed plugins from user layer; user wins on id collision; both layers surface `origin` in API responses; user layer persists across container rebuild AND DMG reinstall.

2. **Warm pool.** A workflow with N MCP calls to the same server uses 1 subprocess spawn (verified by PID inspection during run). The workflow ends with zero zombie processes.

3. **Instrumentation.** Run record contains per-step `skills_activated`, `mcp_calls` arrays. Aggregate counts on the run match the sum of step records. `extension_overhead_seconds` is non-zero when MCPs/skills are used.

4. **Pre-flight.** Validate endpoint flags missing `required_plugins` as errors; unreachable `required_mcps` as warnings (or errors in STRICT mode). Workflow refuses to run if errors present.

5. **Resource accounting.** A workflow that runs MCPs with measurable RSS shows non-zero `mcp_overhead_mb_peak`; the arch scheduler's `effective_memory_gb` is reduced by that amount during the workflow.

6. **Per-deployment paths.** DMG and container both expose `/api/system/extensions` with deployment-correct paths.

7. **Security defaults.** Container runs with `cap_drop: [ALL]` by default; DMG entitlements documented; MCP registry file is `chmod 0600`.

These map to phase gates in the paired implementation plan.
