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
