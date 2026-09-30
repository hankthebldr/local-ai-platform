# Workflows

Enclave ships a declarative, YAML-defined multi-agent **workflow engine** — a DAG of steps with role-based model selection, Jinja2 prompts, output parsers, quality gates, and checkpoint/resume. As of **v1.3.0**, the engine is tick-based and uses the detected architecture to dispatch ready steps in parallel.

## Anatomy of a workflow

```yaml
# workflows/my-workflow.yaml
name: my-workflow
description: Short, one-line purpose
version: 1
defaults:
  model: llama3.2:3b
  keep_alive: 30m          # 1.3.0+ — falls through arch-detected default if unset
inputs:
  - name: target
    type: str
    required: true
steps:
  - id: analyze
    role: analyst
    prompt:
      template: |
        Analyze the following target:
        {{ target }}
    config:
      keep_alive: 10m
      est_size_gb: 4.5     # 1.3.0+ — used by scheduler.validate_feasibility()
    output:
      parser: json
      schema:
        type: object
        properties:
          summary: { type: string }
    gates:
      - kind: refusal
      - kind: schema
  - id: critique
    role: critic
    depends_on: [analyze]
    prompt:
      template: |
        Critique this analysis:
        {{ steps.analyze.output.summary }}
```

## Key concepts

| Concept | Purpose |
|---|---|
| **Step** | Atomic unit. One prompt → one model call → one structured output. |
| **Role** | Indirection layer: `role: analyst` resolves to a model via `model_resolver`. Same workflow runs against different model lineups. |
| **Depends_on** | DAG edges. The scheduler computes `ready_steps()` per tick. |
| **Output parser** | `json`, `text`, `markdown`, `yaml`, or a custom parser registered via plugin. |
| **Quality gate** | Pre/post hooks that fail the step on refusal, schema mismatch, or custom predicates. |
| **Checkpoint** | Every step's output is persisted; runs can resume from any point. |

## Six-phase hook lifecycle

Every step fires these hooks (registered in `api/hooks/builtins/`):

1. `before_prompt_render` — mutate inputs or context
2. `before_llm_call` — inject few-shot, budget tokens
3. `after_llm_call` — token counting, raw-output logging
4. `before_parse` — coerce stray output
5. `before_gate` — extract structured fields
6. `after_gate` — retry-with-feedback, plugin tool invocation

## Running a workflow

```bash
# CLI
enclave workflow run workflows/my-workflow.yaml --input target="example.com"
# or
python -m cli.workflow run workflows/my-workflow.yaml --input target=...

# HTTP
curl -X POST http://localhost:8000/api/workflows/run \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "my-workflow", "inputs": {"target": "example.com"}}'
```

## Parallel dispatch (1.3.0+)

Each tick:

1. Engine asks the scheduler for `ready_steps()` — every step whose `depends_on` is satisfied.
2. Scheduler delegates to `arch.schedule_ready()` — the detected architecture decides which to dispatch concurrently vs defer (e.g. unified architecture serializes when total est_size_gb exceeds budget).
3. Non-deferred steps go to a `ThreadPoolExecutor`; the tick drains via `as_completed`.
4. `OllamaService._LLM_SEMAPHORE` keeps actual model calls serialized regardless of dispatcher concurrency — the parallelism is in the orchestration layer, not the inference layer.

Workflows without `depends_on` collapse to one step per tick — identical to pre-1.3.0 behavior.

## Feasibility validation (1.3.0+)

`AgentStep.est_size_gb` is an operator-supplied estimate. At load time, `scheduler.validate_feasibility()` checks every step against the arch's memory budget:

```
WorkflowValidationError: step 'huge-model' requests 80.0 GB but arch budget is 24.0 GB
```

Common values: 7B Q4_K_M ≈ 4.5 GB, 13B Q4_K_M ≈ 8 GB, 34B Q4_K_M ≈ 20 GB, 70B Q4_K_M ≈ 40 GB.

## Schedule preview endpoint

```bash
curl http://localhost:8000/api/workflows/my-workflow/schedule-preview | jq
```

Returns the per-tick schedule the engine would run on the detected architecture.

## Composite step kinds (1.3.0+)

Beyond simple sequential steps, the engine supports:

- **`kind: parallel`** — fan-out a step across multiple models/inputs. Four parallelism modes including `single_model_pseudo_parallel` for prompt-cache reuse.
- **`kind: loop`** — body executes until a predicate is satisfied.
- **`kind: a2a`** — outbound A2A agent delegation.

See [docs/plans/](https://github.com/hankthebldr/local-ai-platform/tree/main/docs/plans) for the design notes.

## Built-in workflows

Under [`workflows/`](https://github.com/hankthebldr/local-ai-platform/tree/main/workflows):

- `code-review.yaml` — multi-agent PR review
- `data-model-rules.yaml`, `xsiam-data-model-rules.yaml` — Cortex XSIAM rule authoring
- `xdm-rule-from-log.yaml`, `xdm-bulk-onboarding.yaml`, `xdm-vendor-pack.yaml` — XDM normalization
- `xsiam-normalization-pipeline.yaml` — end-to-end normalization
- `document-qa.yaml` — RAG-driven Q&A over uploaded documents
- `email-draft.yaml`, `meeting-summary.yaml`, `research-brief.yaml` — productivity templates

## See also

- [Agents](Agents) — pre-built personas droppable into a workflow as steps
- [Models](Models) — which model to pick for each role
- [Architecture](Architecture) — the engine internals
- [Configuration](Configuration) — env vars that affect dispatch
