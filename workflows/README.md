# Workflow Definitions

YAML-based multi-agent workflow definitions for the Local AI Platform.

## Quick Start

Run a workflow:
```bash
# Via CLI
python cli/workflow.py run workflows/data-model-rules.yaml \
  --seed '{"source_files": ["models/user.py"], "constraints": "PostgreSQL"}'

# Via API
curl -X POST http://localhost:8000/api/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "data-model-rules", "seed": {"source_files": ["models/user.py"], "constraints": "PostgreSQL"}}'
```

## Writing Workflows

See `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md` for the full
specification including YAML format, context layers, and model selection.

## Model Selection

Each step can specify a model two ways:
- **Explicit**: `model: "qwen3.5-uncensored:35b"` — uses this exact model
- **Role-based**: `role: reasoning` — resolves to best available model

Available roles: `reasoning`, `fast`, `coding`, `uncensored`, `general`

## Step Kinds

Each step declares a `kind:` that selects execution semantics. `kind:` defaults
to `llm` when omitted — every workflow written before Phase 1 of the multi-agent
patterns spec keeps working without changes.

| Kind           | What it does                                                                  | Phase |
|----------------|-------------------------------------------------------------------------------|-------|
| `llm`          | Single LLM call (the default — what every step was before)                    | core  |
| `parallel`     | Fan out to N `branches`, then a `gather` step synthesizes results             | 1     |
| `loop`         | Re-run `body` until `until.gate` is true or `max_iterations` is hit           | 1     |
| `a2a`          | Delegate to an external A2A-protocol agent                                    | 3a    |
| `orchestrator` | Lead agent dynamically spawns workers from a catalog via a JSON-directive protocol | 3b    |

See `workflows/example-parallel-loop.yaml`, `workflows/example-a2a-enrichment.yaml`,
and `workflows/example-orchestrator.yaml` for worked examples.

### kind: parallel

```yaml
- id: inspect
  kind: parallel
  outputs: [summary]
  execution:
    mode: auto                         # auto | multi_model_concurrent
                                       # | single_model_concurrent
                                       # | single_model_pseudo_parallel
    max_concurrency: 3
    failure_policy: fail_fast          # or continue_on_partial
  branches:
    - id: branch_a
      role: fast
      prompt: { role_inline: "...", task: "..." }
      outputs: [data]
    - id: branch_b
      role: fast
      prompt: { role_inline: "...", task: "..." }
      outputs: [data]
  gather:
    id: synth
    role: reasoning
    prompt: { role_inline: "...", task: "..." }
    inputs: [branch_a.data, branch_b.data]
    outputs: [summary]                  # must match parent.outputs
```

#### Execution modes

| Mode                            | When to use                                           | Dispatch shape                                                                |
|---------------------------------|-------------------------------------------------------|-------------------------------------------------------------------------------|
| `auto`                          | Most workflows — let the engine pick                  | Resolves to `single_model_pseudo_parallel` if all branches share a model, else `multi_model_concurrent` |
| `multi_model_concurrent`        | Heterogeneous specialist branches on a multi-model box | `ThreadPoolExecutor` (concurrent at the network layer)                        |
| `single_model_concurrent`       | Same model, daemon has `OLLAMA_NUM_PARALLEL > 1`      | `ThreadPoolExecutor`; engine validates all branches resolve to the same model |
| `single_model_pseudo_parallel`  | Same model, single-slot daemon (CPU-only is typical) | **Sequential** in declared order; keeps prompt cache warm between branches    |

On a single-Ollama-slot CPU box (the default Enclave shape) all modes
serialize at the `_LLM_SEMAPHORE`. The single-model modes still earn their
keep:

- `single_model_pseudo_parallel` gives **deterministic ordering** so Ollama's
  prompt cache survives between branches — for prefix-heavy workflows this is
  ~70% latency reduction on the second-and-later branches.
- `single_model_concurrent` is the operator's promise that the daemon has
  enough slots provisioned (`OLLAMA_NUM_PARALLEL > 1`); the engine asks the
  daemon for them via the per-request `num_parallel` option. A clear warning
  fires if the deployment can't honor the promise.
- Both single-model modes refuse to run if branches accidentally resolve to
  different models — better a clean failure than silent degradation.

### kind: loop

```yaml
- id: refine
  kind: loop
  outputs: [final_text]                 # every output must appear in last
                                        # body step's outputs (subset by name)
  max_iterations: 4
  until:
    type: gate                          # only type supported in Phase 1
    gate: "critic.approved == True"     # safe-eval'd against workspace
    on_max_iterations: emit_best        # or `fail`
  body:
    - id: editor
      role: reasoning
      prompt: { role_inline: "...", task: "..." }
      outputs: [draft]
    - id: critic
      role: reasoning
      prompt: { role_inline: "...", task: "..." }
      inputs: [editor.draft]
      outputs: [approved, feedback, final_text]
```

The gate expression supports `==`, `!=`, `>`, `<`, `>=`, `<=`, `in`, `not in`,
`and`, `or`, `not`, and literal values. Dotted refs like `critic.approved`
resolve against the workspace exactly the way step `inputs:` do. Attribute
access, function calls, and lambdas are rejected at parse time.

### kind: a2a

Delegate to an external A2A-protocol agent — anything that advertises an
Agent Card at `/.well-known/agent.json` and speaks the JSON-RPC `tasks/*`
methods.

```yaml
- id: enrich
  kind: a2a
  agent_card_url: https://intel.corp.local/.well-known/agent.json
  skill: enrich_iocs
  auth:
    type: bearer                       # or `none` (the default)
    token_env: INTEL_API_TOKEN         # name of the env var holding the token
  inputs:
    - extract_iocs.iocs
  outputs:
    - enriched
  timeout: 120                         # whole-step wall-clock cap (seconds)
  streaming: false                     # reserved for SSE; Phase 3a polls
```

Lifecycle:

1. The engine fetches the Agent Card from `agent_card_url`.
2. Validates `skill` is advertised (fails the step if not, before any work).
3. Packages step inputs as a Message — string inputs become a single TextPart,
   structured inputs become a single DataPart with the input names as keys.
4. POSTs `tasks/send`, then polls `tasks/get` until terminal.
5. Maps returned Artifacts onto declared `outputs` (exact name match first,
   then best-effort: single-artifact-single-output → use it; multi-output →
   walk DataParts looking for matching keys).

Enclave's own A2A surface is symmetric — every loaded workflow auto-advertises
as a skill at `/.well-known/agent.json`, so two Enclave instances can call
each other's workflows over A2A. See the live card at `GET /a2a/.well-known/agent.json`.

Auth supported in Phase 3a: `none` and `bearer` (token resolved from env var
at request time; the token itself never appears in YAML). mTLS / OAuth /
custom-header schemes land in follow-up phases.

### kind: orchestrator

Lead-agent pattern. The planner sees a catalog of worker templates and
dispatches them dynamically by emitting a JSON directive each turn. The
engine intercepts the directive, runs the worker in an isolated child
context, and feeds the result back to the lead for the next turn.

```yaml
- id: investigate
  kind: orchestrator
  outputs: [findings, recommended_actions]
  planner:
    role_inline: |
      You are the lead investigator. Spawn specialists as needed.
    task: "Investigate the alert."
  workers:
    extractor:
      id: w_extractor
      role: fast
      prompt: { role_inline: "...", task: "extract IOCs" }
      inputs:  [seed.task, seed.raw_text]   # MUST be seed.* refs
      outputs: [iocs]
    classifier:
      id: w_classifier
      role: fast
      prompt: { role_inline: "...", task: "classify" }
      inputs:  [seed.task]
      outputs: [labels]
  budget:
    max_workers_spawned: 6
    max_planner_turns: 12
    max_total_tokens: 200000
    max_wall_seconds: 600
```

**Worker isolation**: each spawn runs in a CHILD `WorkflowContext` whose
`seed` layer is the spawn directive's `inputs` object (plus `task`). Worker
outputs go to the child workspace; the planner only sees them via the
formatted tool-result message. The final answer comes from the lead's
`complete` directive, not from the workers' outputs directly.

**The text protocol** (rendered into the planner's system prompt
automatically — operators don't write it):

```json
{"action": "spawn_worker", "worker_id": "<id>", "task": "<one-line directive>", "inputs": {...}}
```
```json
{"action": "complete", "outputs": {<every declared output key>: <value>}}
```

The engine parses the LAST JSON-fenced block in the planner's response.
Malformed output gets a feedback message nudging the lead to retry; the
planner is given budget.max_planner_turns to converge.

**Why a text protocol vs native function-calling**: many local Ollama models
(uncensored finetunes, smaller quants, older releases) don't reliably emit
function-call output. A JSON-fenced block works on every model that can hold
the protocol in its system prompt. Native tool-calling can be layered on
later for models that support it; the dispatch logic stays the same.

See `workflows/example-orchestrator.yaml` for a complete worked example.
