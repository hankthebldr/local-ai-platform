#!/usr/bin/env python3
"""
Local AI Platform - CLI Chat Interface
Interactive chat with local LLMs
"""

import sys
import argparse
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
import requests

console = Console()

def chat_with_ollama(model: str, host: str = "http://localhost:11434"):
    """Interactive chat session with Ollama"""

    console.print(Panel.fit(
        f"[bold bright_cyan]Local AI Platform - Chat Interface[/bold bright_cyan]\n"
        f"[dim]Model:[/dim] [bright_white]{model}[/bright_white]\n"
        f"[dim]Type 'exit' or 'quit' to end the session[/dim]\n"
        f"[dim]Type '/help' for commands[/dim]",
        border_style="bright_cyan"
    ))

    conversation_history = []

    while True:
        try:
            # Get user input
            user_input = console.input("\n[bold bright_magenta]❯[/bold bright_magenta] ")

            if not user_input.strip():
                continue

            if user_input.lower() in ['exit', 'quit', '/exit', '/quit']:
                console.print("\n[bright_yellow]👋 Goodbye![/bright_yellow]")
                break

            if user_input.lower() == '/help':
                console.print(Panel(
                    "[bold bright_white]Available Commands:[/bold bright_white]\n"
                    "[bright_cyan]/help[/bright_cyan]   - Show this help message\n"
                    "[bright_cyan]/clear[/bright_cyan]  - Clear conversation history\n"
                    "[bright_cyan]/models[/bright_cyan] - List available models\n"
                    "[bright_cyan]/exit[/bright_cyan]   - Exit the chat",
                    title="[bold bright_blue]Help[/bold bright_blue]",
                    border_style="bright_blue"
                ))
                continue

            if user_input.lower() == '/clear':
                conversation_history = []
                console.print("[bright_green]✓ Conversation history cleared[/bright_green]")
                continue

            if user_input.lower() == '/models':
                try:
                    response = requests.get(f"{host}/api/tags")
                    response.raise_for_status()
                    models = response.json().get("models", [])
                    console.print("\n[bold bright_white]Available Models:[/bold bright_white]")
                    for m in models:
                        console.print(f"  [bright_cyan]•[/bright_cyan] [bright_white]{m['name']}[/bright_white]")
                except Exception as e:
                    console.print(f"[bright_red]✗ Error listing models: {e}[/bright_red]")
                continue

            # Add to conversation history
            conversation_history.append({"role": "user", "content": user_input})

            # Build prompt from conversation history
            prompt = ""
            for msg in conversation_history:
                if msg["role"] == "user":
                    prompt += f"User: {msg['content']}\n\n"
                elif msg["role"] == "assistant":
                    prompt += f"Assistant: {msg['content']}\n\n"
            prompt += "Assistant:"

            # Call Ollama API
            console.print("\n[dim italic]Thinking...[/dim italic]", end="")

            ollama_request = {
                "model": model,
                "prompt": prompt,
                "stream": False
            }

            response = requests.post(
                f"{host}/api/generate",
                json=ollama_request,
                timeout=300
            )
            response.raise_for_status()
            result = response.json()

            assistant_response = result["response"]
            conversation_history.append({"role": "assistant", "content": assistant_response})

            # Print response
            console.print("\r" + " " * 20 + "\r", end="")  # Clear "Thinking..."
            console.print("[bold bright_blue]AI:[/bold bright_blue]")
            console.print(Markdown(assistant_response))

        except KeyboardInterrupt:
            console.print("\n\n[bright_yellow]⚠ Interrupted. Type 'exit' to quit.[/bright_yellow]")
            continue
        except requests.exceptions.RequestException as e:
            console.print(f"\n[bright_red]✗ Error communicating with Ollama:[/bright_red] [dim]{e}[/dim]")
            console.print("[bright_yellow]💡 Make sure Ollama is running:[/bright_yellow] [bright_white]ollama serve[/bright_white]")
            continue
        except Exception as e:
            console.print(f"\n[bright_red]✗ Error:[/bright_red] [dim]{e}[/dim]")
            continue


def main():
    parser = argparse.ArgumentParser(description="Chat with local LLMs via Ollama")
    parser.add_argument("--model", "-m", default="mistral", help="Model to use (default: mistral)")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama host URL")

    args = parser.parse_args()

    try:
        chat_with_ollama(args.model, args.host)
    except Exception as e:
        console.print(f"[bright_red]✗ Fatal error:[/bright_red] [dim]{e}[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    main()
