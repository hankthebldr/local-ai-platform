# XQL / XDM Out-of-the-Box Bundle

End-to-end OOTB content for generating Palo Alto Networks **Cortex XSIAM**
data model rules in **XQL** (XDR Query Language) — entirely local, no
tenant connection required.

This bundle exercises the full Enclave product surface:

- **Agents** that author XQL rules with discipline (no hallucinated XDM paths)
- **Plugin** with skills + tools that auto-inject XQL writing rules
- **Workflows** that wrap single-log and bulk-vendor onboarding pipelines
- **MCP example** showing how to bridge to a live Cortex tenant

## What's in the bundle

| Artifact | Location | Purpose |
|----------|----------|---------|
| Knowledge reference | `docs/seed/xql/xql-xdm-knowledge.md` | Full ~20K-token XQL/XDM reference (sections 1-11): language reference, schema, patterns, pitfalls, parser conformance |
| Ollama Modelfile | `docs/seed/xql/Modelfile.gocortex-xql-offline` | Build a tuned `qwen3.5:27b` variant that bakes in the system prompt; recommended for offline use |
| Agent: XQL Data Model Rule Engineer | `agents/xql-data-model-engineer.yaml` | Authors full MODEL blocks from raw log samples. References the knowledge as a context source. |
| Agent: XDM Schema Navigator | `agents/xdm-schema-navigator.yaml` | Fast lookup helper: vendor field name → XDM path candidates. Small-model friendly. |
| Plugin: XDM Toolkit | `plugins/xdm-toolkit/` | Two skills (`xdm-rule-writer`, `xql-validator`) that auto-inject when the user message contains XQL keywords. Two tools: `validate_xql` and `lookup_xdm_path`. |
| Workflow: XDM Rule from Log | `workflows/xdm-rule-from-log.yaml` | 4-step single-sample pipeline with a built-in validator gate |
| Workflow: Bulk Vendor Onboarding | `workflows/xdm-bulk-onboarding.yaml` | 6-step multi-sample pipeline producing one rule per event-type cluster + a markdown onboarding brief |
| MCP example | `docs/examples/mcp-cortex-tenant.example.json` | Sample registration JSON for bridging Enclave to a live Cortex tenant |

## Quickstart (local hardware)

### Option A — use a stock chat model

The agents work with any chat-capable model you've pulled. Defaults are
permissive: the model resolver falls back from `qwen3.5:27b` →
"largest reasoning model loaded" → "largest model loaded" automatically.

```bash
# pull a starter model
ollama pull qwen2.5:14b

# in the dashboard:
# 1. Open the Composer tab
# 2. Drop the "XQL Data Model Rule Engineer" agent from the Agents palette
# 3. In the engaged step's chat, paste a raw log and ask for a rule
```

### Option B — build the tuned offline model (recommended)

If you have ~17GB RAM + can afford a `qwen3.5:27b` model on disk:

```bash
ollama create gocortex-xql-offline -f docs/seed/xql/Modelfile.gocortex-xql-offline
ollama run gocortex-xql-offline   # standalone, or wire into Enclave by name
```

The Modelfile bakes the entire knowledge into the system prompt, so the
agent runs with maximum context budget free for user prompts (logs,
field samples, conversation).

### Option C — full workflow run

To exercise the multi-step pipeline:

```bash
curl -X POST http://localhost:8000/api/workflows/run \
  -H 'Content-Type: application/json' \
  -d '{
    "workflow_id": "xdm-rule-from-log",
    "seed": {
      "vendor": "Cisco",
      "product": "ASA",
      "raw_log": "<paste a raw ASA log line here>"
    }
  }'
```

The 4 steps run sequentially and the final output is a validated
`MODEL` block + the pre-flight verdict.

## Why this is the next hands-on test

This bundle deliberately covers every shipped surface:

- **Agents** with both a heavy reasoning persona AND a fast small-model
  lookup helper
- **Plugin** with two skills (markdown-injected on trigger) AND two
  tools (callable from any step's agentic loop)
- **Workflows** with quality gates, before-step hooks invoking plugin
  tools, output schemas, and per-step roles
- **MCP example** demonstrating the registration shape for external bridges

If anything in the create/compose/run flow breaks, this bundle will
surface it.

## Notes on file size

The knowledge file is **~150KB**. It's vendored in the repo because:

1. It IS the OOTB content — pulling it from a CDN would defeat the
   "no telemetry, no cloud, all data local" promise.
2. It loads once at agent-start (via `ContextSource type=file`) and
   gets cached server-side after the first request.
3. The Ollama Modelfile (`option B`) bakes it into the model directly,
   so subsequent runs don't reload it from disk.

If you fork the knowledge for your own domain (vendor-specific addenda,
internal XDM_CONST overrides, etc.), keep the section structure intact
so the agent prompts continue to reference `§1`, `§2`, etc. correctly.
