# Hugging Face Model Marketplace Setup

Complete guide to accessing and downloading models from Hugging Face and other marketplaces.

## Hugging Face Hub

Hugging Face is the largest repository of open-source AI models with 500,000+ models available.

### Installation

```bash
# Already included in requirements.txt
pip install huggingface-hub

# Verify installation
huggingface-cli --version
```

### Authentication (Optional but Recommended)

Some models require authentication. Create a free account at https://huggingface.co/

```bash
# Login to Hugging Face
huggingface-cli login

# Or set token as environment variable
export HUGGINGFACE_TOKEN="your_token_here"
```

### Finding Models

#### Web Interface
1. Visit https://huggingface.co/models
2. Filter by:
   - Task: "Text Generation"
   - Sort by: "Most Downloads" or "Most Likes"
   - License: "apache-2.0", "mit", "llama2"

#### Popular Uncensored Model Collections

**TheBloke** (GGUF Quantizations)
- Profile: https://huggingface.co/TheBloke
- 1000+ quantized models optimized for llama.cpp/Ollama
- Multiple quantization levels (Q2-Q8)
- Detailed documentation for each model

**cognitivecomputations** (Dolphin Series)
- Profile: https://huggingface.co/cognitivecomputations
- Truly uncensored models by Eric Hartford
- Models: dolphin-mistral, dolphin-mixtral
- Philosophy: "Fully uncensored, follows all instructions"

**NousResearch**
- Profile: https://huggingface.co/NousResearch
- Advanced models: Hermes, Capybara, Obsidian
- State-of-the-art training techniques
- Long-context specialists

**teknium** (OpenHermes)
- Profile: https://huggingface.co/teknium
- OpenHermes series (excellent instruction following)
- Trained on 1M+ GPT-4 samples
- Function calling support

**jondurbin** (Airoboros)
- Profile: https://huggingface.co/jondurbin
- Airoboros series (no RLHF)
- Strong reasoning and creative tasks
- Multiple sizes up to 70B

### Downloading Models

#### Method 1: Using Our Download Tool (Recommended)

```bash
# List available models
python models/download.py --list

# Show model info
python models/download.py --info dolphin-mixtral

# Download via Ollama (easiest)
python models/download.py dolphin-mixtral

# Download GGUF from Hugging Face
python models/download.py dolphin-mixtral --source gguf

# Download full model
python models/download.py dolphin-mixtral --source huggingface
```

#### Method 2: Hugging Face CLI

```bash
# Download specific file
huggingface-cli download TheBloke/dolphin-2.5-mixtral-8x7b-GGUF \
  dolphin-2.5-mixtral-8x7b.Q4_K_M.gguf \
  --local-dir ./data/models/dolphin-mixtral

# Download entire repository
huggingface-cli download cognitivecomputations/dolphin-2.6-mistral-7b \
  --local-dir ./data/models/dolphin-mistral

# Download with specific revision/branch
huggingface-cli download NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO \
  --revision main \
  --local-dir ./data/models/nous-hermes2-mixtral
```

#### Method 3: Python API

```python
from huggingface_hub import hf_hub_download, snapshot_download

# Download single file
file_path = hf_hub_download(
    repo_id="TheBloke/dolphin-2.5-mixtral-8x7b-GGUF",
    filename="dolphin-2.5-mixtral-8x7b.Q4_K_M.gguf",
    local_dir="./data/models"
)

# Download entire repository
snapshot_download(
    repo_id="cognitivecomputations/dolphin-2.6-mistral-7b",
    local_dir="./data/models/dolphin-mistral"
)
```

### Model Formats

#### GGUF (Recommended for CPU)
- **Format**: GGUF (successor to GGML)
- **Compatibility**: llama.cpp, Ollama, LM Studio, GPT4All
- **Advantages**: Optimized for CPU, quantized, fast loading
- **Source**: TheBloke's collection on Hugging Face

#### PyTorch/Safetensors
- **Format**: .bin, .safetensors, .pt
- **Compatibility**: Transformers, vLLM, Text Gen WebUI
- **Advantages**: Full precision, maximum quality
- **Size**: Large (7B model = 14GB+)

#### Quantization Levels (GGUF)

| Quant | Size | Quality | Speed | Use Case |
|-------|------|---------|-------|----------|
| Q2_K | Smallest | Lower | Fastest | Fitting large models in limited RAM |
| Q3_K_S | Small | Acceptable | Very Fast | 70B models on 60GB RAM |
| Q3_K_M | Medium | Good | Very Fast | Balance for large models |
| Q4_0 | Medium | Good | Fast | Standard option |
| Q4_K_S | Medium | Good | Fast | Recommended minimum |
| Q4_K_M | Medium | Very Good | Fast | **Best balance** ⭐ |
| Q5_K_S | Large | Very Good | Medium | Higher quality |
| Q5_K_M | Large | Excellent | Medium | Best quality/size |
| Q6_K | Larger | Excellent | Slower | Near-original quality |
| Q8_0 | Largest | Maximum | Slowest | Closest to original |

**Recommendation**: Use Q4_K_M for best balance, Q5_K_M for better quality, Q3_K_M for fitting larger models.

## Other Model Sources

### Ollama Library
- **Website**: https://ollama.ai/library
- **Models**: Curated selection, ready to run
- **Download**: `ollama pull <model>`
- **Advantages**: Simplest method, automatic quantization

### GPT4All
- **Website**: https://gpt4all.io/models
- **Format**: GGUF
- **Focus**: Privacy-first, locally runnable
- **Client**: Desktop app available

### LM Studio
- **Website**: https://lmstudio.ai
- **Platform**: Desktop app (Windows/Mac/Linux)
- **Features**: Built-in browser, one-click downloads
- **Format**: GGUF

### CivitAI
- **Website**: https://civitai.com
- **Focus**: Fine-tuned models, roleplay, creative
- **Note**: More permissive content policies

## Example Workflows

### Workflow 1: Quick Start (Ollama)

```bash
# 1. List available models
ollama list

# 2. Search for models
ollama search dolphin

# 3. Pull model
ollama pull dolphin-mistral

# 4. Run immediately
ollama run dolphin-mistral "Hello!"
```

### Workflow 2: Hugging Face GGUF (Best Quality Control)

```bash
# 1. Browse TheBloke's models
# Visit: https://huggingface.co/TheBloke

# 2. Download specific quantization
python models/download.py dolphin-mixtral --source gguf

# 3. Load in Ollama from local file
ollama create my-dolphin -f Modelfile

# Modelfile content:
# FROM ./data/models/dolphin-mixtral/dolphin-2.5-mixtral-8x7b.Q4_K_M.gguf
```

### Workflow 3: Full Model for Fine-tuning

```bash
# 1. Download full precision model
huggingface-cli download cognitivecomputations/dolphin-2.6-mistral-7b \
  --local-dir ./data/models/dolphin-mistral-full

# 2. Use for fine-tuning
python finetuning/train.py \
  --model ./data/models/dolphin-mistral-full \
  --dataset ./finetuning/datasets/my_data.jsonl
```

## Model Registry

We maintain a curated registry of models in `models/download.py`:

```python
# View all models
python models/download.py --list

# Filter by tag
python models/download.py --list --filter uncensored
python models/download.py --list --filter coding
python models/download.py --list --filter creative

# Get model info
python models/download.py --info dolphin-mixtral
```

## Managing Storage

### Check Model Sizes

```bash
# Ollama models
ollama list

# Downloaded models
du -sh data/models/*

# Hugging Face cache
du -sh ~/.cache/huggingface
```

### Clean Up

```bash
# Remove Ollama model
ollama rm model-name

# Clean Hugging Face cache
huggingface-cli delete-cache

# Remove downloaded models
rm -rf data/models/model-name
```

## Advanced: Private Models

Some models require authentication:

```bash
# 1. Get token from https://huggingface.co/settings/tokens

# 2. Login
huggingface-cli login

# 3. Download private model
huggingface-cli download organization/private-model \
  --local-dir ./data/models/private-model
```

## Troubleshooting

### Download Fails

```bash
# Check connection
curl -I https://huggingface.co

# Check authentication
huggingface-cli whoami

# Try with token
huggingface-cli download repo/model \
  --token YOUR_TOKEN \
  --local-dir ./models
```

### Out of Disk Space

```bash
# Check space
df -h

# Use smaller quantization
# Instead of Q5_K_M, use Q4_K_M or Q3_K_M

# Download to external drive
export HF_HOME=/mnt/external/huggingface
```

### Slow Downloads

```bash
# Use mirror (if available)
export HF_ENDPOINT=https://hf-mirror.com

# Resume interrupted download
# huggingface-cli automatically resumes

# Parallel downloads
huggingface-cli download repo/model \
  --max-workers 4
```

## Best Practices

1. **Start with Ollama**: Easiest for beginners
2. **Use TheBloke for GGUF**: Pre-quantized, tested, documented
3. **Q4_K_M for most cases**: Best balance of quality and size
4. **Check file integrity**: Verify checksums if provided
5. **Keep models organized**: Use consistent directory structure
6. **Version control**: Note model version/date for reproducibility
7. **Test before deployment**: Verify quality before switching

## Resources

- **Hugging Face Hub**: https://huggingface.co/models
- **TheBloke's Models**: https://huggingface.co/TheBloke
- **Ollama Library**: https://ollama.ai/library
- **Model Leaderboard**: https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard
- **GGUF Spec**: https://github.com/ggerganov/ggml/blob/master/docs/gguf.md

---

**Quick Reference**:
```bash
# List models in registry
python models/download.py --list

# Download via Ollama (easiest)
python models/download.py dolphin-mistral

# Download GGUF from HF
python models/download.py dolphin-mixtral --source gguf

# Browse on web
https://huggingface.co/models?pipeline_tag=text-generation&sort=downloads
```
