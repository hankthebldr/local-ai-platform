#!/usr/bin/env bash
#
# Local AI Platform - Master Installation Script
# Installs all components for local LLM deployment
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

echo_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
echo_success() { echo -e "${GREEN}[✓]${NC} $1"; }
echo_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
echo_error() { echo -e "${RED}[✗]${NC} $1"; }

clear
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     LOCAL AI PLATFORM - Installation Script              ║
║                                                           ║
║     Self-hosted LLM Infrastructure                        ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo_error "Please run this script as a normal user (it will use sudo when needed)"
    exit 1
fi

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo_info "Installation directory: $PROJECT_ROOT"
echo ""

# System check
echo_info "Checking system requirements..."
echo ""

# Check CPU
CPU_CORES=$(nproc)
echo "  CPU Cores: $CPU_CORES"
if [ "$CPU_CORES" -lt 4 ]; then
    echo_warning "  Recommended: 8+ cores for optimal performance"
fi

# Check RAM
TOTAL_RAM=$(free -g | awk '/^Mem:/{print $2}')
echo "  RAM: ${TOTAL_RAM}GB"
if [ "$TOTAL_RAM" -lt 16 ]; then
    echo_warning "  Recommended: 16GB+ for running larger models"
fi

# Check disk space
AVAILABLE_SPACE=$(df -BG "$PROJECT_ROOT" | awk 'NR==2 {print $4}' | sed 's/G//')
echo "  Available Disk Space: ${AVAILABLE_SPACE}GB"
if [ "$AVAILABLE_SPACE" -lt 100 ]; then
    echo_warning "  Recommended: 100GB+ for models and data"
fi

echo ""
read -p "Continue with installation? [Y/n] " response
if [[ "$response" =~ ^[Nn]$ ]]; then
    echo_info "Installation cancelled"
    exit 0
fi

echo ""
echo_info "Starting installation..."
echo ""

# Update package lists
echo_info "Updating system packages..."
sudo apt update -qq

# Install system dependencies
echo_info "Installing system dependencies..."
sudo apt install -y \
    build-essential \
    cmake \
    git \
    curl \
    wget \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    pkg-config \
    libopenblas-dev \
    liblapack-dev \
    libomp-dev \
    jq \
    tmux \
    htop \
    2>/dev/null

echo_success "System dependencies installed"

# Create Python virtual environment
echo_info "Creating Python virtual environment..."
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
pip install --upgrade pip setuptools wheel --quiet

# Install Python dependencies
echo_info "Installing Python dependencies..."
pip install -r "$PROJECT_ROOT/setup/requirements.txt" --quiet
echo_success "Python dependencies installed"

# Install Ollama
echo_info "Installing Ollama..."
if command -v ollama &> /dev/null; then
    echo_info "Ollama already installed"
    ollama --version
else
    curl -fsSL https://ollama.ai/install.sh | sh
    echo_success "Ollama installed"
fi

# Setup Ollama service
echo_info "Configuring Ollama service..."
mkdir -p ~/.ollama

# Create Ollama systemd user service (if systemd available)
if command -v systemctl &> /dev/null; then
    mkdir -p ~/.config/systemd/user

    cat > ~/.config/systemd/user/ollama.service << 'OLLAMA_SERVICE'
[Unit]
Description=Ollama Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ollama serve
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_NUM_PARALLEL=2"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
OLLAMA_SERVICE

    systemctl --user daemon-reload
    systemctl --user enable ollama.service
    systemctl --user start ollama.service
    echo_success "Ollama service configured and started"
else
    echo_warning "Systemd not available, you'll need to start Ollama manually"
fi

# Install Open WebUI
echo_info "Installing Open WebUI..."
if command -v docker &> /dev/null; then
    echo_info "Docker detected, will use Docker for Open WebUI"
    # Will be set up in separate script
else
    echo_info "Installing Open WebUI via pip..."
    pip install open-webui --quiet
fi
echo_success "Open WebUI installed"

# Create necessary directories
echo_info "Creating project directories..."
mkdir -p "$PROJECT_ROOT/data"/{models,vectors,cache,logs}
mkdir -p "$PROJECT_ROOT/finetuning"/{datasets,configs,outputs}

# Copy environment file
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo_info "Creating .env file..."
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo_success ".env file created (please review and update)"
else
    echo_info ".env file already exists"
fi

# Make scripts executable
echo_info "Setting script permissions..."
chmod +x "$PROJECT_ROOT"/setup/*.sh 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/scripts/*.sh 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/webui/*.sh 2>/dev/null || true

echo ""
echo_success "╔════════════════════════════════════════════════╗"
echo_success "║                                                ║"
echo_success "║       Installation Complete!                   ║"
echo_success "║                                                ║"
echo_success "╚════════════════════════════════════════════════╝"
echo ""

echo_info "Next steps:"
echo ""
echo "  1. Review and update configuration:"
echo "     ${CYAN}nano .env${NC}"
echo ""
echo "  2. Download your first model:"
echo "     ${CYAN}ollama pull mistral${NC}"
echo "     ${CYAN}ollama pull llama2-uncensored${NC}"
echo ""
echo "  3. Test Ollama:"
echo "     ${CYAN}ollama run mistral \"Hello!\"${NC}"
echo ""
echo "  4. Start the API server:"
echo "     ${CYAN}source venv/bin/activate${NC}"
echo "     ${CYAN}python api/main.py${NC}"
echo ""
echo "  5. Start Open WebUI:"
echo "     ${CYAN}./webui/launch.sh${NC}"
echo "     Then open: ${CYAN}http://localhost:8080${NC}"
echo ""
echo "  6. Explore the CLI:"
echo "     ${CYAN}python cli/chat.py --help${NC}"
echo ""

echo_info "Documentation:"
echo "  - ${CYAN}docs/INSTALLATION.md${NC}"
echo "  - ${CYAN}docs/USAGE.md${NC}"
echo "  - ${CYAN}PROJECT_PLAN.md${NC}"
echo ""

echo_warning "Important: Activate the virtual environment before using Python scripts:"
echo "  ${CYAN}source venv/bin/activate${NC}"
echo ""

echo_success "Happy hacking! 🚀"
echo ""
