#!/usr/bin/env python3
"""
RunnerRegistry — the active set of Runner instances on this host.

Holds one Runner per RunnerKind. Populated at startup by detect_runners()
(Phase 3) and consumed by the ModelResolver to dispatch a model id to the
runner that serves it.

Phase 1 / Task 1.3 of gpu-runner-abstraction.
See docs/plans/2026-05-23-gpu-runner-abstraction.md
"""

from __future__ import annotations

from typing import Dict, Set

from .runner import Runner, RunnerKind


class RunnerNotConfigured(Exception):
    """Raised when a registry lookup asks for a runner that isn't installed.

    The message names the missing runner so the operator immediately sees
    which dependency to install (e.g. "vllm not configured — set
    ENCLAVE_VLLM_BASE_URLS or install vllm on this host").
    """


def runner_for_registry_entry(entry: dict) -> RunnerKind:
    """Read a MODEL_REGISTRY entry's `runner` field, defaulting to OLLAMA.

    Backwards compat: every existing entry in models/download.py implicitly
    has runner="ollama". This helper centralizes that defaulting so callers
    don't sprinkle `.get("runner", "ollama")` everywhere.

    Raises ValueError if `runner` is set but not a known RunnerKind value
    (catches typos like "ollam" / "rocketship" at parse time).
    """
    raw = entry.get("runner")
    if raw is None:
        return RunnerKind.OLLAMA
    if isinstance(raw, RunnerKind):
        return raw
    try:
        return RunnerKind(str(raw).lower())
    except ValueError as e:
        raise ValueError(
            f"unknown runner value {raw!r} in registry entry "
            f"(valid: {[k.value for k in RunnerKind]})"
        ) from e


class RunnerRegistry:
    """Active Runner instances keyed by RunnerKind.

    Singleton-shaped (one instance per process is typical), but constructed
    explicitly rather than via class-level state so tests can stand up
    isolated registries without monkeypatching globals.
    """

    def __init__(self) -> None:
        self._runners: Dict[RunnerKind, Runner] = {}

    def register(self, runner: Runner) -> None:
        """Add (or replace) a runner. Replacement is intentional — supports
        dev-time swap and clean test setup."""
        self._runners[runner.name] = runner

    def get(self, kind: RunnerKind) -> Runner:
        """Look up a runner by kind. Raises RunnerNotConfigured if missing."""
        if kind not in self._runners:
            installed = (
                ", ".join(sorted(k.value for k in self._runners.keys())) or "<none>"
            )
            raise RunnerNotConfigured(
                f"runner '{kind.value}' is not configured on this host "
                f"(installed: {installed})"
            )
        return self._runners[kind]

    def kinds(self) -> Set[RunnerKind]:
        """All registered runner kinds — for /api/system/runner reporting."""
        return set(self._runners.keys())

    def for_entry(self, entry: dict) -> Runner:
        """Resolve a MODEL_REGISTRY entry to the Runner that serves it.

        Reads entry["runner"] (defaulting to OLLAMA) and returns the
        registered Runner instance. Raises RunnerNotConfigured if the
        entry asks for a runner that isn't installed on this host.
        """
        kind = runner_for_registry_entry(entry)
        return self.get(kind)


# ── Singleton accessor ────────────────────────────────────────────────────
# Phase 3 (architecture-driven selection) populates this from
# detect_runners() during api/main.py startup. Phase 1 just defines the
# accessor shape — no auto-population.


_current_registry: "RunnerRegistry | None" = None


def _set_current(registry: RunnerRegistry) -> None:
    """Used by detect_runners() (Phase 3). Not part of the public API."""
    global _current_registry
    _current_registry = registry


def get_current_registry() -> RunnerRegistry:
    """Return the process-wide RunnerRegistry singleton.

    Raises RuntimeError if called before detect_runners() — mirrors
    Architecture.current() / Deployment.current() semantics.
    """
    if _current_registry is None:
        raise RuntimeError(
            "get_current_registry() called before detect_runners(). "
            "Call detect_runners() during app startup (api/main.py)."
        )
    return _current_registry
