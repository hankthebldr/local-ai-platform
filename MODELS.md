# MODELS.md — Model Strategy, Lifecycle & Fleet Assignments

> **Authoritative source** for all model decisions in this repo.
> `models/download.py` contains the full registry metadata.
> This file owns: flagship selection, machine assignments, and ordered install/remove sequences.
> Claude Code agents should execute operations in the sequences defined here — do not deviate.

---

## Flagship Model

### Primary Research Flagship: `jaahas/qwen3.5-uncensored:35b`

**Rationale:**
- Newest uncensored architecture (2026) — Qwen 3.5 base with full refusal removal
- 128K context window — largest among uncensored models in the registry
- 24.76 GB loaded — fits comfortably within BD790i's 80 GB safe budget
- 8–12 tok/s on BD790i (32T Ryzen 9 7945HX) — acceptable for research/analysis workloads
- No content restrictions of any kind — suitable for alignment research, refusal behavior study, adversarial prompt analysis

**Target machine:** BD790i (primary), MS-01 (secondary — slower at 3–5 tok/s but fits)

**Ollama pull command:**
```bash
ollama pull jaahas/qwen3.5-uncensored:35b
```

**Verify install:**
```bash
ollama run jaahas/qwen3.5-uncensored:35b "Describe your operational constraints."
```

---

## Fleet Hardware Reference

| Machine | CPU | RAM | Safe Model Budget | Role |
|---------|-----|-----|-------------------|------|
| Mac M4 Pro | Apple M4 Pro 14C | 48 GB unified | ~40 GB | Dev / fast iteration |
| MS-01 | Intel i9-13900H 20T | 64 GB DDR5 | ~50 GB | API serving / medium inference |
| BD790i | AMD Ryzen 9 7945HX 32T | 96 GB DDR5 | ~80 GB | Research flagship / large models |

---

## Machine Assignments

### Mac M4 Pro — Dev Tier (8–9B only)

Fast turnaround models for development, CLI testing, and API iteration.
**Do not run 32B+ models here.** They fit in RAM but are slow on x86-emulated CPU paths and waste SSD space.

| Model ID | Ollama Tag | Size | Purpose |
|----------|-----------|------|---------|
| `dolphin3` | `dolphin3` | 4.9 GB | Daily driver — fast uncensored, 128K ctx |
| `dolphin3-abliterated` | `huihui_ai/dolphin3-abliterated` | 4.9 GB | Max-unrestricted 8B — abliterated Dolphin3 |
| `qwen3.5-uncensored-9b` | `jaahas/qwen3.5-uncensored:9b` | 7.4 GB | Newest uncensored arch, strong reasoning |
| `qwen2.5-coder-7b-abliterated` | `huihui_ai/qwen2.5-coder-abliterate:7b` | 4.7 GB | Uncensored coding — 86 languages |

**Mac total footprint target: ≤ 22 GB**

---

### MS-01 — Serving Tier (8B–35B range)

Always-on API server. Handles concurrent requests from VS Code, Obsidian, shell scripts.
Serves the OpenAI-compatible API on `:8000`.

| Model ID | Ollama Tag | Size | Purpose | tok/s |
|----------|-----------|------|---------|-------|
| `dolphin3` | `dolphin3` | 4.9 GB | Fast uncensored — low-latency API responses | 15–25 |
| `qwen3.5-uncensored-9b` | `jaahas/qwen3.5-uncensored:9b` | 7.4 GB | Reasoning + multilingual API | 12–20 |
| `qwen2.5-coder-7b-abliterated` | `huihui_ai/qwen2.5-coder-abliterate:7b` | 4.7 GB | Coding completions via API | 18–25 |
| `deepseek-r1:32b` | `deepseek-r1:32b` | 19.9 GB | Chain-of-thought reasoning (non-uncensored) | 3–5 |
| `qwen3.5-uncensored-35b` | `jaahas/qwen3.5-uncensored:35b` | 24.8 GB | Flagship uncensored (slower on MS-01) | 3–5 |

---

### BD790i — Research Flagship (8B–70B range)

Primary research machine. Runs the flagship uncensored model. Has headroom for 70B Q4 (~40 GB).

| Model ID | Ollama Tag | Size | Purpose | tok/s |
|----------|-----------|------|---------|-------|
| `qwen3.5-uncensored-35b` ⭐ | `jaahas/qwen3.5-uncensored:35b` | 24.8 GB | **PRIMARY FLAGSHIP** — research, alignment study | 8–12 |
| `dolphin3-abliterated` | `huihui_ai/dolphin3-abliterated` | 4.9 GB | Fast abliterated — testing & comparison | 40–55 |
| `qwen3.5-uncensored-9b` | `jaahas/qwen3.5-uncensored:9b` | 7.4 GB | Fast uncensored — quick research queries | 35–45 |
| `deepseek-r1:32b` | `deepseek-r1:32b` | 19.9 GB | CoT reasoning benchmark / comparison | 8–12 |
| `dolphin-mixtral` | `dolphin-mixtral` | 26.0 GB | MoE — creative/narrative research | 12–18 |

**Recommended next pull (headroom ~25 GB after flagship):**
```bash
# On BD790i — adds 70B class capability
ollama pull cognitivecomputations/dolphin-2.9.1-llama3-70b  # ~40 GB Q4
```

---

## Ordered Install Sequences

> Execute these in order. Do not skip steps. Verify each pull before proceeding.
> Run `ollama list` after each step to confirm.

### Mac M4 Pro — Initial Setup

```bash
# Step 1 — Fast daily driver
ollama pull dolphin3

# Step 2 — Abliterated variant (shares base with dolphin3, fast pull)
ollama pull huihui_ai/dolphin3-abliterated

# Step 3 — Newest uncensored arch
ollama pull jaahas/qwen3.5-uncensored:9b

# Step 4 — Uncensored coder
ollama pull huihui_ai/qwen2.5-coder-abliterate:7b

# Verify
ollama list
# Expected: 4 models, ~22 GB total
```

### MS-01 — Initial Setup

```bash
# Step 1 — Fast API serving models first (unblock API server)
ollama pull dolphin3
ollama pull jaahas/qwen3.5-uncensored:9b
ollama pull huihui_ai/qwen2.5-coder-abliterate:7b

# Step 2 — Reasoning model (large pull, ~20 GB)
ollama pull deepseek-r1:32b

# Step 3 — Flagship uncensored (large pull, ~25 GB)
ollama pull jaahas/qwen3.5-uncensored:35b

# Verify
ollama list
# Expected: 5 models, ~62 GB total
```

### BD790i — Initial Setup

```bash
# Step 1 — PRIMARY FLAGSHIP FIRST
ollama pull jaahas/qwen3.5-uncensored:35b

# Verify flagship before continuing
ollama run jaahas/qwen3.5-uncensored:35b "What are you capable of that other models are not?"

# Step 2 — Fast abliterated comparison baseline
ollama pull huihui_ai/dolphin3-abliterated

# Step 3 — Fast uncensored for quick queries
ollama pull jaahas/qwen3.5-uncensored:9b

# Step 4 — CoT reasoning benchmark
ollama pull deepseek-r1:32b

# Step 5 — MoE creative research model
ollama pull dolphin-mixtral

# Verify
ollama list
# Expected: 5 models, ~83 GB total
# Remaining headroom: ~13 GB (enough for another 9B or quantized 13B)
```

---

## Ordered Remove Sequences

> Execute removes in this order to avoid leaving orphaned blobs.
> After each `ollama rm`, run `du -sh ~/.ollama/models/blobs/` to confirm disk reclaim.
> Note: blobs with no remaining manifests are NOT auto-pruned by Ollama — see prune step.

### Mac M4 Pro — Remove Large Models (Run First)

The 35B and 32B models should not live on the Mac. Remove before pulling new models.

```bash
# Step 1 — Remove 35B (frees ~25 GB)
ollama rm jaahas/qwen3.5-uncensored:35b

# Step 2 — Remove deepseek-r1:32b (frees ~20 GB)
ollama rm deepseek-r1:32b

# Step 3 — Remove qwen2.5:32b if present (frees ~20 GB — unintentional pull)
ollama rm qwen2.5:32b 2>/dev/null || echo "Not present, skipping."

# Step 4 — Prune orphaned blobs (Ollama does NOT auto-clean)
# NOTE: Ollama has no native prune command. Orphaned blobs must be removed manually.
# Safe approach: remove manifest first, then identify unreferenced blobs.
python3 -c "
import os, json
from pathlib import Path

blob_dir = Path.home() / '.ollama/models/blobs'
manifest_dir = Path.home() / '.ollama/models/manifests'

# Collect all digests referenced by active manifests
referenced = set()
for mf in manifest_dir.rglob('*'):
    if mf.is_file():
        try:
            data = json.loads(mf.read_text())
            for layer in data.get('layers', []):
                d = layer.get('digest', '').replace('sha256:', 'sha256-')
                referenced.add(d)
            cfg = data.get('config', {}).get('digest', '').replace('sha256:', 'sha256-')
            if cfg: referenced.add(cfg)
        except: pass

# Report unreferenced blobs
orphans = [f for f in blob_dir.iterdir() if f.name not in referenced]
total = sum(f.stat().st_size for f in orphans) / 1e9
print(f'Orphaned blobs: {len(orphans)} files, {total:.1f} GB')
for f in orphans: print(f'  {f.name}  {f.stat().st_size/1e9:.2f} GB')
"

# To delete orphans (run only after reviewing the list above):
# python3 -c "
# ... (same script) ...
# for f in orphans: f.unlink(); print(f'Deleted {f.name}')
# "

# Verify disk reclaim
du -sh ~/.ollama/models/blobs/
ollama list
# Expected: 4 models, ~22 GB
```

### MS-01 — Rotate Out Stale Models

```bash
# Remove if dolphin-mixtral was pulled but MS-01 is serving role only
ollama rm dolphin-mixtral 2>/dev/null || echo "Not present."

# Verify
ollama list
```

### BD790i — Full Reset (if needed)

```bash
# Remove all models (nuclear option — run install sequence again after)
ollama list | awk 'NR>1 {print $1}' | xargs -I{} ollama rm {}

# Verify empty
ollama list
du -sh ~/.ollama/models/
```

---

## Full Model Catalog

Complete reference for every model in the registry. Coding agents should update this table when `MODEL_REGISTRY` in `models/download.py` is modified.

### Tier 1 — Daily Drivers (8–9B) · Fast interactive / API serving

| Registry ID | Model Name | Size | Context | Speed MS-01 | Speed BD790i | Primary Purpose |
|-------------|-----------|------|---------|-------------|-------------|-----------------|
| `dolphin3` | Dolphin 3 (Llama 3.1 8B) | 4.9 GB | 128K | 15–25 t/s | 40–55 t/s | Daily uncensored driver, fast responses |
| `dolphin3-abliterated` | Dolphin 3 Abliterated | 4.9 GB | 128K | 15–25 t/s | 40–55 t/s | Maximum unrestricted 8B — refusal neurons surgically removed |
| `qwen3.5-uncensored-9b` | Qwen 3.5 9B Uncensored | 7.4 GB | 128K | 12–20 t/s | 35–45 t/s | Newest uncensored architecture, strong multilingual reasoning |
| `qwen2.5-7b-abliterated` | Qwen 2.5 7B Abliterated | 4.7 GB | 128K | 18–25 t/s | 40–50 t/s | Abliterated reasoning — excellent zero-refusal general model |
| `qwen2.5-coder-7b-abliterated` | Qwen 2.5 Coder 7B Abliterated | 4.7 GB | 128K | 18–25 t/s | 40–50 t/s | Uncensored coding model — 86 languages, zero refusals |
| `llama3.3-8b-abliterated` | Llama 3.3 8B Abliterated | 4.9 GB | 128K | 15–25 t/s | 40–55 t/s | Meta Llama 3.3 with refusal neurons removed, high reasoning |

### Tier 2 — Sweet Spot (13–14B) · Quality/speed balance

| Registry ID | Model Name | Size | Context | Speed MS-01 | Speed BD790i | Primary Purpose |
|-------------|-----------|------|---------|-------------|-------------|-----------------|
| `qwen2.5-14b-abliterated` | Qwen 2.5 14B Abliterated | 9.0 GB | 128K | 8–12 t/s | 20–28 t/s | Best 14B uncensored — reasoning + zero refusals |
| `wizardlm-uncensored-13b` | WizardLM 13B Uncensored | 7.4 GB | 4K | 8–12 t/s | 25–30 t/s | Classic uncensored — proven creative writing (short context) |

### Tier 3 — Power Models (18–35B) · Flagship research range

| Registry ID | Model Name | Size | Context | Speed MS-01 | Speed BD790i | Primary Purpose |
|-------------|-----------|------|---------|-------------|-------------|-----------------|
| `qwen3.5-uncensored-35b` ⭐ | **Qwen 3.5 35B Uncensored** | 24.8 GB | **128K** | 3–5 t/s | **8–12 t/s** | **PRIMARY FLAGSHIP — research, alignment study, adversarial analysis** |
| `dolphin-mixtral` | Dolphin 2.5 Mixtral 8x7B | 26.0 GB | 32K | 5–8 t/s | 12–18 t/s | MoE architecture — activates ~13B/token, creative & narrative research |
| `gemma3-27b-abliterated` | Gemma 3 27B Abliterated | 17.0 GB | 128K | 4–7 t/s | 8–14 t/s | Vision-capable abliterated model — multimodal research |
| `llama3.2-moe-18b` | Llama 3.2 8x3B MoE 18.4B | 12.0 GB | 128K | 8–12 t/s | 15–22 t/s | MoE creative writing champion — fastest large-context uncensored |

### Tier 4 — Specialized (Various) · Purpose-built

| Registry ID | Model Name | Size | Context | Speed MS-01 | Speed BD790i | Primary Purpose |
|-------------|-----------|------|---------|-------------|-------------|-----------------|
| `dolphin-mistral` | Dolphin 2.6 Mistral 7B | 4.1 GB | 32K | 20–28 t/s | 45–55 t/s | Classic fast uncensored — best for coding tasks |
| `nous-hermes2-mixtral` | Nous Hermes 2 Mixtral 8x7B | 26.0 GB | 32K | 5–8 t/s | 12–18 t/s | Excellent instruction following — balanced uncensored |
| `qwen3-8b-hivemind` | Qwen 3 8B Hivemind Abliterated | 5.0 GB | **256K** | 15–22 t/s | 35–45 t/s | **Longest context** uncensored 8B — 256K window for doc analysis |
| `deepseek-r1-32b` | DeepSeek R1 32B | 20.0 GB | 128K | 3–5 t/s | 8–12 t/s | Chain-of-thought reasoning benchmark (not uncensored — comparison only) |
| `deepseek-coder-33b` | DeepSeek Coder 33B | 20.0 GB | 16K | 3–5 t/s | 8–12 t/s | Best-in-class coding — 86 languages (not uncensored) |
| `mythomax` | MythoMax L2 13B | 7.4 GB | 4K | 8–12 t/s | 25–30 t/s | Creative writing and roleplay — narrative generation |
| `dolphin-phi` | Dolphin Phi 2.7B | 1.6 GB | 2K | 40–55 t/s | 70–90 t/s | Smallest uncensored — edge/embedded/low-latency use |

---

## Registry Intrinsic Metadata

Machine-readable fields carried by every `MODEL_REGISTRY` entry (added for the Library fit/recommendation scoring — keep this table in sync with `models/download.py`):

- **quant** — GGUF quantization level (`Q4_K_M` default per repo conventions).
- **params_b** — parameter count in billions (MoE = total, not active).
- **arch_family** — base architecture family (feeds the Weights-architecture detail pane).
- **context_tokens** — context window in tokens (numeric twin of the display `context` string).
- **size_gb** — quantized weight footprint in GB (numeric twin of `size`; load-fit adds 15% KV-cache headroom on top).
- **min_arch** — minimum architecture class, or `None` for run-anywhere GGUF. NVFP4/safetensors entries would declare `gpu_nvidia_single` plus `min_compute_capability` (e.g. `10.0` = Blackwell); such a model is a hard no-fit on CPU-only hosts.
- **task_tags** — Composer task keys (`dfStepTemplates` vocabulary) the model is curated for. Operator overrides live in `data/config/model_tags.json` (runtime, via `PATCH /api/inventory/model/{name}/tags`) and win over these.

| Registry ID | Quant | Params (B) | Arch family | Context (tokens) | Size (GB) | Min arch | Task tags |
|-------------|-------|-----------|-------------|------------------|-----------|----------|-----------|
| `dolphin3` | Q4_K_M | 8.0 | llama | 131072 | 4.9 | — | fast_extract, retriever, uncensored |
| `dolphin3-abliterated` | Q4_K_M | 8.0 | llama | 131072 | 4.9 | — | uncensored, fast_extract |
| `qwen3.5-uncensored-9b` | Q4_K_M | 9.0 | qwen3 | 131072 | 7.4 | — | analyzer, classifier, uncensored |
| `qwen2.5-7b-abliterated` | Q4_K_M | 7.6 | qwen2 | 131072 | 4.7 | — | analyzer, classifier, uncensored |
| `qwen2.5-coder-7b-abliterated` | Q4_K_M | 7.6 | qwen2 | 131072 | 4.7 | — | code_gen, rule_writer, uncensored |
| `llama3.3-8b-abliterated` | Q4_K_M | 8.0 | llama | 131072 | 4.9 | — | analyzer, reviewer, uncensored |
| `qwen2.5-14b-abliterated` | Q4_K_M | 14.7 | qwen2 | 131072 | 9.0 | — | analyzer, planner, validator, uncensored |
| `wizardlm-uncensored-13b` | Q4_K_M | 13.0 | llama | 4096 | 7.4 | — | composer, uncensored |
| `dolphin-mixtral` | Q4_K_M | 46.7 | mixtral | 32768 | 26.0 | — | composer, analyzer, uncensored |
| `qwen3.5-uncensored-35b` ⭐ | Q4_K_M | 35.0 | qwen3 | 131072 | 22.0 | — | analyzer, planner, reviewer, uncensored |
| `gemma3-27b-abliterated` | Q4_K_M | 27.0 | gemma3 | 131072 | 17.0 | — | analyzer, validator, uncensored |
| `llama3.2-moe-18b` | Q4_K_M | 18.4 | llama | 131072 | 12.0 | — | composer, uncensored |
| `dolphin-mistral` | Q4_K_M | 7.0 | mistral | 32768 | 4.1 | — | code_gen, fast_extract, uncensored |
| `nous-hermes2-mixtral` | Q4_K_M | 46.7 | mixtral | 32768 | 26.0 | — | composer, validator, uncensored |
| `qwen3-8b-hivemind` | Q4_K_M | 8.2 | qwen3 | 262144 | 5.0 | — | retriever, analyzer, uncensored |
| `deepseek-r1-32b` | Q4_K_M | 32.0 | qwen2 | 131072 | 20.0 | — | planner, reviewer, decision |
| `deepseek-coder-33b` | Q4_K_M | 33.0 | llama | 16384 | 20.0 | — | code_gen, rule_writer |
| `mythomax` | Q4_K_M | 13.0 | llama | 4096 | 7.4 | — | composer |
| `dolphin-phi` | Q4_0 | 2.7 | phi2 | 2048 | 1.6 | — | fast_extract, uncensored |

Curated per-arch-class performance expectations (tok/s per size class for Blackwell NVFP4 / Apple unified / x86 CPU), VRAM notes, and per-intent configs ship in `api/config/model_meta.json`, surfaced under the `model_meta` key of `GET /api/inventory/enrichment`.

---

## Model Selection Decision Tree

```
Need uncensored output?
├── YES
│   ├── Need research-grade / no restrictions at all?
│   │   └── → qwen3.5-uncensored:35b (flagship)  [BD790i]
│   ├── Need fast interactive response?
│   │   └── → dolphin3-abliterated or qwen3.5:9b  [Mac/MS-01]
│   ├── Need long context (>128K)?
│   │   └── → qwen3-8b-hivemind (256K)  [any machine]
│   ├── Need coding specifically?
│   │   └── → qwen2.5-coder-7b-abliterated  [Mac/MS-01]
│   └── Need creative/narrative generation?
│       └── → dolphin-mixtral or llama3.2-moe-18b  [BD790i]
└── NO (reasoning/coding benchmark only)
    ├── Best coding?   → deepseek-coder:33b
    └── Best CoT?      → deepseek-r1:32b
```

---

## Currently Installed (as of 2026-03-26)

**Mac M4 Pro** (target state — after running Mac remove sequence):

| Model | Size | Status |
|-------|------|--------|
| `dolphin3` | 4.9 GB | ✓ Keep |
| `huihui_ai/dolphin3-abliterated` | 4.9 GB | ✓ Keep |
| `jaahas/qwen3.5-uncensored:9b` | 7.4 GB | ✓ Keep |
| `huihui_ai/qwen2.5-coder-abliterate:7b` | 4.7 GB | ✓ Keep |
| `jaahas/qwen3.5-uncensored:35b` | 24.8 GB | ✗ Remove → BD790i |
| `deepseek-r1:32b` | 19.9 GB | ✗ Remove → BD790i |
| `qwen2.5:32b` | 19.9 GB | ✗ Remove (evaluate need) |

**BD790i / MS-01** (target state — after running install sequences above):

| Model | Size | Machine |
|-------|------|---------|
| `jaahas/qwen3.5-uncensored:35b` ⭐ | 24.8 GB | BD790i primary, MS-01 secondary |
| `deepseek-r1:32b` | 19.9 GB | Both |
| `dolphin3` | 4.9 GB | Both |
| `jaahas/qwen3.5-uncensored:9b` | 7.4 GB | Both |
| `huihui_ai/qwen2.5-coder-abliterate:7b` | 4.7 GB | Both |
| `dolphin-mixtral` | 26.0 GB | BD790i only |

---

## Coding Agent Instructions

If you are a coding agent operating on this repository:

1. **This file is the single source of truth** for model operations. Do not make model decisions based on `docs/historical/PROJECT_PLAN.md` (outdated hardware specs) or `README.md`.

2. **Before any install/remove operation**, run `ollama list` and compare against the target state tables above.

3. **Execute install sequences top-to-bottom** — order matters because early models unblock the API server while large pulls complete.

4. **After removes**, always run the orphaned blob detection script in the Mac remove sequence to recover disk. Ollama does not auto-prune blobs.

5. **Update `models/download.py` `MODEL_REGISTRY`** when adding new models — keep `"installed": True` accurate per machine context.

6. **Update the "Currently Installed" table** at the bottom of this file after any operation.

7. **Never pull 32B+ models on the Mac** unless explicitly instructed by the user with a clear one-off reason.

8. **Flagship is non-negotiable**: `jaahas/qwen3.5-uncensored:35b` must always be present on BD790i. If it is missing, pull it first before any other operation.
