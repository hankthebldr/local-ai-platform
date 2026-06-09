#!/usr/bin/env python3
"""
Eval CLI — run agent/workflow regression suites from the terminal.

Usage:
  python -m cli.eval evals/meeting-summary.eval.yaml
  python -m cli.eval evals/*.eval.yaml            # multiple suites
  python -m cli.eval evals/                        # every *.eval.yaml in a dir

Assertions are property-based (see api/services/eval_harness.py), so they
tolerate model wording and check structure. Exits non-zero if any case fails,
so it drops straight into CI.
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console

from api.services.eval_harness import format_report, run_suite_file
from api.services.ollama_service import OllamaService
from api.services.workflow_engine import WorkflowEngine

console = Console()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def _expand(paths):
    """Expand dirs → their *.eval.yaml, globs → matches, files → themselves."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(sorted(glob.glob(os.path.join(p, "*.eval.yaml"))))
        elif any(ch in p for ch in "*?["):
            out.extend(sorted(glob.glob(p)))
        else:
            out.append(p)
    return out


def main():
    parser = argparse.ArgumentParser(description="Run agent/workflow eval suites")
    parser.add_argument("suites", nargs="+", help="Suite file(s), glob(s), or dir(s)")
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON instead of text"
    )
    args = parser.parse_args()

    files = _expand(args.suites)
    if not files:
        console.print("[red]No suite files matched.[/red]")
        sys.exit(2)

    engine = WorkflowEngine(OllamaService(OLLAMA_HOST))
    any_failed = False
    json_blobs = []

    for f in files:
        try:
            result = run_suite_file(f, engine=engine)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Suite {f} could not run: {e}[/red]")
            any_failed = True
            continue

        if args.json:
            json_blobs.append(result.model_dump())
        else:
            color = "green" if result.ok else "red"
            console.print(f"[{color}]{format_report(result)}[/{color}]")
            console.print("")
        any_failed = any_failed or not result.ok

    if args.json:
        import json

        print(json.dumps(json_blobs, indent=2, default=str))

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
