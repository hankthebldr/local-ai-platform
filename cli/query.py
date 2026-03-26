#!/usr/bin/env python3
"""
Local AI Platform — Single-shot query CLI

Pipe-friendly: outputs plain text when stdout is not a TTY.

Usage:
    python cli/query.py "What is the capital of France?"
    python cli/query.py "Explain TCP" --model dolphin3:latest
    echo "Summarize this" | python cli/query.py --model dolphin3:latest
    python cli/query.py "List 3 things" --api http://localhost:8000
"""

import sys
import argparse
import json
import requests


def query_ollama(prompt: str, model: str, host: str) -> str:
    """Send a single query to Ollama and return the response text."""
    resp = requests.post(
        f"{host}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def query_api(prompt: str, model: str, api_url: str, api_key: str = "") -> str:
    """Send a single query to our API server and return the response text."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.post(
        f"{api_url}/v1/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def main():
    parser = argparse.ArgumentParser(description="Single-shot query to local LLM")
    parser.add_argument("prompt", nargs="?", help="Query prompt (reads from stdin if omitted)")
    parser.add_argument("--model", "-m", default="dolphin3:latest", help="Model name (default: dolphin3:latest)")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama host (default: http://localhost:11434)")
    parser.add_argument("--api", default="", help="Use API server instead of Ollama directly (e.g., http://localhost:8000)")
    parser.add_argument("--api-key", default="", help="API key for authenticated endpoints")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Get prompt from argument or stdin
    prompt = args.prompt
    if not prompt:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        else:
            print("Error: No prompt provided. Pass as argument or pipe via stdin.", file=sys.stderr)
            sys.exit(1)

    if not prompt:
        print("Error: Empty prompt.", file=sys.stderr)
        sys.exit(1)

    is_tty = sys.stdout.isatty()

    try:
        if args.api:
            response = query_api(prompt, args.model, args.api, args.api_key)
        else:
            response = query_ollama(prompt, args.model, args.host)

        if args.json:
            print(json.dumps({"model": args.model, "prompt": prompt, "response": response}))
        elif is_tty:
            # Rich formatting for interactive use
            from rich.console import Console
            from rich.markdown import Markdown
            from rich.panel import Panel

            console = Console()
            console.print(Panel(
                Markdown(response),
                title=f"[bright_cyan]{args.model}[/bright_cyan]",
                border_style="bright_blue",
            ))
        else:
            # Plain text for piping
            print(response)

    except requests.ConnectionError:
        target = args.api or args.host
        print(f"Error: Cannot connect to {target}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
