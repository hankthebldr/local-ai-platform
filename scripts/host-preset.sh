#!/usr/bin/env bash
# Detect the host fleet box and emit the right ENCLAVE_HOST_* + GPU env vars.
#
# Usage:
#   source scripts/host-preset.sh             # auto-detect
#   source scripts/host-preset.sh mac-m4      # force a preset
#   source scripts/host-preset.sh bd790i      # force a preset
#   source scripts/host-preset.sh ms01        # force a preset
#
# After sourcing, run:
#   docker compose up -d        # uses COMPOSE_FILE override if GPU detected
# (the GPU override is only useful when ENCLAVE_HOST_GPU is set).

set -u

_detect() {
  case "$(uname -s)" in
    Darwin)
      local brand
      brand="$(sysctl -n machdep.cpu.brand_string 2>/dev/null)"
      case "$brand" in
        *M4\ Pro*|*M4\ Max*|*M3*|*M2*) echo "mac-m4"; return ;;
      esac
      ;;
    Linux)
      local cpu
      cpu="$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo 2>/dev/null)"
      case "$cpu" in
        *7945HX*) echo "bd790i"; return ;;
        *13900H*) echo "ms01"; return ;;
      esac
      ;;
  esac
  echo "generic"
}

_preset="${1:-$(_detect)}"

case "$_preset" in
  mac-m4)
    export ENCLAVE_HOST_PLATFORM="darwin"
    export ENCLAVE_HOST_CPU_BRAND="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'Apple M4 Pro')"
    export ENCLAVE_HOST_CPU_CORES="$(sysctl -n hw.physicalcpu 2>/dev/null || echo 14)"
    export ENCLAVE_HOST_RAM_GB="$(( $(sysctl -n hw.memsize 2>/dev/null || echo 51539607552) / 1073741824 ))"
    export ENCLAVE_HOST_GPU=""        # Apple Silicon: Metal via ollama-native; no NVIDIA bridge.
    ;;

  bd790i)
    # ASRock BD790i — Ryzen 9 7945HX (16C/32T), 96 GB, PNY RTX 4000 Blackwell.
    export ENCLAVE_HOST_PLATFORM="linux"
    export ENCLAVE_HOST_CPU_BRAND="${ENCLAVE_HOST_CPU_BRAND:-AMD Ryzen 9 7945HX}"
    export ENCLAVE_HOST_CPU_CORES="${ENCLAVE_HOST_CPU_CORES:-32}"
    export ENCLAVE_HOST_RAM_GB="${ENCLAVE_HOST_RAM_GB:-96}"
    export ENCLAVE_HOST_GPU="NVIDIA RTX 4000 Blackwell"
    # Ollama tuning knobs for a single 24GB-class card; tweak as needed.
    export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-4}"
    export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"
    export OLLAMA_GPU_LAYERS="${OLLAMA_GPU_LAYERS:--1}"
    export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"
    # Compose-file chain that includes the GPU override.
    export COMPOSE_FILE="docker-compose.yml:docker-compose.gpu.yml"
    ;;

  ms01)
    # Minisforum MS-01 — i9-13900H (6P+8E/20T), 64 GB, no discrete GPU.
    export ENCLAVE_HOST_PLATFORM="linux"
    export ENCLAVE_HOST_CPU_BRAND="${ENCLAVE_HOST_CPU_BRAND:-Intel i9-13900H}"
    export ENCLAVE_HOST_CPU_CORES="${ENCLAVE_HOST_CPU_CORES:-20}"
    export ENCLAVE_HOST_RAM_GB="${ENCLAVE_HOST_RAM_GB:-64}"
    export ENCLAVE_HOST_GPU=""
    ;;

  generic)
    if [ "$(uname -s)" = "Darwin" ]; then
      export ENCLAVE_HOST_PLATFORM="darwin"
      export ENCLAVE_HOST_CPU_BRAND="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'unknown')"
      export ENCLAVE_HOST_CPU_CORES="$(sysctl -n hw.physicalcpu 2>/dev/null || echo 0)"
      export ENCLAVE_HOST_RAM_GB="$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 ))"
    else
      export ENCLAVE_HOST_PLATFORM="linux"
      export ENCLAVE_HOST_CPU_BRAND="$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo 2>/dev/null || echo 'unknown')"
      export ENCLAVE_HOST_CPU_CORES="$(nproc 2>/dev/null || echo 0)"
      export ENCLAVE_HOST_RAM_GB="$(awk '/MemTotal/{printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0)"
    fi
    # Auto-enable GPU override if nvidia-smi is on PATH and responds.
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
      export ENCLAVE_HOST_GPU="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
      export COMPOSE_FILE="docker-compose.yml:docker-compose.gpu.yml"
    fi
    ;;

  *)
    echo "Unknown preset: $_preset. Valid: mac-m4 | bd790i | ms01 | generic" >&2
    return 1 2>/dev/null || exit 1
    ;;
esac

echo "─── Enclave host preset: ${_preset} ───"
echo "  ENCLAVE_HOST_PLATFORM   = ${ENCLAVE_HOST_PLATFORM}"
echo "  ENCLAVE_HOST_CPU_BRAND  = ${ENCLAVE_HOST_CPU_BRAND}"
echo "  ENCLAVE_HOST_CPU_CORES  = ${ENCLAVE_HOST_CPU_CORES}"
echo "  ENCLAVE_HOST_RAM_GB     = ${ENCLAVE_HOST_RAM_GB}"
echo "  ENCLAVE_HOST_GPU        = ${ENCLAVE_HOST_GPU:-(none)}"
if [ -n "${COMPOSE_FILE:-}" ]; then
  echo "  COMPOSE_FILE            = ${COMPOSE_FILE}"
fi
