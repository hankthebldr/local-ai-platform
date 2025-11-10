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

# Model registry with sources
MODEL_REGISTRY = {
    # Tier 1: Best Uncensored Models
    "dolphin-mixtral": {
        "name": "Dolphin 2.5 Mixtral 8x7B",
        "ollama": "dolphin-mixtral",
        "huggingface": "cognitivecomputations/dolphin-2.5-mixtral-8x7b",
        "gguf": "TheBloke/dolphin-2.5-mixtral-8x7b-GGUF",
        "size": "26GB",
        "speed": "15-20 tok/s",
        "description": "Best uncensored model, excellent reasoning",
        "tags": ["uncensored", "reasoning", "creative"]
    },
    "dolphin-mistral": {
        "name": "Dolphin 2.6 Mistral 7B",
        "ollama": "dolphin-mistral",
        "huggingface": "cognitivecomputations/dolphin-2.6-mistral-7b",
        "gguf": "TheBloke/dolphin-2.6-mistral-7B-GGUF",
        "size": "4.1GB",
        "speed": "45-55 tok/s",
        "description": "Fastest uncensored model, great for coding",
        "tags": ["uncensored", "fast", "coding"]
    },
    "nous-hermes2-mixtral": {
        "name": "Nous Hermes 2 Mixtral 8x7B",
        "ollama": "nous-hermes2-mixtral",
        "huggingface": "NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO",
        "gguf": "TheBloke/Nous-Hermes-2-Mixtral-8x7B-DPO-GGUF",
        "size": "26GB",
        "speed": "15-20 tok/s",
        "description": "Excellent instruction following, balanced",
        "tags": ["uncensored", "balanced", "instruction"]
    },
    "yi-34b": {
        "name": "Yi-34B-200K",
        "ollama": "yi:34b-chat",
        "huggingface": "01-ai/Yi-34B-200K",
        "gguf": "TheBloke/Yi-34B-200K-GGUF",
        "size": "20GB",
        "speed": "10-12 tok/s",
        "description": "Massive 200K context, excellent for long documents",
        "tags": ["uncensored", "long-context", "multilingual"]
    },
    # Tier 2: High Performance
    "openhermes": {
        "name": "OpenHermes 2.5 Mistral 7B",
        "ollama": "openhermes",
        "huggingface": "teknium/OpenHermes-2.5-Mistral-7B",
        "gguf": "TheBloke/OpenHermes-2.5-Mistral-7B-GGUF",
        "size": "4.1GB",
        "speed": "45-50 tok/s",
        "description": "Excellent instruction following, coding",
        "tags": ["instruction", "coding", "function-calling"]
    },
    "neural-chat": {
        "name": "Neural-Chat 7B v3.3",
        "ollama": "neural-chat",
        "huggingface": "Intel/neural-chat-7b-v3-3",
        "gguf": "TheBloke/neural-chat-7B-v3-3-GGUF",
        "size": "4.1GB",
        "speed": "45-50 tok/s",
        "description": "CPU-optimized, strong conversations",
        "tags": ["cpu-optimized", "conversational"]
    },
    "wizardlm-uncensored-13b": {
        "name": "WizardLM-13B-Uncensored",
        "ollama": "wizardlm-uncensored:13b",
        "huggingface": "ehartford/WizardLM-13B-Uncensored",
        "gguf": "TheBloke/WizardLM-13B-Uncensored-GGUF",
        "size": "7.4GB",
        "speed": "25-30 tok/s",
        "description": "Classic uncensored, creative writing",
        "tags": ["uncensored", "creative", "classic"]
    },
    # Specialized
    "mythomax": {
        "name": "MythoMax L2 13B",
        "ollama": "mythomax",
        "huggingface": "Gryphe/MythoMax-L2-13b",
        "gguf": "TheBloke/MythoMax-L2-13B-GGUF",
        "size": "7.4GB",
        "speed": "25-30 tok/s",
        "description": "Best for creative writing and roleplay",
        "tags": ["creative", "roleplay", "storytelling"]
    },
    "deepseek-coder-33b": {
        "name": "DeepSeek Coder 33B",
        "ollama": "deepseek-coder:33b",
        "huggingface": "deepseek-ai/deepseek-coder-33b-instruct",
        "gguf": "TheBloke/deepseek-coder-33B-instruct-GGUF",
        "size": "20GB",
        "speed": "10-12 tok/s",
        "description": "Best coding model, supports 86 languages",
        "tags": ["coding", "programming", "technical"]
    },
    "codellama-34b": {
        "name": "CodeLlama 34B Instruct",
        "ollama": "codellama:34b-instruct",
        "huggingface": "codellama/CodeLlama-34b-Instruct-hf",
        "gguf": "TheBloke/CodeLlama-34B-Instruct-GGUF",
        "size": "20GB",
        "speed": "10-12 tok/s",
        "description": "Meta's coding specialist",
        "tags": ["coding", "meta", "instruct"]
    },
    # Large models
    "airoboros-70b": {
        "name": "Airoboros L2 70B",
        "ollama": "airoboros:70b",
        "huggingface": "jondurbin/airoboros-l2-70b-gpt4-1.4.1",
        "gguf": "TheBloke/airoboros-L2-70B-GPT4-1.4.1-GGUF",
        "size": "40GB (Q4), 25GB (Q3)",
        "speed": "3-5 tok/s",
        "description": "Maximum capability, needs Q3 quantization",
        "tags": ["uncensored", "large", "capable"]
    }
}


def list_models(filter_tag=None):
    """List available models"""
    table = Table(title="Available Models", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="green")
    table.add_column("Name", style="cyan")
    table.add_column("Size")
    table.add_column("Speed")
    table.add_column("Description")

    for model_id, info in MODEL_REGISTRY.items():
        if filter_tag and filter_tag not in info.get("tags", []):
            continue
        table.add_row(
            model_id,
            info["name"],
            info["size"],
            info["speed"],
            info["description"]
        )

    console.print(table)
    console.print(f"\n[dim]Total models: {len(MODEL_REGISTRY)}[/dim]")
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

    console.print(Panel.fit(
        f"[bold cyan]{info['name']}[/bold cyan]\n\n"
        f"[bold]Size:[/bold] {info['size']}\n"
        f"[bold]Speed:[/bold] {info['speed']}\n"
        f"[bold]Description:[/bold] {info['description']}\n\n"
        f"[bold]Tags:[/bold] {', '.join(info.get('tags', []))}\n\n"
        f"[bold]Sources:[/bold]\n"
        f"  • Ollama: {info.get('ollama', 'N/A')}\n"
        f"  • Hugging Face: {info.get('huggingface', 'N/A')}\n"
        f"  • GGUF: {info.get('gguf', 'N/A')}",
        title=f"Model Info: {model_id}",
        border_style="cyan"
    ))


def main():
    parser = argparse.ArgumentParser(description="Download and manage LLM models")
    parser.add_argument("model_id", nargs="?", help="Model ID to download")
    parser.add_argument("--list", "-l", action="store_true", help="List available models")
    parser.add_argument("--info", "-i", metavar="MODEL", help="Show model information")
    parser.add_argument("--source", "-s", choices=["ollama", "huggingface", "gguf"],
                       default="ollama", help="Download source (default: ollama)")
    parser.add_argument("--filter", "-f", metavar="TAG", help="Filter models by tag")

    args = parser.parse_args()

    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    if args.list:
        list_models(filter_tag=args.filter)
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
