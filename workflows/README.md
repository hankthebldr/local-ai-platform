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
| `consolidate`  | Distill inputs into durable cross-run memory (playbook / semantic / episodic) | 4     |
| `ralph`        | Autonomous recursive loop (plan → execute → verify → reflect) with a journal + halt conditions; self-learns via a playbook | 5 |

See `workflows/example-parallel-loop.yaml`, `workflows/example-a2a-enrichment.yaml`,
`workflows/example-orchestrator.yaml`, `workflows/example-consolidate.yaml`,
and `workflows/example-ralph.yaml` for worked examples.

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
| `sharded`                       | One large input split across N shards, one persona | Declares **one** branch (the persona); engine clones it per shard, runs sequentially, gather reads `$shards` |

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

#### Sharded mode

For one large input that you want to process in pieces with a single persona
(e.g. "summarize each of these 40 log files", "extract entities from each
chunk of this huge document"). Unlike the other modes you don't enumerate
branches — you declare **one** persona and a shard strategy, and the engine
generates one branch per shard at runtime.

```yaml
- id: per_doc_extract
  kind: parallel
  outputs: [summary]
  execution:
    mode: sharded
    sharder: by_file        # by_file | by_chunk | by_token_window
    shard_input: ingest.documents   # context ref to the data to split
    shard_size: 2000        # by_chunk: items/chars per shard; by_token_window: tokens
    max_shards: 32          # hard cap; tail beyond this is dropped
    failure_policy: continue_on_partial
  branches:
    - id: extractor         # exactly ONE persona — cloned per shard
      role: fast
      prompt: { role_inline: "...", task: "extract from this shard" }
      inputs: [seed.shard]  # the engine seeds each clone with its shard
      outputs: [extracted]
  gather:
    id: synth
    role: reasoning
    prompt: { role_inline: "...", task: "combine all shard extractions" }
    inputs: [$shards.extracted]   # list of `extracted` from every shard
    outputs: [summary]
```

Shard strategies (see `api/services/sharders.py`):
- **`by_file`** — input is a list; one shard per element (the canonical
  one-branch-per-document split).
- **`by_chunk`** — list → groups of `shard_size` elements; string →
  `shard_size`-char substrings.
- **`by_token_window`** — string → ~`shard_size`-token windows, breaking on
  whitespace so words aren't split.

Each persona clone runs in a child context seeded with `seed.shard`,
`seed.shard_index`, and `seed.shard_count`. Dispatch is always sequential
(single-model) so the prompt cache stays warm and there are no concurrent
workspace writes. The gather step reads every shard's output via the
**`$shards`** accessor: `$shards` → the full list of per-shard output dicts,
`$shards.<key>` → the list of that key from each shard.

See `workflows/example-sharded.yaml` for a worked example.

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

### kind: consolidate

Distill a run's findings into **durable cross-run memory** — the "Dreaming"
pattern. The step runs one LLM call (its `system_prompt` over the declared
inputs) and writes the output into a memory store that future runs can read
via `$memory.*` inputs.

```yaml
- id: distill
  kind: consolidate
  depends_on: [investigate]
  inputs:
    - investigate.findings
    - $memory.playbook.incident_response   # prior playbook (for merge context)
  outputs:
    - updated_playbook
  consolidate:
    target: playbook                       # playbook | semantic | episodic
    target_name: incident_response         # file key within the store
    merge_strategy: append_with_dedup      # replace | append | append_with_dedup
    system_prompt: |
      Extract durable, imperative rules from this run's findings. Phrase each
      as "When X, prefer Y because Z". Skip anything already in the playbook.
```

**The three stores** (all local files under `MEMORY_DATA_DIR`, default `./data`):

| Target | On disk | Use |
|--------|---------|-----|
| `playbook` | `playbooks/<name>.md` | Human-readable operating rules; editable, git-committable |
| `semantic` | `memory/semantic/<concept>.md` | Distilled facts about a concept |
| `episodic` | `memory/episodic/<key>.jsonl` | Append-only run digests (recency-ordered) |

**Reading memory back** — any step (any kind) can declare a `$memory.*` input:

```yaml
inputs:
  - $memory.playbook.incident_response   # → the playbook markdown body
  - $memory.semantic.xdm_timestamps      # → the concept's markdown body
  - $memory.episodic.incident_log        # → recency digest of recent records
```

A first run against an empty store reads `""` — never an error. The accessor
resolves at input-resolution time, exactly like a `seed.*` or workspace ref.

**Merge strategies** (playbook/semantic only; episodic always appends):
- `replace` — overwrite the file
- `append` — append under a timestamped heading
- `append_with_dedup` — append only blocks not already present (whitespace/
  case-insensitive comparison), so re-running a workflow doesn't duplicate
  rules it already wrote

This store is the foundation the autonomous `ralph` loop (a future phase)
builds on for self-learning between iterations.

See `workflows/example-consolidate.yaml` for a worked example.

### kind: ralph

The **autonomous recursive loop** — plan → execute → verify → reflect,
repeated until a halt condition. Named after the community "Ralph" pattern
(`while :; do agent "do the next thing"; done`). Builds on `consolidate` +
`$memory.*` for self-learning: the `reflect` body step appends lessons to a
playbook the `plan` body step reads back on the next iteration.

```yaml
- id: autopilot
  kind: ralph
  outputs: [progress]
  ralph:
    journal_path: .enclave/journal.jsonl   # append-only iteration record
    halt:
      max_iterations: 50
      max_wall_seconds: 28800              # 8h
      max_total_tokens: 5000000
      max_consecutive_failures: 3          # stuck-loop guard
      halt_file: .enclave/HALT             # touch to stop gracefully
      goal_gate: "verify.done == True"     # optional success predicate
  body:
    - id: plan
      role: reasoning
      prompt: { role_inline: "...", task: "pick the next task" }
      inputs: [$memory.playbook.dev_lessons]   # read accumulated lessons
      outputs: [chosen_task, progress]
    - id: execute
      role: coding
      prompt: { role_inline: "...", task: "do the task" }
      inputs: [plan.chosen_task]
      outputs: [result]
    - id: verify
      role: reasoning
      prompt: { role_inline: "...", task: "check it worked" }
      inputs: [execute.result]
      outputs: [done]
    - id: reflect
      kind: consolidate                    # writes lessons back to the playbook
      inputs: [execute.result, verify.done]
      outputs: [lesson]
      consolidate:
        target: playbook
        target_name: dev_lessons
        merge_strategy: append_with_dedup
        system_prompt: "Extract durable lessons from this iteration."
```

**Halt conditions** (any fires → stop):

| Condition | Outcome |
|-----------|---------|
| `goal_gate` true | success |
| `halt_file` exists | success (graceful — operator's brake) |
| `max_iterations` / `max_wall_seconds` / `max_total_tokens` | success (bounded work done) |
| `max_consecutive_failures` | **failure** (stuck loop) |

**Outputs** are materialized from whichever body step produced each declared
key (last-producer-wins) — unlike `loop`, the headline output usually comes
from a middle step (`plan`/`execute`) while the last step is `reflect`.

**Resume**: the journal is read on entry; already-recorded iterations are
skipped so a restarted loop continues rather than re-running from zero. The
playbook on disk is the durable learning state — even a cold restart picks
up the accumulated rules.

**Safety rails**: the `halt_file`, `max_consecutive_failures`, and the hard
budgets are the engine-enforced rails. The other two rails from the spec —
**branch isolation** (operate only on a dedicated branch, never push to main)
and **read-only-until-promoted** (restrict write tools for the first N
iterations) — are tool-execution concerns enforced by the enclave-code layer
that gives ralph body steps real filesystem/git access. The workflow engine
itself dispatches LLM steps, not OS tools, so those rails live where the
tools do.

See `workflows/example-ralph.yaml` for a complete worked example.
