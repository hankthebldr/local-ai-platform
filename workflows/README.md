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

| Kind       | What it does                                                        | Phase |
|------------|---------------------------------------------------------------------|-------|
| `llm`      | Single LLM call (the default — what every step was before)          | core  |
| `parallel` | Fan out to N `branches`, then a `gather` step synthesizes results   | 1     |
| `loop`     | Re-run `body` until `until.gate` is true or `max_iterations` is hit | 1     |

See `workflows/example-parallel-loop.yaml` for a worked example combining both
new kinds.

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
