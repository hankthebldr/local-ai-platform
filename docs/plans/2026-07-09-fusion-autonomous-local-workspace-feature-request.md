# Feature Request: Fusion runtime — durable autonomous workflows that operate on local directories

- **Date:** 2026-07-09
- **Status:** Proposed (feature request / product direction — not yet scheduled)
- **Owner:** single operator (sovereign-appliance track)
- **Relates to:**
  - `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md` (the DAG orchestrator)
  - `docs/plans/2026-05-23-gpu-runner-abstraction.md` (Ollama/vLLM runner abstraction)
  - `docs/plans/2026-06-07-openshell-agent-runtime-decision.md` (sandbox tiers; Ollama+vLLM stay the inference servers)
  - `docs/plans/2026-05-19-architecture-aware-orchestration-design.md` (arch-aware scheduling, 1.3.0)
  - CLAUDE.md roadmap items **1.4.x fleet awareness** and **1.5.x pluggable inference engines**

---

## Executive summary

Enclave today can *orchestrate* multi-agent workflows and can *serve* local
inference on the Blackwell (vLLM) — but the two capabilities that would make it
a platform for **long-running autonomous work** are not yet fused: (1) the
operator cannot pick the local engine/model as a first-class choice at run time,
and (2) autonomous runs cannot durably operate on a **named local project
directory** the way an agentic coding tool (opencode/OpenWork) does — they are
confined to ephemeral per-conversation sandboxes.

The recommendation is to harden Enclave into a **fusion of two runtimes we
already operate**: the agentic-local-directory execution model of
**OpenWork/opencode** and the durable, checkpointed orchestration model of
**LangChain/LangGraph** — both driven by local vLLM/Blackwell inference. The
outcome: an operator defines a workflow, points it at a local directory (a repo,
the Obsidian vault, a scratch project), and the platform runs a resumable,
policy-governed, autonomous task that **produces and edits real files on disk**
and reports progress — with human-in-the-loop approval where it matters.

This is **hardening and fusion, not greenfield**: the runner abstraction, the
workflow engine with checkpoint/resume, the sandbox tiers, and a sandboxed FS
already exist. The gaps are the seams between them and the control surface on top.

---

## Trigger

While validating the local LangGraph + vLLM stack (Qwen3-Coder-30B NVFP4 on the
RTX PRO 4000 Blackwell), the operator could log into LangGraph Studio but "could
not select the local model to leverage vLLM and the Blackwell card."

Root cause (not a bug): the LangGraph graphs bind the model in **code**
(`ChatOpenAI(base_url=http://127.0.0.1:8000/v1)`), so every run already uses
vLLM/Blackwell — but Studio's visible model selector is LangSmith's **cloud**
provider config, unrelated to local inference. There is no first-class,
in-product control that says "run this on the local Blackwell vLLM engine."
That missing control is the narrow symptom of the broader gap this request names.

---

## What we already have (the fusion is mostly assembly)

| Capability | Where it lives today | Fusion-readiness |
|---|---|---|
| Multi-engine inference (Ollama :11434, vLLM :8000) | `runner.py`, `runner_registry.py`, `runner_detection.py`, `engine_executors/` | vLLM/Blackwell is already a first-class `RunnerKind`; dispatch works |
| Role→model resolution | `model_resolver.py`, `model_adapters.py` | Resolves roles to concrete models per runner; **not yet surfaced to a UI/run-config selector** |
| Durable multi-agent orchestration | `workflow_engine.py`, `step_executor.py` | Sequential + composite steps, 6-hook lifecycle, **checkpoint/resume**, cancel, pre-warm, telemetry |
| Isolated code/agent execution | `sandbox.py` (+ tier-3 OpenShell), `sandbox_reaper.py` | HITL gate + tiered isolation; egress + local-only inference policy |
| Sandboxed filesystem | `sandbox_fs.py` | Per-conversation FS boundary (read/write/mkdir/walk/delete) — **ephemeral, not a named durable workspace** |
| Iterative tool-calling loop | `tool_executor.py`, `mcp_runner_pool.py`, plugins | Agentic loop with sandbox + MCP tools |
| Local-directory agentic execution + HITL | **OpenWork/opencode** (`~/projects/openwork-ws`, `openwork serve` :8787) | Operates on real local dirs; issues owner/collaborator tokens for approvals — **but external to the engine and blocked on strict-vLLM agentic turns; see `opencode-vllm-context-overflow-bug`** |
| Durable graph orchestration + Studio UI | **LangGraph** (`~/projects/langgraph-vllm`, `langgraph dev` :2024) | Checkpointed graphs, tool loops, Studio — **but model hardcoded in graph code; in-memory checkpointer** |

---

## The gap, as capabilities to close

### C1 — First-class engine + model selection at run time (P0, small)
Make "which local engine/model runs this" a real, surfaced choice, not a code
constant.
- Expose an **engine/model registry endpoint** (`GET /api/models` filtered by
  live runners) so any UI can list what the Blackwell vLLM + Ollama actually serve.
- LangGraph graphs read the model from `config.configurable.model` (falling back
  to env) so Studio's *assistant configuration* can override it per run.
- Native workflows already accept `model:`/role per step — ensure the operator
  UI presents the runner-resolved options (vLLM/Blackwell vs Ollama) explicitly.

### C2 — Durable local **workspace** runtime (P0, the core of the fusion)
Promote the ephemeral per-conversation `SandboxedFS` to a **named, persistent
workspace** bound to a real local directory (a repo, the vault, a project),
with the opencode-style operation set: read / write / edit / list / search /
shell / git — governed by the existing sandbox tiers and egress policy.
- A `Workspace` concept (root dir + policy + retention) that a workflow run
  attaches to, distinct from the ephemeral code-exec sandbox.
- Reuse the tier-3 OpenShell policy (`block_cloud`, local-only inference,
  egress allowlist) so autonomous file operations stay policy-governed.
- The research agent's vault-scoped writer (now targeting the Obsidian
  `_research/` folder) is the minimal proof of this pattern; generalize it.

### C3 — Long-running, resumable, HITL-gated autonomous tasks (P1)
The engine already checkpoints and resumes; extend that to workspace-bound runs
and wire **human-in-the-loop approvals** through OpenWork's existing owner/host
token model (approve a shell command, a git push, a bulk file write) instead of
inventing a new approval surface.

### C4 — Unified control surface / execution backend choice (P1–P2)
Decide the orchestration seam so we run **one** mental model, not three:
- Option A — LangGraph durable graphs become a selectable **execution backend**
  behind the native workflow engine (engine compiles a workflow → graph; gains
  LangGraph's persistence + Studio observability).
- Option B — the native engine stays authoritative and we surface its runs to a
  Studio-like local UI (Runs view already exists in console-v2 backlog).
- This is the key open decision (see below); C1–C3 are valuable under either.

---

## Proposed shape

```
            ┌───────────────────────── Control surface ─────────────────────────┐
            │  Enclave console  ·  LangGraph Studio (Chrome)  ·  OpenWork UI/HITL │
            └───────────────┬───────────────────────────────┬───────────────────┘
                            │ run-config: engine/model, workspace, policy
                 ┌──────────▼───────────┐        approvals   │ owner/host tokens
                 │  Orchestrator         │◄──────────────────┘
                 │  workflow_engine /     │   checkpoint + resume (durable)
                 │  LangGraph graph       │
                 └──────────┬───────────┘
             resolve model  │  dispatch step
                 ┌──────────▼───────────┐        ┌──────────────────────────────┐
                 │  RunnerRegistry       │───────►│ vLLM :8000 (Qwen3-Coder-30B  │
                 │  model_resolver       │        │ NVFP4, Blackwell) · Ollama    │
                 └──────────┬───────────┘        └──────────────────────────────┘
                 tool calls │  (sandbox-governed)
                 ┌──────────▼───────────┐        ┌──────────────────────────────┐
                 │  Tool layer           │───────►│ Workspace (named local dir):  │
                 │  sandbox_fs +          │        │  repo · Obsidian vault ·      │
                 │  workspace ops + MCP +  │        │  scratch project              │
                 │  opencode bridge        │        │  read/write/edit/shell/git    │
                 └───────────────────────┘        └──────────────────────────────┘
```

---

## Phasing (phase-gated per project convention)

- **Phase F0 — Selection (C1).** Model/engine registry endpoint + graph
  `configurable` override + UI selector. **Gate:** operator picks "vLLM /
  Blackwell" for a run in a UI and telemetry confirms the run hit :8000.
- **Phase F1 — Workspace runtime (C2).** `Workspace` abstraction over
  `SandboxedFS`, bound to a named local dir, policy-governed. **Gate:** an
  autonomous run edits & writes files in a chosen local directory and a diff is
  reviewable; escapes are refused.
- **Phase F2 — Durable HITL autonomy (C3).** Workspace-bound checkpoint/resume +
  OpenWork approval gating for privileged ops. **Gate:** a long task survives a
  restart (resume) and pauses for approval on a git push.
- **Phase F3 — Control-surface decision (C4).** Resolve Option A vs B; converge
  the UIs. **Gate:** one documented run path from define → run → observe.

---

## Non-goals

- Not building a new inference server (settled: Ollama + vLLM are the servers).
- Not multi-tenant / RBAC (that stays a 2.x concern).
- Not cloud orchestration; all inference and file operations remain local.
- Not replacing OpenWork or LangGraph — **fusing** their models into Enclave.

---

## Open questions

1. **C4 seam:** compile-to-LangGraph (adopt its persistence + Studio) vs.
   keep the native engine authoritative and build the local Runs UI? This
   dictates how much of LangGraph we absorb vs. wrap.
2. **HITL transport:** reuse OpenWork's token/approval server as the approval
   plane, or add a native approval endpoint to the engine?
3. **Strict-vLLM agentic turns:** the OpenWork path is blocked by the +1-token
   context-overflow issue; does C2/C3 route agentic loops through the native
   engine (which already handles this) and reserve OpenWork for HITL + messaging?
4. **Workspace vs sandbox lifetime:** named workspaces are durable; code-exec
   sandboxes are ephemeral and reaped. Confirm they are distinct objects with
   distinct retention/policy.
