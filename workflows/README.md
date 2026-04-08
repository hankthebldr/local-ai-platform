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
