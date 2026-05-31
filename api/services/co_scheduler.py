"""
Co-scheduler — resource-maximization compiler pass.

Phase 2b of the MCP & Skills plan. Walks the workflow's leaf steps and
asks, for each one, "does (model footprint + MCP RSS) fit alongside this
deployment's effective memory budget?" Steps that don't fit are
**contention steps**; the pass picks an action per the priority order:

  1. **Archetype-aware substitution** — if the step has an archetype,
     try the next smaller model in that role family (a ``bash_script``
     step's smaller option stays a *coding* model).
  2. **Split** — if the step bundles a heavy model + a single MCP, suggest
     splitting into an MCP-bound step (lightweight model) and a
     model-bound step (no MCPs).
  3. **Reorder** — if the chain has slack (an earlier position where no
     MCPs are active), suggest moving the step there.
  4. **Block** — refuse to compile; operator must rewrite.

The action choice obeys the workflow-level ``co_scheduling_policy``:

  ``off``              — no analysis
  ``recommend`` (default) — emit suggestions; workflow runs unchanged
  ``warn_strict``      — promote suggestions to warnings (still runs)
  ``reject``           — block compile on any contention step
  ``auto_substitute``  — apply ``recommend_smaller_model`` automatically
                         when available, leaves the rest as recommendations

The actual *application* of auto_substitute (rewriting the workflow's
model field) is deferred to the engine integration that wires this
output into ``WorkflowEngine.validate``; this module just produces the
recommendation records.

MCP RSS estimates: we don't have a per-server RSS history yet, so we use
a conservative ``DEFAULT_MCP_RSS_GB`` per declared server. Once the run
record starts persisting peak_rss_mb (from MCPRunnerStats — Phase 2),
``MCPService.peak_rss_gb_estimate`` will look up the running average.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from ..logging_config import logger
from ..models.workflow_models import AgentStep, WorkflowDefinition
from .archetypes import get_archetype, infer_archetype
from .model_resolver import ROLE_PATTERNS

# ── Tunables ─────────────────────────────────────────────────────────────


# Conservative per-MCP RSS estimate when we have no observed history.
# Lower than the design's 1 GB to avoid false-positive contention on
# lightweight stdio MCPs (filesystem, web-search) that typically peak
# under 500 MB.
DEFAULT_MCP_RSS_GB = 0.5

# KV-cache headroom on top of declared est_size_gb. Matches the unified-arch
# feasibility check (15%).
KV_HEADROOM_PCT = 0.15

# Safety margin on the budget: we flag contention when combined pressure
# exceeds budget × CONTENTION_BUDGET_PCT, not the full budget. Matches the
# design's 85% threshold.
CONTENTION_BUDGET_PCT = 0.85


CoSchedulingPolicy = Literal[
    "off",
    "recommend",
    "warn_strict",
    "reject",
    "auto_substitute",
]

RecommendationAction = Literal[
    "recommend_smaller_model",
    "recommend_split_step",
    "recommend_reorder",
    "block_with_error",
]


# ── Result models ────────────────────────────────────────────────────────


class StepPressure(BaseModel):
    """Per-step memory pressure breakdown."""

    step_id: str
    model_footprint_gb: float
    mcp_servers_in_use: List[str]
    mcp_peak_rss_gb_estimate: float
    combined_pressure_gb: float
    effective_budget_gb: float
    is_contention: bool
    archetype: Optional[str] = None


class OptimizationRecommendation(BaseModel):
    """One action the operator (or auto-substitute) can take to resolve a
    contention step.

    ``rationale`` is human-readable for the composer UI / CLI; the action
    code + suggested_* fields are structured so the auto-substitute path
    can apply them programmatically.
    """

    step_id: str
    action: RecommendationAction
    contention_pressure_gb: float
    available_budget_gb: float
    rationale: str
    archetype: Optional[str] = None
    suggested_substitution: Optional[str] = None
    suggested_split: Optional[Dict[str, Any]] = None
    suggested_reorder_position: Optional[int] = None


class CoSchedulingResult(BaseModel):
    """What ``apply_co_scheduling_policy`` returned.

    ``errors`` block compile (only populated under ``reject``); the engine
    raises ``WorkflowValidationError`` containing the human messages.
    ``warnings`` are non-fatal advisories surfaced in the validate-response
    body. ``recommendations`` is the raw advisory feed (composer renders
    these inline).
    """

    pressures: Dict[str, StepPressure] = Field(default_factory=dict)
    recommendations: List[OptimizationRecommendation] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


# ── Pressure computation ────────────────────────────────────────────────


def _leaf_steps(step: AgentStep) -> List[AgentStep]:
    """Same walker shape as extension_preflight._leaf_steps."""
    out: List[AgentStep] = [step]
    for branch in step.branches or []:
        out.extend(_leaf_steps(branch))
    if step.gather is not None:
        out.extend(_leaf_steps(step.gather))
    for body_step in step.body or []:
        out.extend(_leaf_steps(body_step))
    for worker in (step.workers or {}).values():
        out.extend(_leaf_steps(worker))
    return out


def _flatten(workflow: WorkflowDefinition) -> List[AgentStep]:
    out: List[AgentStep] = []
    for top in workflow.steps:
        out.extend(_leaf_steps(top))
    return out


def _model_footprint_gb(step: AgentStep) -> float:
    """The step's declared est_size_gb × KV headroom. Returns 0 when the
    operator didn't size the step (the analysis is opt-in — the pre-Phase-4
    feasibility path has the same shape)."""
    if step.est_size_gb is None or step.est_size_gb <= 0:
        return 0.0
    return step.est_size_gb * (1 + KV_HEADROOM_PCT)


def _mcp_rss_estimate_gb(step: AgentStep, mcp_service=None) -> Tuple[List[str], float]:
    """Best-effort estimate of MCP RSS across all servers this step uses."""
    server_ids: List[str] = []
    seen = set()
    for tool in step.tools:
        if not tool.mcp:
            continue
        sid = tool.mcp.split(".", 1)[0]
        if sid not in seen:
            seen.add(sid)
            server_ids.append(sid)
    if not server_ids:
        return [], 0.0

    # When MCPService has a per-server RSS history (peak_rss_gb_estimate),
    # use it; otherwise fall back to the conservative default. The lookup is
    # designed so tests can pass a fake mcp_service with the method defined.
    total = 0.0
    for sid in server_ids:
        observed = None
        if mcp_service is not None:
            est = getattr(mcp_service, "peak_rss_gb_estimate", None)
            if est is not None:
                try:
                    observed = est(sid)
                except Exception:  # noqa: BLE001
                    observed = None
        total += (
            observed if (observed is not None and observed > 0) else DEFAULT_MCP_RSS_GB
        )
    return server_ids, round(total, 3)


def _arch_budget_gb(arch=None) -> float:
    """The contention threshold = effective memory × 85%.

    Prefer the *deployment*'s effective memory (Phase 6 subtracts live MCP
    overhead), then fall back to the architecture's total_memory_gb.
    Returns 0.0 when nothing is detected — callers see "no contention"
    rather than a crash."""
    # Deployment effective memory (Phase 6 — already subtracts pool overhead).
    try:
        from .deployment import _get_current as _get_dep

        d = _get_dep()
        eff = d.effective_memory_gb()
        if eff > 0:
            return eff * CONTENTION_BUDGET_PCT
    except Exception:  # noqa: BLE001
        pass
    # Fallback to arch.total_memory_gb.
    if arch is not None and getattr(arch, "total_memory_gb", 0):
        return arch.total_memory_gb * CONTENTION_BUDGET_PCT
    try:
        from .architecture import _get_current as _get_arch

        a = _get_arch()
        return getattr(a, "total_memory_gb", 0.0) * CONTENTION_BUDGET_PCT
    except Exception:  # noqa: BLE001
        return 0.0


def compute_pressures(
    workflow: WorkflowDefinition,
    arch=None,
    mcp_service=None,
) -> Dict[str, StepPressure]:
    """Walk every leaf step; emit one ``StepPressure`` per step.

    The result map preserves the leaf walk's order (Python dict order).
    Skips composite kinds with no model and no tools — they're empty
    parents whose pressure is the sum of their children, already accounted
    for separately.
    """
    budget = _arch_budget_gb(arch=arch)
    pressures: Dict[str, StepPressure] = {}
    for step in _flatten(workflow):
        model_gb = _model_footprint_gb(step)
        servers, mcp_gb = _mcp_rss_estimate_gb(step, mcp_service)
        # Composite parents (parallel/loop/orchestrator/ralph) typically have
        # no model + no tools — skip so we don't pollute the pressure map.
        if model_gb == 0.0 and not servers:
            continue
        combined = round(model_gb + mcp_gb, 3)
        pressures[step.id] = StepPressure(
            step_id=step.id,
            model_footprint_gb=round(model_gb, 3),
            mcp_servers_in_use=servers,
            mcp_peak_rss_gb_estimate=mcp_gb,
            combined_pressure_gb=combined,
            effective_budget_gb=round(budget, 3),
            is_contention=(budget > 0 and combined > budget),
            archetype=infer_archetype(step),
        )
    return pressures


# ── Smaller-model lookup (in-archetype) ─────────────────────────────────


def _model_size_gb(name: str) -> float:
    """Cheap heuristic — pull the trailing size token from an Ollama model
    name. ``llama3.3:70b`` → 70.0; ``qwen2.5:1.5b`` → 1.5; ``phi`` → 2.7
    (a known default). Used by ``pick_smaller_in_archetype`` to compare
    candidates; not a precise GB figure."""
    import re

    m = re.search(r":(\d+(?:\.\d+)?)b", name.lower())
    if m:
        return float(m.group(1))
    # Heuristic defaults for size-less tags.
    nlower = name.lower()
    if "phi" in nlower:
        return 2.7
    if "gemma" in nlower:
        return 2.0
    return 7.0


def pick_smaller_in_archetype(
    current_model: Optional[str],
    archetype_name: str,
    pressure: StepPressure,
    available_models: Optional[List[str]] = None,
) -> Optional[str]:
    """Pick the largest model in ``archetype.default_role`` that fits.

    "Fits" means: candidate footprint (× KV) + the step's MCP RSS estimate
    is under the effective budget. Returns None when nothing fits.

    ``available_models`` is normally the role-pattern list; tests inject a
    custom list (so they don't depend on a live Ollama instance).
    """
    spec = get_archetype(archetype_name)
    if spec is None:
        return None
    role = spec.get("default_role", "general")
    candidates = available_models or ROLE_PATTERNS.get(role, [])
    if not candidates:
        return None

    budget = pressure.effective_budget_gb
    headroom = budget - pressure.mcp_peak_rss_gb_estimate
    if headroom <= 0:
        return None

    # Score each candidate: smallest model that still fits headroom × KV.
    # Stay strictly smaller than the current model (avoid recommending a
    # no-op or upgrade).
    current_size = _model_size_gb(current_model) if current_model else float("inf")
    fitting: List[Tuple[str, float]] = []
    for cand in candidates:
        size = _model_size_gb(cand)
        if size >= current_size:
            continue
        # Apply KV headroom on top of the candidate size.
        if size * (1 + KV_HEADROOM_PCT) <= headroom:
            fitting.append((cand, size))
    if not fitting:
        return None
    # Prefer the largest-that-fits (most capable while still under budget).
    fitting.sort(key=lambda t: -t[1])
    return fitting[0][0]


# ── Reorder slack ──────────────────────────────────────────────────────


def _find_chain_slack(
    step: AgentStep,
    workflow: WorkflowDefinition,
    pressures: Dict[str, StepPressure],
) -> Optional[int]:
    """Return an earlier index in the top-level chain where the step's
    heavy model could fit with no MCPs resident.

    Only considers the top-level sequential chain — recursion into composite
    kinds is out of scope for v1. Returns None when no such slot exists.
    """
    top_ids = [s.id for s in workflow.steps]
    if step.id not in top_ids:
        return None
    cur_index = top_ids.index(step.id)
    # Find the first index where (a) the predecessor is not MCP-active and
    # (b) the candidate's model alone fits.
    candidate_pressure = pressures.get(step.id)
    if candidate_pressure is None or candidate_pressure.model_footprint_gb == 0:
        return None
    for i, sid in enumerate(top_ids[:cur_index]):
        adjacent_pressure = pressures.get(sid)
        if adjacent_pressure is None or not adjacent_pressure.mcp_servers_in_use:
            # No MCPs near this position → model-only fit check.
            if (
                candidate_pressure.model_footprint_gb
                <= candidate_pressure.effective_budget_gb
            ):
                return i
    return None


# ── Action picker ──────────────────────────────────────────────────────


def choose_action(
    pressure: StepPressure,
    step: AgentStep,
    workflow: WorkflowDefinition,
    pressures: Dict[str, StepPressure],
    available_models: Optional[List[str]] = None,
) -> OptimizationRecommendation:
    """Pick the right action for a contention step.

    Priority order (matches the design doc):
      1. archetype-aware substitution
      2. split (only when one MCP + heavy model bundled in one step)
      3. reorder (when chain slack exists)
      4. block
    """
    archetype = pressure.archetype

    # 1. Archetype-aware substitution.
    if archetype is not None:
        smaller = pick_smaller_in_archetype(
            step.model, archetype, pressure, available_models=available_models
        )
        if smaller is not None:
            return OptimizationRecommendation(
                step_id=step.id,
                action="recommend_smaller_model",
                contention_pressure_gb=pressure.combined_pressure_gb,
                available_budget_gb=pressure.effective_budget_gb,
                rationale=(
                    f"archetype '{archetype}' has a smaller in-role option "
                    f"('{smaller}') that fits alongside the step's MCP RSS"
                ),
                suggested_substitution=smaller,
                archetype=archetype,
            )

    # 2. Split — model + a single MCP. Operator with multiple tools chose to
    # bundle them; we don't unbundle without explicit consent.
    if step.model and len(step.tools) == 1 and step.tools[0].mcp:
        return OptimizationRecommendation(
            step_id=step.id,
            action="recommend_split_step",
            contention_pressure_gb=pressure.combined_pressure_gb,
            available_budget_gb=pressure.effective_budget_gb,
            rationale=(
                "MCP + heavy model in one step; split into a "
                "lightweight MCP-bound step + a model-bound step"
            ),
            suggested_split={
                "mcp_step": {
                    "role": "lightweight",
                    "tools": [step.tools[0].model_dump()],
                },
                "model_step": {
                    "model": step.model,
                    "tools": [],
                },
            },
            archetype=archetype,
        )

    # 3. Reorder.
    new_pos = _find_chain_slack(step, workflow, pressures)
    if new_pos is not None:
        return OptimizationRecommendation(
            step_id=step.id,
            action="recommend_reorder",
            contention_pressure_gb=pressure.combined_pressure_gb,
            available_budget_gb=pressure.effective_budget_gb,
            rationale=(
                f"chain has slack at position {new_pos} where MCPs are inactive"
            ),
            suggested_reorder_position=new_pos,
            archetype=archetype,
        )

    # 4. Block.
    return OptimizationRecommendation(
        step_id=step.id,
        action="block_with_error",
        contention_pressure_gb=pressure.combined_pressure_gb,
        available_budget_gb=pressure.effective_budget_gb,
        rationale=(
            "step exceeds budget; no in-archetype substitute fits, "
            "step has bundled tools (cannot split safely), chain has no slack"
        ),
        archetype=archetype,
    )


# ── Policy application ────────────────────────────────────────────────


def apply_co_scheduling_policy(
    workflow: WorkflowDefinition,
    policy: CoSchedulingPolicy = "recommend",
    arch=None,
    mcp_service=None,
    available_models: Optional[List[str]] = None,
) -> CoSchedulingResult:
    """Run the pressure walk + action picker under ``policy``."""
    result = CoSchedulingResult()
    if policy == "off":
        return result

    pressures = compute_pressures(workflow, arch=arch, mcp_service=mcp_service)
    result.pressures = pressures

    contention = [p for p in pressures.values() if p.is_contention]
    if not contention:
        return result

    step_by_id = {s.id: s for s in _flatten(workflow)}
    for p in contention:
        step = step_by_id.get(p.step_id)
        if step is None:
            continue
        rec = choose_action(
            p, step, workflow, pressures, available_models=available_models
        )
        result.recommendations.append(rec)

        if policy == "reject":
            result.errors.append(
                f"step '{p.step_id}' exceeds budget "
                f"({p.combined_pressure_gb:.1f} GB > "
                f"{p.effective_budget_gb:.1f} GB); "
                f"action: {rec.action}"
            )
        elif policy == "warn_strict":
            result.warnings.append(
                f"[strict] {rec.action} for step '{p.step_id}': {rec.rationale}"
            )
        # 'recommend' and 'auto_substitute' don't emit errors/warnings here;
        # the engine surfaces recommendations to the operator. The actual
        # substitution rewrite for auto_substitute is left to a follow-up
        # that wires this into validate.

    logger.info(
        "co-scheduler: policy=%s contention=%d recommendations=%d",
        policy,
        len(contention),
        len(result.recommendations),
    )
    return result
