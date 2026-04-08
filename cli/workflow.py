#!/usr/bin/env python3
"""
Workflow CLI — Run and monitor multi-agent workflows from the terminal

Usage:
  python cli/workflow.py run <workflow.yaml> --seed '{"key": "value"}'
  python cli/workflow.py compile <workflow.yaml>
  python cli/workflow.py list
  python cli/workflow.py status <run_id>
  python cli/workflow.py runs
  python cli/workflow.py artifact <run_id> <step_id>
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich import print as rprint

from api.services.ollama_service import OllamaService
from api.services.workflow_engine import WorkflowEngine
from api.services.workflow_events import EventType, WorkflowEventBus

console = Console()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "./workflows")


def get_engine() -> WorkflowEngine:
    ollama = OllamaService(OLLAMA_HOST)
    bus = WorkflowEventBus()

    # Real-time step progress handler
    def progress_handler(event):
        if event.event_type == EventType.STEP_STARTED:
            console.print(f"  [bright_cyan]▶[/] Starting [bold]{event.step_id}[/]...", highlight=False)
        elif event.event_type == EventType.STEP_COMPLETED:
            dur = event.data.get("duration_seconds", 0)
            tok = event.data.get("total_tokens", 0)
            cached = " [dim](cached)[/]" if event.data.get("cached") else ""
            console.print(
                f"  [green]✓[/] {event.step_id} — {dur:.1f}s, {tok:,} tokens{cached}",
                highlight=False,
            )
        elif event.event_type == EventType.STEP_FAILED:
            err = event.data.get("error", "unknown")
            console.print(f"  [red]✗[/] {event.step_id} — {err}", highlight=False)
        elif event.event_type == EventType.STEP_SKIPPED:
            console.print(f"  [dim]⊘[/] {event.step_id} — skipped (condition not met)", highlight=False)
        elif event.event_type == EventType.BATCH_STARTED:
            batch_idx = event.data.get("batch_index", "?")
            step_ids = event.data.get("step_ids", [])
            if len(step_ids) > 1:
                console.print(
                    f"\n[bright_magenta]Batch {batch_idx}[/] "
                    f"[dim]({len(step_ids)} steps in parallel)[/]",
                    highlight=False,
                )
            else:
                console.print(f"\n[bright_magenta]Batch {batch_idx}[/]", highlight=False)
        elif event.event_type == EventType.GATE_FAILED:
            console.print(
                f"    [red]⚑ Gate failed:[/] {event.data.get('gate', '?')} — "
                f"{event.data.get('reason', '')}",
                highlight=False,
            )
        elif event.event_type == EventType.GATE_WARNING:
            console.print(
                f"    [yellow]⚠ Gate warning:[/] {event.data.get('gate', '?')} — "
                f"{event.data.get('reason', '')}",
                highlight=False,
            )

    bus.on_all(progress_handler)
    return WorkflowEngine(ollama, event_bus=bus)


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

    # Compile
    plan = engine.compile(defn, seed_keys=list(seed.keys()) if seed else None)
    console.print(f"  [dim]Batches:[/] {plan.total_batches}")
    console.print(f"  [dim]Max parallel:[/] {plan.parallelism}")
    console.print("  [green]Compilation passed[/]\n")

    # Show execution plan
    console.print("[bright_cyan]Execution Plan:[/]")
    for batch in plan.batches:
        parallel_tag = f" [dim](parallel)[/]" if len(batch.step_ids) > 1 else ""
        step_names = []
        for sid in batch.step_ids:
            step_def = next((s for s in defn.steps if s.id == sid), None)
            model_ref = ""
            if step_def:
                model_ref = step_def.model or f"role:{step_def.role or defn.defaults.role}"
            step_names.append(f"{sid} [dim]({model_ref})[/]")
        console.print(f"  Batch {batch.batch_index}: {', '.join(step_names)}{parallel_tag}")

    console.print(f"\n[bright_cyan]Executing...[/]")

    # Execute
    run = engine.run(defn, seed=seed)

    # Results
    console.print()
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
    table.add_column("Gates", justify="right")
    table.add_column("Notes", style="dim")

    for r in run.step_results:
        status_map = {
            "completed": "[green]Done[/]",
            "failed": "[red]Failed[/]",
            "skipped": "[dim]Skipped[/]",
        }
        status = status_map.get(str(r.status), str(r.status))
        dur = f"{r.duration_seconds:.1f}s" if r.duration_seconds else "-"
        tokens = f"{r.token_count.get('total_tokens', 0):,}"
        gates = ""
        if r.gate_results:
            passed = sum(1 for g in r.gate_results if g["passed"])
            total = len(r.gate_results)
            gates = f"{passed}/{total}"
        notes = []
        if r.cached:
            notes.append("cached")
        if r.retries > 0:
            notes.append(f"{r.retries} retries")
        table.add_row(r.step_id, status, r.model_used or "-", dur, tokens, gates, ", ".join(notes))

    console.print(table)

    # Totals
    console.print(f"\n[dim]Run ID: {run.run_id}[/]")
    console.print(f"[dim]Total duration: {run.total_duration:.1f}s[/]")
    console.print(f"[dim]Total tokens: {run.total_tokens:,}[/]")
    console.print(f"[dim]Results saved to: data/workflows/{run.run_id}/[/]\n")


def cmd_compile(args):
    """Compile a workflow and show execution plan"""
    engine = get_engine()
    defn = engine.load(args.workflow)
    seed_keys = json.loads(args.seed_keys) if args.seed_keys else None
    plan = engine.compile(defn, seed_keys=seed_keys)
    analysis = engine.compiler.analyze_parallelism(plan)

    console.print(Panel(f"[bold]{defn.name}[/] v{defn.version or '?'}"))
    if defn.description:
        console.print(f"  [dim]{defn.description.strip()}[/]\n")

    # DAG tree visualization
    tree = Tree(f"[bright_cyan]{defn.id}[/]")
    for batch in plan.batches:
        batch_label = f"[bright_magenta]Batch {batch.batch_index}[/]"
        if len(batch.step_ids) > 1:
            batch_label += f" [dim](parallel)[/]"
        batch_node = tree.add(batch_label)
        for sid in batch.step_ids:
            step_def = next((s for s in defn.steps if s.id == sid), None)
            if step_def:
                features = []
                if step_def.condition or step_def.conditions:
                    features.append("conditional")
                if step_def.loop:
                    features.append("loop")
                if step_def.quality_gates:
                    features.append(f"{len(step_def.quality_gates)} gates")
                if step_def.output_parser.format.value != "raw":
                    features.append(step_def.output_parser.format.value)
                feat_str = f" [dim]({', '.join(features)})[/]" if features else ""
                role = step_def.model or f"role:{step_def.role or defn.defaults.role}"
                batch_node.add(f"[cyan]{sid}[/] — {step_def.name} [{role}]{feat_str}")

    console.print(tree)

    # Parallelism analysis
    console.print(f"\n[bright_cyan]Parallelism Analysis:[/]")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Total steps", str(analysis["total_steps"]))
    table.add_row("Total batches", str(analysis["total_batches"]))
    table.add_row("Max parallel width", str(analysis["max_parallel_width"]))
    table.add_row("Avg parallel width", str(analysis["avg_parallel_width"]))
    table.add_row("Sequential fraction", f"{analysis['sequential_fraction']:.0%}")
    table.add_row("Speedup factor", f"{analysis['speedup_factor']}x")
    console.print(table)


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
    table.add_column("Batches", justify="right")
    table.add_column("Parallel", justify="right")
    table.add_column("Category", style="dim")
    table.add_column("Version", style="dim")

    for wf in workflows:
        table.add_row(
            wf["id"], wf["name"], str(wf["steps"]),
            str(wf.get("batches", "-")), str(wf.get("max_parallel", "-")),
            wf.get("category") or "-", wf.get("version", "-"),
        )

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
    table.add_column("Duration", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Started", style="dim")

    for r in runs:
        status_map = {"completed": "[green]completed[/]", "failed": "[red]failed[/]"}
        status = status_map.get(r["status"], r["status"])
        dur = f"{r.get('total_duration', 0):.1f}s"
        tok = f"{r.get('total_tokens', 0):,}"
        table.add_row(
            r["run_id"][:12] + "...", r["workflow_id"],
            status, dur, tok, str(r.get("started_at", "-"))[:19],
        )

    console.print(table)


def cmd_status(args):
    """Get status of a specific run"""
    engine = get_engine()
    run = engine.get_run(args.run_id)

    if not run:
        console.print(f"[red]Run '{args.run_id}' not found[/]")
        return

    console.print(Panel(f"[bold]{run['workflow_id']}[/] — {run['status']}"))
    console.print(f"  [dim]Run ID:[/] {run['run_id']}")
    console.print(f"  [dim]Status:[/] {run['status']}")
    console.print(f"  [dim]Started:[/] {run.get('started_at')}")
    console.print(f"  [dim]Completed:[/] {run.get('completed_at')}")
    console.print(f"  [dim]Total tokens:[/] {run.get('total_tokens', 0):,}")
    console.print(f"  [dim]Total duration:[/] {run.get('total_duration', 0):.1f}s")

    if run.get("error"):
        console.print(f"  [red]Error:[/] {run['error']}")

    # Show step results
    step_results = run.get("step_results", [])
    if step_results:
        console.print("\n[bright_cyan]Steps:[/]")
        for r in step_results:
            icon = {"completed": "[green]✓[/]", "failed": "[red]✗[/]", "skipped": "[dim]⊘[/]"}.get(r["status"], "?")
            dur = f"{r.get('duration_seconds', 0):.1f}s" if r.get("duration_seconds") else "-"
            console.print(f"  {icon} {r['step_id']} — {r['status']} ({dur})")


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


def main():
    parser = argparse.ArgumentParser(description="Workflow CLI — Multi-Agent Orchestrator")
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Run a workflow")
    p_run.add_argument("workflow", help="Path to workflow YAML")
    p_run.add_argument("--seed", default="{}", help="Seed data as JSON string")

    # compile
    p_compile = sub.add_parser("compile", help="Compile and show execution plan")
    p_compile.add_argument("workflow", help="Path to workflow YAML")
    p_compile.add_argument("--seed-keys", default=None, help="Seed keys as JSON array")

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

    args = parser.parse_args()

    commands = {
        "run": cmd_run,
        "compile": cmd_compile,
        "list": cmd_list,
        "runs": cmd_runs,
        "status": cmd_status,
        "artifact": cmd_artifact,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
