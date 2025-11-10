# Local AI Platform

A comprehensive, self-hosted AI platform for running and deploying uncensored local LLM models with custom fine-tuning capabilities.

## Features

- **Multiple Inference Engines**: Ollama, vLLM, llama.cpp
- **Model Management**: Download, quantize, and manage models
- **Web Interface**: Modern ChatGPT-like UI (Open WebUI)
- **API Server**: OpenAI-compatible REST API
- **Fine-tuning**: LoRA/QLoRA support for custom models
- **RAG Support**: Document retrieval and embedding
- **CLI Tools**: Command-line interface for all operations
- **100% Local**: No internet required for inference, complete privacy

## System Requirements

### Minimum
- CPU: 8+ cores
- RAM: 16GB
- Storage: 100GB

### Recommended (Current System)
- CPU: AMD Ryzen 9 7945HX (32 threads)
- RAM: 60GB
- Storage: 200GB+

## Quick Start

```bash
# 1. Clone the repository
git clone <repository-url>
cd local-ai-platform

# 2. Run installation
./setup/install.sh

# 3. Download your first model
python models/download.py mistral-7b-instruct

# 4. Start the platform
./scripts/start.sh

# 5. Access the Web UI
open http://localhost:8080
```

## Installation

See [INSTALLATION.md](docs/INSTALLATION.md) for detailed installation instructions.

## Usage

### Web Interface
```bash
# Start Open WebUI
./webui/launch.sh
```

Access at: http://localhost:8080

### CLI Chat
```bash
# Interactive chat
python cli/chat.py --model mistral-7b-instruct

# Single query
python cli/query.py "What is the capital of France?"
```

### API Server
```bash
# Start API server
python api/main.py

# Test with curl
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral-7b-instruct",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Fine-tuning
```bash
# Prepare dataset
python finetuning/train.py \
  --model mistral-7b \
  --dataset datasets/my_data.jsonl \
  --output outputs/my-model
```

## Supported Models

### Uncensored Models
- WizardLM-13B-Uncensored
- Nous-Hermes-2-Mixtral-8x7B
- Nous-Capybara-34B
- Yi-34B-Chat
- Goliath-120B

### General Purpose
- Mistral-7B-Instruct
- Llama-2-70B-Chat
- CodeLlama-34B
- Nous-Hermes-2-Solar-10.7B

See [MODEL_GUIDE.md](docs/MODEL_GUIDE.md) for complete list and recommendations.

## Project Structure

```
local-ai-platform/
├── setup/          # Installation scripts
├── api/            # API server
├── models/         # Model management tools
├── finetuning/     # Training scripts
├── webui/          # Web interface
├── cli/            # Command-line tools
├── scripts/        # Utility scripts
├── config/         # Configuration files
├── data/           # Models and data storage
└── docs/           # Documentation
```

## Documentation

- [Installation Guide](docs/INSTALLATION.md)
- [Usage Guide](docs/USAGE.md)
- [Model Guide](docs/MODEL_GUIDE.md)
- [Fine-tuning Guide](docs/FINE_TUNING.md)
- [API Reference](docs/API_REFERENCE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Project Plan](PROJECT_PLAN.md)

## Architecture

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for detailed architecture and implementation plan.

## Performance

On AMD Ryzen 9 7945HX (32 threads, 60GB RAM):

| Model Size | Tokens/sec | Use Case |
|------------|-----------|----------|
| 7B (Q4_K_M) | 40-50 | General purpose, fast |
| 13B (Q4_K_M) | 25-30 | Balanced quality/speed |
| 34B (Q4_K_M) | 10-15 | High quality |
| 70B (Q4_K_M) | 3-5 | Maximum quality |

## Contributing

This is a personal project. Feel free to fork and adapt to your needs.

## License

MIT License - See LICENSE file for details

## Acknowledgments

- [Ollama](https://ollama.ai) - Model serving
- [llama.cpp](https://github.com/ggerganov/llama.cpp) - Inference engine
- [Open WebUI](https://github.com/open-webui/open-webui) - Web interface
- [TheBloke](https://huggingface.co/TheBloke) - Quantized models
- [Axolotl](https://github.com/OpenAccess-AI-Collective/axolotl) - Fine-tuning framework

## Status

**Current Phase**: Phase 1 - Foundation Setup

- [x] Project planning
- [x] Repository initialization
- [ ] Core infrastructure setup
- [ ] Model management
- [ ] Basic API

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for detailed roadmap.

---

**Last Updated**: 2025-01-10
