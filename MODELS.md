# MODELS.md — Model Strategy, Catalog & Lifecycle Ops

> **For Claude Code**: This document is the authoritative source for model decisions.
> All install/remove operations must follow the per-machine sequences defined here.
> Update `models/download.py → MODEL_REGISTRY` to match after any changes.

---

## Flagship Research Model

### ⚑ PRIMARY: `huihui_ai/qwen2.5-abliterated:72b`

**Why this model**: Qwen 2.5 72B is the highest-capability open-weight model that fits the BD790i's
80 GB budget at Q4_K_M (~45 GB). The `huihui_ai` abliteration variant surgically removes refusal
neurons without degrading reasoning quality — this is the difference between a model that
*declines* and one that *engages*. For security research, red-team scenario generation, and
unconstrained analysis this is the correct tool.

| Property | Value |
|---|---|
| Ollama tag | `huihui_ai/qwen2.5-abliterated:72b` |
| HuggingFace | `huihui_ai/Qwen2.5-72B-Instruct-abliterated` |
| Disk (Q4_K_M) | ~44 GB |
| Context | 128K tokens |
| BD790i speed | 4–7 tok/s |
| MS-01 speed | ❌ Does not fit (exceeds 50 GB safe limit) |
| Mac M4 speed | ❌ Do not run locally — use API against workstation |
| Purpose | **Flagship research, security analysis, unconstrained reasoning** |

**Fallback if 72B is unavailable**: `jaahas/qwen3.5-uncensored:35b` (24.8 GB, 8–12 tok/s on BD790i)

---

## Machine Assignments

Think of this like a three-tier warehouse:
- **Mac** = fast staging area (lightweight, iterative dev)
- **MS-01** = production floor (32B and under, always-on serving)
- **BD790i** = heavy machinery (70B class, flagship research)

### Mac M4 Pro (48 GB unified)
**Role**: Dev & iteration. Keep only models you actively test code against.

| Model | Ollama Tag | Size | Purpose | Action |
|---|---|---|---|---|
| dolphin3 | `dolphin3` | 4.9 GB | General uncensored, fast iteration | **KEEP** |
| dolphin3-abliterated | `huihui_ai/dolphin3-abliterated` | 4.9 GB | Abliterated baseline testing | **KEEP** |
| qwen3.5-uncensored-9b | `jaahas/qwen3.5-uncensored:9b` | 7.4 GB | Reasoning, multilingual | **KEEP** |
| qwen2.5-coder-7b | `huihui_ai/qwen2.5-coder-abliterate:7b` | 4.7 GB | Coding dev testing | **KEEP** |
| qwen3.5-uncensored-35b | `jaahas/qwen3.5-uncensored:35b` | 24.8 GB | Oversized for Mac | **REMOVE** |
| deepseek-r1-32b | `deepseek-r1:32b` | 19.9 GB | Oversized for Mac | **REMOVE** |
| qwen2.5-32b | `qwen2.5:32b` | 19.9 GB | Untracked / evaluate need | **REMOVE** |

**Mac cleanup sequence** (run after workstation pulls are confirmed):
```bash
ollama rm jaahas/qwen3.5-uncensored:35b
ollama rm deepseek-r1:32b
ollama rm qwen2.5:32b
# Verify
ollama list
# Expected remaining: ~22 GB total (4 models)
```

---

### MS-01 (64 GB DDR5 / i9-13900H / 20T)
**Role**: Always-on API server. Handles 8B–32B inference, serves local clients.
Max safe model load: **50 GB**

| Model | Ollama Tag | Size | Speed | Purpose | Action |
|---|---|---|---|---|---|
| dolphin3 | `dolphin3` | 4.9 GB | 15–25 tok/s | Fast chat, API default | **PULL** |
| dolphin3-abliterated | `huihui_ai/dolphin3-abliterated` | 4.9 GB | 15–25 tok/s | Max unrestricted 8B | **PULL** |
| qwen3.5-uncensored-9b | `jaahas/qwen3.5-uncensored:9b` | 7.4 GB | 12–20 tok/s | Reasoning / multilingual | **PULL** |
| qwen2.5-coder-7b | `huihui_ai/qwen2.5-coder-abliterate:7b` | 4.7 GB | 18–25 tok/s | Code completion | **PULL** |
| qwen2.5-14b-abliterated | `huihui_ai/qwen2.5-abliterated:14b` | 9 GB | 8–12 tok/s | Quality sweet spot | **PULL** |
| deepseek-r1-32b | `deepseek-r1:32b` | 19.9 GB | 3–5 tok/s | Chain-of-thought reasoning | **PULL** |
| qwen3.5-uncensored-35b | `jaahas/qwen3.5-uncensored:35b` | 24.8 GB | 3–5 tok/s | Heavy reasoning (fits, barely) | **PULL** |

**MS-01 install sequence**:
```bash
# Step 1: Install smaller models first, verify Ollama service is healthy
ollama pull dolphin3
ollama pull huihui_ai/dolphin3-abliterated
ollama pull jaahas/qwen3.5-uncensored:9b
ollama pull huihui_ai/qwen2.5-coder-abliterate:7b
ollama pull huihui_ai/qwen2.5-abliterated:14b

# Step 2: Check disk space before large pulls
df -h ~/.ollama

# Step 3: Pull 32B class (run separately — one at a time)
ollama pull deepseek-r1:32b

# Step 4: Pull 35B (confirm 50 GB budget not exceeded)
ollama list  # check current usage
ollama pull jaahas/qwen3.5-uncensored:35b

# Step 5: Verify all models respond
ollama run dolphin3 "respond with: online" --nowordwrap
```

**MS-01 concurrent limits**:
- One 35B model OR two 8B models simultaneously
- Set `OLLAMA_MAX_LOADED_MODELS=1` when running 35B to prevent OOM

---

### BD790i (96 GB DDR5 / Ryzen 9 7945HX / 32T)
**Role**: Research & flagship inference. 70B+ class. Primary destination for uncensored work.
Max safe model load: **80 GB**

| Model | Ollama Tag | Size | Speed | Purpose | Action |
|---|---|---|---|---|---|
| **qwen2.5-abliterated-72b** | `huihui_ai/qwen2.5-abliterated:72b` | ~44 GB | 4–7 tok/s | **FLAGSHIP RESEARCH** | **PULL FIRST** |
| qwen3.5-uncensored-35b | `jaahas/qwen3.5-uncensored:35b` | 24.8 GB | 8–12 tok/s | Fallback / concurrent use | **PULL** |
| deepseek-r1-32b | `deepseek-r1:32b` | 19.9 GB | 8–12 tok/s | Chain-of-thought research | **PULL** |
| dolphin-mixtral | `dolphin-mixtral` | 26 GB | 12–18 tok/s | MoE, creative/research | **PULL** |
| dolphin3 | `dolphin3` | 4.9 GB | 40–55 tok/s | Fast API baseline | **PULL** |
| qwen3.5-uncensored-9b | `jaahas/qwen3.5-uncensored:9b` | 7.4 GB | 35–45 tok/s | Fast reasoning | **PULL** |

**BD790i install sequence**:
```bash
# Step 1: Check disk before starting (need ~130 GB free for full set)
df -h ~/.ollama

# Step 2: Pull flagship first — this is the priority install
ollama pull huihui_ai/qwen2.5-abliterated:72b
# Verify flagship responds before continuing
ollama run huihui_ai/qwen2.5-abliterated:72b "respond with: online" --nowordwrap

# Step 3: Pull the supporting tier
ollama pull jaahas/qwen3.5-uncensored:35b
ollama pull deepseek-r1:32b

# Step 4: Check disk again before heavy model
df -h ~/.ollama
ollama pull dolphin-mixtral

# Step 5: Fast-inference baseline
ollama pull dolphin3
ollama pull jaahas/qwen3.5-uncensored:9b

# Step 6: Final inventory check
ollama list
```

**BD790i concurrent limits**:
- 72B alone: ~44 GB loaded, 36 GB headroom → can load a 9B alongside
- 35B + 9B simultaneously: ~32 GB → fine
- Never load 72B + 35B simultaneously: 69 GB combined, cuts into OS headroom

---

## Full Model Catalog

### Tier 1 — Daily Drivers (4–7 GB, 8–9B class)
Fast interactive use, always-on API defaults, dev testing.

| ID | Name | Tag | Size | Context | Use Case |
|---|---|---|---|---|---|
| `dolphin3` | Dolphin 3 (Llama 3.1 8B) | `dolphin3` | 4.9 GB | 128K | General uncensored chat, system prompting |
| `dolphin3-abliterated` | Dolphin 3 Abliterated | `huihui_ai/dolphin3-abliterated` | 4.9 GB | 128K | Maximum unrestricted 8B — refusal neurons removed |
| `qwen3.5-uncensored-9b` | Qwen 3.5 9B Uncensored | `jaahas/qwen3.5-uncensored:9b` | 7.4 GB | 128K | Strong reasoning, multilingual, latest arch (2026) |
| `qwen2.5-coder-7b` | Qwen 2.5 Coder 7B Abliterated | `huihui_ai/qwen2.5-coder-abliterate:7b` | 4.7 GB | 128K | Code generation / completion, 86 languages |
| `dolphin-mistral` | Dolphin 2.6 Mistral 7B | `dolphin-mistral` | 4.1 GB | 32K | Classic fast uncensored, lightweight coding |
| `dolphin-phi` | Dolphin Phi 2.7B | `dolphin-phi` | 1.6 GB | 2K | Edge / embedded, minimal RAM, rapid testing |

### Tier 2 — Quality Sweet Spot (7–14 GB, 13–14B class)
Best quality/speed balance. Fits comfortably on all machines.

| ID | Name | Tag | Size | Context | Use Case |
|---|---|---|---|---|---|
| `qwen2.5-14b-abliterated` | Qwen 2.5 14B Abliterated | `huihui_ai/qwen2.5-abliterated:14b` | 9 GB | 128K | Primary upgrade from 8B — reasoning + abliterated |
| `wizardlm-uncensored-13b` | WizardLM 13B Uncensored | `wizardlm-uncensored:13b` | 7.4 GB | 4K | Classic creative writing baseline |
| `qwen3-8b-hivemind` | Qwen 3 8B Hivemind Abliterated | GGUF: `DavidAU/...` | 5 GB | **256K** | Ultra-long context tasks, abliterated |

### Tier 3 — Power Models (17–26 GB, 18–35B class)
Slower but significantly more capable. MS-01 and BD790i only.

| ID | Name | Tag | Size | Context | Use Case |
|---|---|---|---|---|---|
| `qwen3.5-uncensored-35b` | Qwen 3.5 35B Uncensored | `jaahas/qwen3.5-uncensored:35b` | 24.8 GB | 128K | Primary MS-01 workhorse, flagship fallback |
| `dolphin-mixtral` | Dolphin 2.5 Mixtral 8x7B | `dolphin-mixtral` | 26 GB | 32K | MoE — activates 13B per token, faster than dense |
| `gemma3-27b-abliterated` | Gemma 3 27B Abliterated | GGUF: `mradermacher/...` | 17 GB | 128K | Vision-capable, multimodal research |
| `llama3.2-moe-18b` | Llama 3.2 8x3B MoE 18.4B | GGUF: `DavidAU/...` | 12 GB | 128K | Creative writing, MoE speed advantage |
| `nous-hermes2-mixtral` | Nous Hermes 2 Mixtral 8x7B | `nous-hermes2-mixtral` | 26 GB | 32K | Instruction following, balanced task performance |

### Tier 4 — Research Flagship (44+ GB, 32–72B class)
BD790i only. Priority for unconstrained research and complex analysis.

| ID | Name | Tag | Size | Context | Use Case |
|---|---|---|---|---|---|
| `qwen2.5-abliterated-72b` | **Qwen 2.5 72B Abliterated** ⚑ | `huihui_ai/qwen2.5-abliterated:72b` | ~44 GB | 128K | **PRIMARY RESEARCH FLAGSHIP** |
| `deepseek-r1-32b` | DeepSeek R1 32B | `deepseek-r1:32b` | 19.9 GB | 128K | Chain-of-thought, step-by-step reasoning |
| `deepseek-coder-33b` | DeepSeek Coder 33B | `deepseek-coder:33b` | 20 GB | 16K | Best-in-class coding, 86 languages |

### Tier 5 — Specialized
Niche use cases. Pull on demand, remove when not needed.

| ID | Name | Tag | Size | Use Case |
|---|---|---|---|---|
| `mythomax` | MythoMax L2 13B | `mythomax` | 7.4 GB | Roleplay, narrative, creative fiction |
| `llama3.3-8b-abliterated` | Llama 3.3 8B Abliterated | GGUF: `mradermacher/...` | 4.9 GB | Meta Llama 3.3 with high reasoning, abliterated |
| `qwen2.5-7b-abliterated` | Qwen 2.5 7B Abliterated | `huihui_ai/qwen2.5-abliterated:7b` | 4.7 GB | Compact abliterated reasoning backup |
| `wizardlm-uncensored-13b` | WizardLM 13B Uncensored | `wizardlm-uncensored:13b` | 7.4 GB | Classic creative writing |

---

## Remove Operations

**Remove a model (any machine)**:
```bash
# Single model
ollama rm <tag>

# Remove and free blobs (Ollama handles blob dedup automatically)
ollama rm <tag>
ollama list  # verify removed
du -sh ~/.ollama/models/blobs/  # verify disk reclaimed
```

**Remove all models not in current machine assignment** (run per-machine):
```bash
# Get current list
ollama list

# Remove by name — cross-reference with your machine's table above
# Ollama does NOT prompt for confirmation — double-check the name
ollama rm <exact-tag-from-list>
```

> ⚠️ **Important**: `deepseek-r1:32b` and `qwen2.5:32b` have separate blobs despite identical
> sizes (19.85 GB each). Removing one does NOT reclaim the other's disk. Verified 2026-03-26.

---

## Adding a New Model to Registry

Edit `models/download.py → MODEL_REGISTRY`:
```python
"model-key": {
    "name": "Display Name",
    "ollama": "registry/tag:version",          # ollama pull target
    "huggingface": "org/repo-name",             # optional
    "gguf": "org/repo-GGUF",                    # optional, for HF GGUF download
    "size": "X.XGB",                            # disk footprint at Q4_K_M
    "speed": {"ms01": "X-Y tok/s", "bd790i": "X-Y tok/s"},
    "context": "128K",
    "description": "One-line purpose statement",
    "tags": ["tier", "uncensored|abliterated|censored", "use-case", "machine-target"],
    "machine": ["bd790i"],                      # which machines this belongs on
    "installed": False,
}
```

**Tags convention**:
- Restriction: `uncensored` / `abliterated` / `censored`
- Speed class: `fast` / `balanced` / `large`
- Use case: `coding` / `reasoning` / `creative` / `research` / `edge`
- Machine fit: `mac-ok` / `ms01-ok` / `bd790i-only`

---

## Quantization Reference

| Quant | Quality | Size vs FP16 | Notes |
|---|---|---|---|
| Q2_K | Low | ~30% | Emergency fit only — noticeable degradation |
| Q3_K_M | Acceptable | ~40% | Use for 70B on tight RAM |
| **Q4_K_M** | **Good** | **~50%** | **Default — best quality/speed balance** |
| Q5_K_M | Better | ~60% | Use when RAM allows, better factual recall |
| Q8_0 | Near-lossless | ~80% | Dev/eval only — large RAM requirement |

**BD790i 80 GB budget examples**:
- 72B @ Q4_K_M: ~44 GB ✅
- 72B @ Q5_K_M: ~54 GB ✅
- 72B @ Q8_0: ~76 GB ⚠️ Tight
- 120B @ Q3_K_M: ~58 GB ✅ (future expansion candidate)

---

## Context: Why Abliteration vs Fine-Tuning

Both approaches remove model refusals, but they're different mechanisms:

- **Uncensored fine-tuning** (Dolphin, WizardLM): Trained from scratch on uncensored data.
  Refusals were never reinforced. More natural, but relies on training data coverage.

- **Abliteration** (huihui_ai, mradermacher): Post-training surgical removal of refusal-direction
  vectors from residual stream. Applied to any base model. More consistent and extreme removal —
  the model literally cannot construct refusal outputs because the direction is zeroed.

**For security research purposes**, abliterated models on strong base weights (72B Qwen, 70B Llama)
are preferred because:
1. Stronger base reasoning (larger parameter count)
2. Consistent non-refusal regardless of prompt framing
3. Abliteration preserves helpfulness tuning while removing safety tuning

---

## Model Status Check (Quick Commands)

```bash
# What's installed right now
ollama list

# Check Ollama API models endpoint  
curl -s http://localhost:11434/api/tags | python3 -m json.tool | grep name

# Platform-aware status (compares registry vs installed)
source venv/bin/activate
python models/download.py --status

# RAM currently consumed by Ollama
ps aux | grep ollama | awk '{print $6/1024 " MB"}'

# Disk usage breakdown
du -sh ~/.ollama/models/blobs/
du -sh ~/.ollama/models/manifests/
```

---

*Last updated: 2026-03-26 | Maintained by: Claude Code agent*
*Hardware: Mac M4 Pro 48GB / MS-01 64GB / BD790i 96GB*
