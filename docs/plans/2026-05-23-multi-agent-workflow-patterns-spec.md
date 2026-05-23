# Multi-Agent Workflow Patterns — Step Kinds Spec

**Date**: 2026-05-23
**Status**: Draft
**Branch**: `claude/multi-agent-workflow-brainstorm-eAR83`
**Builds on**: `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md`,
`docs/plans/2026-05-19-architecture-aware-orchestration-design.md`

## Purpose

The current engine (`api/services/workflow_engine.py`, `step_executor.py`) treats every
step as a single LLM call with `depends_on` DAG wiring. That covers sequential pipelines
and shallow fan-out, but does not cover the patterns that Anthropic's research system and
Google ADK have converged on:

- **Parallel fan-out / gather** (ADK `ParallelAgent`, Anthropic subagent spawn)
- **Refine-until-good loop** (ADK `LoopAgent`, Anthropic generator-critic)
- **Dynamic orchestrator-worker** (Anthropic lead-agent pattern, ADK `LlmAgent` with
  sub-agent tools)
- **Cross-agent calls over A2A** (Google A2A spec, Linux Foundation)
- **Cross-session memory consolidation** (Anthropic "Dreaming")
- **Autonomous recursive loop** (RALPH-style self-driving development)

This spec defines a discriminated `kind` field on every step plus six new step kinds,
keeping the `seed` / `workspace` / `shared` three-layer context model unchanged. All
existing workflows continue to validate without changes (the new field defaults to
`kind: llm`).

The defining constraint of Enclave is **CPU-first, single-operator, one-Ollama-instance**.
That rules out treating "parallel" as "more processes hitting more GPUs" and forces
a more interesting question: *how do you get the multi-agent quality lift on a single
30B–70B model running on one box?* That question gets its own section below.

---

## 1. Step kind discrimination

### Today

`AgentStep` in `api/models/workflow_models.py` has no kind field. Every step is an LLM
call. To introduce new step types without breaking existing workflows, add an optional
`kind` discriminator that defaults to `llm`.

### Proposed schema change

```python
# api/models/workflow_models.py

class AgentStep(BaseModel):
    id: str
    name: str
    kind: Literal["llm", "parallel", "loop", "orchestrator", "a2a", "consolidate", "ralph"] = "llm"
    depends_on: List[str] = Field(default_factory=list)
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(min_length=1)
    config: StepConfig = Field(default_factory=StepConfig)
    hooks: StepHooks = Field(default_factory=StepHooks)

    # ── kind: llm (current behavior) ───────────────────────────────────
    model: Optional[str] = None
    role: Optional[str] = None
    est_size_gb: Optional[float] = None
    system_prompt: Optional[str] = None
    prompt: Optional[StepPrompt] = None
    output_schema: Optional[Dict[str, Any]] = None

    # ── kind: parallel ────────────────────────────────────────────────
    branches: Optional[List["AgentStep"]] = None     # children to fan out
    gather: Optional["AgentStep"] = None              # synthesis step
    execution: Optional[ParallelExecutionConfig] = None

    # ── kind: loop ────────────────────────────────────────────────────
    body: Optional[List["AgentStep"]] = None
    until: Optional[LoopTermination] = None
    max_iterations: int = 5

    # ── kind: orchestrator ────────────────────────────────────────────
    workers: Optional[Dict[str, "AgentStep"]] = None  # worker_id -> step template
    planner: Optional[StepPrompt] = None              # lead-agent system prompt
    max_workers_spawned: int = 8
    budget: Optional[OrchestratorBudget] = None

    # ── kind: a2a ─────────────────────────────────────────────────────
    agent_card_url: Optional[str] = None              # /.well-known/agent.json
    skill: Optional[str] = None
    auth: Optional[A2AAuth] = None

    # ── kind: consolidate ─────────────────────────────────────────────
    consolidate: Optional[ConsolidateSpec] = None

    # ── kind: ralph ───────────────────────────────────────────────────
    ralph: Optional[RalphSpec] = None
```

A `@model_validator` enforces that the required field set for each kind is populated
(e.g. `kind: parallel` requires `branches` and `gather`; `kind: a2a` requires
`agent_card_url` and `skill`).

### Engine dispatch

`StepExecutor.execute(step, ctx)` becomes a thin dispatch on `step.kind`:

```python
EXECUTORS = {
    "llm":          LlmStepExecutor,
    "parallel":     ParallelStepExecutor,
    "loop":         LoopStepExecutor,
    "orchestrator": OrchestratorStepExecutor,
    "a2a":          A2AStepExecutor,
    "consolidate":  ConsolidateStepExecutor,
    "ralph":        RalphStepExecutor,
}
```

Each kind-specific executor is a subclass of a new `BaseStepExecutor` with the existing
hook lifecycle preserved (`before_step`, `after_step`, `on_retry`, `on_failure`,
`on_skip`, `on_complete` from `hook_bus.py`).

### Backwards compatibility

- Existing YAML without `kind:` parses to `kind: llm` and runs identically.
- The composer/preview UI gets a kind-aware renderer; unknown kinds render as a generic
  box with a warning. The YAML schema in `workflow_index.py` is bumped to
  `schema_version: 2`; v1 workflows are auto-upgraded on load.

---

## 2. `kind: parallel` — fan-out / gather

### Semantics

`parallel` is a composite step. It declares N sibling `branches` that read from the
shared context and write to *isolated* sub-workspaces under
`workspace.{parent_id}.branches.{branch_id}`. After all branches succeed (or fail
according to `execution.failure_policy`), an optional `gather` step runs with read
access to all branch sub-workspaces and writes to `workspace.{parent_id}` (the
synthesis output).

This matches ADK `ParallelAgent` + a downstream synthesizer, and matches Anthropic's
"lead spawns N subagents, each with isolated context, lead synthesizes" pattern. The
difference from Anthropic's version: the fan-out shape is **static** (declared in
YAML), not dynamic. Dynamic shape is the `orchestrator` kind below.

### YAML

```yaml
- id: investigate_log_source
  kind: parallel
  depends_on: [ingest_samples]
  inputs: [ingest_samples.raw_logs]
  outputs: [findings]                       # what `gather` writes to workspace
  execution:
    mode: multi_model_concurrent            # see §3
    max_concurrency: 3
    failure_policy: continue_on_partial     # or `fail_fast`
    timeout_per_branch: 180

  branches:
    - id: extract_schema
      kind: llm
      role: reasoning
      inputs: [ingest_samples.raw_logs]
      outputs: [schema]
      system_prompt: |
        You are a log-format expert. Extract field schema, types, sample values.

    - id: classify_events
      kind: llm
      role: fast
      inputs: [ingest_samples.raw_logs]
      outputs: [event_types]
      system_prompt: |
        Categorize distinct event types in the samples.

    - id: detect_pii
      kind: llm
      role: fast
      inputs: [ingest_samples.raw_logs]
      outputs: [pii_fields]
      system_prompt: |
        Flag fields that may contain PII (email, IP, username, tokens).

  gather:
    id: synthesize_findings
    kind: llm
    role: reasoning
    inputs:
      - extract_schema.schema
      - classify_events.event_types
      - detect_pii.pii_fields
    outputs: [findings]
    system_prompt: |
      You are the lead analyst. Synthesize the three branch reports into a single
      findings document. Resolve disagreements explicitly.
```

### Context flow

Branches read from `seed` and any prior workspace namespace, exactly like top-level
steps. Branches write to `workspace.investigate_log_source.branches.{branch_id}`. The
gather step reads `branches.*` (or specific branch outputs by ID) and writes to
`workspace.investigate_log_source.findings`. Anything outside the parent's sub-tree
is read-only to branches and to the gather step.

### Engine implementation

```python
class ParallelStepExecutor(BaseStepExecutor):
    async def execute(self, step, ctx):
        mode = step.execution.mode
        sem = asyncio.Semaphore(step.execution.max_concurrency)
        scheduler = self._pick_scheduler(mode, step.execution)

        async def run_branch(branch):
            async with sem:
                branch_ctx = ctx.scoped(parent_id=step.id, branch_id=branch.id)
                return await scheduler.run(branch, branch_ctx)

        results = await asyncio.gather(
            *[run_branch(b) for b in step.branches],
            return_exceptions=(step.execution.failure_policy == "continue_on_partial"),
        )
        self._merge_branch_results(ctx, step, results)
        return await self._executor_for(step.gather).execute(step.gather, ctx)
```

The `scheduler` abstraction is what makes `mode` meaningful — covered next.

---

## 3. Parallelism on CPU / single Ollama instance

This is the section that matters for Enclave specifically. A naïve
`asyncio.gather` over three `ollama.generate(model="qwen3:32b", ...)` calls will be
serialized by Ollama's runner pool. The illusion of parallelism without the throughput
benefit is worse than honest sequential execution because it hides where the time
actually went. The engine must distinguish between **execution modes** and pick
intentionally.

### 3.1 Mode `multi_model_concurrent` (default for heterogeneous fan-out)

Each branch runs on a *different* model. Ollama loads each model into its own runner
slot (`OLLAMA_MAX_LOADED_MODELS` controls how many can be resident; bumped from default 1
to e.g. 3 on the 96GB box). Branches genuinely execute in parallel, bottlenecked by
CPU thread count and RAM bandwidth.

Best for: heterogeneous specialist branches (one 7B fast + one 13B coding + one 34B
reasoning). Scheduler maps branches to specific models, validates against
`Architecture.feasible()` from the architecture-aware orchestration design, and
refuses to schedule if combined `est_size_gb` exceeds the deployment budget.

### 3.2 Mode `single_model_concurrent` (one model, multiple concurrent requests)

Branches all target the same model. Ollama 0.23.4 (the pinned floor) supports
`OLLAMA_NUM_PARALLEL=N`, which gives the runner N concurrent generation slots
backed by separate KV caches. Each slot consumes additional context-window memory
(2K context × N slots, scaled by model size). On a 70B model with 8K context, each
extra slot costs ~1–2 GB.

**Throughput characteristic**: with N parallel slots, total tokens/sec is roughly
`base_tps × (0.6 × N + 0.4)` — i.e. ~60% scaling per slot due to memory-bandwidth
contention. Two slots is the sweet spot; four slots is the practical ceiling on
the BD790i. The win is *latency-of-the-slowest-branch*, not throughput multiplied.

Best for: same-model multi-persona fan-out where you want context isolation more
than raw speed. Scheduler:

1. Asserts all branches resolve to the same `model_name`.
2. Sets `OLLAMA_NUM_PARALLEL` for this run (or asserts it's pre-configured).
3. Issues N concurrent `/api/generate` calls.
4. Falls back to `single_model_pseudo_parallel` (3.3) if the slot count is
   insufficient or RAM pressure is high.

### 3.3 Mode `single_model_pseudo_parallel` (one model, sequential calls, isolated contexts)

This is the **interesting one** for the user's specific question about getting
fan-out behavior from single-large-model workflows. Branches resolve to the same model
but are executed *sequentially*. The compute cost is `N × base_latency` — no speedup.
But the *output quality* benefit of multi-agent is preserved because:

- Each branch sees only its own persona prompt + the shared inputs, not the other
  branches' work-in-progress.
- The gather step synthesizes from N independent first-principles attempts rather
  than from one attempt biased by what it already wrote.

In Anthropic's research-system writeup, this is the explicit finding: the bulk of
the multi-agent quality gain comes from *aggregate context expansion* (more total
tokens spent on the problem) and *context isolation* (each subagent reasons without
contamination), not from wall-clock parallelism. Pseudo-parallel mode delivers both
of those on a single-model single-machine deployment.

**Prompt-prefix sharing optimization**: when branches share large prefixes (system
prompt, common context, RAG-retrieved chunks), structure the prompt so that the
shared prefix is byte-identical across branches. Ollama's prompt cache reuses the
KV state for matching prefixes, so branch N+1 only re-evaluates the divergent
persona/task portion. On a 32B model with an 8K shared prefix and a 512-token
divergent suffix, this drops branch latency by ~70%. The prompt composer
(`api/services/prompt_composer.py`) needs a `prefix_lock` flag to enforce identical
byte-prefixes — Jinja2 by default whitespace-mangles output and breaks the cache.

YAML:

```yaml
execution:
  mode: single_model_pseudo_parallel
  prefix_lock: true                    # composer emits identical shared prefixes
  shared_prefix:                        # explicit shared block, rendered once
    - seed.constraints
    - rag.chunks
```

The scheduler exports `(shared_prefix_hash, branch_id)` to the telemetry layer so
operators can see cache-hit rates per run.

### 3.4 Mode `sharded` (long-context single-model partition)

Designed for cases where you have one very large input that doesn't fit in context.
The parent step shards the input deterministically (e.g. one branch per source file,
or per log file, or per RAG chunk cluster) and dispatches the *same persona prompt*
across shards. The branches all hit the same model in pseudo-parallel mode.

```yaml
execution:
  mode: sharded
  sharder: by_file              # built-in: by_file, by_chunk, by_token_window
  shard_input: ingest.documents
  shared_persona: schema_extractor   # one persona, applied per shard
```

Differs from `single_model_pseudo_parallel` in that branches are *generated* by
the sharder rather than declared in YAML — there's a single persona spec and N
shards become N branches at runtime.

### 3.5 Mode selection table

| Hardware | Branch count | Model size | Recommended mode |
|---|---|---|---|
| MS-01 64GB | 2–3 | 7B–13B mixed | `multi_model_concurrent` |
| MS-01 64GB | 2–4 | same 30B | `single_model_concurrent` (N=2) |
| BD790i 96GB | 3–5 | 7B–34B mixed | `multi_model_concurrent` |
| BD790i 96GB | 2–4 | same 70B | `single_model_pseudo_parallel` |
| BD790i 96GB | 8+ | same model, large input | `sharded` |
| Mac M4 Pro 48GB | 2 | same 13B | `single_model_concurrent` (N=2) |
| Mac M4 Pro 48GB | 3+ | same 30B | `single_model_pseudo_parallel` |

The engine can auto-select mode if the YAML omits `execution.mode` and the
architecture detector (from `architecture-aware-orchestration-design.md`) has
populated `Deployment.capabilities`.

---

## 4. `kind: loop` — refine-until-good

### Semantics

A `loop` step executes its `body` (one or more child steps) repeatedly until the
`until` predicate is satisfied or `max_iterations` is reached. Each iteration's
workspace is namespaced as `workspace.{loop_id}.iterations.{n}`. The `until`
predicate runs after each iteration and can reference any field in the iteration's
workspace.

This is the generator-critic pattern. ADK has it as `LoopAgent`. Anthropic does it
ad-hoc via tool-call loops in the agent SDK.

### YAML

```yaml
- id: refine_rule
  kind: loop
  depends_on: [draft_rule]
  inputs: [draft_rule.rule_yaml]
  outputs: [final_rule]
  max_iterations: 5
  until:
    type: gate                              # built-in predicates: gate, jsonpath_eq, llm_judge
    gate: critic.approved == true
    on_max_iterations: emit_best            # or `fail`

  body:
    - id: critic
      kind: llm
      role: reasoning
      inputs:
        - draft_rule.rule_yaml              # iteration 0
        - $loop.previous_iteration.refined  # iterations 1+
      outputs: [approved, issues, suggestions]
      output_schema:
        type: object
        properties:
          approved: {type: boolean}
          issues: {type: array, items: {type: string}}
          suggestions: {type: string}
      system_prompt: |
        You are a strict reviewer. Score the rule on correctness and style.
        Set approved=true only if zero issues remain.

    - id: refine
      kind: llm
      role: coding
      depends_on: [critic]
      inputs: [critic.suggestions, critic.issues]
      outputs: [refined]
      system_prompt: |
        Revise the rule to address every issue and adopt the suggestions.
```

The `$loop.previous_iteration` is a special context accessor available only inside
loop bodies. On iteration 0 it resolves to the loop's declared inputs; on iteration
N it resolves to iteration N-1's outputs.

### Termination strategies

- `gate` — boolean expression over the iteration's outputs (uses the existing
  `quality_gates.py` evaluator)
- `jsonpath_eq` — JSONPath equality check
- `llm_judge` — fire a small judge model to score the iteration; stop when score ≥ threshold
- `fixed_point` — stop when iteration N output equals iteration N-1 output (Levenshtein < threshold)
- `external_signal` — wait for an external `/loop/{run_id}/halt` API call (for human-in-the-loop)

### Engine implementation

```python
class LoopStepExecutor(BaseStepExecutor):
    async def execute(self, step, ctx):
        for n in range(step.max_iterations):
            iter_ctx = ctx.scoped(loop_id=step.id, iteration=n)
            for child in step.body:
                await self._executor_for(child).execute(child, iter_ctx)
            if await self._predicate_satisfied(step.until, iter_ctx):
                ctx.write(step.outputs[0], iter_ctx.final_output())
                return
        await self._on_max_iterations(step, ctx)
```

---

## 5. `kind: orchestrator` — dynamic lead-agent delegation

### Semantics

The orchestrator step is the **Anthropic research-system pattern** in YAML form.
A lead agent receives the inputs, decides *at runtime* how many workers to spawn
and what each should do, dispatches them, and synthesizes results. Unlike
`kind: parallel`, the fan-out shape is determined by the LLM, not the YAML.

The YAML declares:
- The lead agent's persona (`planner`)
- A library of available **worker templates** (`workers: {worker_id: AgentStep}`)
- A budget (max workers, max total tokens, max wall time)

At runtime, the lead receives a tool `spawn_worker(worker_id, task_description,
inputs)` which the engine intercepts. Each `spawn_worker` call instantiates the
template, populates its inputs with whatever the lead passed, executes it (in
parallel with other spawned workers, subject to `max_concurrency`), and returns
the worker's outputs as a tool result the lead sees.

### YAML

```yaml
- id: investigate_incident
  kind: orchestrator
  depends_on: [ingest_alert]
  inputs: [ingest_alert.alert_blob]
  outputs: [findings, recommended_actions]

  planner:
    role: reasoning
    model: qwen3-uncensored:32b
    template: |
      You are the lead incident investigator. You can spawn specialist workers.
      Available workers: {{ worker_catalog | yaml }}

      Alert: {{ inputs.alert_blob }}

      Plan: decompose the investigation into independent subtasks. Spawn workers
      for each. When all results are back, synthesize findings and recommend
      actions. Spawn at most {{ budget.max_workers }} workers total.

  workers:
    log_correlator:
      kind: llm
      role: reasoning
      inputs: [task_description, time_window]
      outputs: [correlated_events]
      system_prompt: |
        You are a log correlation specialist. Find events related to the task.

    ioc_extractor:
      kind: llm
      role: fast
      inputs: [task_description, raw_data]
      outputs: [iocs]
      system_prompt: |
        Extract IOCs (IPs, domains, hashes, users) from the data.

    threat_intel:
      kind: a2a
      agent_card_url: https://intel.local/.well-known/agent.json
      skill: enrich_iocs

  budget:
    max_workers: 6
    max_total_tokens: 200000
    max_wall_seconds: 600
    execution_mode: single_model_pseudo_parallel    # how spawned workers run
```

### Execution model

The lead agent runs as a standard `kind: llm` step with one critical addition:
its tool set includes `spawn_worker`. The model adapter
(`api/services/model_adapters.py`) presents `spawn_worker` as a regular function
tool. When the model invokes it, the orchestrator executor:

1. Validates `worker_id` against `step.workers`.
2. Instantiates the worker template, binding `inputs` from the tool-call args.
3. Schedules execution per `budget.execution_mode` (one of the parallel modes
   from §3).
4. Tracks token spend and worker count against `budget` — refuses further spawns
   when limits are hit (returns an error tool result the lead must handle).
5. When the worker completes, returns its outputs to the lead as a structured
   tool result.

The lead can spawn workers in waves (spawn 3, see results, spawn 2 more
informed by the first batch) — this is the key behavior that makes
orchestrator-worker more powerful than static fan-out.

### Why this matters for CPU-first

On a single-model deployment, the orchestrator mode is *especially valuable*:
the lead agent itself is the same 32B/70B that the workers use, called sequentially
in pseudo-parallel mode. The wall-clock cost is `(lead_planning + N × worker_latency
+ lead_synthesis)`, which is high — but on the kinds of tasks where this pattern
wins (open-ended research, incident investigation, codebase exploration), the
quality lift justifies the extra minutes. And operators always have the escape
hatch of switching `budget.execution_mode` to `single_model_concurrent` if they've
provisioned multiple Ollama slots.

---

## 6. `kind: a2a` — call external agents

### Semantics

An `a2a` step delegates to an external agent that conforms to the Google A2A
protocol (now Linux Foundation governed). The step declares:

- `agent_card_url` — where the remote agent advertises its capabilities
- `skill` — which advertised skill to invoke
- `auth` — bearer token / mTLS config
- Inputs are mapped to the A2A task payload; outputs are pulled from the task's
  final artifacts.

### YAML

```yaml
- id: enrich_with_intel
  kind: a2a
  depends_on: [extract_iocs]
  agent_card_url: https://intel.corp.local/.well-known/agent.json
  skill: enrich_iocs
  inputs: [extract_iocs.iocs]
  outputs: [enriched_iocs]
  auth:
    type: bearer
    token_env: INTEL_API_TOKEN
  streaming: true                       # consume SSE updates as workspace.intermediate
  timeout: 120
```

### Engine implementation

The existing `api/services/a2a_service.py` already speaks the protocol. The
`A2AStepExecutor` is a thin wrapper that:

1. Fetches and caches the Agent Card.
2. Validates the requested skill is advertised.
3. Posts a `tasks/send` with inputs mapped per the skill's input schema.
4. Polls (or streams via SSE) until `state in {completed, failed, canceled}`.
5. Maps task artifacts to the step's declared outputs.

### Serving our own card

Symmetrically, every loaded workflow gets advertised in the local
`/.well-known/agent.json`, with each workflow becoming an A2A skill. This is
config-only on the existing `a2a.py` router — no new server. The result: any
ADK or LangGraph agent can call an Enclave workflow as if it were an external
agent, with full streaming and artifact return. This is the cheapest possible
"play nicely with the ecosystem" move and worth doing in the same release as
the `kind: a2a` step.

---

## 7. `kind: consolidate` — memory consolidation ("Dreaming")

### Semantics

A `consolidate` step takes a body of transcript/workspace data and produces a
compressed, structured memory artifact that future workflow runs can load as
seed context. It's the explicit analogue of Anthropic's "Dreaming" feature —
between-session learning expressed as a workflow step rather than as a hidden
managed-service behavior.

This is also the prerequisite for the RALPH loop in §8.

### YAML

```yaml
- id: distill_session
  kind: consolidate
  depends_on: [investigate_incident]
  inputs:
    - investigate_incident.findings
    - $run.transcripts                 # special: all step transcripts in this run
    - $memory.playbook                 # current playbook (read)
  outputs: [updated_playbook, lessons]
  consolidate:
    role: reasoning
    target: playbook                   # where to store: playbook | episodic | semantic
    target_path: data/playbooks/incident_response.md
    merge_strategy: append_with_dedup   # or replace, structured_merge
    system_prompt: |
      You are the system's memory consolidator. Given this run's findings and
      transcripts, extract durable lessons that should inform future runs.

      Current playbook:
      ---
      {{ memory.playbook }}
      ---

      For each lesson:
      - Phrase as an imperative rule ("When X, prefer Y because Z")
      - Tag with the conditions under which it applies
      - Cite the run_id and step_id that justifies it
      - If a new lesson contradicts an existing one, mark the existing one as
        superseded rather than deleting it.

      Output the merged playbook and a list of net-new lessons.
```

### Storage

Three memory stores, all on local disk (no cloud):

- **`data/playbooks/{name}.md`** — durable, human-readable, append-only rules.
  Loaded as part of the system prompt for steps that declare
  `inputs: [$memory.playbook]`.
- **`data/memory/episodic/{run_id}.jsonl`** — compressed run transcripts indexed
  for similarity search via the existing RAG pipeline. Loaded selectively (top-K
  similar past runs) by steps that declare `inputs: [$memory.episodic(query=...)]`.
- **`data/memory/semantic/{concept}.md`** — distilled facts (e.g. "the
  data_received_time field is the canonical XDM timestamp"). Indexed and loaded
  per concept reference.

Consolidate steps write to the store identified by `target`. Read access is
exposed to other steps via the `$memory.*` context accessors, which are
implemented as a thin extension to the `WorkflowContext` shared layer.

---

## 8. `kind: ralph` — autonomous recursive loop

### What RALPH is

RALPH (Recursive Agentic Loop with Persistent Heuristics — the community
acronym for the pattern Geoff Huntley described as
`while :; do claude "do the next thing"; done`) is a self-driving development
loop. The agent reads a todo list / playbook, picks the next item, executes it,
verifies the result, updates the playbook with what it learned, and repeats —
indefinitely, until a halt condition.

In Anthropic terms it's `orchestrator + outcomes + dreaming` composed into a
single autonomous primitive. In ADK terms it's `LoopAgent(SequentialAgent([
LlmAgent(planner), LlmAgent(executor), LlmAgent(verifier), CustomAgent(consolidator)
]))` with a halt predicate.

This is the end-state primitive Enclave needs to expose for **enclave-code**'s
"almost fully autonomous development" mode (referenced in
`docs/plans/2026-05-16-enclave-code-spec.md`).

### YAML

```yaml
- id: autonomous_dev_loop
  kind: ralph
  inputs: [seed.repo_path, seed.charter]
  outputs: [completed_tasks, final_state, learned_rules]

  ralph:
    # Persistent state lives on disk between iterations
    state:
      todo_path: "{{ seed.repo_path }}/.enclave/todo.md"
      playbook_path: "{{ seed.repo_path }}/.enclave/playbook.md"
      journal_path: "{{ seed.repo_path }}/.enclave/journal.jsonl"

    # Halt conditions — any one stops the loop
    halt:
      max_iterations: 100
      max_wall_hours: 8
      max_total_tokens: 5_000_000
      max_consecutive_failures: 3
      external_signal_path: "{{ seed.repo_path }}/.enclave/HALT"
      goal_reached:
        type: llm_judge
        prompt: "Is the charter fully satisfied based on the journal?"
        threshold: 0.95

    # Budget per iteration (prevents one bad iteration from burning everything)
    iteration_budget:
      max_tokens: 50000
      max_wall_minutes: 15
      execution_mode: single_model_pseudo_parallel

    # The four sub-agents that compose each iteration
    body:
      - id: plan
        kind: llm
        role: reasoning
        inputs: [$ralph.todo, $ralph.playbook, $ralph.journal_tail(10)]
        outputs: [chosen_task, plan]
        system_prompt: |
          You are the planner. Read the todo list and playbook. Pick the next
          best task. Produce a step-by-step plan that respects the playbook.

      - id: execute
        kind: orchestrator
        depends_on: [plan]
        inputs: [plan.chosen_task, plan.plan]
        outputs: [execution_log, artifacts]
        planner:
          template: |
            You are executing this plan. Spawn workers as needed. Stop when the
            plan is done or you hit a blocker.
        workers:
          code_writer: {kind: llm, role: coding, ...}
          test_runner: {kind: llm, role: fast, ...}
          file_reader: {kind: llm, role: fast, ...}

      - id: verify
        kind: llm
        role: reasoning
        depends_on: [execute]
        inputs: [plan.chosen_task, execute.execution_log, execute.artifacts]
        outputs: [verified, evidence, regressions]
        system_prompt: |
          You are the verifier. Independently check that the task was actually
          completed. Run tests. Check for regressions. Be skeptical.

      - id: reflect
        kind: consolidate
        depends_on: [verify]
        inputs: [plan.chosen_task, execute.execution_log, verify.evidence]
        outputs: [new_rules]
        consolidate:
          target: playbook
          target_path: "{{ ralph.state.playbook_path }}"
          merge_strategy: append_with_dedup
          system_prompt: |
            What did this iteration teach us? Extract rules that would have made
            the planner pick a better task or the executor produce better code.
            Only emit rules with concrete evidence from this iteration.

      - id: commit_journal
        kind: builtin                    # not an LLM call — writes to disk
        builtin: journal_append
        inputs: [plan, verify.verified, verify.evidence, reflect.new_rules]
```

### Execution model

The RALPH executor runs the body steps as an inner `SequentialAgent`-style pipeline,
then loops with persistent on-disk state, checking the halt condition between
iterations. The journal is structured so that on container/process restart the
loop can resume from the last journaled iteration without losing progress —
this is critical for an 8-hour autonomous session on a self-hosted box where
power cycles happen.

### Self-learning behavior

The playbook is the heart of self-learning. The `reflect` step appends rules
between iterations; the `plan` step reads them on the next iteration; over
hundreds of iterations the playbook becomes the agent's accumulated competence
for *this specific repo*. Because it's a flat markdown file at
`.enclave/playbook.md`, the operator can read it, edit it, redact it, or commit
it to git — keeping the operator in the loop on what the agent has "learned"
about their code.

To keep the playbook from drowning in stale rules, the consolidate step uses
`append_with_dedup`: new rules that semantically duplicate existing ones increment
a confidence counter on the existing rule rather than creating a duplicate. Rules
that contradict newer rules are marked `superseded` but kept (for audit). A
periodic `prune` consolidation (built-in skill, fires every 50 iterations)
removes superseded rules older than N iterations and rewrites the playbook
canonically.

### Safety rails

Autonomous = scary. Three rails are non-negotiable:

1. **Read-only by default until promoted.** The first M iterations (configurable,
   default 5) run with worker tool allowlists restricted to read-only operations.
   Only after the operator promotes the session (CLI command or API call) do
   write tools (`Edit`, `Write`, `Bash` with write effects) become available.
2. **Branch isolation.** RALPH operates only on a dedicated branch
   (`enclave-autopilot/{session_id}`). It cannot push to main, cannot force-push,
   cannot delete branches. The git hook bus already supports this — wire it as
   a default.
3. **External HALT signal.** A file at `{repo}/.enclave/HALT` halts the loop at
   the next iteration boundary, gracefully. The operator can also `kill -SIGTERM`
   the process; the journal is flushed on signal and the loop resumes from there
   when restarted.

---

## 9. Implementation plan

Ordered by dependency. Each row is one PR-sized chunk.

| # | Change | Files | Depends on |
|---|---|---|---|
| 1 | Add `kind` discriminator to `AgentStep`, default `llm`, no behavior change | `api/models/workflow_models.py`, tests | — |
| 2 | Refactor `StepExecutor.execute` to dispatch on `kind` via `EXECUTORS` table | `api/services/step_executor.py` | 1 |
| 3 | Implement `ParallelStepExecutor` with `multi_model_concurrent` mode only | `api/services/executors/parallel.py` (new) | 2 |
| 4 | Add `single_model_concurrent` mode + `OLLAMA_NUM_PARALLEL` plumbing | `api/services/executors/parallel.py`, `architecture.py` | 3 |
| 5 | Add `single_model_pseudo_parallel` mode + prompt-prefix-locking in composer | `api/services/prompt_composer.py`, `parallel.py` | 4 |
| 6 | Add `sharded` mode + built-in sharders (`by_file`, `by_chunk`, `by_token_window`) | `parallel.py`, `api/services/sharders/` (new) | 5 |
| 7 | Implement `LoopStepExecutor` + termination predicates | `api/services/executors/loop.py` (new), `quality_gates.py` | 2 |
| 8 | Implement `OrchestratorStepExecutor` + `spawn_worker` tool injection | `api/services/executors/orchestrator.py` (new), `model_adapters.py` | 5, 7 |
| 9 | Implement `A2AStepExecutor` (wraps existing `a2a_service.py`) | `api/services/executors/a2a.py` (new) | 2 |
| 10 | Auto-advertise loaded workflows as A2A skills at `/.well-known/agent.json` | `api/routers/a2a.py` | 9 |
| 11 | Implement `ConsolidateStepExecutor` + `data/playbooks/`, `data/memory/` stores | `api/services/executors/consolidate.py` (new), `api/services/memory_store.py` (new) | 2 |
| 12 | Add `$memory.*` context accessors to `WorkflowContext` | `api/models/workflow_models.py`, `prompt_composer.py` | 11 |
| 13 | Implement `RalphStepExecutor` (composite, uses 7/8/11) | `api/services/executors/ralph.py` (new) | 7, 8, 11 |
| 14 | Add safety rails: tool-allowlist promotion, branch isolation, HALT file | `ralph.py`, `hook_bus.py`, new git-isolation hook | 13 |
| 15 | CLI: `enclave workflow run --kind=ralph` with interactive promotion prompts | `cli/workflow.py` | 14 |
| 16 | Composer UI: kind-aware step renderers (parallel as fan-out box, loop as cycle, ralph as inner DAG) | `desktop/`, web composer | 1–13 |
| 17 | Docs: update `workflows/README.md`, add `MULTI_AGENT_PATTERNS.md` | docs | 1–15 |

Rows 1–6 are "the parallel story" and ship as a unit (one minor release, say 1.2.0).
Rows 7–10 are "the loop and external delegation story" (1.3.0).
Rows 11–17 are "the autonomous story" (1.4.0 / enclave-code).

The single-model parallelism modes (rows 4–5) are the highest-leverage work in the
plan: they unlock the multi-agent quality lift for operators who only have one
big model loaded, which is the dominant Enclave deployment shape.

---

## 10. Open questions

- **Prompt cache stability across Ollama restarts.** Ollama 0.23.4's prompt cache
  is in-process. A model unload/reload between branches destroys the cache. Does
  `single_model_pseudo_parallel` need to pin `keep_alive` for the duration of the
  parallel block? (Probably yes — set it engine-side, restore on completion.)

- **`OLLAMA_NUM_PARALLEL` is process-global.** It can't be set per-request. Does
  the engine need to advertise the slot count as a deployment capability and
  refuse workflows that demand more? (Yes — extend `Architecture.feasible()` to
  check parallel-slot demand.)

- **A2A streaming + the workspace model.** Streaming A2A artifacts naturally
  produce intermediate states; the workspace is keyed by step outputs that
  resolve at step completion. How should intermediate artifacts surface to
  downstream steps? (Proposal: a new `workspace.{step_id}.intermediate` namespace
  that's read-only and only available to other in-flight steps via a
  `$stream.*` accessor.)

- **RALPH playbook concurrency.** If two enclave-code sessions run RALPH against
  the same repo, they share the same playbook file. Lock file? Per-session
  playbooks with a periodic merge? (Default: per-session playbook + a `merge`
  consolidate step that runs on session end.)

- **Budget enforcement granularity.** Orchestrator and RALPH budgets are
  declared per step; the engine has no global per-run budget today. Should
  there be? (Yes, but out of scope for this spec — track in 1.4.0.)

- **Composability rules between kinds.** Can a `loop` body contain a `parallel`?
  (Yes — straightforward.) Can a `parallel` branch contain a `loop`? (Yes.)
  Can a `ralph` body contain a `ralph`? (No — refuse at validate time;
  nested autonomy is a foot-gun without much upside.)
