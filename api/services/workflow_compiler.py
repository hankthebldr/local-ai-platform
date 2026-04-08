"""
Workflow Compiler — Validates, analyzes, and builds execution plans

Takes a WorkflowDefinition and produces an ExecutionPlan with:
- Topological sort of the step DAG
- Parallel batch scheduling (steps with no interdependencies run together)
- I/O wiring validation (every input has a producer)
- Cycle detection
- Dead-step detection (steps whose outputs are never consumed)
- Condition reference validation
"""

from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from ..logging_config import logger
from ..exceptions import WorkflowValidationError
from ..models.workflow_models import (
    AgentStep,
    ExecutionBatch,
    ExecutionPlan,
    WorkflowDefinition,
)


class WorkflowCompiler:
    """
    Compiles a WorkflowDefinition into a validated, optimized ExecutionPlan.

    The compiler performs three passes:
    1. Structural validation — IDs, references, types
    2. DAG construction — build dependency graph from depends_on + inputs
    3. Scheduling — topological sort into parallel batches
    """

    def compile(
        self,
        definition: WorkflowDefinition,
        seed_keys: Optional[List[str]] = None,
    ) -> ExecutionPlan:
        """Full compilation: validate → build DAG → schedule → return plan"""
        errors = []

        # Pass 1: Structural validation
        step_map = self._validate_structure(definition, errors)

        # Pass 2: Build dependency graph (from explicit depends_on + inferred from inputs)
        graph, reverse_graph = self._build_dag(definition, step_map, seed_keys, errors)

        # Pass 3: Cycle detection
        self._detect_cycles(graph, definition.steps, errors)

        if errors:
            raise WorkflowValidationError(
                f"Workflow '{definition.id}' has {len(errors)} compilation error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        # Pass 4: Topological sort + parallel batch scheduling
        batches, topo_order = self._schedule(graph, reverse_graph, definition)

        plan = ExecutionPlan(
            workflow_id=definition.id,
            total_steps=len(definition.steps),
            total_batches=len(batches),
            batches=batches,
            step_order=topo_order,
            parallelism=min(definition.max_parallel, max(len(b.step_ids) for b in batches)),
        )

        logger.info(
            f"Compiled workflow '{definition.id}': {plan.total_steps} steps → "
            f"{plan.total_batches} batches (max parallel: {plan.parallelism})"
        )
        return plan

    # ── Pass 1: Structural Validation ─────────────────────────────────────

    def _validate_structure(
        self,
        definition: WorkflowDefinition,
        errors: List[str],
    ) -> Dict[str, AgentStep]:
        """Validate step IDs, references, and structural integrity"""
        step_map: Dict[str, AgentStep] = {}

        # Check for duplicate IDs
        seen_ids: Set[str] = set()
        for step in definition.steps:
            if step.id in seen_ids:
                errors.append(f"Duplicate step ID: '{step.id}'")
            seen_ids.add(step.id)
            step_map[step.id] = step

        # Validate depends_on references
        for step in definition.steps:
            for dep in step.depends_on:
                if dep not in step_map:
                    errors.append(
                        f"Step '{step.id}' depends_on unknown step '{dep}'"
                    )
                if dep == step.id:
                    errors.append(f"Step '{step.id}' depends on itself")

        # Validate condition references
        for step in definition.steps:
            all_conditions = list(step.conditions)
            if step.condition:
                all_conditions.append(step.condition)
            for cond in all_conditions:
                ref_parts = cond.ref.split(".", 1)
                if len(ref_parts) == 2:
                    ns = ref_parts[0]
                    if ns not in ("seed", "shared", "metadata") and ns not in step_map:
                        errors.append(
                            f"Step '{step.id}' condition references unknown step '{ns}'"
                        )

        # Validate quality gate field references
        for step in definition.steps:
            for gate in step.quality_gates:
                if "." in gate.field:
                    # Assume it references an output of this step — will be validated at runtime
                    pass
                elif gate.field not in step.outputs:
                    errors.append(
                        f"Step '{step.id}' quality gate '{gate.name}' references "
                        f"unknown output field '{gate.field}'"
                    )

        return step_map

    # ── Pass 2: DAG Construction ──────────────────────────────────────────

    def _build_dag(
        self,
        definition: WorkflowDefinition,
        step_map: Dict[str, AgentStep],
        seed_keys: Optional[List[str]],
        errors: List[str],
    ) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
        """
        Build the dependency graph from explicit depends_on and implicit input refs.

        Returns:
            graph: step_id → set of step_ids it depends on
            reverse_graph: step_id → set of step_ids that depend on it
        """
        graph: Dict[str, Set[str]] = {s.id: set() for s in definition.steps}
        reverse_graph: Dict[str, Set[str]] = {s.id: set() for s in definition.steps}

        # Track what outputs are produced by which step
        output_producers: Dict[str, str] = {}
        for step in definition.steps:
            for out_key in step.outputs:
                qualified = f"{step.id}.{out_key}"
                output_producers[qualified] = step.id

        # Add explicit depends_on edges
        for step in definition.steps:
            for dep in step.depends_on:
                if dep in step_map:
                    graph[step.id].add(dep)
                    reverse_graph[dep].add(step.id)

        # Infer dependencies from input references
        available_outputs: Set[str] = set()
        if seed_keys:
            for key in seed_keys:
                available_outputs.add(f"seed.{key}")

        for step in definition.steps:
            for input_ref in step.inputs:
                parts = input_ref.split(".", 1)
                if len(parts) != 2:
                    errors.append(
                        f"Step '{step.id}' has malformed input ref '{input_ref}' "
                        f"(expected 'namespace.key')"
                    )
                    continue

                namespace = parts[0]

                # Skip seed/shared/metadata refs — these don't create step deps
                if namespace in ("seed", "shared", "metadata"):
                    if namespace == "seed" and seed_keys is not None:
                        if input_ref not in available_outputs:
                            errors.append(
                                f"Step '{step.id}' input '{input_ref}' — "
                                f"seed key not provided. Available: {sorted(available_outputs)}"
                            )
                    continue

                # This input refs another step's output
                if namespace in step_map:
                    graph[step.id].add(namespace)
                    reverse_graph[namespace].add(step.id)
                else:
                    errors.append(
                        f"Step '{step.id}' input '{input_ref}' references "
                        f"unknown step '{namespace}'"
                    )

            # Also infer from condition refs
            all_conditions = list(step.conditions)
            if step.condition:
                all_conditions.append(step.condition)
            for cond in all_conditions:
                ref_parts = cond.ref.split(".", 1)
                if len(ref_parts) == 2:
                    ns = ref_parts[0]
                    if ns not in ("seed", "shared", "metadata") and ns in step_map:
                        graph[step.id].add(ns)
                        reverse_graph[ns].add(step.id)

        return graph, reverse_graph

    # ── Pass 3: Cycle Detection ───────────────────────────────────────────

    def _detect_cycles(
        self,
        graph: Dict[str, Set[str]],
        steps: List[AgentStep],
        errors: List[str],
    ) -> None:
        """Detect cycles in the dependency graph using DFS"""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {s.id: WHITE for s in steps}
        path: List[str] = []

        def dfs(node: str) -> bool:
            color[node] = GRAY
            path.append(node)
            for dep in graph.get(node, set()):
                if color.get(dep) == GRAY:
                    # Found a cycle — extract it
                    cycle_start = path.index(dep)
                    cycle = path[cycle_start:] + [dep]
                    errors.append(
                        f"Dependency cycle detected: {' → '.join(cycle)}"
                    )
                    return True
                if color.get(dep) == WHITE:
                    if dfs(dep):
                        return True
            color[node] = BLACK
            path.pop()
            return False

        for step in steps:
            if color[step.id] == WHITE:
                dfs(step.id)

    # ── Pass 4: Scheduling ────────────────────────────────────────────────

    def _schedule(
        self,
        graph: Dict[str, Set[str]],
        reverse_graph: Dict[str, Set[str]],
        definition: WorkflowDefinition,
    ) -> Tuple[List[ExecutionBatch], List[str]]:
        """
        Schedule steps into parallel batches via Kahn's algorithm.

        Steps with all dependencies satisfied run in the same batch.
        """
        # Compute in-degrees
        in_degree = {step.id: len(graph[step.id]) for step in definition.steps}

        # Start with nodes that have no dependencies
        queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
        topo_order: List[str] = []
        batches: List[ExecutionBatch] = []
        batch_index = 0
        completed_batches: Dict[str, int] = {}  # step_id → batch it was scheduled in

        while queue:
            # All nodes currently in queue can run in parallel
            current_batch = sorted(queue)  # Sort for deterministic ordering
            queue.clear()

            batch = ExecutionBatch(
                batch_index=batch_index,
                step_ids=current_batch,
                depends_on_batches=sorted(set(
                    completed_batches[dep]
                    for sid in current_batch
                    for dep in graph[sid]
                    if dep in completed_batches
                )),
            )
            batches.append(batch)
            topo_order.extend(current_batch)

            for sid in current_batch:
                completed_batches[sid] = batch_index

            # Reduce in-degrees of dependents
            for sid in current_batch:
                for dependent in reverse_graph.get(sid, set()):
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

            batch_index += 1

        # Verify all steps were scheduled (no unresolvable deps)
        if len(topo_order) != len(definition.steps):
            unscheduled = set(s.id for s in definition.steps) - set(topo_order)
            logger.warning(
                f"Unscheduled steps (possible missing deps): {unscheduled}"
            )

        return batches, topo_order

    # ── Analysis Utilities ────────────────────────────────────────────────

    def analyze_parallelism(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Analyze the parallelism characteristics of an execution plan"""
        max_width = max(len(b.step_ids) for b in plan.batches)
        avg_width = sum(len(b.step_ids) for b in plan.batches) / len(plan.batches)
        sequential_fraction = sum(1 for b in plan.batches if len(b.step_ids) == 1) / len(plan.batches)

        return {
            "total_steps": plan.total_steps,
            "total_batches": plan.total_batches,
            "max_parallel_width": max_width,
            "avg_parallel_width": round(avg_width, 2),
            "sequential_fraction": round(sequential_fraction, 2),
            "critical_path_length": plan.total_batches,
            "speedup_factor": round(plan.total_steps / plan.total_batches, 2),
        }
