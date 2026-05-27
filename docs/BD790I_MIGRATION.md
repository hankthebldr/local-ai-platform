# Migrating Enclave to the BD790i

Target box: ASRock BD790i — Ryzen 9 7945HX (16C/32T) · 96 GB DDR5 ·
PNY RTX 4000 Blackwell.

This is the runbook for moving the test stack off the M4 Pro and onto
the BD790i so we can exercise the workflow engine against larger models
(34B+ Q4_K_M) with real GPU acceleration. Targets ~10× the throughput of
the M4 Pro on equivalent workloads.

## Prereqs on the BD790i

```bash
# 1. NVIDIA driver — confirm working
nvidia-smi   # must list the RTX 4000 Blackwell

# 2. NVIDIA Container Toolkit (Debian/Ubuntu paths)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit

# 3. Wire the nvidia runtime into Docker
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# 4. Sanity check: container can see the GPU
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

## Standing up the stack

```bash
# 1. Clone the repo and check out the same branch
git clone <repo> ~/enclave && cd ~/enclave
git checkout master   # or the release branch you're testing

# 2. Source the host preset (auto-detects BD790i + enables GPU override)
source scripts/host-preset.sh
# Expected output:
#   ENCLAVE_HOST_PLATFORM   = linux
#   ENCLAVE_HOST_CPU_BRAND  = AMD Ryzen 9 7945HX
#   ENCLAVE_HOST_CPU_CORES  = 32
#   ENCLAVE_HOST_RAM_GB     = 96
#   ENCLAVE_HOST_GPU        = NVIDIA RTX 4000 Blackwell
#   COMPOSE_FILE            = docker-compose.yml:docker-compose.gpu.yml

# 3. Up the stack — COMPOSE_FILE merges the GPU override automatically.
docker compose up -d

# 4. Verify the ollama container actually has GPU access
docker compose exec ollama nvidia-smi
docker compose logs ollama | grep -iE 'cuda|gpu'
```

## Pull larger models the BD790i can run

The RTX 4000 Blackwell ships with 24 GB GDDR7. With Q4_K_M quant a 34B
model lands at ~20 GB VRAM and inference flies. Some sensible pulls:

```bash
docker compose exec ollama ollama pull yi-coder:34b           # heavy reasoning
docker compose exec ollama ollama pull qwen2.5-coder:32b      # XQL drafting
docker compose exec ollama ollama pull nous-hermes2-mixtral   # uncensored, 8x7B MoE
docker compose exec ollama ollama pull dolphin-mixtral:8x7b   # general purpose
docker compose exec ollama ollama pull llama3.3:70b           # if you want to peg the card
```

## Validate the move

```bash
# Stack health
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/api/inventory/system \
  -H "Authorization: Bearer $(cat data/config/first-run-key.txt)" \
  | jq '.cpu, .gpu, .memory'
# Expect: cpu.count=32, memory.total_gb=96, gpu.model="NVIDIA RTX 4000 Blackwell"

# Browse to http://<BD790i-ip>:8000  (or use Tailscale hostname)

# Full E2E
pip install -r setup/requirements-playwright.txt
playwright install chromium
pytest tests/playwright -v -m "not slow"
pytest tests/playwright -v -m slow      # full workflow execution
```

## Validate the multi-agent step kinds (parallel / loop / a2a / orchestrator / consolidate / ralph)

The whole reason to move to the BD790i is to exercise the new workflow step
kinds against real models. The unit + integration suites already cover the
engine logic with a stubbed Ollama; this section is about a *live* shakedown.

### 1. Run the new-kind suite first (no models, no daemon needed)

These files cover the new step kinds with a stubbed Ollama + httpx mock, so
they pass with only the dev deps installed — before you stand up the stack:

```bash
source venv/bin/activate           # or your env of choice
pip install -r setup/requirements-dev.txt   # pulls pytest-asyncio etc.

pytest -q \
  tests/test_workflow_models.py \
  tests/test_memory_store.py \
  tests/integration/test_composite_steps.py \
  tests/integration/test_a2a_step.py \
  tests/integration/test_orchestrator_step.py \
  tests/integration/test_consolidate_step.py \
  tests/integration/test_ralph_step.py
# Expect ~120 passed.
```

Then the broader engine suite once the stack is up (some tests need a live
Ollama on :11434; RAG tests additionally need `setup/requirements-rag.txt`):

```bash
pip install -r setup/requirements-rag.txt        # langchain / chromadb / etc.
pytest tests/ --ignore=tests/e2e -m "not slow" -q
```

### 2. Env knobs that matter on the BD790i (NVIDIA-single)

Unlike the M4 (CPU, where `MAX_CONCURRENT_LLM=1` forces serialization), the
RTX 4000 can actually run concurrent decode. Set these before `docker compose
up` (or export in the host env / `.env`) to exercise the parallel modes for
real:

```bash
# Daemon-side parallel slots. Each slot holds its own KV cache, so this
# trades VRAM for concurrency. On a 24 GB card running a 34B (~20 GB), keep
# this modest — 2 is realistic, higher risks OOM at large context.
OLLAMA_NUM_PARALLEL=2

# Let the ENGINE dispatch branches concurrently. Default is 1 (serialize at
# the _LLM_SEMAPHORE — correct for CPU boxes). Bump to match NUM_PARALLEL so
# kind=parallel mode=single_model_concurrent is genuinely concurrent here.
MAX_CONCURRENT_LLM=2

# Memory stores for kind=consolidate + kind=ralph. Defaults to ./data; point
# it at a persistent path you want to inspect/commit. The ralph playbook is
# the durable self-learning state.
MEMORY_DATA_DIR=/srv/enclave/memory

# keep_alive: the NVIDIA arch default is "0" (evict between steps to free
# VRAM). That's right for VRAM-tight single-GPU, BUT it kills the prompt-cache
# reuse that single_model_pseudo_parallel relies on. To test that mode's
# cache benefit, keep the model warm for the duration of the parallel block:
OLLAMA_KEEP_ALIVE=10m
```

### 3. Live smoke-test each kind

Each example workflow ships in `workflows/`. Run them against the live stack
(role-based steps resolve to whatever you pulled above):

```bash
KEY=$(cat data/config/first-run-key.txt)
run() { curl -sS -X POST http://localhost:8000/api/workflows/run \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d "$1" | jq '.run_id'; }

# parallel + loop — fan-out inspection then refine-until-good
run '{"workflow_id":"example-parallel-loop","seed":{"document":"<paste a doc>"}}'

# consolidate — writes lessons to the incident_response playbook, then check:
run '{"workflow_id":"example-consolidate","seed":{"report":"<paste an incident report>"}}'
cat "$MEMORY_DATA_DIR/playbooks/incident_response.md"   # should hold distilled rules

# orchestrator — lead spawns workers dynamically (needs a model that follows
# the JSON-directive protocol reliably; qwen2.5/llama3.3 do well)
run '{"workflow_id":"example-orchestrator","seed":{"alert_text":"<alert>","time_window":"1h","raw_text":"<logs>","asset_identifier":"host-01"}}'

# ralph — the autonomous loop. Start with a TIGHT budget for the first live
# run (max_iterations in the YAML), and keep the HALT brake handy:
run '{"workflow_id":"example-ralph","seed":{"charter":"<a small, verifiable goal>"}}'
touch .enclave/HALT      # graceful stop at the next iteration boundary
tail -f .enclave/journal.jsonl   # watch iterations land

# a2a — only if you have a second A2A agent to call (or point it at this same
# box: every loaded workflow is advertised as a skill). Inspect the card:
curl -sS http://localhost:8000/a2a/.well-known/agent.json | jq '.skills[].id'
```

### 4. What to watch in the Runs view

- **parallel**: branches should overlap in wall-clock on the GPU (they won't
  on the M4). The Runs view mini-DAG shows the fan-out rank.
- **single_model_concurrent**: if you set `MAX_CONCURRENT_LLM=1` you'll see a
  warning in the logs that branches serialized — bump it to see real overlap.
- **ralph**: the journal at the YAML's `ralph.journal_path` (the example uses
  `.enclave/journal.jsonl`) records each iteration; kill the process mid-run
  and re-trigger to confirm it resumes past completed iterations rather than
  restarting from zero.
- **consolidate dedup**: run `example-consolidate` twice on the same report —
  the second run should NOT duplicate rules already in the playbook.

## Expected gains

| Workload | Mac M4 Pro (Q4 CPU) | BD790i + RTX 4000 (Q4 GPU) |
|---|---|---|
| 3B model first-token latency | ~1-2 s | ~50-100 ms |
| 3B model tokens/sec | 40-50 | 200-300 |
| 8x7B MoE tokens/sec | 8-12 | 60-90 |
| 6-stage workflow wall-clock | 65 s (after parser fix) | est. 10-20 s |

## Caveats

- The `ENABLE_API_AUTH` first-run key is per-host. The BD790i will
  generate its own key on first boot; pull it from
  `data/config/first-run-key.txt` after the stack is up.
- `RATE_LIMIT_RPM` default is 600 — fine for the Playwright suite + a
  single operator. Bump higher if multiple browsers are testing in
  parallel.
- `OLLAMA_GPU_LAYERS=-1` offloads ALL layers to GPU. If you ever pull a
  model larger than 24 GB at Q4 (e.g. 70B Q5_K_M), drop this to a
  specific layer count or accept CPU-fallback for the overflow.
- The data volume names (`local-ai-*-data`) are shared — if you ever
  rsync the volumes from the Mac, the keystore + first-run key come
  with them.
