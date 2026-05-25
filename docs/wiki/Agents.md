# Agents

**Agents** in Enclave are YAML-defined personas (Gems-style) — a system prompt, a pinned model, pinned context sources, and a callable identity. They live in [`agents/`](https://github.com/hankthebldr/local-ai-platform/tree/master/agents).

## Anatomy of an agent

```yaml
# agents/my-analyst.yaml
name: my-analyst
display_name: My Analyst
description: Reviews a target and produces a structured analysis.
model: qwen2.5:14b-instruct-q5_K_M
system_prompt: |
  You are a careful, methodical analyst. You return JSON with the
  fields described below. You ask one clarifying question if the
  input is ambiguous; otherwise you proceed.
context_sources:
  - kind: document_collection
    name: my-internal-docs
  - kind: file
    path: agents/context/my-analyst-cheatsheet.md
default_inputs:
  format: json
tools:
  - plugin: xdm-toolkit
    tool: validate_xql
  - plugin: xdm-toolkit
    tool: lookup_xdm_path
```

## Where agents show up

| Surface | How |
|---|---|
| **Dashboard → Agents** | Browse, chat, edit, clone via the web UI. State persists in `localStorage`. |
| **Workflow Composer** | Drag an agent onto the canvas — its model, system prompt, and context travel with it. |
| **HTTP API** | `POST /api/agents/{name}/chat` |
| **CLI** | `enclave chat --agent my-analyst` |

## Pinned model + fallback

If the pinned model isn't installed locally, Enclave falls back to **role-based resolution** instead of failing the chat. The dashboard surfaces a `model_fallback` banner so the operator sees which model actually responded. This makes agents portable across machines with different installed model sets.

## Context sources

Three kinds are supported:

| Kind | Use |
|---|---|
| `file` | One static file injected into the system prompt. |
| `document_collection` | Chroma collection. Retrieved per-turn via semantic search. |
| `url` | Fetched once at agent load. Cached. |

## Tools

`tools:` references plugin-provided callables. The runtime invokes them via the `plugin_tool_invoker` hook in the workflow engine, then injects the result into the next prompt. Plugins live under [`plugins/`](https://github.com/hankthebldr/local-ai-platform/tree/master/plugins).

## A2A delegation (1.3.0+)

A workflow step with `kind: a2a` can delegate to a different agent — including a remote one — via the agent-to-agent protocol. Useful for cross-team workflows where one agent owns the entry point and farms out specialized steps.

## Built-in agents

| Agent | Purpose |
|---|---|
| `xsiam-analyst` | Cortex XSIAM analyst — investigations, alert triage, rule reasoning |
| `xql-data-model-engineer` | Authors XQL data model rules from vendor logs |
| `xdm-schema-navigator` | Resolves XDM paths and field mappings |

## Creating a custom agent

1. Drop `agents/<name>.yaml` matching the schema above.
2. Restart the API (the agent registry is loaded at startup).
3. The agent appears in **Dashboard → Agents** and at `/api/agents`.

See [`agents/xsiam-analyst.yaml`](https://github.com/hankthebldr/local-ai-platform/blob/master/agents/xsiam-analyst.yaml) for a fully-worked example with context sources and tools.

## See also

- [Workflows](Workflows) — agents as DAG steps
- [Models](Models) — picking a model to pin
