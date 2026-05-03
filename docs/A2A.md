# A2A Protocol Support

Enclave implements [Google's Agent-to-Agent (A2A) protocol](https://google.github.io/A2A/)
so external agents — from any vendor or framework that speaks A2A — can call
local Enclave workflows and chat as first-class skills.

## Endpoints

| Path                          | Purpose                                      | Auth        |
|-------------------------------|----------------------------------------------|-------------|
| `GET /.well-known/agent.json` | Agent Card (discovery)                       | Public      |
| `POST /a2a`                   | JSON-RPC 2.0 dispatch + SSE streaming        | `a2a` scope |

## Skills advertised

The Agent Card lists two kinds of skills:

- **`chat`** — built-in single-turn chat against the platform's default model
  (`DEFAULT_MODEL` env var, defaults to `mistral`).
- **`workflow:<id>`** — every YAML workflow under `workflows/` is advertised
  automatically (e.g. `workflow:data-model-rules`).

The active skill is selected via `params.metadata.skillId` or
`message.metadata.skillId`. Defaults to `chat`.

## Methods supported in this build

- `tasks/send` — synchronous: returns the final `Task`.
- `tasks/sendSubscribe` — Server-Sent Events stream of
  `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` envelopes.
- `tasks/get` — fetch a persisted task by id.
- `tasks/cancel` — cancel an in-flight task. Cancel after terminal returns
  `-32002 Task Not Cancelable`.

## Methods deferred

`tasks/pushNotification/{set,get}` and `tasks/resubscribe` return
`-32004 Unsupported Operation` until the follow-up release adds webhook
delivery and SSE resume.

Multi-turn `input-required` state and non-text Parts (file/data uploads as
inputs) are likewise scheduled for a follow-up.

## Mapping to Enclave primitives

| A2A concept       | Enclave concept                                              |
|-------------------|--------------------------------------------------------------|
| `Task`            | `WorkflowRun` (or a chat-only run for the `chat` skill)      |
| `Task.id`         | A2A task id; workflow runs also keep their own `run_id`      |
| `Task.artifacts`  | One per workflow step's `workspace.<step_id>` payload        |
| `Message` text    | Workflow `seed.input` if no `DataPart` is supplied           |
| `DataPart.data`   | Merged into the workflow `seed`                              |

## Persistence

A2A tasks are mirrored to `data/a2a/<task_id>/task.json`. The directory is
gitignored; this is local state, not a shared database.

## Example: discover and call

```bash
# 1. Discover
curl http://localhost:8000/.well-known/agent.json | jq '.skills[].id'

# 2. Send a chat task
curl -X POST http://localhost:8000/a2a \
  -H "content-type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tasks/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "summarize the A2A spec in two sentences"}],
        "metadata": {"skillId": "chat"}
      }
    }
  }'

# 3. Run a workflow
curl -X POST http://localhost:8000/a2a \
  -H "content-type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tasks/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"type": "data", "data": {"source_files": ["models/user.py"], "constraints": "PostgreSQL"}}],
        "metadata": {"skillId": "workflow:data-model-rules"}
      }
    }
  }'

# 4. Stream a long-running task
curl -N -X POST http://localhost:8000/a2a \
  -H "content-type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tasks/sendSubscribe","params":{"message":{"role":"user","parts":[{"type":"text","text":"hi"}]}}}'
```

## Authentication

When `ENABLE_API_AUTH=true`, the Agent Card advertises `bearer` auth and the
`/a2a` endpoint requires the `a2a` scope on the API key. The Agent Card itself
remains public — discovery without auth is part of the spec.

## Roadmap

1. Push notifications (`tasks/pushNotification/{set,get}`) over webhooks
2. SSE resume (`tasks/resubscribe`) with task event log replay
3. Multi-turn `input-required` state — pause workflows for user input
4. Bidirectional A2A — Enclave workflow steps that call out to remote A2A agents
5. A2A + MCP composition — advertise plugin tools as MCP resources alongside skills
