#!/usr/bin/env bash
#
# vllm-serve.sh — launch a vLLM OpenAI-compatible server for the Enclave
# vLLM runner (gpu-runner-abstraction Phase 2).
#
# vLLM is the performance inference backend on Linux + NVIDIA (the BD790i
# Blackwell box). It serves the model out-of-band; the Enclave API talks to
# it over HTTP via VllmRunner. Point Enclave at it with:
#
#     ENCLAVE_VLLM_BASE_URLS=http://localhost:8000
#
# then restart the API. Confirm with:  curl localhost:8001/api/system/runner
#
# vLLM must be installed in its OWN environment (it pulls a heavy CUDA stack
# you do NOT want in the Enclave venv):
#
#     python3 -m venv ~/vllm-env && source ~/vllm-env/bin/activate
#     pip install vllm
#
# Usage:
#     scripts/vllm-serve.sh                       # serve the default NVFP4 model
#     VLLM_MODEL=<hf-repo> scripts/vllm-serve.sh   # serve a specific model
#     VLLM_PORT=8002 scripts/vllm-serve.sh         # different port
#
set -euo pipefail

# ── Tunables (env-overridable) ──────────────────────────────────────────────
# Default to a Blackwell-native NVFP4 model. NVFP4 is the 4-bit FP format the
# RTX PRO 4000 Blackwell accelerates in hardware — the reason to prefer vLLM
# over Ollama's GGUF path on this box.
VLLM_MODEL="${VLLM_MODEL:-nvidia/Qwen3-Coder-30B-A3B-NVFP4}"
VLLM_PORT="${VLLM_PORT:-8000}"
VLLM_HOST="${VLLM_HOST:-0.0.0.0}"
# Fraction of VRAM vLLM may claim. 0.90 leaves headroom for the desktop/X
# server on a workstation GPU; raise toward 0.95 on a headless box.
VLLM_GPU_UTIL="${VLLM_GPU_UTIL:-0.90}"
VLLM_MAX_LEN="${VLLM_MAX_LEN:-8192}"
VLLM_MAX_SEQS="${VLLM_MAX_SEQS:-8}"
# modelopt = NVIDIA's NVFP4/FP8 quant path. Override to "" for an unquantized
# or GGUF model, or "awq"/"fp8" as appropriate.
VLLM_QUANT="${VLLM_QUANT:-modelopt}"
VLLM_KV_DTYPE="${VLLM_KV_DTYPE:-fp8}"

# ── Preflight ───────────────────────────────────────────────────────────────
if ! command -v vllm >/dev/null 2>&1; then
  echo "ERROR: 'vllm' not found on PATH." >&2
  echo "Install it in a dedicated env (NOT the Enclave venv):" >&2
  echo "  python3 -m venv ~/vllm-env && source ~/vllm-env/bin/activate && pip install vllm" >&2
  exit 1
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)"
  echo "[vllm-serve] GPU free VRAM: ${free_mib} MiB"
  if [ "${free_mib:-0}" -lt 8000 ]; then
    echo "[vllm-serve] WARNING: <8 GB free VRAM. Another process (Ollama? a stale" >&2
    echo "            vLLM?) may be holding the GPU. Check: nvidia-smi" >&2
  fi
fi

# ── Launch ──────────────────────────────────────────────────────────────────
echo "[vllm-serve] model=${VLLM_MODEL} port=${VLLM_PORT} gpu_util=${VLLM_GPU_UTIL} quant=${VLLM_QUANT:-none}"

args=(
  serve "${VLLM_MODEL}"
  --host "${VLLM_HOST}"
  --port "${VLLM_PORT}"
  --gpu-memory-utilization "${VLLM_GPU_UTIL}"
  --max-model-len "${VLLM_MAX_LEN}"
  --max-num-seqs "${VLLM_MAX_SEQS}"
  --trust-remote-code
)
[ -n "${VLLM_QUANT}" ] && args+=(--quantization "${VLLM_QUANT}")
[ -n "${VLLM_KV_DTYPE}" ] && args+=(--kv-cache-dtype "${VLLM_KV_DTYPE}")

exec vllm "${args[@]}"
