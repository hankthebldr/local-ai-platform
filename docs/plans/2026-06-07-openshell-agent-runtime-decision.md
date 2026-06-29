# Decision: OpenShell & agent-dev-kits for stabilizing intra-agent behavior

- **Date:** 2026-06-07
- **Status:** Accepted (sandbox tier-3 shipped as an opt-in spike — commit `c98aec6`)
- **Context owner:** single operator (sovereign-appliance track)
- **Supersedes / relates to:** the code-execution sandbox (#165), the runner
  abstraction (Ollama/vLLM), the architecture-aware orchestration work (1.3.0).

## Context

We evaluated three external "agent development kit"–class projects for whether
they could **stabilize intra-agent behavior** (the reliability of multi-step
agent/workflow runs: context handoffs, output adherence, retries, isolation):

| Project | What it is | Layer | Maturity |
|---|---|---|---|
| **Nerve** (evilsocket) | Declarative YAML agents/tasks/tools ADK + eval mode | Agent definition + eval | v1.8 — **ARCHIVED Feb 2026 (read-only)** |
| **smolagents** (HF) | Lightweight code-writing agent lib (`CodeAgent`) | Single-agent reasoning loop | v1.26 (May 2026), **active**, 27k★ |
| **NVIDIA OpenShell** | Rust runtime: policy-governed sandboxes + privacy router | Execution isolation + egress/inference policy | **Alpha v0.0.57** ("single-player"), Apache-2.0 |

Key realization: these operate at **different layers** and only partially
overlap what Enclave already has (`workflow_engine`, `step_executor`,
`output_parsers`, `quality_gates`, agents/*.yaml, the #165 sandbox). None is a
drop-in "stabilizer."

## Decisions

### 1. OpenShell for **model hosting** → **NO**

OpenShell is not an inference server. Its privacy router *strips caller creds,
injects backend creds, and forwards to a managed model* — it routes **to** a
model endpoint, it does not serve one. Running vLLM inside an ephemeral
OpenShell sandbox would also fight its design (long-lived process pinning
~16 GB VRAM vs. per-task sandboxes) for zero benefit. **Ollama (:11434) +
vLLM (:8000) remain the inference servers.**

### 2. OpenShell as an **isolated code/agent runtime** → **YES (tier-3, opt-in)**

Adopted as a third isolation tier behind the existing `SandboxBackend`
Protocol + registry (`api/services/sandbox.py`). This is additive — the HITL
gate, reaper, and tier selection are unchanged. It closes the two gaps the
tier-2 container backend explicitly punts on:

1. **Real egress allowlist.** `CodeExecSpec.network` already has an
   `"allowlist"` value, but `container.py` downgrades it to deny
   (*"no real egress allowlist exists yet"*). The tier-3 backend maps
   `"allowlist"` → a named host set (default: local inference endpoints only).
2. **Privacy router as policy.** `_render_policy()` emits an `inference:`
   domain (`block_cloud: true`) so sandboxed code can reach **only** the local
   model — turning "no cloud inference, all data local" into an enforced policy.

**Guardrails on adoption:** registration is OPT-IN
(`ENCLAVE_ENABLE_OPENSHELL=true` + binary present + `--version` probe) because
the registry auto-prefers the highest tier; we don't let an alpha runtime
silently become the default code-exec path. Default detection is unchanged
when the flag is unset.

**Open integration seams** (OpenShell is alpha, CLI/policy schema moving):
`_render_policy()` (policy YAML keys) and `_build_run_cmd()` (the one-shot
`openshell` invocation) are isolated + env-overridable; validate both against a
real install before relying on the tier.

### 3. OpenShell **privacy router in front of inference** → **roadmap (1.4.x+)**

Independent of the sandbox tier, an OpenShell inference proxy in front of
:11434/:8000 could enforce local-only model access platform-wide. This is
arguably the highest-value angle for the sovereign-appliance story but is a
larger, separate integration. Deferred; sequence after the tier-3 spike is
validated and alongside fleet/privacy-routing work.

### 4. **Nerve** → **do not adopt; mine its eval harness**

Archived/read-only — a dead dependency for a shipping platform, and its YAML
agents/tasks/tools/MCP already overlap what we have. The one borrowable idea is
its **evaluation mode** (reproducible YAML/Parquet test cases benchmarking
agent output) — the right basis for an Enclave **agent/workflow regression
harness** built on `output_parsers` + `quality_gates`. This, not OpenShell, is
the most direct answer to "stabilize intra-agent behavior." Tracked as a
follow-up.

### 5. **smolagents** → **pocket `CodeAgent` for a future optional step kind**

Actively maintained and safe to depend on, but its code-as-action ReAct loop is
an *open-ended autonomous* paradigm — the opposite of our deterministic DAG. Not
a stabilizer for the workflow engine. Revisit only if/when we add a
`kind: agentic` step for genuinely open-ended sub-tasks; then smolagents is the
preferred embedded engine.

## Consequences

- **Positive:** code-exec gains a real egress allowlist + policy-enforced
  local-only inference *when enabled*; the spike is zero-risk to existing tiers
  (opt-in, default unchanged); no new always-on dependency.
- **Negative / risk:** OpenShell is alpha + a Rust gateway daemon (extra moving
  part if enabled); the two integration seams must be reconciled with the real
  CLI; the privacy-router and eval-harness items remain unbuilt.
- **Rejected alternative:** wholesale adoption of any one kit — each overlaps
  existing work or isn't production-ready.

## Follow-ups

1. Validate `_render_policy()` + `_build_run_cmd()` against a live OpenShell
   gateway; run one `kind: code` step end-to-end with a network allowlist.
2. Design the Nerve-inspired agent/workflow **eval/regression harness**
   (reproducible cases → assert on parsed output + quality-gate pass).
3. Scope the OpenShell **inference-router** integration for 1.4.x privacy/fleet
   routing.

## References

- Tier-3 backend: `api/services/sandbox_impl/openshell.py`,
  detection in `api/services/sandbox_detection.py`,
  tests `tests/test_sandbox_openshell.py` (commit `c98aec6`).
- Sandbox abstraction: `api/services/sandbox.py` (Protocol + tiers).
- NVIDIA OpenShell — https://github.com/NVIDIA/OpenShell (Apache-2.0, alpha)
- smolagents — https://github.com/huggingface/smolagents
- Nerve — https://github.com/evilsocket/nerve (archived)
