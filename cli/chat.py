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
        f"[bold cyan]Local AI Platform - Chat Interface[/bold cyan]\n"
        f"Model: {model}\n"
        f"Type 'exit' or 'quit' to end the session\n"
        f"Type '/help' for commands",
        border_style="cyan"
    ))

    conversation_history = []

    while True:
        try:
            # Get user input
            user_input = console.input("\n[bold green]You:[/bold green] ")

            if not user_input.strip():
                continue

            if user_input.lower() in ['exit', 'quit', '/exit', '/quit']:
                console.print("\n[yellow]Goodbye![/yellow]")
                break

            if user_input.lower() == '/help':
                console.print(Panel(
                    "[bold]Available Commands:[/bold]\n"
                    "/help - Show this help message\n"
                    "/clear - Clear conversation history\n"
                    "/models - List available models\n"
                    "/exit or /quit - Exit the chat",
                    title="Help",
                    border_style="blue"
                ))
                continue

            if user_input.lower() == '/clear':
                conversation_history = []
                console.print("[yellow]Conversation history cleared[/yellow]")
                continue

            if user_input.lower() == '/models':
                try:
                    response = requests.get(f"{host}/api/tags")
                    response.raise_for_status()
                    models = response.json().get("models", [])
                    console.print("\n[bold]Available Models:[/bold]")
                    for m in models:
                        console.print(f"  • {m['name']}")
                except Exception as e:
                    console.print(f"[red]Error listing models: {e}[/red]")
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
            console.print("\n[dim]Thinking...[/dim]", end="")

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
            console.print("[bold cyan]Assistant:[/bold cyan]")
            console.print(Markdown(assistant_response))

        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
            continue
        except requests.exceptions.RequestException as e:
            console.print(f"\n[red]Error communicating with Ollama: {e}[/red]")
            console.print("[yellow]Make sure Ollama is running: ollama serve[/yellow]")
            continue
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            continue


def main():
    parser = argparse.ArgumentParser(description="Chat with local LLMs via Ollama")
    parser.add_argument("--model", "-m", default="mistral", help="Model to use (default: mistral)")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama host URL")

    args = parser.parse_args()

    try:
        chat_with_ollama(args.model, args.host)
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
