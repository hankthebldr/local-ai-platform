#!/usr/bin/env python3
"""
Workflow CLI — Run and monitor multi-agent workflows from the terminal

Usage:
  python cli/workflow.py run <workflow.yaml> --seed '{"key": "value"}'
  python cli/workflow.py list
  python cli/workflow.py status <run_id>
  python cli/workflow.py runs
  python cli/workflow.py artifact <run_id> <step_id>
"""

import argparse
import json
import sys
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich import print as rprint

from api.services.ollama_service import OllamaService
from api.services.workflow_engine import WorkflowEngine

console = Console()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "./workflows")


def get_engine() -> WorkflowEngine:
    ollama = OllamaService(OLLAMA_HOST)
    return WorkflowEngine(ollama)


def cmd_run(args):
    """Run a workflow"""
    engine = get_engine()

    # Load
    console.print(f"\n[bright_cyan]Loading workflow:[/] {args.workflow}")
    defn = engine.load(args.workflow)
    console.print(f"  [dim]ID:[/] {defn.id}")
    console.print(f"  [dim]Steps:[/] {len(defn.steps)}")

    # Parse seed
    seed = json.loads(args.seed) if args.seed else {}
    console.print(f"  [dim]Seed keys:[/] {list(seed.keys())}")

    # Validate
    engine.validate(defn, seed_keys=list(seed.keys()))
    console.print("  [green]Validation passed[/]\n")

    # Execute
    for i, step in enumerate(defn.steps):
        model_ref = step.model or f"role:{step.role or defn.defaults.role}"
        console.print(
            f"[bright_magenta]Step {i+1}/{len(defn.steps)}:[/] "
            f"{step.name} [dim]({model_ref})[/]"
        )

    console.print()
    run = engine.run(defn, seed=seed)

    # Results
    if run.status == "completed":
        console.print(Panel("[green bold]Workflow completed successfully[/]"))
    else:
        console.print(Panel(f"[red bold]Workflow failed: {run.error}[/]"))

    # Summary table
    table = Table(title="Step Results")
    table.add_column("Step", style="cyan")
    table.add_column("Status")
    table.add_column("Model", style="dim")
    table.add_column("Duration", justify="right")
    table.add_column("Tokens", justify="right")

    for r in run.step_results:
        status = "[green]Done[/]" if r.status == "completed" else "[red]Failed[/]"
        dur = f"{r.duration_seconds:.1f}s" if r.duration_seconds else "-"
        tokens = str(r.token_count.get("total_tokens", 0))
        table.add_row(r.step_id, status, r.model_used or "-", dur, tokens)

    console.print(table)
    console.print(f"\n[dim]Run ID: {run.run_id}[/]")
    console.print(f"[dim]Results saved to: data/workflows/{run.run_id}/[/]\n")


def cmd_list(args):
    """List available workflows"""
    engine = get_engine()
    workflows = engine.list_workflows(WORKFLOWS_DIR)

    if not workflows:
        console.print("[dim]No workflows found in workflows/ directory[/]")
        return

    table = Table(title="Available Workflows")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Steps", justify="right")
    table.add_column("Version", style="dim")

    for wf in workflows:
        table.add_row(wf["id"], wf["name"], str(wf["steps"]), wf.get("version", "-"))

    console.print(table)


def cmd_runs(args):
    """List recent runs"""
    engine = get_engine()
    runs = engine.list_runs(limit=args.limit)

    if not runs:
        console.print("[dim]No workflow runs found[/]")
        return

    table = Table(title="Recent Runs")
    table.add_column("Run ID", style="cyan")
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Started", style="dim")

    for r in runs:
        status = "[green]completed[/]" if r["status"] == "completed" else "[red]failed[/]"
        table.add_row(
            r["run_id"][:12] + "...",
            r["workflow_id"],
            status,
            str(r.get("started_at", "-"))[:19],
        )

    console.print(table)


def cmd_status(args):
    """Get status of a specific run"""
    engine = get_engine()
    run = engine.get_run(args.run_id)

    if not run:
        console.print(f"[red]Run '{args.run_id}' not found[/]")
        return

    console.print(Panel(f"[bold]{run['workflow_id']}[/] -- {run['status']}"))
    console.print(f"  [dim]Run ID:[/] {run['run_id']}")
    console.print(f"  [dim]Status:[/] {run['status']}")
    console.print(f"  [dim]Started:[/] {run.get('started_at')}")
    console.print(f"  [dim]Completed:[/] {run.get('completed_at')}")

    if run.get("error"):
        console.print(f"  [red]Error:[/] {run['error']}")


def cmd_artifact(args):
    """View a step's output artifact"""
    engine = get_engine()
    run = engine.get_run(args.run_id)

    if not run:
        console.print(f"[red]Run '{args.run_id}' not found[/]")
        return

    workspace = run.get("context", {}).get("workspace", {})
    step_data = workspace.get(args.step_id)

    if not step_data:
        console.print(f"[red]No artifacts for step '{args.step_id}'[/]")
        return

    console.print(Panel(f"[bold]Artifacts: {args.step_id}[/]"))
    console.print_json(json.dumps(step_data, indent=2))


def upgrade_v1_to_v2(src_path, dst_path):
    """Upgrade a v1 workflow YAML into v2 schema. Never overwrites.

    Heuristics:
      - `system_prompt` → split: first sentence = role_inline, rest = task
      - `outputs` list → output_schema with string-typed properties
    """
    import re
    from pathlib import Path
    import yaml

    src = Path(src_path)
    dst = Path(dst_path)
    if dst.exists():
        raise FileExistsError(f"refusing to overwrite {dst}")

    data = yaml.safe_load(src.read_text())
    data["schema_version"] = 2

    for step in data.get("steps", []):
        sp = step.pop("system_prompt", None)
        if sp is None:
            continue
        sp = sp.strip()
        m = re.match(r"([^.\n]+[.\n])(.*)", sp, re.DOTALL)
        if m:
            role_inline = m.group(1).strip()
            task = m.group(2).strip() or "(Perform the role described above.)"
        else:
            role_inline = sp
            task = "(Perform the role described above.)"
        step["prompt"] = {
            "role_inline": role_inline,
            "task": task,
            "constraints": [
                "Return JSON only. No prose, no markdown fences.",
            ],
        }
        outputs = step.get("outputs", [])
        step["output_schema"] = {
            "type": "object",
            "required": list(outputs),
            "properties": {k: {"type": "string"} for k in outputs},
        }

    dst.write_text(yaml.safe_dump(data, sort_keys=False))
    print(f"Upgraded → {dst}")
    print("Review generated output_schema: stubs are all type:string. Tighten as needed.")


def main():
    parser = argparse.ArgumentParser(description="Workflow CLI")
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Run a workflow")
    p_run.add_argument("workflow", help="Path to workflow YAML")
    p_run.add_argument("--seed", default="{}", help="Seed data as JSON string")

    # list
    sub.add_parser("list", help="List available workflows")

    # runs
    p_runs = sub.add_parser("runs", help="List recent runs")
    p_runs.add_argument("--limit", type=int, default=20)

    # status
    p_status = sub.add_parser("status", help="Get run status")
    p_status.add_argument("run_id", help="Run ID")

    # artifact
    p_art = sub.add_parser("artifact", help="View step artifact")
    p_art.add_argument("run_id", help="Run ID")
    p_art.add_argument("step_id", help="Step ID")

    # upgrade
    p_upgrade = sub.add_parser("upgrade", help="Upgrade a v1 workflow YAML to v2")
    p_upgrade.add_argument("src")
    p_upgrade.add_argument(
        "--out",
        default=None,
        help="Destination path (defaults to <src>.v2.yaml)",
    )

    args = parser.parse_args()

    commands = {
        "run": cmd_run,
        "list": cmd_list,
        "runs": cmd_runs,
        "status": cmd_status,
        "artifact": cmd_artifact,
    }

    if args.command == "upgrade":
        from pathlib import Path

        src = Path(args.src)
        dst = Path(args.out) if args.out else src.with_suffix(".v2.yaml")
        upgrade_v1_to_v2(src, dst)
    elif args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
