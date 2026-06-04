# Code-Execution Sandbox — Design

**Status:** Draft · **Date:** 2026-06-03 · **Target release:** 1.x (post-1.3.0)
**Spec author:** brainstormed with operator; informed by a deep-read of the
`anthropics/claude-cookbooks` `managed_agents/` + `claude_agent_sdk/hosting/` recipes.

## 1. Context & motivation

Enclave is already a natural-language agent harness at parity-or-better with most
open agent frameworks (LangGraph, AutoGen, CrewAI, Strands, LlamaIndex) — it has a
DAG engine, durable 3-tier memory, dynamic orchestration, A2A, MCP runner pool,
RAG, and a hook bus. The one genuine *category* gap is **OpenHands' signature
primitive: a secure code-execution sandbox**. Today `sandbox_fs.py` is a path-
traversal boundary only — no process, no terminal, no `kind: code`. The CHANGELOG's
ralph entry names the missing piece directly: *"branch isolation +
read-only-until-promoted are enclave-code tool-layer concerns."* This spec gives
that tool layer a body.

**Goal:** let an agent write code → run it isolated on the operator's own machine →
read the result → iterate, with isolation auto-resolved to the strongest the host
offers, and a human approval gate as the default backstop on the weakest tier.

**Non-goals (v1):** WASM tier · non-Python runtimes · agent web-browsing · data
lineage · the full outcome-grader (captured separately — see §12).

## 2. Design principles

1. **Reuse the host-resolved-backend idiom.** Isolation is detected and selected
   exactly like `architecture.py`, `deployment.py`, and `runner.py` already do.
   This is the fourth instance of a pattern the codebase already trusts.
2. **Two gates, not one.** *Execution* (running code in isolation) and *promotion*
   (writing results back into the real workspace) are distinct risk events.
   Low-isolation execution gates; promotion always gates by default. This split is
   what lets a hardened container tier auto-*run* safely.
3. **Honest per-host ceiling.** The macOS/DMG tier has the weakest isolation; the
   spec states this plainly and compensates with a mandatory approval gate rather
   than pretending parity.
4. **Off by default.** `CODE_EXEC_ENABLED=false`, network denied by default —
   matching Enclave's auth/telemetry house rules.

## 3. Architecture overview

```
kind: code step  /  code_exec tool
        │
        ▼
  SandboxRegistry.resolve(step)          ← detect_sandboxes() at startup
        │  strongest available; override DOWN only
        ▼
  CodeExecSpec  (lang, code, files_in, limits, network=none)
        │
        ▼
  approval policy ──"required"──▶  HITLGate → checkpoint (durable pause)
        │ "auto"                        │ approve/edit          │ reject
        ▼                               ▼                       ▼
  SandboxBackend.execute(spec)  ◀───────┘                  step fails
        │   (subprocess | container)                        (ralph reflect learns)
        ▼
  scratch overlay workspace  (read-only-until-promoted)
        │
        ▼
  CodeExecResult (stdout/stderr/files/exit + telemetry)
        │
        ▼
  promotion gate ──"gated"/"auto_on_green"──▶ merge files_out → workspace
                                          else discard scratch
```

### Backend abstraction (mirrors `runner.py` / `runner_registry.py` / `runner_detection.py`)

| New file | Mirrors | Responsibility |
|---|---|---|
| `api/services/sandbox.py` | `runner.py` | `SandboxBackend` Protocol + `SandboxCapabilities`, `CodeExecSpec`, `CodeExecResult` dataclasses; `SandboxKind` enum |
| `api/services/sandbox_impl/subprocess.py` | `runner_impl/ollama.py` | Tier-1 subprocess backend |
| `api/services/sandbox_impl/container.py` | `runner_impl/vllm.py` | Tier-2 Podman/Docker backend |
| `api/services/sandbox_detection.py` | `runner_detection.py` | `detect_sandboxes()` — probe host at startup |
| `api/services/sandbox_registry.py` | `runner_registry.py` | `SandboxRegistry` + `SandboxNotAvailable(name)` |

## 4. Isolation tiers (v1)

### Tier 1 — subprocess (`isolation_tier = 1`)
Available **everywhere incl. the DMG**. Lowest ceiling → **approval-gated by default**.
- Child process, cwd pinned to the per-run scratch root via existing `SandboxedFS`.
- `resource.setrlimit`: `RLIMIT_CPU`, `RLIMIT_AS` (mem), `RLIMIT_FSIZE`, `RLIMIT_NOFILE`.
- **Scrubbed env** — allowlist only; no `ENCLAVE_*`, no API keys, no `OLLAMA_*` inherited.
- Network denied by default: Linux → `unshare` net namespace when available; **macOS →
  rlimits + FS-boundary only, no net namespaces (ceiling stated, not hidden)**.
- Wall-clock timeout → process-group kill.

### Tier 2 — container (`isolation_tier = 2`)
Available where a container runtime is present (MS-01 / BD790i). May **auto-run**
(policy in §6). **Podman-first**, Docker fallback.
```
podman run --rm --network=none --read-only \
  --tmpfs /tmp:rw,size=256m --memory=<m> --cpus=<c> --pids-limit=256 \
  --cap-drop=ALL --security-opt=no-new-privileges \
  --user <uid:gid>  -v <scratch>:/work:rw  <enclave-sandbox-image>
```
Hardening rationale (from the cookbook deep-read): Anthropic's own hosting image runs
**as root with no read-only rootfs, no pids-limit, and no caps dropped in the Compose
tier** — explicitly acknowledged in their `k8s.py`. Enclave's Tier-2 is **strictly
harder** and is a deliberate differentiator. Critically, **no runtime socket and no
host-credential paths are ever mounted** — only `/work:rw`.

> **Enclave is simpler than the reference here.** The cookbook image needs Node +
> `claude-code` and egress to `api.anthropic.com` because it *hosts an agent*. Enclave
> runs the agent's *code*, not an agent — so the image is `python + declared packages`
> and `--network=none` is the clean default with nothing to phone home to.

### Resolution (`SandboxRegistry.resolve`)
Strongest available backend by default. `step.code.backend_override → workflow defaults
→ env (SANDBOX_TIER_OVERRIDE) → detected max` may **downgrade only** — never select a
tier the host can't provide (raises `SandboxNotAvailable`, naming the missing runtime).
Same four-tier precedence shape as the existing `keep_alive` resolver.

## 5. Step kind & tool surface

### `kind: code` step
- Extend `AgentStep.kind` Literal in `api/models/workflow_models.py` with `"code"`.
- Add `code: Optional[CodeStepConfig]` field on `AgentStep`.
- New `api/services/engine_executors/code.py` exporting
  `execute(engine, step, definition, context, workflow_run, ...) -> StepResult`,
  dispatched by `workflow_engine._execute_one_step` like every other kind.

### `code_exec` tool (the iterate path)
- Registered into the tool layer so **`llm` and `ralph` steps** that declare it in
  their existing `tools: List[ToolRef]` can call it mid-reasoning. The agent owns the
  edit→run→observe loop *within one step turn* (confirmed by the cookbook's fix-tests
  recipe — the engine does not drive each cycle; it just permits repeated calls).
- Runs through the existing `ToolExecutor` iterative loop; exposure gated by
  `profile_service.filter_tools` so it's **off unless the active profile allows it**.

## 6. The two gates

### Execution gate (HITL — generic primitive)
Designed as a reusable `HITLGate`, not code-specific (so the later general-HITL spec
generalizes it to any kind rather than rebuilding it).
- **Trigger:** a `pre_exec` hook on `hook_bus` raises the gate when
  `approval == "required"` (default for Tier-1; see policy below).
- **Pause:** run checkpoints via the existing `context_store` checkpoint/resume — no
  new pause machinery. DAG runner blocks the step until the gate resolves.
- **`gate.pending` event** (richer than the cookbook's, which carries only a question
  string): `gate_id`, `run_id`, `step_id`, `step_kind`, **proposed payload** (the code
  / diff / command), **risk metadata** (`network`, target `file paths`, `tier_used`),
  agent `question`, `created_at`.
- **Approval endpoint:** `POST /api/workflows/runs/{run_id}/approvals/{gate_id}` in
  `api/routers/workflows.py`, body `{action: approve|edit|reject, edited_payload?, reason?}`.
  Edit replaces the proposed payload (the cookbook has no first-class edit — the human's
  version is just injected as the result; we make it explicit). **Idempotent:** a second
  POST to a resolved gate returns `409`.
- **Resume:** posting the result resumes from checkpoint; reject fails the step with
  reason (ralph's `reflect` can learn from the rejection).
- **Single-operator simplification:** no webhook/async-reviewer infra (that's CMA's
  multi-tenant concern). The operator *is* the reviewer; the Runs view *is* the
  approval UI; the endpoint is called from it directly.

### Promotion gate (the part that has real-world effect)
- Code runs against a **scratch overlay** under the run's `SandboxedFS` namespace.
  Nothing touches the canonical workspace until promoted.
- `code.promote`: `gated` (default) | `auto_on_green` | `never`. `auto_on_green` reuses
  `engine_executors/loop.py::evaluate_gate` (the existing safe-AST predicate grammar)
  over the `CodeExecResult` (e.g. `exit_code == 0`).
- Promotion copies only declared `files_out` paths into the canonical workspace.
- Scratch dir retained with a TTL (`SANDBOX_SCRATCH_TTL_HOURS=24`, cookbook's
  archive-not-delete) so the operator can inspect what ran before promoting.

### Auto-run policy (resolves open decision ②)
| Tier | Execution | Promotion |
|---|---|---|
| Tier-1 subprocess | **gate always** | gate (or `auto_on_green`) |
| Tier-2 container | **auto-run allowed iff `network=none ∧ non-root ∧ read-only-rootfs`**; any relaxation forces the gate | gate (or `auto_on_green`) |

## 7. Data model (`api/models/workflow_models.py` + `api/services/sandbox.py`)

```python
class CodeStepConfig(BaseModel):           # on AgentStep.code
    language: Literal["python"] = "python"   # v1: python only
    source: Literal["inline", "from_input"] = "inline"
    code: Optional[str] = None               # when source == inline
    code_input: Optional[str] = None         # workspace ref when source == from_input
    files_in: List[str] = []                 # workspace paths staged read-only
    files_out: List[str] = []                # promotion candidates
    timeout_s: int = 60
    limits: ResourceLimits = ResourceLimits()  # mem_mb, cpus, pids
    network: Literal["none", "allowlist"] = "none"
    approval: Literal["auto", "required", "tier_default"] = "tier_default"
    backend_override: Optional[Literal["subprocess", "container"]] = None
    promote: Literal["gated", "auto_on_green", "never"] = "gated"
    promote_predicate: Optional[str] = None  # evaluate_gate grammar; for auto_on_green

# sandbox.py dataclasses
SandboxCapabilities: name, isolation_tier, network_modes, max_mem_mb, languages, can_auto_run
CodeExecSpec:        language, code, stdin, files_in, timeout_s, limits, network, env_allowlist, scratch_path
CodeExecResult:      exit_code, stdout, stderr (capped), files_produced, duration_ms, peak_rss_mb, tier_used, violations
```
`StepResult` already carries telemetry fields; add `code_exit_code`, `tier_used`,
`peak_rss_mb`, `files_produced`, `approval_status`, `promoted`.

## 8. Security threat register (abbreviated — full STRIDE via `stride-threat-model` skill)

| Threat | Control |
|---|---|
| FS escape / traversal | `SandboxedFS` guard; re-validate `files_out` post-exec before promotion |
| Resource exhaustion (fork bomb, mem hog) | rlimits (Tier-1) / `--pids-limit` + `--memory` + `--cpus` (Tier-2); wall-clock kill |
| Network exfil | `--network=none` / net-ns deny by default; honest macOS ceiling; allowlist is opt-in |
| Secret exfil | env allowlist — no `ENCLAVE_*`/keys inherited; no `.env` mount (ties to secret-scan hook) |
| Privilege escalation | container non-root + `--cap-drop=ALL` + `--security-opt=no-new-privileges`; Podman rootless |
| Runtime takeover | never mount the Docker/Podman socket or host creds into the sandbox |
| macOS Tier-1 weak ceiling | **mandatory HITL execution gate** as the human backstop |
| Untrusted promotion | promotion gate distinct from execution; `files_out` allowlist only |

## 9. Telemetry & config

- Env (all opt-in / safe defaults): `CODE_EXEC_ENABLED=false`, `SANDBOX_DEFAULT_NETWORK=none`,
  `SANDBOX_TIER_OVERRIDE` (down-only), `SANDBOX_APPROVAL_DEFAULT`, `SANDBOX_SCRATCH_TTL_HOURS=24`,
  `SANDBOX_CONTAINER_IMAGE`, `SANDBOX_CONTAINER_RUNTIME=auto|podman|docker`.
- Runs-view code panel: exit code, `tier_used`, duration, peak_rss, network policy,
  files produced, approval + promotion status (same way pre-warm/parallel got panels).

## 10. Testing strategy (mirrors existing `tests/{unit,integration,hooks}`)

- **Unit:** `detect_sandboxes` (mock podman present/absent × deployment mode); registry
  resolution is **down-only, never up**; `SandboxedFS` post-exec re-validation; rlimit
  enforcement; env-scrub asserts no keys leak.
- **Integration:** `kind: code` happy path (subprocess + container); gate
  pause→approve→resume; reject path; promote vs discard; `auto_on_green` predicate.
- **Security:** traversal escape blocked; `--network=none` egress blocked; secret env
  absent in child; timeout kills runaway; fork bomb killed by pids-limit.

## 11. Decisions (resolved during brainstorming + cookbook deep-read)

1. **Isolation = tiered, auto-detected** (subprocess everywhere; container where present).
2. **Container runtime = Podman-first**, Docker fallback — rootless means a container
   escape lands as an *unprivileged* host user, fixing the reference's root gap at the
   runtime layer.
3. **Tier-2 may auto-run** under the §6 hardening conjunction; Tier-1 always gates.
4. **Filesystem = three-zone** (`files_in` RO → scratch RW → `files_out` promote),
   adopted from CMA, with the **execution-gate vs promotion-gate** split as the seam.

## 12. Deferred / future

- **Outcome grader** (separate-context verifier, same tools, rubric-driven) — this is
  the *Strands/evaluator-optimizer self-correct* gap, **not** the sandbox. Strong
  candidate for the next spec. v1 pulls in only the cheap **verification turn** (re-run
  to confirm rather than trust self-report).
- WASM tier (`sandbox_impl/wasm.py` — the Protocol leaves the seam).
- Non-Python runtimes (node/bash) · network **allowlisting** UI (v1 = on/off) · microVM ·
  agent web-browsing (separate OpenHands gap) · data lineage.

## 13. References

- Cookbook recipes that informed this: `managed_agents/data_analyst_agent.ipynb`
  (sandbox + file-mount three-zone model), `managed_agents/CMA_gate_human_in_the_loop.ipynb`
  (gate-as-tool-call + resume-by-id), `claude_agent_sdk/hosting/` (container hardening
  deltas + Podman rationale).
- Realizes the deferred concern in `CHANGELOG.md` (ralph: "enclave-code tool-layer").
- Mirrors the `runner.py` / `runner_registry.py` / `runner_detection.py` backend idiom.
