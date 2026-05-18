# Enclave E2E testing — the canonical methodology

## TL;DR

```bash
# Bring the stack up with the right host env vars.
source scripts/host-preset.sh

docker compose up -d
docker compose exec ollama ollama pull llama3.2:3b  # one-time per host

# Install Playwright once.
pip install -r setup/requirements-playwright.txt
playwright install chromium

# Run the canonical e2e suite (everything Playwright-driven + workflow-static).
pytest -m e2e -v

# Include the long-running workflow EXECUTION tests too.
pytest -m e2e -v  # smoke
pytest -m "e2e and slow" -v  # heavy

# Or use the wrapper that does the health-check + report formatting.
scripts/run-playwright.sh        # smoke
scripts/run-playwright.sh --slow # smoke + heavy
```

## The marker model

Every test under `tests/playwright/` automatically gets the canonical
`e2e` marker (see `conftest.py::pytest_collection_modifyitems`).

| marker | covers | when |
|---|---|---|
| `e2e` | Everything in `tests/playwright/` (browser-driven + workflow API tests) | Always, against a running compose stack. The canonical "did anything regress in the user-facing surface?" gate. |
| `playwright` | Legacy alias for `e2e` | Old commands keep working — prefer `-m e2e`. |
| `slow` | Tests that actually execute workflows or chats against a real model | ~30s+ each; skip with `-m "not slow"`. |
| `integration` | Service-level tests that need Ollama but don't drive a browser | `pytest -m integration`. |
| `rag` | Tests requiring chromadb + sentence-transformers | `pytest -m rag` |

## How a workflow gets tested — the standard battery

Adding a new file at `workflows/<wf_id>.yaml` automatically earns **six
free regression tests** via the parametrized auto-discovery in
`tests/playwright/test_all_workflows.py`. You write zero new test code.

The battery is:

| # | Test | Catches |
|---|---|---|
| 1 | `test_workflow_yaml_parses[<wf_id>]` | YAML parse errors, missing `id`/`name`, malformed schema |
| 2 | `test_workflow_in_api_catalogue[<wf_id>]` | Workflow on disk but not loadable by the engine; renamed; broken loader |
| 3 | `test_workflow_step_shape[<wf_id>]` | Step has no prompt; both v1 + v2 set; **dangling `inputs` refs** (typos pointing to non-existent upstream step outputs) |
| 4 | `test_workflow_step_shape` (same test) | Step declares no outputs; output names don't survive in `seen_outputs` for downstream consumption |
| 5 | `test_workflow_models_present_or_resolver_will_fall_back[<wf_id>]` | Pinned `model:` not installed (info-level by default; set `ENCLAVE_STRICT_WORKFLOW_MODELS=1` to fail) |
| 6 | (optional, @slow) `test_workflow_executes_with_fixture_seed[<wf_id>]` | Real end-to-end: status=completed, every step produced non-None output (regression-guards the output-parser fix) |

### Enabling test #6 for your workflow

Drop a fixture JSON at `tests/fixtures/workflows/<wf_id>.json`:

```json
{
  "_comment": "Describe the realistic input shape this workflow expects.",
  "timeout_seconds": 600,
  "seed": {
    "alert_id": "...",
    "raw_log": "...",
    "...": "...whatever your workflow.context.description says"
  }
}
```

Then:

```bash
pytest -m "e2e and slow" tests/playwright/test_all_workflows.py -k <wf_id> -v
```

The slow test will:
1. POST `/api/workflows/run` with your seed
2. Wait up to `timeout_seconds` (default 600)
3. Assert `status: "completed"` and **every step produced non-None output**
   (this last assertion is the regression guard for the May 2026
   output-parser bug that made multi-stage workflows un-composable)

## Per-surface coverage (browser-driven)

| Surface | File | Covers |
|---|---|---|
| Boot | `test_boot.py` | License auto-fetch, modal stays closed, default tab lands, breadcrumb gone |
| Composer | `test_composer.py` | Workbench panes populate; canvas is full-width; Step Config relocated below dock; system strip shows host values |
| Top-level tabs | `test_top_level_tabs.py` | Promoted Plugins/Skills/MCP tabs exist; Runs moved into System; load handlers fire |
| Admin dropdown | `test_admin_panels.py` | 3-item dropdown shape; System hub sub-nav; no admin-lock anywhere |
| Workflow index | `test_workflow_index.py` | All OOTB workflows listed; clickable into Composer with metadata pre-filled |
| Data-model-rule flow | `test_data_model_rule_smoke.py` | XDM workflow visible, loads with N step nodes, seed input writable |
| **All workflows (auto)** | `test_all_workflows.py` | Per-workflow battery described above |
| Workflow execution | `test_workflow_execution.py` | xsiam-detection-engineering: 6 stages, 3 models, complex context, skill references |
| RAG | `test_rag_roundtrip.py` | Upload → index → semantic search → cleanup. Guards the tensor-bridge fix |
| Chat | `test_chat.py` | Model picker populates; send/receive round-trip against a real model |
| Inventory | `test_inventory.py` | Models tab lists installed models; Discover section present |
| Skills | `test_skill_registration.py` | xdm-toolkit manifest discipline; new skills surface after registration |

## CI integration

```bash
# In CI, run only the fast smoke tier — exclude slow:
pytest -m "e2e and not slow" -v --tracing=retain-on-failure

# Then on nightly / pre-release, include slow:
pytest -m e2e -v --tracing=retain-on-failure
```

Both modes assume the compose stack is up; the fixture `_require_stack`
in `conftest.py` skips the whole suite if `/health` doesn't respond on
`$ENCLAVE_PLAYWRIGHT_BASE_URL` (default `http://localhost:8000`).

## When you add a new workflow

1. Write `workflows/<wf_id>.yaml`.
2. Sync to the container: `docker cp workflows/<wf_id>.yaml local-ai-api:/app/workflows/`.
3. Restart api: `docker compose restart api`.
4. Run `pytest -m e2e tests/playwright/test_all_workflows.py -k <wf_id> -v` — you immediately get tests 1-5.
5. Drop `tests/fixtures/workflows/<wf_id>.json` to opt into the full execution test.

No new test code required for steps 4-5.
