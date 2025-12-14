#!/usr/bin/env bash
#
# Local AI Platform - Automated Installation Script
# Non-interactive setup for CI/automated deployment
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
echo_success() { echo -e "${GREEN}[✓]${NC} $1"; }
echo_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
echo_error() { echo -e "${RED}[✗]${NC} $1"; }

clear
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     LOCAL AI PLATFORM - Automated Setup                  ║
║                                                           ║
║     Self-hosted LLM Infrastructure                        ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo_info "Installation directory: $PROJECT_ROOT"
echo ""

# System check
echo_info "Checking system requirements..."
CPU_CORES=$(nproc)
TOTAL_RAM=$(free -g | awk '/^Mem:/{print $2}')
AVAILABLE_SPACE=$(df -BG "$PROJECT_ROOT" | awk 'NR==2 {print $4}' | sed 's/G//')

echo "  CPU Cores: $CPU_CORES"
echo "  RAM: ${TOTAL_RAM}GB"
echo "  Available Disk Space: ${AVAILABLE_SPACE}GB"

if [ "$CPU_CORES" -lt 4 ]; then
    echo_warning "  Recommended: 8+ cores for optimal performance"
fi
if [ "$TOTAL_RAM" -lt 16 ]; then
    echo_warning "  Recommended: 16GB+ for running larger models"
fi
if [ "$AVAILABLE_SPACE" -lt 100 ]; then
    echo_warning "  Recommended: 100GB+ for models and data"
fi

echo ""
echo_info "Starting automated installation..."
echo ""

# Create Python virtual environment
echo_info "Setting up Python virtual environment..."
if [ ! -d "$PROJECT_ROOT/venv" ]; then
    python3 -m venv "$PROJECT_ROOT/venv"
    echo_success "Virtual environment created"
else
    echo_info "Virtual environment already exists"
fi

# Activate virtual environment
source "$PROJECT_ROOT/venv/bin/activate"

# Upgrade pip
echo_info "Upgrading pip..."
pip install --upgrade pip setuptools wheel -q

# Install Python dependencies
echo_info "Installing Python dependencies (this may take a few minutes)..."
pip install -r "$PROJECT_ROOT/setup/requirements.txt" -q
echo_success "Python dependencies installed"

# Check for Ollama
echo_info "Checking Ollama installation..."
if command -v ollama &> /dev/null; then
    echo_success "Ollama already installed: $(ollama --version)"
else
    echo_warning "Ollama not found. Installing..."
    curl -fsSL https://ollama.ai/install.sh | sh
    echo_success "Ollama installed"
fi

# Check if Ollama is running
if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo_success "Ollama service is running"
else
    echo_warning "Ollama is not running. Starting it..."
    nohup ollama serve > /dev/null 2>&1 &
    sleep 3
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo_success "Ollama service started"
    else
        echo_error "Failed to start Ollama. Please start it manually: ollama serve"
    fi
fi

# Create necessary directories
echo_info "Creating project directories..."
mkdir -p "$PROJECT_ROOT/data"/{models,vectors,cache,logs}
mkdir -p "$PROJECT_ROOT/finetuning"/{datasets,configs,outputs}
echo_success "Directories created"

# Copy environment file
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo_info "Creating .env file..."
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo_success ".env file created"
else
    echo_info ".env file already exists"
fi

# Make scripts executable
chmod +x "$PROJECT_ROOT"/setup/*.sh 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/scripts/*.sh 2>/dev/null || true

echo ""
echo_success "╔════════════════════════════════════════════════╗"
echo_success "║                                                ║"
echo_success "║       Installation Complete!                   ║"
echo_success "║                                                ║"
echo_success "╚════════════════════════════════════════════════╝"
echo ""

echo_info "Quick Start:"
echo ""
echo "  1. Activate virtual environment:"
echo "     source venv/bin/activate"
echo ""
echo "  2. Start the API server:"
echo "     python -m api.main"
echo ""
echo "  3. Test the CLI:"
echo "     python cli/chat.py --model mistral:7b"
echo ""
echo "  4. Download models:"
echo "     python models/download.py --list"
echo "     ollama pull mistral"
echo ""

echo_info "For full setup options, run: ./setup/install.sh"
echo ""
echo_success "Happy hacking! 🚀"
