# Top Uncensored Open-Source LLM Models

Comprehensive guide to the best uncensored, open-source language models available for local deployment.

## What Makes a Model "Uncensored"?

**Uncensored models** are fine-tuned without RLHF (Reinforcement Learning from Human Feedback) safety alignment that typically restricts outputs. They:
- Have no content filtering or refusal training
- Don't decline requests based on content policy
- Provide direct, unfiltered responses
- Are trained or fine-tuned specifically to remove censorship

## Top Uncensored Models by Size

### Tier 1: Best Uncensored Models (Large Training Sets)

#### 1. **Dolphin 2.5 Mixtral 8x7B** ⭐ RECOMMENDED
- **Creator**: Eric Hartford (Cognitive Computations)
- **Base Model**: Mixtral-8x7B-v0.1
- **Training**: Fine-tuned on extensive uncensored datasets
- **Quant Size**: 26GB (Q4_K_M)
- **Speed on Your System**: ~15-20 tokens/sec
- **Special Features**:
  - Completely uncensored, follows all instructions
  - Excellent at creative writing, roleplay, coding
  - Strong reasoning capabilities
  - Function calling support
- **Download**:
  ```bash
  ollama pull dolphin-mixtral
  # Or from HuggingFace
  cognitivecomputations/dolphin-2.5-mixtral-8x7b
  ```

#### 2. **WizardLM-2 8x22B Uncensored**
- **Base Model**: Mixtral-8x22B
- **Training**: Evol-Instruct on diverse datasets, uncensored fine-tune
- **Quant Size**: 80GB (Q4_K_M) - Requires careful memory management
- **Speed**: ~3-5 tokens/sec (will need aggressive quantization)
- **Features**:
  - State-of-the-art reasoning
  - Complex problem solving
  - Minimal censorship
- **Note**: May need Q3 or Q2 quantization on 60GB RAM

#### 3. **Nous Hermes 2 Mixtral 8x7B DPO/SFT**
- **Creator**: Nous Research
- **Training**: DPO (Direct Preference Optimization) + SFT
- **Quant Size**: 26GB (Q4_K_M)
- **Speed**: ~15-20 tokens/sec
- **Features**:
  - Excellent instruction following
  - Strong multi-turn conversations
  - Balanced and versatile
- **Download**:
  ```bash
  ollama pull nous-hermes2-mixtral
  # HuggingFace: NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO
  ```

#### 4. **Yi-34B-200K Uncensored**
- **Base Model**: Yi-34B (trained on 3T tokens!)
- **Context**: 200K tokens
- **Quant Size**: 20GB (Q4_K_M)
- **Speed**: ~10-12 tokens/sec
- **Features**:
  - Massive 200K context window
  - Excellent for long documents
  - Strong multilingual capabilities
  - Uncensored community fine-tune
- **Download**:
  ```bash
  ollama pull yi:34b-chat
  # HuggingFace: 01-ai/Yi-34B-200K
  ```

### Tier 2: High-Performance Uncensored (7-13B)

#### 5. **Dolphin 2.6 Mistral 7B** ⭐ BEST FOR SPEED
- **Training**: Latest uncensored dataset from Eric Hartford
- **Quant Size**: 4.1GB (Q4_K_M)
- **Speed**: 45-55 tokens/sec on your system
- **Features**:
  - Fastest option with excellent quality
  - Great for coding and creative tasks
  - Latest alignment techniques
- **Download**:
  ```bash
  ollama pull dolphin-mistral
  # HuggingFace: cognitivecomputations/dolphin-2.6-mistral-7b
  ```

#### 6. **OpenHermes 2.5 Mistral 7B**
- **Training**: 1M+ GPT-4 generated samples
- **Quant Size**: 4.1GB (Q4_K_M)
- **Speed**: 45-50 tokens/sec
- **Features**:
  - Excellent instruction following
  - Strong coding capabilities
  - Function calling
- **Download**:
  ```bash
  ollama pull openhermes
  # HuggingFace: teknium/OpenHermes-2.5-Mistral-7B
  ```

#### 7. **Neural-Chat 7B v3.3**
- **Training**: Intel's uncensored fine-tune
- **Quant Size**: 4.1GB (Q4_K_M)
- **Speed**: 45-50 tokens/sec
- **Features**:
  - Optimized for CPU inference (perfect for your system!)
  - Strong conversational abilities
  - Good safety/capability balance
- **Download**:
  ```bash
  ollama pull neural-chat
  # HuggingFace: Intel/neural-chat-7b-v3-3
  ```

#### 8. **WizardLM-13B-Uncensored-v1.2**
- **Training**: Evol-Instruct methodology
- **Quant Size**: 7.4GB (Q4_K_M)
- **Speed**: 25-30 tokens/sec
- **Features**:
  - Classic uncensored model
  - Strong creative writing
  - Good at following complex instructions

### Tier 3: Specialized Uncensored Models

#### 9. **MythoMax L2 13B**
- **Type**: Merge of Mytholite and Huginn
- **Training**: Creative writing and roleplay focused
- **Quant Size**: 7.4GB (Q4_K_M)
- **Speed**: 25-30 tokens/sec
- **Best For**: Creative writing, storytelling, roleplay
- **Download**:
  ```bash
  ollama pull mythomax
  # HuggingFace: Gryphe/MythoMax-L2-13b
  ```

#### 10. **Airoboros L2 70B**
- **Training**: Extensive instruction tuning, no RLHF
- **Quant Size**: 40GB (Q4_K_M)
- **Speed**: 3-5 tokens/sec (usable with Q3 quant)
- **Features**:
  - Extremely capable
  - Strong reasoning
  - Creative and technical tasks
- **Download**:
  ```bash
  ollama pull airoboros:70b
  # HuggingFace: jondurbin/airoboros-l2-70b-gpt4-1.4.1
  ```

### Tier 4: Experimental & Cutting Edge

#### 11. **Goliath-120B** (Experimental)
- **Type**: Merge of multiple 70B models
- **Quant Size**: 70GB+ (Q2_K minimum)
- **Speed**: 1-2 tokens/sec (very slow)
- **Features**:
  - Absolute maximum capability
  - Requires careful quantization
  - Best quality regardless of topic
- **Note**: Experimental, may need special setup

#### 12. **Nous Capybara 34B**
- **Training**: Multi-turn conversation specialist
- **Quant Size**: 20GB (Q4_K_M)
- **Speed**: 10-12 tokens/sec
- **Features**:
  - Excellent multi-turn conversations
  - Strong context retention
  - Uncensored fine-tune

## Training Dataset Sizes (Largest to Smallest)

1. **Yi Models**: 3 Trillion tokens (largest public training set)
2. **Mixtral Models**: ~Unknown, estimated 1-2T tokens
3. **Llama 2**: 2 Trillion tokens
4. **Mistral**: ~Unknown, estimated 1T+ tokens
5. **WizardLM**: Base model + Evol-Instruct synthetic data
6. **Dolphin Series**: Base model + extensive uncensored fine-tuning

## Recommended Combinations for Your System (60GB RAM)

### Setup 1: Speed & Quality Balance
```bash
ollama pull dolphin-mistral     # 4GB - Primary fast model
ollama pull dolphin-mixtral     # 26GB - High-quality model
ollama pull yi:34b-chat         # 20GB - Long context specialist
```
**Total**: ~50GB, room for active inference

### Setup 2: Maximum Capability
```bash
ollama pull dolphin-mistral     # 4GB - Fast queries
ollama pull nous-hermes2-mixtral # 26GB - Balanced
ollama pull airoboros:70b       # Use Q3_K_M (~25GB) - Best quality
```

### Setup 3: Specialized Workload
```bash
ollama pull openhermes          # 4GB - Coding & functions
ollama pull mythomax            # 7GB - Creative writing
ollama pull dolphin-mixtral     # 26GB - General purpose
ollama pull yi:34b-chat         # 20GB - Long documents
```

## Model Sources & Marketplaces

### Primary Sources

#### 1. Ollama Library (Easiest)
```bash
ollama list          # See installed models
ollama search uncensored  # Search for models
ollama pull <model>  # Download model
```
Website: https://ollama.ai/library

#### 2. Hugging Face (Largest Selection)
- **Website**: https://huggingface.co/models
- **Search**: Filter by "text-generation", sort by downloads/likes
- **Popular Collections**:
  - TheBloke - GGUF quantized models
  - cognitivecomputations - Dolphin series
  - NousResearch - Hermes, Capybara series
  - teknium - OpenHermes series
  - jondurbin - Airoboros series

**Download via CLI**:
```bash
# Install huggingface-cli
pip install huggingface_hub

# Download GGUF model
huggingface-cli download TheBloke/dolphin-2.5-mixtral-8x7b-GGUF \
  dolphin-2.5-mixtral-8x7b.Q4_K_M.gguf \
  --local-dir ./models
```

#### 3. GPT4All Model Explorer
- **Website**: https://gpt4all.io/models
- Curated selection of safe-to-run models
- Includes metadata and benchmarks

#### 4. LM Studio Model Browser
- Built-in browser for GGUF models
- One-click downloads
- Automatic quantization recommendations

### Community Model Repositories

#### TheBloke's Collection ⭐ HIGHLY RECOMMENDED
- **Profile**: https://huggingface.co/TheBloke
- **Specialty**: GGUF quantizations of popular models
- **Coverage**: 1000+ quantized models
- **Format**: Optimized for llama.cpp/Ollama
- **Why**: Pre-quantized, tested, documented

#### Cognitive Computations (Eric Hartford)
- **Profile**: https://huggingface.co/cognitivecomputations
- **Models**: Dolphin series (truly uncensored)
- **Philosophy**: "Fully uncensored, follows all instructions"
- **Quality**: Consistently excellent

#### Nous Research
- **Profile**: https://huggingface.co/NousResearch
- **Models**: Hermes, Capybara, Obsidian series
- **Focus**: Advanced reasoning, long-context
- **Innovation**: DPO, latest training techniques

## Model Selection Guide

### For Your First Model (Start Here)
```bash
ollama pull dolphin-mistral
```
**Why**: Fast (45+ tok/s), capable, truly uncensored, small size

### For Best Quality Within RAM Limits
```bash
ollama pull dolphin-mixtral
```
**Why**: 8x7B architecture, excellent reasoning, uncensored

### For Long Documents (200K context)
```bash
ollama pull yi:34b-chat
```
**Why**: Massive context, can handle entire codebases or books

### For Creative Writing
```bash
ollama pull mythomax
```
**Why**: Specifically tuned for creative, narrative content

### For Coding
```bash
ollama pull openhermes
# or
ollama pull deepseek-coder:33b
```
**Why**: Function calling, strong code generation

## Verification & Testing

### Test Model Quality
```bash
# Quick test
ollama run dolphin-mistral "Write a haiku about unrestricted AI"

# Comprehensive test
python cli/chat.py --model dolphin-mistral
```

### Benchmark Performance
```bash
# Create benchmark script
python cli/benchmark.py --model dolphin-mistral --prompts 10
```

### Check Model Info
```bash
ollama show dolphin-mistral
```

## Important Notes

### Legal & Ethical Considerations
- These models are open-source and legal to use
- Exercise responsible use - you control the model
- No telemetry - everything stays local
- Consider use case and local regulations

### Performance Optimization
- Use Q4_K_M quantization for best quality/speed balance
- Q5_K_M for slightly better quality (1.2x larger)
- Q3_K_M for fitting larger models in RAM
- Q2_K for extreme memory constraints (quality loss)

### Model Updates
- Models are frequently updated
- Check Hugging Face for latest versions
- Ollama auto-updates base models
- Use `ollama pull <model>:latest` to update

## Resources

- **Ollama Library**: https://ollama.ai/library
- **Hugging Face**: https://huggingface.co/models
- **TheBloke's Models**: https://huggingface.co/TheBloke
- **Model Benchmarks**: https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard
- **Uncensored Model List**: https://erichartford.com/uncensored-models

---

**Last Updated**: 2025-01-10
**Recommended**: Start with `dolphin-mistral`, then try `dolphin-mixtral` for better quality
