---
name: enclave-pm
description: >-
  Drive an Enclave project board (tasks, columns, milestones) from an agent or
  workflow through the proposals-only plan-ops contract. Use when a Claude Code
  session, LangGraph graph, n8n flow, or Enclave workflow step needs to propose
  task changes a human will review — never to mutate a board directly.
---

# Enclave PM — plan-ops contract

The Enclave project board is driven by a **proposals-only** contract. Agents and
workflows never write tasks directly; they submit a **plan** (an array of typed
ops) and every op lands `state:"proposed"`. The operator reviews and accepts or
rejects. This is the honesty guarantee: **AI never mutates the board silently.**

## The two ways in

1. **HTTP** — `POST /api/projects/{project_id}/plan/apply` (master-key when auth
   is on) with body `{"ops": [...], "source": {"run_id": ..., "agent": ...}}`.
2. **Plugin** — the `enclave-pm` plugin exposes `pm_plan_apply(project_id,
   ops_json)`, `pm_list_tasks(project_id)`, `pm_log_run(project_id, run_id,
   label)` as in-process tools for workflow steps and chat agents. Same service,
   same proposals-only semantics, no socket or key needed.

Both funnel through one service function, so there is exactly one code path and
no bypass.

## Lifecycle

```
plan/apply  → ops land as PROPOSED (invisible to the board)
GET  /proposals                          → operator sees pending proposals
POST /proposals/{proposal_id}/accept     → effective events re-appended; board materialises them
POST /proposals/{proposal_id}/reject     → proposal annulled (auditable reject marker)
```

`plan/apply` returns `{proposal_id, ops_accepted, errors, pending_count}`.
Structurally-invalid plans are rejected wholesale (HTTP 400). Structurally-valid
but semantically-impossible ops (e.g. `update_task` on an unknown id) are skipped
and reported in `errors` — the rest of the batch still lands. A project caps at
**50 pending proposals** (HTTP 409); accept or reject before proposing more.

## Op vocabulary

- `add_task` — new task. Required `title`. Optional `column` (default `todo`),
  `description`, `priority`, `due_date`, `start_date`, `estimate`, `milestone`,
  `labels`.
- `update_task` — patch an existing task. Required `id`. Any `add_task` optional
  field (plus `title`).
- `set_status` — move a task. Required `id`, `column`.
- `set_milestone` — set a task's milestone. Required `id`, `milestone`.

Columns: `backlog | todo | doing | review | done`. Priorities: `p0 | p1 | p2 |
p3`. Dates: `YYYY-MM-DD`. `estimate` is a display-only number 0–16.

## Schema (authoritative)

This block is the single source of truth for op **structure**. It is
deep-compared against the router's `PLAN_OPS_SCHEMA` constant by
`tests/test_project_plan_ops.py` — the two are guaranteed identical.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "enclave-pm plan-ops",
  "type": "array",
  "items": {
    "type": "object",
    "required": [
      "op"
    ],
    "additionalProperties": false,
    "properties": {
      "op": {
        "type": "string",
        "enum": [
          "add_task",
          "update_task",
          "set_status",
          "set_milestone"
        ]
      },
      "id": {
        "type": "string"
      },
      "title": {
        "type": "string",
        "maxLength": 240
      },
      "description": {
        "type": "string",
        "maxLength": 4000
      },
      "column": {
        "type": "string",
        "enum": [
          "backlog",
          "todo",
          "doing",
          "review",
          "done"
        ]
      },
      "priority": {
        "type": "string",
        "enum": [
          "p0",
          "p1",
          "p2",
          "p3"
        ]
      },
      "due_date": {
        "type": "string",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "start_date": {
        "type": "string",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "estimate": {
        "type": "number",
        "minimum": 0,
        "maximum": 16
      },
      "milestone": {
        "type": "string",
        "maxLength": 80
      },
      "labels": {
        "type": "array",
        "items": {
          "type": "string"
        },
        "maxItems": 8
      }
    },
    "allOf": [
      {
        "if": {
          "properties": {
            "op": {
              "const": "add_task"
            }
          }
        },
        "then": {
          "required": [
            "op",
            "title"
          ]
        }
      },
      {
        "if": {
          "properties": {
            "op": {
              "const": "update_task"
            }
          }
        },
        "then": {
          "required": [
            "op",
            "id"
          ]
        }
      },
      {
        "if": {
          "properties": {
            "op": {
              "const": "set_status"
            }
          }
        },
        "then": {
          "required": [
            "op",
            "id",
            "column"
          ]
        }
      },
      {
        "if": {
          "properties": {
            "op": {
              "const": "set_milestone"
            }
          }
        },
        "then": {
          "required": [
            "op",
            "id",
            "milestone"
          ]
        }
      }
    ]
  }
}
```

## Example plan

```json
[
  {"op": "add_task", "title": "Draft data model", "column": "todo", "priority": "p1", "milestone": "v1"},
  {"op": "add_task", "title": "Write ingestion tests", "column": "backlog", "estimate": 4},
  {"op": "set_status", "id": "task_abc_123456", "column": "doing"}
]
```
