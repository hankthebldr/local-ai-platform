# Quick Start Guide

Get up and running with Local AI Platform in 15 minutes.

## Prerequisites

- Linux system (tested on Parrot OS / Debian-based)
- 16GB+ RAM (60GB recommended)
- 100GB+ free disk space
- Python 3.10+

## Installation

### 1. Clone and Install

```bash
cd ~/Projects
git clone <your-repo-url> local-ai-platform
cd local-ai-platform

# Run installation script
./setup/install.sh
```

The installation script will:
- Install system dependencies
- Create Python virtual environment
- Install Python packages
- Install and configure Ollama
- Set up directory structure

### 2. Activate Virtual Environment

```bash
source venv/bin/activate
```

### 3. Download Your First Model

```bash
# Popular uncensored 7B model (fast)
ollama pull mistral

# Or a larger uncensored model (better quality)
ollama pull dolphin-mixtral

# List available models
ollama list
```

## Usage

### Option 1: CLI Chat (Simplest)

```bash
python cli/chat.py --model mistral
```

Interactive commands:
- `/help` - Show commands
- `/models` - List models
- `/clear` - Clear history
- `exit` - Quit

### Option 2: API Server

```bash
# Terminal 1: Start API server
python api/main.py

# Terminal 2: Test the API
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral",
    "messages": [
      {"role": "user", "content": "What is the meaning of life?"}
    ]
  }'
```

### Option 3: Enclave SPA (the application)

The full Enclave UI is served by the API itself at the same origin:

```
http://localhost:8000
```

It auto-fetches the first-run license key on boot and lands on the
Composer. No separate launcher needed.

### Optional: Open WebUI (third-party chat client)

If you specifically want Open WebUI's chat surface alongside the Enclave
SPA, opt in via the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.webui.yml up -d
# Open WebUI is now on http://localhost:8081
```

## Recommended Models

### Fast & Capable (7-13B)
```bash
ollama pull mistral              # Excellent general purpose
ollama pull dolphin-mistral      # Uncensored variant
ollama pull codellama:13b        # Best for coding
```

### Best Quality (30-34B)
```bash
ollama pull mixtral              # Top quality, good speed
ollama pull yi:34b               # Excellent reasoning
```

### Specialized
```bash
ollama pull llama2-uncensored    # Classic uncensored
ollama pull nous-hermes2         # Function calling
```

## Testing Your Setup

```bash
# Test Ollama directly
ollama run mistral "Write a haiku about AI"

# Test API
python api/main.py &
curl http://localhost:8000/health

# Test CLI
python cli/chat.py --model mistral
```

## Common Issues

### Ollama not starting
```bash
# Check if Ollama is running
systemctl --user status ollama

# Start manually
ollama serve

# Or restart service
systemctl --user restart ollama
```

### Python dependencies error
```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r setup/requirements.txt
```

### Out of memory
```bash
# Use smaller model
ollama pull mistral:7b-instruct-q4_K_M

# Or reduce context length in .env
OLLAMA_NUM_CTX=2048
```

## Next Steps

1. **Explore Models**: Try different models to find what works best
2. **Configure**: Edit `.env` file for customization
3. **API Integration**: Use the API in your applications
4. **Fine-tuning**: Create custom models (see FINE_TUNING.md)

## Resources

- Full Documentation: [docs/](../docs/)
- Project Plan: [PROJECT_PLAN.md](../PROJECT_PLAN.md)
- API Reference: [docs/API_REFERENCE.md](../docs/API_REFERENCE.md)

---

**Need Help?** Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
