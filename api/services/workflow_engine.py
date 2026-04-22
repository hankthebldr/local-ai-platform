"""
Workflow Engine — Load, validate, and execute multi-agent workflows

Orchestrates sequential step execution with three-layer context management.
Integrates with ModelResolver for role-based model selection and
StepExecutor for individual step execution with retry logic.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from ..logging_config import logger
from ..exceptions import WorkflowValidationError, WorkflowExecutionError
from ..models.workflow_models import (
    AgentStep,
    WorkflowDefinition,
    WorkflowContext,
    WorkflowRun,
    StepResult,
)
from .model_resolver import ModelResolver
from .step_executor import StepExecutor
from .ollama_service import OllamaService
from .hook_bus import HookBus
from .prompt_composer import PromptComposer


# Default data directory for workflow run persistence
DATA_DIR = os.getenv("WORKFLOW_DATA_DIR", "./data/workflows")


class WorkflowEngine:
    """
    Central orchestrator for multi-agent workflows.

    Phases:
    1. Load — parse YAML into WorkflowDefinition
    2. Validate — check I/O wiring, model availability
    3. Execute — run steps sequentially, manage context
    4. Persist — save run results to disk
    """

    def __init__(self, ollama_service: OllamaService):
        self.ollama = ollama_service
        self.resolver = ModelResolver(ollama_service)
        # Prompt composer
        project_root = Path(__file__).resolve().parents[2]
        self.composer = PromptComposer(
            roles_dir=project_root / "prompts" / "roles",
            templates_dir=project_root / "prompts" / "templates",
        )
        # Hook bus default is built per-step in _build_step_bus()
        self._project_root = project_root

    # ── Load Phase ─────────────────────────────────────────────────────

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

    # ── Validate Phase ─────────────────────────────────────────────────

    def validate(
        self,
        definition: WorkflowDefinition,
        seed_keys: Optional[List[str]] = None,
    ) -> None:
        """
        Validate workflow I/O wiring.

        Checks that every step's declared inputs can be traced to:
        - A seed key
        - A prior step's declared output
        - A shared key produced by a prior step

        Raises WorkflowValidationError if validation fails.
        """
        available_outputs: Set[str] = set()

        # Seed keys are available from the start
        if seed_keys:
            for key in seed_keys:
                available_outputs.add(f"seed.{key}")

        errors = []

        for step in definition.steps:
            # Check all inputs are available
            for input_ref in step.inputs:
                if input_ref not in available_outputs:
                    # Allow seed.* references even if we don't know exact keys
                    if input_ref.startswith("seed.") and seed_keys is None:
                        continue
                    errors.append(
                        f"Step '{step.id}' input '{input_ref}' has no producer. "
                        f"Available: {sorted(available_outputs)}"
                    )

            # Register this step's outputs as available
            for output_key in step.outputs:
                available_outputs.add(f"{step.id}.{output_key}")

        # Check for duplicate step IDs
        step_ids = [s.id for s in definition.steps]
        dupes = [sid for sid in step_ids if step_ids.count(sid) > 1]
        if dupes:
            errors.append(f"Duplicate step IDs: {set(dupes)}")

        if errors:
            raise WorkflowValidationError(
                f"Workflow '{definition.id}' has {len(errors)} validation error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        logger.info(f"Workflow '{definition.id}' validated successfully")

    # ── Execute Phase ──────────────────────────────────────────────────

    def run(
        self,
        definition: WorkflowDefinition,
        seed: Dict[str, Any],
    ) -> WorkflowRun:
        """
        Execute a workflow end-to-end.

        Creates a WorkflowRun, iterates through steps sequentially,
        and returns the completed (or failed) run.
        """
        # Initialize run
        context = WorkflowContext(seed=seed)
        workflow_run = WorkflowRun(
            workflow_id=definition.id,
            context=context,
            started_at=datetime.utcnow(),
        )
        workflow_run.status = "running"

        logger.info(
            f"Starting workflow '{definition.id}' run={workflow_run.run_id} "
            f"({len(definition.steps)} steps)"
        )

        for step in definition.steps:
            logger.info(f"Executing step '{step.id}' ({step.name})")

            # Resolve model for this step
            try:
                resolved_model = self.resolver.resolve(
                    model=step.model,
                    role=step.role,
                    default_role=definition.defaults.role,
                )
            except Exception as e:
                step_result = StepResult(
                    step_id=step.id,
                    status="failed",
                    error=f"Model resolution failed: {e}",
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                )
                workflow_run.step_results.append(step_result)
                workflow_run.status = "failed"
                workflow_run.error = f"Step '{step.id}' failed: model resolution error"
                workflow_run.completed_at = datetime.utcnow()
                logger.error(f"Workflow failed at step '{step.id}': {e}")
                break

            # Execute the step — build a fresh hook bus and executor per step
            step_bus = self._build_step_bus(step)
            step_executor = StepExecutor(
                ollama_service=self.ollama,
                composer=self.composer,
                hook_bus=step_bus,
                model_resolver=self.resolver,
            )
            step_result = step_executor.execute(
                step=step,
                workflow=definition,
                context=context,
                resolved_model=resolved_model,
                defaults=definition.defaults,
                workflow_run=workflow_run,
            )
            workflow_run.step_results.append(step_result)

            # Check for failure — abort workflow
            if step_result.status == "failed":
                workflow_run.status = "failed"
                workflow_run.error = (
                    f"Step '{step.id}' failed after {step_result.retries + 1} attempts: "
                    f"{step_result.error}"
                )
                workflow_run.completed_at = datetime.utcnow()
                logger.error(f"Workflow '{definition.id}' failed at step '{step.id}'")
                break
        else:
            # All steps completed successfully
            workflow_run.status = "completed"
            workflow_run.completed_at = datetime.utcnow()
            total_duration = sum(
                r.duration_seconds or 0 for r in workflow_run.step_results
            )
            total_tokens = sum(
                r.token_count.get("total_tokens", 0) for r in workflow_run.step_results
            )
            logger.info(
                f"Workflow '{definition.id}' completed in {total_duration:.1f}s "
                f"({total_tokens} total tokens)"
            )

        # Persist results
        self._persist_run(workflow_run, definition)

        return workflow_run

    # ── Hook Bus Assembly ──────────────────────────────────────────────

    def _build_step_bus(self, step) -> HookBus:
        """Return a fresh HookBus with default hooks + step-scoped json_schema + YAML-declared hooks."""
        from api.hooks.builtins.token_budget import TokenBudgetHook
        from api.hooks.builtins.output_logger import OutputLoggerHook
        from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
        from api.hooks.builtins.refusal_detector import RefusalDetectorHook
        from api.hooks.builtins.json_schema import JsonSchemaHook

        bus = HookBus()
        # Default hooks
        bus.register(TokenBudgetHook(max_prompt_tokens=3500, reserve_for_output=1024))
        bus.register(OutputLoggerHook(include_prompt=False))
        bus.register(RetryWithFeedbackHook(max_attempts=2, include_example=True))
        bus.register(RefusalDetectorHook(patterns=[], use_family_defaults=True))
        # Step-scoped json_schema (requires output_schema)
        if getattr(step, "output_schema", None):
            bus.register(JsonSchemaHook(schema=step.output_schema, strip_fences=True))
        # YAML-declared per-step hook overrides — safe access (may not be present on v1 steps)
        hooks_block = getattr(step, "hooks", None)
        if hooks_block is not None:
            for stage_name in ("before_step", "transform_prompt", "after_step", "validate_output", "on_failure"):
                for spec in getattr(hooks_block, stage_name, []) or []:
                    bus.register(self._instantiate_hook(spec, stage_name))
        # Custom hooks auto-discovered from api/hooks/custom/
        custom_dir = self._project_root / "api" / "hooks" / "custom"
        if custom_dir.is_dir():
            bus.discover_and_register(custom_dir, source="custom")
        return bus

    def _instantiate_hook(self, spec, stage):
        """Map a YAML HookSpec into a concrete built-in hook instance."""
        from api.hooks.builtins.json_schema import JsonSchemaHook
        from api.hooks.builtins.refusal_detector import RefusalDetectorHook
        from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
        from api.hooks.builtins.token_budget import TokenBudgetHook
        from api.hooks.builtins.output_logger import OutputLoggerHook
        from api.hooks.builtins.few_shot_injector import FewShotInjectorHook

        factory = {
            "json_schema": JsonSchemaHook,
            "refusal_detector": RefusalDetectorHook,
            "retry_with_feedback": RetryWithFeedbackHook,
            "token_budget": TokenBudgetHook,
            "output_logger": OutputLoggerHook,
            "few_shot_injector": FewShotInjectorHook,
        }.get(spec.name)
        if factory is None:
            raise ValueError(f"Unknown built-in hook: {spec.name}")
        return factory(**spec.config)

    # ── Persist Phase ──────────────────────────────────────────────────

    def _persist_run(self, run: WorkflowRun, definition: WorkflowDefinition) -> None:
        """Save workflow run results to disk"""
        run_dir = Path(DATA_DIR) / run.run_id
        artifacts_dir = run_dir / "artifacts"

        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)

            # Save full run as JSON
            run_path = run_dir / "run.json"
            with open(run_path, "w") as f:
                json.dump(run.model_dump(mode="json"), f, indent=2, default=str)

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

            logger.info(f"Run persisted to {run_dir}")

        except Exception as e:
            logger.error(f"Failed to persist run {run.run_id}: {e}")

    def _generate_summary(self, run: WorkflowRun, definition: WorkflowDefinition) -> str:
        """Generate a markdown summary of a workflow run"""
        lines = [
            f"# Workflow Run: {definition.name}",
            f"",
            f"- **Run ID**: {run.run_id}",
            f"- **Workflow**: {definition.id} v{definition.version or '0.0'}",
            f"- **Status**: {run.status}",
            f"- **Started**: {run.started_at}",
            f"- **Completed**: {run.completed_at}",
            f"",
            f"## Steps",
            f"",
        ]

        for result in run.step_results:
            step_def = next((s for s in definition.steps if s.id == result.step_id), None)
            status_icon = "+" if result.status == "completed" else "x"
            lines.append(
                f"### [{status_icon}] {result.step_id}"
                f"{f' -- {step_def.name}' if step_def else ''}"
            )
            lines.append(f"- Model: {result.model_used}")
            lines.append(f"- Duration: {result.duration_seconds:.1f}s" if result.duration_seconds else "- Duration: N/A")
            lines.append(f"- Tokens: {result.token_count.get('total_tokens', 0)}")
            if result.error:
                lines.append(f"- Error: {result.error}")
            lines.append("")

        if run.error:
            lines.extend(["## Error", "", run.error, ""])

        return "\n".join(lines)

    # ── Utilities ──────────────────────────────────────────────────────

    def list_workflows(self, workflows_dir: str = "./workflows") -> List[Dict]:
        """List all available workflow definitions"""
        results = []
        wf_path = Path(workflows_dir)
        if not wf_path.exists():
            return results

        for f in sorted(wf_path.glob("*.yaml")):
            try:
                defn = self.load(str(f))
                results.append({
                    "id": defn.id,
                    "name": defn.name,
                    "description": defn.description,
                    "version": defn.version,
                    "steps": len(defn.steps),
                    "file": str(f),
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
                        })
                    except Exception:
                        pass
            if len(runs) >= limit:
                break

        return runs
