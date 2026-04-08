# Multi-Agent Workflow Engine Design

**Date**: 2026-04-06
**Status**: Design Approved
**Author**: Claude + Henry

## Overview

A sequential pipeline engine for composing multi-agent workflows on the Local AI Platform. Users define step-based workflows in YAML, where each step is an agent with its own system prompt, model selection, and declared inputs/outputs. The engine executes steps sequentially, manages context flow between agents, and persists results.

**Immediate use case**: Using multiple cooperating agents to generate data model rules from source code.

**Core principles**:
- YAML definitions in `workflows/` directory, triggerable via CLI or API
- Shared context with explicit I/O declarations per step (no implicit coupling)
- Retry with backoff on failure (configurable per step)
- Model selection by explicit name or role-based resolution via existing inventory
- All state persisted to `data/workflows/{run_id}/`

## Approach Selection

Three approaches were evaluated:

### A. Sequential Pipeline Engine (Selected)
Steps execute one at a time. Each step reads declared inputs from context, calls the LLM, writes outputs to its namespace. Engine validates I/O wiring at load time.

**Why chosen**: Fits the primary use case (linear code-gen workflows), simple to debug, natural evolution path to parallel execution and context graphs.

### B. Actor-Based Agents (Backlog)
Long-lived agents with message queues, supervised by a coordinator. Natural concurrency but requires message broker infrastructure and is hard to debug.

**Future consideration**: When workflows need real-time multi-agent negotiation or long-running background agents.

### C. LangGraph-Style State Machine (Backlog)
Workflow as a state machine with conditional transitions between nodes. Good for branching logic but overcomplicates linear workflows.

**Future consideration**: When workflows need conditional routing ("if validation fails, loop back to draft step").

## Core Data Model

### AgentStep

A single unit of work in a workflow.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique step identifier (e.g., `analyze_schema`) |
| `name` | string | yes | Human-readable label |
| `model` | string | no | Explicit model name (e.g., `qwen3.5-uncensored:35b`) |
| `role` | string | no | Model role for resolution (`reasoning`, `fast`, `coding`, `uncensored`, `general`) |
| `system_prompt` | string | yes | Agent persona and instructions |
| `inputs` | list[string] | yes | Context keys this step reads (e.g., `seed.constraints`, `analyze_schema.entities`) |
| `outputs` | list[string] | yes | Context keys this step writes (e.g., `entities`, `relationships`) |
| `config` | object | no | Step-level overrides: `temperature`, `max_tokens`, `retries`, `retry_delay`, `timeout` |

**Model resolution**: If `model` is set, use it directly (validated against inventory). If `role` is set, resolve via inventory to the best available model tagged with that role. If neither, use workflow `defaults.role`. At least one must resolve.

### WorkflowDefinition

The full workflow, parsed from YAML.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique workflow identifier |
| `name` | string | yes | Human-readable name |
| `description` | string | no | What this workflow does |
| `version` | string | no | Semver for workflow evolution |
| `defaults` | object | no | Workflow-level defaults: `role`, `temperature`, `max_tokens`, `retries`, `retry_delay` |
| `steps` | list[AgentStep] | yes | Ordered list of steps to execute |

### WorkflowContext (Three-Layer Model)

The shared state object passed through the execution chain. Three distinct layers provide traceability, isolation, and selective injection.

#### Layer 1: `seed` (immutable)

The user's original input. Never modified by agents. Always available to every step. This is the ground truth the workflow was invoked with.

```yaml
seed:
  task: "Generate data model rules for user authentication"
  constraints: "PostgreSQL, follows existing naming conventions"
  source_files: ["models/user.py", "models/session.py"]
```

#### Layer 2: `workspace` (scoped per-step, accumulated)

Each step writes to its own namespace within the workspace. Steps can read from any prior step's namespace but can only write to their own. This prevents clobbering and gives full traceability.

```yaml
workspace:
  analyze_schema:          # written by step 1
    entities: [...]
    relationships: [...]
  draft_rules:             # written by step 2, can read analyze_schema
    rules: [...]
    confidence_scores: [...]
  validate_rules:          # written by step 3, can read both above
    issues: [...]
    approved_rules: [...]
```

#### Layer 3: `shared` (mutable, cross-cutting)

A small shared scratchpad for things that accumulate across steps — running summaries, error logs, decision rationale. Steps must declare shared keys in their I/O mapping.

```yaml
shared:
  decisions: ["chose PostgreSQL enum over check constraint because..."]
  warnings: ["table 'sessions' has no index on user_id"]
```

#### Context Access Rules

- Every step can read `seed` (always, implicitly available)
- Every step can read any prior step's `workspace` namespace (by name in `inputs`)
- Steps write to `workspace.{own_step_id}` only
- `shared` keys require explicit declaration in `inputs`/`outputs`
- Engine validates at load time: every declared input must trace to a prior step's output or exist in seed

#### Context Windowing

Each step's prompt is assembled from only its declared inputs + seed. Large outputs (full code files, long analyses) get summarized or truncated, with full artifact stored on disk at `data/workflows/{run_id}/artifacts/`.

#### Future: Context Graph

The namespaced workspace entries are already nodes with producer/consumer edges. A future context graph implementation can layer on top of this model without restructuring — each workspace entry becomes a node, each input/output declaration becomes an edge, and the `shared` layer becomes a set of cross-cutting edges.

### WorkflowRun

A single execution instance.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | string | UUID for this execution |
| `workflow_id` | string | References the workflow definition |
| `status` | enum | `pending` → `running` → `completed` / `failed` |
| `context` | WorkflowContext | Full context snapshot |
| `step_results` | list[StepResult] | Per-step outcomes |
| `started_at` | datetime | Execution start |
| `completed_at` | datetime | Execution end |
| `error` | string | Error message if failed |

### StepResult

| Field | Type | Description |
|-------|------|-------------|
| `step_id` | string | Which step this result is for |
| `status` | enum | `pending` → `running` → `completed` / `failed` |
| `model_used` | string | Resolved model name (after role resolution) |
| `duration_seconds` | float | Wall clock time for this step |
| `token_count` | object | `{prompt_tokens, completion_tokens, total_tokens}` |
| `retries` | int | Number of retries before success/failure |
| `error` | string | Error message if failed |

## Engine Architecture

### WorkflowEngine

The central orchestrator. Three phases:

**1. Load Phase**
- Parses YAML definition into `WorkflowDefinition` (Pydantic validation)
- Validates I/O wiring: every step's declared `inputs` must trace to a prior step's `outputs` or exist in `seed`
- Resolves model roles against inventory service
- Fails fast with clear errors if anything is missing or misconfigured

**2. Execute Phase**
- Creates `WorkflowRun` and `WorkflowContext` (seeded with user input)
- Iterates through steps sequentially
- For each step:
  1. Assembles the prompt: `system_prompt` + relevant `seed` data + resolved inputs from workspace namespaces
  2. Resolves model (explicit name or role → inventory lookup)
  3. Calls `OllamaService.chat()` with assembled prompt
  4. Parses response and writes to `workspace.{step_id}.{output_key}`
  5. Updates `shared` if step declares shared outputs
  6. Records metadata (duration, tokens, model used)
  7. On failure: retry up to `num_retries` with exponential backoff, then abort run

**3. Persist Phase**
- Writes full `WorkflowRun` (context + results) to `data/workflows/{run_id}/run.json`
- Each step's raw output saved as individual artifact: `data/workflows/{run_id}/artifacts/{step_id}.json`
- Summary written to `data/workflows/{run_id}/summary.md`

### ModelResolver

Bridges workflows to the existing inventory system.

- If explicit `model`: validates it exists via inventory router, returns it
- If `role`: queries inventory for models tagged with that role, picks the best available (prefers larger/higher-quality if multiple match)
- Returns resolved model name to engine
- Roles: `reasoning`, `fast`, `coding`, `uncensored`, `general`

### StepExecutor

Runs a single step in isolation.

- Builds LLM prompt from context (only declared inputs, not entire context)
- Handles retry logic with exponential backoff
- Enforces timeout per step
- Parses structured output if step declares an output format (JSON, markdown)
- Writes results back to context under its namespace
- Returns `StepResult` with metadata

## Failure Handling

- Each step gets configurable retries (default: 2) with exponential backoff
- On exhausted retries: workflow run is marked `failed`, error recorded with step context
- Partial results are preserved — if step 3 of 4 fails, steps 1-2 outputs are still available
- No automatic rollback (outputs are additive, not destructive)
- Future: fallback model per step (if 35B times out, try 9B)

## YAML Workflow Format

### Complete Example: Data Model Rules

```yaml
# workflows/data-model-rules.yaml
id: data-model-rules
name: "Generate Data Model Rules"
version: "1.0"
description: "Multi-agent workflow to analyze source code and generate data model validation rules"

defaults:
  role: coding
  temperature: 0.7
  max_tokens: 4096
  retries: 2
  retry_delay: 5  # seconds

steps:
  - id: analyze_schema
    name: "Analyze Schema Structure"
    role: reasoning
    system_prompt: |
      You are a senior data architect. Analyze the provided source code
      and extract all entities, fields, types, and relationships.
      Return structured JSON with entities, fields, and relationships.
    inputs:
      - seed.source_files
      - seed.constraints
    outputs:
      - entities
      - relationships
      - field_types
    config:
      temperature: 0.3

  - id: draft_rules
    name: "Draft Validation Rules"
    role: coding
    system_prompt: |
      You are a data modeling expert. Given the analyzed schema,
      generate comprehensive validation rules covering: type constraints,
      referential integrity, business logic, and naming conventions.
    inputs:
      - seed.constraints
      - analyze_schema.entities
      - analyze_schema.relationships
      - analyze_schema.field_types
    outputs:
      - rules
      - rule_categories
    config:
      temperature: 0.5

  - id: validate_rules
    name: "Review & Validate Rules"
    role: reasoning
    system_prompt: |
      You are a QA engineer specializing in data integrity. Review the
      drafted rules for: completeness, conflicts, redundancy, and
      enforceability. Flag issues and suggest improvements.
    inputs:
      - analyze_schema.entities
      - draft_rules.rules
      - draft_rules.rule_categories
    outputs:
      - issues
      - approved_rules
      - suggestions
    config:
      max_tokens: 8192

  - id: generate_code
    name: "Generate Implementation Code"
    model: "qwen3.5-uncensored:35b"
    system_prompt: |
      You are a Python developer. Generate Pydantic model validators
      and SQLAlchemy constraints implementing the approved rules.
      Follow the existing project conventions.
    inputs:
      - seed.constraints
      - analyze_schema.entities
      - validate_rules.approved_rules
      - validate_rules.suggestions
    outputs:
      - pydantic_models
      - sqlalchemy_constraints
      - migration_script
```

## Triggering Workflows

### CLI

```bash
# Run a workflow with seed data
python cli/workflow.py run workflows/data-model-rules.yaml \
  --seed '{"source_files": ["models/user.py"], "constraints": "PostgreSQL, Pydantic v2"}'

# Check status of a run
python cli/workflow.py status {run_id}

# List recent runs
python cli/workflow.py list

# View a specific step's output
python cli/workflow.py artifact {run_id} generate_code
```

### API

```
POST /api/workflows/run
{
  "workflow_id": "data-model-rules",
  "seed": {
    "source_files": ["models/user.py", "models/session.py"],
    "constraints": "PostgreSQL, Pydantic v2"
  }
}
→ {"run_id": "abc-123", "status": "pending"}

GET /api/workflows/{run_id}/status
→ {"run_id": "abc-123", "status": "running", "current_step": "draft_rules", "step_results": [...]}

GET /api/workflows/{run_id}/artifacts/{step_id}
→ {"step_id": "generate_code", "outputs": {"pydantic_models": "...", ...}}

GET /api/workflows
→ [list of available workflow definitions]

GET /api/workflows/runs
→ [list of recent workflow runs with status]
```

## File Structure (New Files)

```
local-ai-platform/
├── api/
│   ├── routers/
│   │   └── workflows.py          # API endpoints for workflow CRUD and execution
│   ├── services/
│   │   ├── workflow_engine.py     # WorkflowEngine: load, validate, execute
│   │   ├── step_executor.py      # StepExecutor: run single step with retry
│   │   └── model_resolver.py     # ModelResolver: role → model via inventory
│   └── models/
│       └── workflow_models.py     # Pydantic models: WorkflowDefinition, AgentStep, etc.
├── cli/
│   └── workflow.py                # CLI tool for running/monitoring workflows
├── workflows/                     # YAML workflow definitions (user-created)
│   ├── data-model-rules.yaml      # Example: data model rule generation
│   └── README.md                  # How to write workflows
├── data/
│   └── workflows/                 # Execution data (gitignored)
│       └── {run_id}/
│           ├── run.json           # Full WorkflowRun serialization
│           ├── summary.md         # Human-readable execution summary
│           └── artifacts/
│               ├── analyze_schema.json
│               ├── draft_rules.json
│               ├── validate_rules.json
│               └── generate_code.json
└── tests/
    ├── test_workflow_engine.py     # Engine unit tests
    ├── test_step_executor.py       # Step executor tests
    ├── test_model_resolver.py      # Model resolution tests
    └── test_workflow_api.py        # API integration tests
```

## Integration with Existing Platform

### Inventory Router
ModelResolver calls the existing inventory service to:
- Validate explicit model names exist and are pulled
- Resolve roles to available models based on tags/capabilities
- No new model management — reuses existing infrastructure

### OllamaService
StepExecutor calls existing `OllamaService.chat()` for LLM inference:
- Same streaming, timeout, and error handling patterns
- Same `<think>` block stripping for reasoning models
- No new Ollama integration code

### Middleware
Workflow API endpoints inherit existing auth and rate limiting middleware.

### Logging
All workflow operations use existing structured logging with correlation IDs. Run ID is added as a correlation field for traceability.

## Backlog (Future Enhancements)

### Near-term
- **Parallel step execution**: Steps with no mutual dependencies run concurrently
- **Fallback models**: Per-step fallback if primary model fails/times out
- **Workflow templates**: Parameterized workflows with variable substitution
- **Step output validation**: JSON schema validation on step outputs

### Medium-term
- **Context graph**: Replace flat workspace with graph-based context management (nodes = outputs, edges = dependencies)
- **Conditional branching**: Steps can route to different next-steps based on output (state machine pattern)
- **Human-in-the-loop**: Pause workflow for user review/approval at designated checkpoints

### Long-term
- **Actor-based agents**: Long-lived agents with message queues for complex multi-turn interactions
- **Inter-agent communication**: Agents can message each other directly, not just through context
- **Workflow marketplace**: Share and discover community workflow definitions
- **Visual workflow editor**: Web UI for building workflows by connecting nodes (see UI/UX section below)

## UI/UX Flows — Node-Based Workflow Builder

The YAML is the serialization/persistence format. The primary creation experience is a visual node-based editor. YAML is generated and synced automatically — users never need to hand-edit it unless they choose to.

### Flow 1: Create a New Workflow
1. User clicks "New Workflow" → enters name + description
2. Canvas opens with a **Seed Node** pre-placed (the starting input block)
3. Seed node has a config panel: "What does this workflow receive?"
4. User adds seed fields — each field has a name, type, and description
5. The seed node's output ports update in real-time as fields are added

### Flow 2: Add Agent Steps
1. User drags an "Agent Step" from a sidebar palette onto the canvas
2. Step block appears with input ports (left edge) and output ports (right edge)
3. User clicks the block → config panel slides open with:
   - **Name**: human-readable step label
   - **System Prompt**: rich text editor with markdown support
   - **Model**: dropdown of available models (from inventory) *or* role picker (`reasoning`, `coding`, `fast`, `uncensored`, `general`)
   - **Config**: temperature slider, max tokens, retries, timeout
4. User defines outputs: "What does this agent produce?" — adds named output ports with descriptions
5. Multiple steps can be placed on canvas in any order; execution order is determined by connection topology

### Flow 3: Wire Connections (I/O Mapping)
1. User drags from an output port on Step A to an input port on Step B
2. Connection line appears with real-time validation:
   - **Green line** = valid connection
   - **Red line** = circular dependency detected
   - **Orange line** = connection valid but step order creates a warning
3. Input ports on a step show what data they expect (name + type hint)
4. Output ports show what they produce
5. Unconnected **required** inputs are highlighted with a warning badge
6. The engine validates the full DAG on every connection change — errors shown in a validation panel

### Flow 4: Run & Monitor
1. User clicks "Run" → modal generates a form from the Seed node's fields
2. User fills in seed values (or loads from a saved preset)
3. Execution starts → SSE connection streams real-time progress:
   - Each step block shows status indicator: ⏳ pending → 🔄 running → ✅ done / ❌ failed
   - Active step streams its LLM output in a panel below the canvas
   - Step blocks show elapsed time and token count as they complete
4. On completion: summary banner with total duration, tokens used, models used
5. On failure: failed step highlighted red, error message shown, option to "Re-run from here"

### Flow 5: Manage Outputs & Context
1. **Results tab**: shows the full three-layer context tree (seed → workspace namespaces → shared)
2. Each workspace namespace is expandable → shows all outputs for that step
3. Artifact rendering:
   - Code → syntax highlighting with copy button
   - JSON → interactive tree view with collapse/expand
   - Markdown → rendered preview
4. **Export options**:
   - Download all artifacts as a zip
   - Copy individual outputs to clipboard
   - Export full run as markdown report
5. **Re-run from step N**: if step 3 of 4 failed, re-run from step 3 with steps 1-2 context preserved
6. **Compare runs**: side-by-side diff of two runs of the same workflow (useful for iterating on prompts)

### Flow 6: Save & Share
1. "Save" persists the workflow as YAML to `workflows/` directory
2. YAML is the canonical format — node positions and UI metadata stored in a companion `.meta.json` file
3. Workflows can be duplicated, versioned, and organized into folders
4. Future: share workflows with other platform users, import community workflows

### Workflow Monitor Dashboard
- List of all workflow definitions with last-run status
- List of recent runs across all workflows with status (running/completed/failed)
- Click into a run → step-by-step timeline with duration, model used, token count
- Drill into any step → see full prompt assembled, raw LLM response, parsed outputs
- Filter/search runs by workflow, status, date range
- Re-run failed workflows from the point of failure

### Key Frontend Components
| Component | Purpose | Tech |
|-----------|---------|------|
| `WorkflowCanvas` | Node graph editor with drag/drop, zoom, pan | React Flow |
| `SeedNodeEditor` | Configure workflow seed fields and types | Custom form |
| `StepConfigPanel` | Edit step properties (prompt, model, config) | Slide-out panel |
| `ConnectionValidator` | Real-time I/O wiring validation with error display | Engine integration |
| `RunProgress` | Live execution tracker with SSE streaming | EventSource API |
| `ArtifactViewer` | Render step outputs (code, JSON, markdown) | Monaco / react-json-tree |
| `RunTimeline` | Step-by-step execution timeline with metrics | Custom component |
| `WorkflowList` | Dashboard: browse, search, filter workflows and runs | Table/card view |
| `RunComparison` | Side-by-side diff of two workflow runs | Custom diff view |

### API Endpoints Supporting UI
All UI flows are backed by the same REST API used by the CLI:
- `GET /api/workflows` — list definitions (powers WorkflowList)
- `POST /api/workflows/run` — trigger execution (powers Run button)
- `GET /api/workflows/{run_id}/status` — SSE stream for live progress (powers RunProgress)
- `GET /api/workflows/{run_id}/artifacts/{step_id}` — fetch outputs (powers ArtifactViewer)
- `POST /api/workflows/validate` — validate a workflow definition without running it (powers ConnectionValidator)
