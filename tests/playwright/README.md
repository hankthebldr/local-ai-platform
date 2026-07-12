# Playwright E2E suite

Browser-driven validation of the Enclave SPA against a running compose
stack. Designed as the single source of truth for "does the product still
work" after every change.

## What's covered

| File | Surface | Key contract |
|---|---|---|
| `test_boot.py` | Clean-slate boot | License auto-fetch, modal stays closed, default tab loads |
| `test_composer.py` | Workbench + canvas | 3 OOTB XQL agents, xdm-toolkit plugin, System strip shows host values |
| `test_workflow_index.py` | Workflows | 5 OOTB workflows listed; each openable in Composer |
| `test_data_model_rule_smoke.py` | XDM rule flow | (smoke) workflow loads with 4 step nodes; (slow) end-to-end execution |
| `test_admin_panels.py` | Admin dropdown | Order, System (Memory), License Keys, Plugins, Skills, MCP, Cloud, Exports — no lock state |
| `test_chat.py` | Chat dock | Model picker populates; send/receive against a real model |
| `test_inventory.py` | Models tab | Local inventory matches `/v1/models`; Discover section present |

## Prerequisites

```bash
# 1. Bring up the stack
export ENCLAVE_HOST_RAM_GB=$(($(sysctl -n hw.memsize)/1073741824))   # macOS
export ENCLAVE_HOST_CPU_CORES=$(sysctl -n hw.physicalcpu)
export ENCLAVE_HOST_CPU_BRAND="$(sysctl -n machdep.cpu.brand_string)"
docker compose up -d

# 2. Install test deps (one-time)
pip install -r setup/requirements-playwright.txt
playwright install chromium   # ~150 MB; one-time download

# 3. Pull at least one model so chat / workflow tests have something to run against
docker compose exec ollama ollama pull llama3.2:3b
```

## Running

```bash
# Whole suite, skipping the slow workflow-execution test
pytest tests/playwright -v -m "not slow"

# Just the centerpiece XDM rule smoke (UI-only)
pytest tests/playwright/test_data_model_rule_smoke.py::test_xdm_rule_workflow_loads_into_composer -v

# Full XDM rule execution (actually runs the model — ~2 min)
pytest tests/playwright/test_data_model_rule_smoke.py -m slow -v

# Visible browser (debug)
pytest tests/playwright -v --headed --slowmo=500

# Save HTML report + traces on failure
pytest tests/playwright -v --tracing=retain-on-failure --output=playwright-results
```

## Convenience wrapper

`scripts/run-playwright.sh` checks the stack is up, picks a marker filter,
and writes an HTML report. Add `--slow` to include the long-running
workflow-execution tests.

## Architecture notes

- **No browser server needed.** `pytest-playwright` ships its own browser
  binary via `playwright install chromium`. The tests drive that browser
  directly against `http://localhost:8000` — no Selenium grid, no remote
  Chrome.

- **License auto-load is bypassed in fixtures.** The `signed_in_page`
  fixture pre-seeds `localStorage['enclave.licenseKey']` before navigation
  so every test starts in a stable authed state without paying the
  modal-then-reload cost. `test_boot.py` is the only file that exercises
  the cold-start path.

- **Skip gracefully when prerequisites are missing.** Tests that need a
  loaded model call `pytest.skip()` when `/v1/models` is empty rather than
  failing — so a fresh stack with no models still gets a green smoke
  run for the rest of the surface.

- **Static markers from conftest.** Every test in this directory gets
  `@pytest.mark.playwright` automatically via `pytest_collection_modifyitems`.
  Skip the whole directory with `pytest -m "not playwright"` to keep the
  unit-test runner fast.
