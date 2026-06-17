# Local inference engine landscape — mid-2026 (deep-research report)

> **Feeds:** 1.5.x pluggable inference engines (vLLM + llama.cpp parity behind the OpenAI-compatible surface).
> **Provenance:** deep-research workflow run `wf_2d8a96db-968` (2026-06-12). 5 search angles → 21 sources → 96 extracted claims → 25 verified (3-vote adversarial) → 7 confirmed. Synthesis + ~8 verification votes lost to a session-limit outage; see [RESEARCH_LOG.md](./RESEARCH_LOG.md) for resume state and the unverified-claim backlog.

## Bottom line

The data supports a **per-arch engine strategy**, not a per-engine race. Ollama+MLX is the confirmed strong path on Apple silicon, vLLM's CPU backend is explicitly second-class and cannot read the GGUF catalog, and on a single consumer GPU llama.cpp is competitive with vLLM at concurrency 1 — vLLM only earns its complexity under parallel load.

## Verified findings (survived 3-vote adversarial check)

- **Apple silicon, Ollama 0.19+ MLX backend** — Ollama's own March 2026 benchmark (Qwen3.5-35B-A3B) showed the MLX backend at NVFP4 hitting **1810 t/s prefill / 112 t/s decode** vs 1154/58 for the prior backend at Q4_K_M — ~1.6× prefill, ~1.9× decode ([ollama.com/blog/mlx](https://ollama.com/blog/mlx)). Vote 3-0.
  - Caveat: the stronger claim that MLX *replaced* the macOS backend was **refuted 0-3** — it is an additional/preview backend. The benchmark also crosses quant formats (NVFP4 vs Q4_K_M), which flatters MLX. The repo's Ollama 0.23.4 pin postdates 0.19, so the backend is within the pinned floor.
- **Ollama long-context weakness** — automatic prefix reuse with LRU caching works (~23% latency cut, 80%+ hit rates in iterative use), but no paged attention → steep degradation past 32k tokens, ~56GB RSS at 100k tokens, TTFT >50s ([arXiv 2511.05502](https://arxiv.org/pdf/2511.05502)). Vote 3-0. Tested on Ollama v0.10.1 — **re-validate on 0.23.4** before treating as current. Directly relevant to `single_model_pseudo_parallel`: the prompt cache helps, the context ceiling hurts.
- **vLLM on x86 CPU is not a real candidate** — vLLM's own docs call the x86 backend "basic model inferencing and serving," FP32/FP16/BF16 only, prebuilt wheels only since 0.17.0 ([docs.vllm.ai CPU install](https://docs.vllm.ai/en/stable/getting_started/installation/cpu/)). Vote 2-1.
- **vLLM CPU quantization excludes GGUF K-quants** — AWQ/GPTQ (x86) + compressed-tensor INT8 W8A8 only. MS-01 parity would mean re-sourcing the entire Q4_K_M catalog in a second format. Vote 3-0.
- **vLLM CPU lagged the 2025 V0→V1 engine transition** — Intel CPU/XPU support was still on the "planned for migration" list at the May 2025 deprecation RFC ([vllm#18571](https://github.com/vllm-project/vllm/issues/18571)). Vote 3-0.
- **Single consumer GPU, single user: llama.cpp ≈ vLLM** — on an RTX 4090 (Qwen 2.5 3B, FP16 vs BF16), llama.cpp completed single requests in 93.6–100.2% of vLLM's time; at 16 parallel requests, 99.2–125.6% ([llama.cpp#15180](https://github.com/ggml-org/llama.cpp/discussions/15180)). Vote 3-0. vLLM's advantage is concurrency, not kernel speed.
- **Ollama concurrency is the weak spot** vs vLLM/TGI ([sesamedisk comparison](https://sesamedisk.com/local-inference-engines-2026-comparison/)). Vote 2-0, blog-grade source — directionally consistent with the rest.

## Killed in verification (do not quote)

These failed the adversarial check (0-3):

- "Ollama on Apple Silicon now runs on MLX, replacing its previous backend" (MLX is preview/additional, not a replacement)
- Mac Studio M2 Ultra "Ollama 5-10× slower than MLX/MLC" throughput table
- "llama.cpp processes one sequence per instance / has no continuous batching"
- "llama-swap is required for llama.cpp/vLLM model-swap parity"
- vLLM V0-removal timeline specifics (v0.9.0 freeze → v0.11.0 deletion)
- "Two LLMs on one GPU broken in vLLM V1 as of May 2025"
- "MLX-LM 20-40% faster than llama.cpp on Apple silicon"

## Unverified (verifiers died on session limit — plausible, confirm before designing against)

- vLLM pre-allocates ~90% of VRAM by default (`gpu_memory_utilization=0.9`) → poor fit for multi-model swap on one 24GB GPU
- vLLM has no production-grade native GGUF path (experimental only)
- HF Text Generation Inference (TGI) archived / maintenance-mode March 2026
- RTX 3090 single-user t/s table (llama.cpp 85-95 > vLLM BF16 75-85 > Ollama 72-80) and the 8-16-user inversion (vLLM 420-820 t/s aggregate)
- M4 Pro Q4_K_M throughput figures (7B ≈ 60-80 t/s, 13B ≈ 35-50 t/s)
- vLLM macOS support experimental, source-build only, no Metal acceleration

## Per-host recommendation

| Host | Engine | Why |
|---|---|---|
| Mac M4 Pro 48GB | **Ollama (MLX backend)** | Confirmed ~2× decode gain; zero parity work; vLLM has no credible macOS path |
| MS-01 64GB CPU | **Ollama / llama.cpp (GGUF)** | vLLM CPU is second-class and can't use the catalog format |
| BD790i 24GB Blackwell | **Ollama/llama.cpp default, vLLM opt-in** | Even at concurrency 1; vLLM pays off only when DAG `kind: parallel` fan-out generates real concurrent requests against one model |

**Architectural consequence:** the 1.3.0 parallel dispatch is precisely what creates vLLM's winning condition. A sensible 1.5.x seam is *engine-per-deployment-mode* — let the compiler route `kind: parallel` steps to a vLLM-backed model on the GPU host and everything else to Ollama, rather than making engine a host-global choice.

## Sources (21 fetched; quality as graded by the harness)

Primary: ollama.com/blog/mlx · arxiv.org/pdf/2511.05502 · docs.vllm.ai CPU install · github.com/ggml-org/llama.cpp/discussions/15180 · github.com/mostlygeek/llama-swap · github.com/vllm-project/vllm/issues/18571
Forum: news.ycombinator.com/item?id=44869466 · github.com/ollama/ollama/issues/15601
Blog (use with care): sesamedisk.com · contracollective.com · quantizelab.dev · bizon-tech.com · explore.n1n.ai · allenkuo.medium.com · dev.to (×2) · yage.ai · pub.towardsai.net · particula.tech · blog.gopenai.com
Rejected as unreliable: xhinker.medium.com
