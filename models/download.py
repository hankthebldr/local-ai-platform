#!/usr/bin/env python3
"""
Local AI Platform - Model Download Manager
Download models from Ollama, Hugging Face, and other sources
"""

import argparse
import os
import sys
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.panel import Panel
import subprocess
import json

console = Console()

# ── Hardware Profiles ──────────────────────────────────────────────
# Speed estimates are per-profile. Select with --hardware flag.
HARDWARE_PROFILES = {
    "ms01": {
        "name": "Minisforum MS-01",
        "cpu": "Intel i9-13900H (6P+8E/20T, 5.4GHz)",
        "threads": 20,
        "ram_gb": 64,
        "max_model_ram_gb": 50,  # Leave ~14GB for OS + Ollama overhead
        "gpu": "None (iGPU only, PCIe x8 slot for LP GPU)",
        "notes": "CPU-only inference. DDR5-5200 dual-channel. 3x NVMe. 2x 10GbE SFP+.",
    },
    "bd790i": {
        "name": "ASRock BD790i (Ryzen 9 7945HX)",
        "cpu": "AMD Ryzen 9 7945HX (16C/32T, 5.4GHz)",
        "threads": 32,
        "ram_gb": 96,
        "max_model_ram_gb": 80,  # Leave ~16GB for OS
        "gpu": "None (iGPU, limited ROCm)",
        "notes": "CPU-only inference. DDR5-5600 dual-channel. 60% more threads than MS-01.",
    },
}

# Default profile (set via --hardware flag or HARDWARE_PROFILE env var)
_hw_key = os.getenv("HARDWARE_PROFILE", "ms01")
HARDWARE_PROFILE = HARDWARE_PROFILES.get(_hw_key, HARDWARE_PROFILES["ms01"])

# Model registry with sources
MODEL_REGISTRY = {
    # ═══════════════════════════════════════════════════════════════
    # Tier 1: Daily Drivers (8B class — fast interactive chat)
    # MS-01: ~15-25 tok/s | BD790i: ~40-55 tok/s
    # ═══════════════════════════════════════════════════════════════
    "dolphin3": {
        "name": "Dolphin 3 (Llama 3.1 8B)",
        "ollama": "dolphin3",
        "huggingface": "cognitivecomputations/Dolphin3.0-Llama3.1-8B",
        "size": "4.9GB",
        "speed": {"ms01": "15-25 tok/s", "bd790i": "40-55 tok/s"},
        "context": "128K",
        "description": "Latest Dolphin, 128K context, proven uncensored",
        "tags": ["uncensored", "fast", "reasoning", "128k-context", "ms01-recommended"],
        "installed": True,
    },
    "dolphin3-abliterated": {
        "name": "Dolphin 3 Abliterated (Llama 3.1 8B)",
        "ollama": "huihui_ai/dolphin3-abliterated",
        "size": "4.9GB",
        "speed": {"ms01": "15-25 tok/s", "bd790i": "40-55 tok/s"},
        "context": "128K",
        "description": "Dolphin3 with refusal neurons surgically removed — most unrestricted 8B",
        "tags": ["uncensored", "abliterated", "fast", "ms01-recommended"],
    },
    "qwen3.5-uncensored-9b": {
        "name": "Qwen 3.5 9B Uncensored",
        "ollama": "jaahas/qwen3.5-uncensored:9b",
        "huggingface": "jaahas/Qwen3.5-9B-Uncensored",
        "size": "7.4GB",
        "speed": {"ms01": "12-20 tok/s", "bd790i": "35-45 tok/s"},
        "context": "128K",
        "description": "Newest architecture, strong reasoning, multilingual",
        "tags": ["uncensored", "reasoning", "multilingual", "2026", "ms01-recommended"],
        "installed": True,
    },
    "qwen2.5-7b-abliterated": {
        "name": "Qwen 2.5 7B Abliterated",
        "ollama": "huihui_ai/qwen2.5-abliterated:7b",
        "size": "4.7GB",
        "speed": {"ms01": "18-25 tok/s", "bd790i": "40-50 tok/s"},
        "context": "128K",
        "description": "Qwen 2.5 with abliteration — excellent reasoning, zero refusals",
        "tags": ["uncensored", "abliterated", "reasoning", "ms01-recommended"],
    },
    "qwen2.5-coder-7b-abliterated": {
        "name": "Qwen 2.5 Coder 7B Abliterated",
        "ollama": "huihui_ai/qwen2.5-coder-abliterate:7b",
        "size": "4.7GB",
        "speed": {"ms01": "18-25 tok/s", "bd790i": "40-50 tok/s"},
        "context": "128K",
        "description": "Best uncensored coding model at 7B — 86 languages",
        "tags": ["uncensored", "abliterated", "coding", "ms01-recommended"],
    },
    "llama3.3-8b-abliterated": {
        "name": "Llama 3.3 8B Abliterated",
        "gguf": "mradermacher/Llama3.3-8B-Instruct-Thinking-Heretic-Uncensored-Claude-4.5-Opus-High-Reasoning-i1-GGUF",
        "size": "4.9GB",
        "speed": {"ms01": "15-25 tok/s", "bd790i": "40-55 tok/s"},
        "context": "128K",
        "description": "Meta Llama 3.3 with refusal neurons removed, high reasoning",
        "tags": ["uncensored", "abliterated", "reasoning", "2026"],
    },
    # ═══════════════════════════════════════════════════════════════
    # Tier 2: Quality Sweet Spot (13B-14B — best quality/speed balance)
    # MS-01: ~8-15 tok/s | BD790i: ~20-30 tok/s
    # ═══════════════════════════════════════════════════════════════
    "qwen2.5-14b-abliterated": {
        "name": "Qwen 2.5 14B Abliterated",
        "ollama": "huihui_ai/qwen2.5-abliterated:14b",
        "size": "9GB",
        "speed": {"ms01": "8-12 tok/s", "bd790i": "20-28 tok/s"},
        "context": "128K",
        "description": "Sweet spot: strong reasoning + abliterated, fits easily on MS-01",
        "tags": ["uncensored", "abliterated", "reasoning", "ms01-recommended"],
    },
    "wizardlm-uncensored-13b": {
        "name": "WizardLM-13B-Uncensored",
        "ollama": "wizardlm-uncensored:13b",
        "huggingface": "ehartford/WizardLM-13B-Uncensored",
        "gguf": "TheBloke/WizardLM-13B-Uncensored-GGUF",
        "size": "7.4GB",
        "speed": {"ms01": "8-12 tok/s", "bd790i": "25-30 tok/s"},
        "context": "4K",
        "description": "Classic uncensored, proven for creative writing",
        "tags": ["uncensored", "creative", "classic"],
    },
    # ═══════════════════════════════════════════════════════════════
    # Tier 3: Power Models (26B-35B — slower but impressive quality)
    # MS-01: ~4-8 tok/s | BD790i: ~8-14 tok/s
    # ═══════════════════════════════════════════════════════════════
    "dolphin-mixtral": {
        "name": "Dolphin 2.5 Mixtral 8x7B",
        "ollama": "dolphin-mixtral",
        "huggingface": "cognitivecomputations/dolphin-2.5-mixtral-8x7b",
        "gguf": "TheBloke/dolphin-2.5-mixtral-8x7b-GGUF",
        "size": "26GB",
        "speed": {"ms01": "5-8 tok/s", "bd790i": "12-18 tok/s"},
        "context": "32K",
        "description": "MoE powerhouse — activates ~13B per token, faster than dense 26B",
        "tags": ["uncensored", "reasoning", "creative", "moe", "ms01-fits"],
    },
    "qwen3.5-uncensored-35b": {
        "name": "Qwen 3.5 35B Uncensored",
        "ollama": "jaahas/qwen3.5-uncensored:35b",
        "size": "22GB",
        "speed": {"ms01": "3-5 tok/s", "bd790i": "8-12 tok/s"},
        "context": "128K",
        "description": "Largest uncensored Qwen — fits on MS-01, optimal on BD790i",
        "tags": ["uncensored", "large", "reasoning", "2026", "ms01-fits"],
    },
    "gemma3-27b-abliterated": {
        "name": "Gemma 3 27B Abliterated",
        "gguf": "mradermacher/Gemma3-27B-it-vl-Polaris-HI16-Heretic-Uncensored-INSTRUCT-i1-GGUF",
        "size": "17GB",
        "speed": {"ms01": "4-7 tok/s", "bd790i": "8-14 tok/s"},
        "context": "128K",
        "description": "Google Gemma 3, vision-capable, abliterated",
        "tags": ["uncensored", "abliterated", "vision", "multimodal", "2026", "ms01-fits"],
    },
    "llama3.2-moe-18b": {
        "name": "Llama 3.2 8x3B MOE Dark Champion 18.4B",
        "gguf": "DavidAU/Llama-3.2-8X3B-MOE-Dark-Champion-Instruct-uncensored-abliterated-18.4B-GGUF",
        "size": "12GB",
        "speed": {"ms01": "8-12 tok/s", "bd790i": "15-22 tok/s"},
        "context": "128K",
        "description": "MoE architecture, creative writing champion",
        "tags": ["uncensored", "abliterated", "moe", "creative", "ms01-fits"],
    },
    # ═══════════════════════════════════════════════════════════════
    # Tier 4: Specialized (Coding, Creative, Niche)
    # ═══════════════════════════════════════════════════════════════
    "dolphin-mistral": {
        "name": "Dolphin 2.6 Mistral 7B",
        "ollama": "dolphin-mistral",
        "huggingface": "cognitivecomputations/dolphin-2.6-mistral-7b",
        "gguf": "TheBloke/dolphin-2.6-mistral-7B-GGUF",
        "size": "4.1GB",
        "speed": {"ms01": "20-28 tok/s", "bd790i": "45-55 tok/s"},
        "context": "32K",
        "description": "Classic fast uncensored, great for coding",
        "tags": ["uncensored", "fast", "coding", "classic"],
    },
    "nous-hermes2-mixtral": {
        "name": "Nous Hermes 2 Mixtral 8x7B",
        "ollama": "nous-hermes2-mixtral",
        "huggingface": "NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO",
        "gguf": "TheBloke/Nous-Hermes-2-Mixtral-8x7B-DPO-GGUF",
        "size": "26GB",
        "speed": {"ms01": "5-8 tok/s", "bd790i": "12-18 tok/s"},
        "context": "32K",
        "description": "Excellent instruction following, balanced",
        "tags": ["uncensored", "balanced", "instruction", "ms01-fits"],
    },
    "qwen3-8b-hivemind": {
        "name": "Qwen 3 8B Hivemind Abliterated",
        "gguf": "DavidAU/Qwen3-8B-Hivemind-Instruct-Heretic-Abliterated-Uncensored-NEO-Imatrix-GGUF",
        "size": "5GB",
        "speed": {"ms01": "15-22 tok/s", "bd790i": "35-45 tok/s"},
        "context": "256K",
        "description": "256K context, heretic abliterated, all-purpose",
        "tags": ["uncensored", "abliterated", "256k-context", "2026"],
    },
    "deepseek-r1-32b": {
        "name": "DeepSeek R1 32B",
        "ollama": "deepseek-r1:32b",
        "size": "20GB",
        "speed": {"ms01": "3-5 tok/s", "bd790i": "8-12 tok/s"},
        "context": "128K",
        "description": "Chain-of-thought reasoning powerhouse (not uncensored but very capable)",
        "tags": ["reasoning", "chain-of-thought", "ms01-fits"],
    },
    "deepseek-coder-33b": {
        "name": "DeepSeek Coder 33B",
        "ollama": "deepseek-coder:33b",
        "huggingface": "deepseek-ai/deepseek-coder-33b-instruct",
        "gguf": "TheBloke/deepseek-coder-33B-instruct-GGUF",
        "size": "20GB",
        "speed": {"ms01": "3-5 tok/s", "bd790i": "8-12 tok/s"},
        "context": "16K",
        "description": "Best coding model, supports 86 languages",
        "tags": ["coding", "programming", "technical", "ms01-fits"],
    },
    "mythomax": {
        "name": "MythoMax L2 13B",
        "ollama": "mythomax",
        "huggingface": "Gryphe/MythoMax-L2-13b",
        "gguf": "TheBloke/MythoMax-L2-13B-GGUF",
        "size": "7.4GB",
        "speed": {"ms01": "8-12 tok/s", "bd790i": "25-30 tok/s"},
        "context": "4K",
        "description": "Best for creative writing and roleplay",
        "tags": ["creative", "roleplay", "storytelling"],
    },
    "dolphin-phi": {
        "name": "Dolphin Phi 2.7B",
        "ollama": "dolphin-phi",
        "size": "1.6GB",
        "speed": {"ms01": "40-55 tok/s", "bd790i": "70-90 tok/s"},
        "context": "2K",
        "description": "Smallest uncensored, edge/embedded use",
        "tags": ["uncensored", "tiny", "fast", "edge"],
    },
}


def _get_speed(info, hw_key=None):
    """Get speed string for the active hardware profile."""
    speed = info.get("speed", "—")
    if isinstance(speed, dict):
        key = hw_key or _hw_key
        return speed.get(key, speed.get("ms01", next(iter(speed.values()))))
    return speed


def list_models(filter_tag=None):
    """List available models"""
    hw = HARDWARE_PROFILE
    table = Table(
        title=f"Available Models — {hw['name']}",
        show_header=True, header_style="bold cyan"
    )
    table.add_column("ID", style="green")
    table.add_column("Name", style="cyan")
    table.add_column("Size")
    table.add_column(f"Speed ({_hw_key})")
    table.add_column("Ctx", style="dim")
    table.add_column("Description")
    table.add_column("", style="green")  # installed indicator

    for model_id, info in MODEL_REGISTRY.items():
        if filter_tag and filter_tag not in info.get("tags", []):
            continue
        installed = "✓" if info.get("installed") else ""
        table.add_row(
            model_id,
            info["name"],
            info["size"],
            _get_speed(info),
            info.get("context", "—"),
            info["description"],
            installed,
        )

    console.print(table)
    console.print(f"\n[dim]Total models: {len(MODEL_REGISTRY)}[/dim]")
    console.print(f"[dim]Hardware: {hw['cpu']} / {hw['ram_gb']}GB RAM "
                  f"(max model: {hw['max_model_ram_gb']}GB)[/dim]")
    console.print(f"[dim]Profile: {_hw_key} (set HARDWARE_PROFILE env or --hardware flag)[/dim]")
    console.print("[yellow]Use: python models/download.py <model-id> to download[/yellow]")


def download_ollama(model_id, info):
    """Download model via Ollama"""
    console.print(Panel.fit(
        f"[bold cyan]Downloading via Ollama[/bold cyan]\n"
        f"Model: {info['name']}\n"
        f"Size: {info['size']}\n"
        f"This may take a while...",
        border_style="cyan"
    ))

    try:
        # Run ollama pull
        cmd = ["ollama", "pull", info["ollama"]]
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )

        for line in process.stdout:
            console.print(line.strip())

        process.wait()

        if process.returncode == 0:
            console.print(f"\n[green]✓ Successfully downloaded {info['name']}[/green]")
            console.print(f"\n[yellow]Test it with:[/yellow]")
            console.print(f"  ollama run {info['ollama']}")
            console.print(f"  python cli/chat.py --model {info['ollama']}")
            return True
        else:
            console.print(f"[red]✗ Download failed[/red]")
            return False

    except FileNotFoundError:
        console.print("[red]✗ Ollama not found. Install it first:[/red]")
        console.print("  curl -fsSL https://ollama.ai/install.sh | sh")
        return False
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        return False


def download_huggingface(model_id, info, model_type="gguf"):
    """Download model from Hugging Face"""
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
    except ImportError:
        console.print("[red]✗ huggingface_hub not installed[/red]")
        console.print("[yellow]Install it with:[/yellow]")
        console.print("  pip install huggingface_hub")
        return False

    hf_repo = info.get(model_type, info.get("huggingface"))

    console.print(Panel.fit(
        f"[bold cyan]Downloading from Hugging Face[/bold cyan]\n"
        f"Repository: {hf_repo}\n"
        f"This may take a while...",
        border_style="cyan"
    ))

    try:
        # Create models directory
        models_dir = Path("data/models") / model_id
        models_dir.mkdir(parents=True, exist_ok=True)

        # Download model
        console.print(f"[dim]Downloading to {models_dir}...[/dim]")

        if model_type == "gguf":
            # Download specific GGUF file
            files = [
                f"{model_id}.Q4_K_M.gguf",  # Try Q4 first
                f"{model_id}.Q5_K_M.gguf",
                f"{model_id}.gguf"
            ]

            for filename in files:
                try:
                    filepath = hf_hub_download(
                        repo_id=hf_repo,
                        filename=filename,
                        local_dir=models_dir,
                        local_dir_use_symlinks=False
                    )
                    console.print(f"[green]✓ Downloaded {filename}[/green]")
                    console.print(f"[yellow]Location: {filepath}[/yellow]")
                    return True
                except:
                    continue

            console.print("[yellow]Downloading full repository...[/yellow]")

        # Download full repository
        snapshot_download(
            repo_id=hf_repo,
            local_dir=models_dir,
            local_dir_use_symlinks=False
        )

        console.print(f"[green]✓ Successfully downloaded to {models_dir}[/green]")
        return True

    except Exception as e:
        console.print(f"[red]✗ Error downloading from Hugging Face: {e}[/red]")
        return False


def show_model_info(model_id):
    """Show detailed model information"""
    if model_id not in MODEL_REGISTRY:
        console.print(f"[red]Model '{model_id}' not found in registry[/red]")
        return

    info = MODEL_REGISTRY[model_id]

    speed = info.get("speed", "—")
    if isinstance(speed, dict):
        speed_lines = "\n".join(f"    {k}: {v}" for k, v in speed.items())
        speed_str = f"\n{speed_lines}"
    else:
        speed_str = speed

    console.print(Panel.fit(
        f"[bold cyan]{info['name']}[/bold cyan]\n\n"
        f"[bold]Size:[/bold] {info['size']}\n"
        f"[bold]Speed:[/bold] {speed_str}\n"
        f"[bold]Context:[/bold] {info.get('context', '—')}\n"
        f"[bold]Description:[/bold] {info['description']}\n\n"
        f"[bold]Tags:[/bold] {', '.join(info.get('tags', []))}\n\n"
        f"[bold]Sources:[/bold]\n"
        f"  • Ollama: {info.get('ollama', 'N/A')}\n"
        f"  • Hugging Face: {info.get('huggingface', 'N/A')}\n"
        f"  • GGUF: {info.get('gguf', 'N/A')}",
        title=f"Model Info: {model_id}",
        border_style="cyan"
    ))


def show_status():
    """Compare installed Ollama models against registry"""
    console.print(Panel.fit(
        "[bold bright_cyan]Model Status — Ollama vs Registry[/bold bright_cyan]",
        border_style="bright_cyan"
    ))

    # Get installed models from Ollama via API (doesn't depend on CLI path)
    import requests as req
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    installed = {}
    try:
        resp = req.get(f"{ollama_host}/api/tags", timeout=10)
        resp.raise_for_status()
        for model in resp.json().get("models", []):
            name = model.get("name", "")
            size_bytes = model.get("size", 0)
            size_gb = f"{size_bytes / (1024**3):.1f} GB" if size_bytes else "?"
            installed[name] = {"size": size_gb}
    except Exception as e:
        console.print(f"[red]Cannot connect to Ollama at {ollama_host}: {e}[/red]")
        return

    table = Table(title="Model Inventory", show_header=True, header_style="bold cyan")
    table.add_column("Status", style="bold", width=10)
    table.add_column("Model", style="cyan")
    table.add_column("Ollama Name", style="dim")
    table.add_column("Size")
    table.add_column("Speed")
    table.add_column("Tags", style="dim")

    # Show registry models with install status
    for model_id, info in MODEL_REGISTRY.items():
        ollama_name = info.get("ollama", "")
        is_installed = any(
            ollama_name in inst_name or inst_name.startswith(ollama_name)
            for inst_name in installed
        )
        status = "[green]✓ Installed[/green]" if is_installed else "[dim]Available[/dim]"
        tags = ", ".join(info.get("tags", [])[:3])
        table.add_row(status, info["name"], ollama_name, info["size"], _get_speed(info), tags)

    # Show installed models NOT in registry
    registry_ollama_names = {info.get("ollama", "") for info in MODEL_REGISTRY.values()}
    for name, details in installed.items():
        if not any(name.startswith(reg) or reg in name for reg in registry_ollama_names if reg):
            table.add_row(
                "[yellow]⚬ Extra[/yellow]", name, name,
                details.get("size", "?"), "—", "not in registry"
            )

    console.print(table)
    console.print(f"\n[dim]Installed: {len(installed)} | Registry: {len(MODEL_REGISTRY)} | "
                  f"Hardware: {HARDWARE_PROFILE['cpu']} / {HARDWARE_PROFILE['ram_gb']}GB RAM[/dim]")


def main():
    parser = argparse.ArgumentParser(description="Download and manage LLM models")
    parser.add_argument("model_id", nargs="?", help="Model ID to download")
    parser.add_argument("--list", "-l", action="store_true", help="List available models")
    parser.add_argument("--status", action="store_true", help="Compare installed vs registry models")
    parser.add_argument("--info", "-i", metavar="MODEL", help="Show model information")
    parser.add_argument("--source", "-s", choices=["ollama", "huggingface", "gguf"],
                       default="ollama", help="Download source (default: ollama)")
    parser.add_argument("--filter", "-f", metavar="TAG", help="Filter models by tag")
    parser.add_argument("--hardware", metavar="PROFILE",
                       choices=list(HARDWARE_PROFILES.keys()),
                       help=f"Hardware profile ({', '.join(HARDWARE_PROFILES.keys())})")

    args = parser.parse_args()

    # Override hardware profile if specified
    global _hw_key, HARDWARE_PROFILE
    if args.hardware:
        _hw_key = args.hardware
        HARDWARE_PROFILE = HARDWARE_PROFILES[_hw_key]

    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    if args.list:
        list_models(filter_tag=args.filter)
        return

    if args.status:
        show_status()
        return

    if args.info:
        show_model_info(args.info)
        return

    if not args.model_id:
        console.print("[yellow]Usage: python models/download.py <model-id>[/yellow]")
        console.print("[dim]Run with --list to see available models[/dim]")
        return

    model_id = args.model_id

    if model_id not in MODEL_REGISTRY:
        console.print(f"[red]Model '{model_id}' not found in registry[/red]")
        console.print("[yellow]Run with --list to see available models[/yellow]")
        return

    info = MODEL_REGISTRY[model_id]

    # Show model info
    show_model_info(model_id)
    console.print()

    # Download
    if args.source == "ollama":
        success = download_ollama(model_id, info)
    elif args.source in ["huggingface", "gguf"]:
        success = download_huggingface(model_id, info, model_type=args.source)

    if success:
        console.print("\n[green]✓ Download complete![/green]")
    else:
        console.print("\n[red]✗ Download failed[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
