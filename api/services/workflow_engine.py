"""
Workflow Engine — Best-in-Class Multi-Agent DAG Orchestrator

Features:
- DAG-based execution with parallel batch scheduling
- Jinja2 prompt templating with full context access
- Structured output parsing (JSON, markdown, regex, CSV)
- Quality gates with configurable severity
- Conditional branching and step skipping
- Loop iteration over collections
- Checkpoint/resume for fault tolerance
- Event system for real-time observability
- Result caching for identical inputs
- Comprehensive persistence (JSON + markdown summary)
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from ..logging_config import logger
from ..exceptions import WorkflowValidationError, WorkflowExecutionError
from ..models.workflow_models import (
    AgentStep,
    ExecutionPlan,
    RunStatus,
    StepResult,
    StepStatus,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRun,
)
from .model_resolver import ModelResolver
from .step_executor import StepExecutor
from .workflow_compiler import WorkflowCompiler
from .workflow_events import EventType, WorkflowEventBus, logging_handler
from .ollama_service import OllamaService


DATA_DIR = os.getenv("WORKFLOW_DATA_DIR", "./data/workflows")


class WorkflowEngine:
    """
    Central orchestrator for multi-agent workflows.

    Lifecycle:
    1. Load — parse YAML into WorkflowDefinition
    2. Compile — validate DAG, build execution plan with parallel batches
    3. Execute — run batches (parallel within, sequential across)
    4. Persist — save run results, artifacts, and summary to disk

    The engine is stateless between runs — all state lives in WorkflowRun.
    """

    def __init__(
        self,
        ollama_service: OllamaService,
        event_bus: Optional[WorkflowEventBus] = None,
    ):
        self.ollama = ollama_service
        self.resolver = ModelResolver(ollama_service)
        self.executor = StepExecutor(ollama_service)
        self.compiler = WorkflowCompiler()
        self.events = event_bus or WorkflowEventBus()
        self.events.on_all(logging_handler)

    # ── Load Phase ────────────────────────────────────────────────────────

    def load(self, yaml_path: str) -> WorkflowDefinition:
        """Load a workflow definition from a YAML file"""
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {yaml_path}")

        with open(path) as f:
            raw = yaml.safe_load(f)

        try:
            definition = WorkflowDefinition(**raw)
        except Exception as e:
            raise WorkflowValidationError(f"Invalid workflow YAML: {e}")

        logger.info(f"Loaded workflow '{definition.id}' ({len(definition.steps)} steps)")
        return definition

    def load_from_dict(self, data: Dict[str, Any]) -> WorkflowDefinition:
        """Load a workflow definition from a dictionary (for API usage)"""
        try:
            return WorkflowDefinition(**data)
        except Exception as e:
            raise WorkflowValidationError(f"Invalid workflow definition: {e}")

    # ── Compile Phase ─────────────────────────────────────────────────────

    def compile(
        self,
        definition: WorkflowDefinition,
        seed_keys: Optional[List[str]] = None,
    ) -> ExecutionPlan:
        """Compile workflow into a validated execution plan"""
        return self.compiler.compile(definition, seed_keys=seed_keys)

    def validate(
        self,
        definition: WorkflowDefinition,
        seed_keys: Optional[List[str]] = None,
    ) -> None:
        """Validate workflow (backward compat — delegates to compile)"""
        self.compiler.compile(definition, seed_keys=seed_keys)

    # ── Execute Phase ─────────────────────────────────────────────────────

    def run(
        self,
        definition: WorkflowDefinition,
        seed: Dict[str, Any],
        resume_from: Optional[str] = None,
    ) -> WorkflowRun:
        """
        Execute a workflow end-to-end using the compiled execution plan.

        Steps within the same batch run in parallel (up to max_parallel).
        Batches execute sequentially in topological order.

        Args:
            definition: The workflow to execute
            seed: Initial context data
            resume_from: Optional checkpoint name to resume from
        """
        # Compile
        plan = self.compile(definition, seed_keys=list(seed.keys()) if seed else None)

        # Initialize run
        context = WorkflowContext(seed=seed)
        workflow_run = WorkflowRun(
            workflow_id=definition.id,
            context=context,
            execution_plan=plan,
            started_at=datetime.utcnow(),
            status=RunStatus.RUNNING,
        )

        # Resume from checkpoint if specified
        if resume_from and context.restore(resume_from):
            logger.info(f"Resumed from checkpoint '{resume_from}'")
            workflow_run.checkpoints.append(f"resumed:{resume_from}")

        # Build step lookup
        step_map: Dict[str, AgentStep] = {s.id: s for s in definition.steps}
        completed_steps: set = set()

        self.events.emit(
            EventType.WORKFLOW_STARTED,
            run_id=workflow_run.run_id,
            data={
                "workflow_id": definition.id,
                "total_steps": plan.total_steps,
                "total_batches": plan.total_batches,
                "seed_keys": list(seed.keys()),
            },
        )

        try:
            for batch in plan.batches:
                self.events.emit(
                    EventType.BATCH_STARTED,
                    run_id=workflow_run.run_id,
                    data={
                        "batch_index": batch.batch_index,
                        "step_ids": batch.step_ids,
                    },
                )

                # Skip already-completed steps (for resume)
                batch_steps = [
                    sid for sid in batch.step_ids if sid not in completed_steps
                ]

                if not batch_steps:
                    continue

                # Execute batch — parallel if multiple steps
                if len(batch_steps) == 1:
                    results = [
                        self._execute_step(
                            step_map[batch_steps[0]], context, definition, workflow_run.run_id
                        )
                    ]
                else:
                    results = self._execute_batch_parallel(
                        batch_steps, step_map, context, definition,
                        workflow_run.run_id, definition.max_parallel,
                    )

                # Process results
                batch_failed = False
                for result in results:
                    workflow_run.step_results.append(result)

                    if result.status == StepStatus.COMPLETED:
                        completed_steps.add(result.step_id)
                    elif result.status == StepStatus.SKIPPED:
                        completed_steps.add(result.step_id)
                    elif result.status == StepStatus.FAILED:
                        batch_failed = True

                self.events.emit(
                    EventType.BATCH_COMPLETED,
                    run_id=workflow_run.run_id,
                    data={
                        "batch_index": batch.batch_index,
                        "results": [
                            {"step_id": r.step_id, "status": r.status.value}
                            for r in results
                        ],
                    },
                )

                if batch_failed:
                    failed = [r for r in results if r.status == StepStatus.FAILED]
                    workflow_run.status = RunStatus.FAILED
                    workflow_run.error = (
                        f"Batch {batch.batch_index} failed: "
                        + ", ".join(
                            f"{r.step_id}: {r.error}" for r in failed
                        )
                    )
                    workflow_run.completed_at = datetime.utcnow()

                    # Create checkpoint for potential resume
                    checkpoint_name = f"batch_{batch.batch_index}_failed"
                    context.snapshot(checkpoint_name)
                    workflow_run.checkpoints.append(checkpoint_name)

                    self.events.emit(
                        EventType.WORKFLOW_FAILED,
                        run_id=workflow_run.run_id,
                        data={
                            "error": workflow_run.error,
                            "checkpoint": checkpoint_name,
                            "completed_steps": list(completed_steps),
                        },
                    )
                    break
            else:
                # All batches completed
                workflow_run.status = RunStatus.COMPLETED
                workflow_run.completed_at = datetime.utcnow()

                self.events.emit(
                    EventType.WORKFLOW_COMPLETED,
                    run_id=workflow_run.run_id,
                    data={
                        "total_duration": self._total_duration(workflow_run),
                        "total_tokens": self._total_tokens(workflow_run),
                        "steps_completed": len(completed_steps),
                    },
                )

        except Exception as e:
            workflow_run.status = RunStatus.FAILED
            workflow_run.error = f"Engine error: {e}"
            workflow_run.completed_at = datetime.utcnow()
            logger.error(f"Workflow '{definition.id}' engine error: {e}")

            self.events.emit(
                EventType.WORKFLOW_FAILED,
                run_id=workflow_run.run_id,
                data={"error": str(e)},
            )

        # Aggregate metrics
        workflow_run.total_tokens = self._total_tokens(workflow_run)
        workflow_run.total_duration = self._total_duration(workflow_run)

        # Persist
        self._persist_run(workflow_run, definition)

        return workflow_run

    def _execute_step(
        self,
        step: AgentStep,
        context: WorkflowContext,
        definition: WorkflowDefinition,
        run_id: str,
    ) -> StepResult:
        """Execute a single step with model resolution and event emission"""
        self.events.emit(
            EventType.STEP_STARTED,
            run_id=run_id,
            step_id=step.id,
            data={"name": step.name, "role": step.role, "model": step.model},
        )

        # Resolve model
        try:
            resolved_model = self.resolver.resolve(
                model=step.model,
                role=step.role,
                default_role=definition.defaults.role,
            )
            self.events.emit(
                EventType.MODEL_RESOLVED,
                run_id=run_id,
                step_id=step.id,
                data={"resolved_model": resolved_model},
            )
        except Exception as e:
            result = StepResult(
                step_id=step.id,
                status=StepStatus.FAILED,
                error=f"Model resolution failed: {e}",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                duration_seconds=0.0,
            )
            self.events.emit(
                EventType.STEP_FAILED,
                run_id=run_id,
                step_id=step.id,
                data={"error": str(e), "phase": "model_resolution"},
            )
            return result

        # Execute
        result = self.executor.execute(
            step=step,
            context=context,
            resolved_model=resolved_model,
            defaults=definition.defaults,
        )

        # Emit completion/failure event
        if result.status == StepStatus.COMPLETED:
            self.events.emit(
                EventType.STEP_COMPLETED,
                run_id=run_id,
                step_id=step.id,
                data={
                    "duration_seconds": result.duration_seconds,
                    "total_tokens": result.token_count.get("total_tokens", 0),
                    "model": result.model_used,
                    "cached": result.cached,
                    "retries": result.retries,
                },
            )
        elif result.status == StepStatus.SKIPPED:
            self.events.emit(
                EventType.STEP_SKIPPED,
                run_id=run_id,
                step_id=step.id,
            )
        elif result.status == StepStatus.FAILED:
            self.events.emit(
                EventType.STEP_FAILED,
                run_id=run_id,
                step_id=step.id,
                data={
                    "error": result.error,
                    "retries": result.retries,
                    "duration_seconds": result.duration_seconds,
                },
            )

        # Emit gate results
        for gate_result in result.gate_results:
            event_type = (
                EventType.GATE_PASSED if gate_result["passed"]
                else (EventType.GATE_WARNING if gate_result["severity"] == "warning"
                      else EventType.GATE_FAILED)
            )
            self.events.emit(
                event_type,
                run_id=run_id,
                step_id=step.id,
                data=gate_result,
            )

        return result

    def _execute_batch_parallel(
        self,
        step_ids: List[str],
        step_map: Dict[str, AgentStep],
        context: WorkflowContext,
        definition: WorkflowDefinition,
        run_id: str,
        max_parallel: int,
    ) -> List[StepResult]:
        """Execute multiple steps in parallel using ThreadPoolExecutor"""
        results: List[StepResult] = []
        effective_parallel = min(max_parallel, len(step_ids))

        logger.info(
            f"Executing batch of {len(step_ids)} steps "
            f"(parallel={effective_parallel}): {step_ids}"
        )

        with ThreadPoolExecutor(max_workers=effective_parallel) as pool:
            futures = {
                pool.submit(
                    self._execute_step, step_map[sid], context, definition, run_id
                ): sid
                for sid in step_ids
            }

            for future in as_completed(futures):
                sid = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"Parallel step '{sid}' raised exception: {e}")
                    results.append(StepResult(
                        step_id=sid,
                        status=StepStatus.FAILED,
                        error=f"Parallel execution error: {e}",
                        started_at=datetime.utcnow(),
                        completed_at=datetime.utcnow(),
                    ))

        return results

    # ── Metrics ───────────────────────────────────────────────────────────

    def _total_tokens(self, run: WorkflowRun) -> int:
        return sum(r.token_count.get("total_tokens", 0) for r in run.step_results)

    def _total_duration(self, run: WorkflowRun) -> float:
        return sum(r.duration_seconds or 0 for r in run.step_results)

    # ── Persist Phase ─────────────────────────────────────────────────────

    def _persist_run(self, run: WorkflowRun, definition: WorkflowDefinition) -> None:
        """Save workflow run results to disk"""
        run_dir = Path(DATA_DIR) / run.run_id
        artifacts_dir = run_dir / "artifacts"

        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)

            # Save full run as JSON
            run_data = run.model_dump(mode="json")
            run_path = run_dir / "run.json"
            with open(run_path, "w") as f:
                json.dump(run_data, f, indent=2, default=str)

            # Save individual step artifacts
            for step in definition.steps:
                step_data = run.context.workspace.get(step.id, {})
                if step_data:
                    artifact_path = artifacts_dir / f"{step.id}.json"
                    with open(artifact_path, "w") as f:
                        json.dump(step_data, f, indent=2, default=str)

            # Save human-readable summary
            summary_path = run_dir / "summary.md"
            with open(summary_path, "w") as f:
                f.write(self._generate_summary(run, definition))

            # Save execution plan
            if run.execution_plan:
                plan_path = run_dir / "execution_plan.json"
                with open(plan_path, "w") as f:
                    json.dump(run.execution_plan.model_dump(), f, indent=2)

            logger.info(f"Run persisted to {run_dir}")

        except Exception as e:
            logger.error(f"Failed to persist run {run.run_id}: {e}")

    def _generate_summary(self, run: WorkflowRun, definition: WorkflowDefinition) -> str:
        """Generate a markdown summary of a workflow run"""
        lines = [
            f"# Workflow Run: {definition.name}",
            f"",
            f"- **Run ID**: `{run.run_id}`",
            f"- **Workflow**: {definition.id} v{definition.version or '0.0'}",
            f"- **Status**: {run.status.value}",
            f"- **Started**: {run.started_at}",
            f"- **Completed**: {run.completed_at}",
            f"- **Total Duration**: {run.total_duration:.1f}s",
            f"- **Total Tokens**: {run.total_tokens:,}",
            f"",
        ]

        if run.execution_plan:
            plan = run.execution_plan
            lines.extend([
                f"## Execution Plan",
                f"",
                f"- Batches: {plan.total_batches}",
                f"- Max Parallelism: {plan.parallelism}",
                f"",
            ])
            for batch in plan.batches:
                deps = f" (after batch {batch.depends_on_batches})" if batch.depends_on_batches else ""
                lines.append(
                    f"  - **Batch {batch.batch_index}**: "
                    f"{', '.join(batch.step_ids)}{deps}"
                )
            lines.append("")

        lines.extend(["## Steps", ""])

        for result in run.step_results:
            step_def = next((s for s in definition.steps if s.id == result.step_id), None)
            icon = {"completed": "+", "failed": "x", "skipped": "-"}.get(result.status.value, "?")
            lines.append(
                f"### [{icon}] {result.step_id}"
                f"{f' — {step_def.name}' if step_def else ''}"
            )
            lines.append(f"- **Status**: {result.status.value}")
            lines.append(f"- **Model**: {result.model_used or 'N/A'}")
            lines.append(f"- **Duration**: {result.duration_seconds:.1f}s" if result.duration_seconds else "- **Duration**: N/A")
            lines.append(f"- **Tokens**: {result.token_count.get('total_tokens', 0):,}")
            if result.cached:
                lines.append("- **Cached**: Yes")
            if result.retries > 0:
                lines.append(f"- **Retries**: {result.retries}")
            if result.gate_results:
                for gr in result.gate_results:
                    icon = "PASS" if gr["passed"] else gr["severity"].upper()
                    lines.append(f"- **Gate [{icon}]**: {gr['gate']} — {gr['reason']}")
            if result.error:
                lines.append(f"- **Error**: {result.error}")
            lines.append("")

        if run.error:
            lines.extend(["## Error", "", run.error, ""])

        if run.checkpoints:
            lines.extend([
                "## Checkpoints",
                "",
                *[f"- {cp}" for cp in run.checkpoints],
                "",
            ])

        return "\n".join(lines)

    # ── Utilities ─────────────────────────────────────────────────────────

    def list_workflows(self, workflows_dir: str = "./workflows") -> List[Dict]:
        """List all available workflow definitions"""
        results = []
        wf_path = Path(workflows_dir)
        if not wf_path.exists():
            return results

        for f in sorted(wf_path.glob("*.yaml")):
            try:
                defn = self.load(str(f))
                plan = self.compile(defn)
                parallelism = self.compiler.analyze_parallelism(plan)
                results.append({
                    "id": defn.id,
                    "name": defn.name,
                    "description": defn.description,
                    "version": defn.version,
                    "steps": len(defn.steps),
                    "file": str(f),
                    "batches": plan.total_batches,
                    "max_parallel": parallelism["max_parallel_width"],
                    "category": defn.metadata.category,
                    "tags": defn.metadata.tags,
                })
            except Exception as e:
                logger.warning(f"Skipping invalid workflow {f}: {e}")

        return results

    def get_run(self, run_id: str) -> Optional[Dict]:
        """Load a persisted workflow run by ID"""
        run_path = Path(DATA_DIR) / run_id / "run.json"
        if not run_path.exists():
            return None
        with open(run_path) as f:
            return json.load(f)

    def list_runs(self, limit: int = 20) -> List[Dict]:
        """List recent workflow runs"""
        data_path = Path(DATA_DIR)
        if not data_path.exists():
            return []

        runs = []
        for run_dir in sorted(data_path.iterdir(), reverse=True):
            if run_dir.is_dir():
                run_file = run_dir / "run.json"
                if run_file.exists():
                    try:
                        with open(run_file) as f:
                            data = json.load(f)
                        runs.append({
                            "run_id": data.get("run_id"),
                            "workflow_id": data.get("workflow_id"),
                            "status": data.get("status"),
                            "started_at": data.get("started_at"),
                            "completed_at": data.get("completed_at"),
                            "total_tokens": data.get("total_tokens", 0),
                            "total_duration": data.get("total_duration", 0),
                        })
                    except Exception:
                        pass
            if len(runs) >= limit:
                break

        return runs
