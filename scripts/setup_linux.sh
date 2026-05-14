#!/usr/bin/env bash
# Enclave — Linux native development setup.
#
# Purpose: bring a fresh Linux dev box (Ubuntu / Debian / Parrot / Fedora /
# Arch) to a state where you can run `python api/main.py` and hit
# http://localhost:8000 against a local Ollama, without docker.
#
# For docker-only first-boot, use ./run.sh instead — it's identical on
# Linux and macOS. This script is for native dev: editing code with
# auto-reload, attaching debuggers, etc.
#
# Usage:
#   ./scripts/setup_linux.sh                 # full setup (system deps + venv + ollama probe + models)
#   ./scripts/setup_linux.sh --venv-only     # skip apt/dnf; just create venv + install Python deps
#   ./scripts/setup_linux.sh --no-models     # skip model pulls (slower first chat, faster setup)
#
# Idempotent: re-running is safe; existing venv / installed packages are kept.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Flags ─────────────────────────────────────────────────────────────
VENV_ONLY=0
NO_MODELS=0
for arg in "$@"; do
    case "$arg" in
        --venv-only) VENV_ONLY=1 ;;
        --no-models) NO_MODELS=1 ;;
        -h|--help)
            sed -n '2,17p' "$0"
            exit 0
            ;;
        *) echo "Unknown flag: $arg" >&2; exit 2 ;;
    esac
done

# ── Output helpers ────────────────────────────────────────────────────
if [ -t 1 ]; then
    BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; CYAN=$'\e[36m'; RESET=$'\e[0m'
else
    BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; CYAN=""; RESET=""
fi
step() { echo "${BOLD}${CYAN}==>${RESET} $*"; }
ok()   { echo "  ${GREEN}✓${RESET} $*"; }
warn() { echo "  ${YELLOW}!${RESET} $*"; }
fail() { echo "  ${RED}✗${RESET} $*" >&2; }

# ── 1. Detect distro + package manager ────────────────────────────────
detect_distro() {
    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        echo "${ID_LIKE:-$ID}"
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)
case "$DISTRO" in
    *debian*|*ubuntu*)        PKG_MANAGER="apt" ;;
    *fedora*|*rhel*|*centos*) PKG_MANAGER="dnf" ;;
    *arch*|*manjaro*)         PKG_MANAGER="pacman" ;;
    *suse*)                   PKG_MANAGER="zypper" ;;
    *)                        PKG_MANAGER="unknown" ;;
esac

step "Detected distro family: ${DISTRO} (pkg: ${PKG_MANAGER})"

# ── 2. System dependencies ────────────────────────────────────────────
# We need: python ≥3.12 with venv + dev headers, curl (for ollama install),
# git (assumed already present — script lives in a repo), and the GTK / WebKit
# stack if you want `python desktop/app.py` to open a native window later.
if [ "$VENV_ONLY" -eq 0 ]; then
    step "Checking system dependencies"
    if [ "$PKG_MANAGER" = "apt" ]; then
        # Use python3.12 if available; fall back to whatever python3 resolves to.
        PY_CANDIDATE="python3.12"
        if ! command -v "$PY_CANDIDATE" >/dev/null 2>&1; then
            PY_CANDIDATE="python3"
        fi
        REQUIRED_PKGS=(
            "$PY_CANDIDATE" "${PY_CANDIDATE}-venv" "${PY_CANDIDATE}-dev"
            curl ca-certificates build-essential
            # For pywebview's GTK backend (optional, only needed for desktop/app.py):
            python3-gi gir1.2-webkit2-4.0
        )
        MISSING=()
        for pkg in "${REQUIRED_PKGS[@]}"; do
            if ! dpkg -s "$pkg" >/dev/null 2>&1; then
                MISSING+=("$pkg")
            fi
        done
        if [ ${#MISSING[@]} -gt 0 ]; then
            warn "Missing apt packages: ${MISSING[*]}"
            echo "    Install with:  sudo apt update && sudo apt install -y ${MISSING[*]}"
            echo "    Then re-run:   ./scripts/setup_linux.sh"
            exit 1
        fi
        ok "All apt packages present"
    elif [ "$PKG_MANAGER" = "dnf" ]; then
        warn "Fedora detected — auto-install not implemented. Ensure these are installed:"
        echo "    python3.12 python3.12-devel curl gcc python3-gobject webkit2gtk3"
    elif [ "$PKG_MANAGER" = "pacman" ]; then
        warn "Arch detected — auto-install not implemented. Ensure these are installed:"
        echo "    python python-pip curl base-devel python-gobject webkit2gtk"
    else
        warn "Unknown distro family ($DISTRO). Make sure python ≥3.12 + venv module + curl are available."
    fi
fi

# ── 3. Pick the Python interpreter ────────────────────────────────────
step "Selecting Python interpreter"
PY_BIN=""
for c in python3.13 python3.12 python3; do
    if command -v "$c" >/dev/null 2>&1; then
        PY_VER=$("$c" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        if [ "$(printf '%s\n3.12\n' "$PY_VER" | sort -V | head -n1)" = "3.12" ]; then
            PY_BIN="$c"
            break
        fi
    fi
done
if [ -z "$PY_BIN" ]; then
    fail "Need Python ≥3.12. Found candidates were too old or absent."
    echo "    On Ubuntu/Debian: sudo apt install python3.12 python3.12-venv python3.12-dev"
    echo "    Or use pyenv:     curl https://pyenv.run | bash && pyenv install 3.12"
    exit 1
fi
ok "Using $PY_BIN ($($PY_BIN --version))"

# ── 4. Create venv if missing ─────────────────────────────────────────
step "Creating venv at ./venv"
if [ -d venv ]; then
    ok "venv already exists (delete ./venv to re-create from scratch)"
else
    "$PY_BIN" -m venv venv
    ok "Created venv with $PY_BIN"
fi

# shellcheck source=/dev/null
source venv/bin/activate
pip install --quiet --upgrade pip

# ── 5. Install Python dependencies ────────────────────────────────────
# Install the RAG profile by default — matches what the Docker image does
# after PR #43. Users who want a slim env can edit this to -core.
step "Installing Python dependencies (requirements-rag.txt)"
pip install --quiet -r setup/requirements-rag.txt
ok "Python deps installed"

# ── 6. Check Ollama ───────────────────────────────────────────────────
if [ "$NO_MODELS" -eq 0 ]; then
    step "Checking Ollama"
    if ! command -v ollama >/dev/null 2>&1; then
        warn "Ollama not found on PATH"
        echo "    Install with:  curl -fsSL https://ollama.com/install.sh | sh"
        echo "    Or run with the docker stack instead:  ./run.sh"
        echo "    (Skipping model pulls; re-run after installing ollama, or use --no-models to bypass.)"
    else
        ok "ollama present: $(ollama --version 2>&1 | head -n1)"

        # Probe daemon — if it isn't running, we can't pull.
        if ! curl -sf -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
            warn "Ollama daemon not responding on :11434"
            echo "    Start it with:  sudo systemctl start ollama   (or just: ollama serve)"
        else
            # Pull starter chat model + embed model if not already present.
            for model in "llama3.2:3b" "nomic-embed-text"; do
                if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$model" \
                    || ollama list 2>/dev/null | awk '{print $1}' | grep -qx "${model}:latest"; then
                    ok "Model already present: $model"
                else
                    step "Pulling $model"
                    if ollama pull "$model"; then
                        ok "Pulled: $model"
                    else
                        warn "Pull failed: $model (continue anyway; re-run later)"
                    fi
                fi
            done
        fi
    fi
fi

# ── 7. Sanity check: import api.main ──────────────────────────────────
step "Verifying api imports cleanly"
if python -c "import api.main" 2>/tmp/enclave-setup-import-err; then
    ok "api.main imports without error"
else
    fail "api.main import failed:"
    sed 's/^/    /' /tmp/enclave-setup-import-err >&2
    echo ""
    echo "    Common causes:"
    echo "      - Missing dep in requirements-rag.txt for your distro"
    echo "      - You're on the wrong Python version (need ≥3.12)"
    exit 1
fi

# ── 8. Status ─────────────────────────────────────────────────────────
echo ""
echo "${BOLD}${GREEN}Enclave dev environment ready.${RESET}"
echo ""
echo "  ${BOLD}Activate venv:${RESET}        source venv/bin/activate"
echo "  ${BOLD}Run native API:${RESET}       python api/main.py"
echo "  ${BOLD}Run with docker:${RESET}      ./run.sh"
echo "  ${BOLD}Open dashboard:${RESET}       ${CYAN}http://localhost:8000${RESET}"
echo ""
echo "  ${DIM}Tip: if you already run Ollama as a systemd service on this host,${RESET}"
echo "  ${DIM}     the docker stack's bundled ollama container will collide on :11434.${RESET}"
echo "  ${DIM}     Either stop the systemd ollama before ./run.sh, or point native dev${RESET}"
echo "  ${DIM}     at the host ollama (default).${RESET}"
echo ""
