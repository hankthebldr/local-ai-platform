#!/usr/bin/env python3
"""
detect_runners() — build and install the host's RunnerRegistry at startup.

Phase 3 of gpu-runner-abstraction (the wiring that lights up the Runner
abstraction). Mirrors detect_architecture() / detect_deployment(): called
once from api/main.py's lifespan, installs a process-wide singleton, and is
idempotent.

Selection policy (Linux / NVIDIA reference — the BD790i Blackwell box):
    - Ollama is ALWAYS registered. It's the universal GGUF fallback and the
      thing every existing call site already uses, so it must stay available
      even when vLLM is the preferred performance path.
    - vLLM is registered when ENCLAVE_VLLM_BASE_URLS is set (comma-separated;
      Phase 2 wires the first URL). The server is launched out-of-band
      (systemd / scripts/vllm-serve.sh); we only need a reachable URL.
    - ENCLAVE_PREFERRED_RUNNER (ollama|vllm) is a dev/operator escape hatch.
      It records which runner the operator wants as the default for models
      that don't pin one. Per-model dispatch still flows through
      ModelResolver.resolve_with_runner() + the MODEL_REGISTRY `runner` field.

Registering an unreachable vLLM:
    By default we register the VllmRunner even if the health probe fails at
    startup — the server may come up moments later, and RunnerNotConfigured
    (the alternative) would wrongly imply the operator never asked for vLLM.
    The unreachable state is logged loudly. STRICT_RUNNER_DETECTION=true flips
    this: an unreachable configured vLLM raises, for CI / fail-fast deploys.

See docs/deployment/vllm-backend.md for the operator guide.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from .ollama_service import OllamaService
from .runner import RunnerKind
from .runner_impl.ollama import OllamaRunner
from .runner_impl.vllm import VllmRunner
from .runner_registry import RunnerRegistry, _set_current

logger = logging.getLogger("local-ai")


def _vllm_base_urls() -> List[str]:
    raw = os.getenv("ENCLAVE_VLLM_BASE_URLS", "").strip()
    if not raw:
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]


def _preferred_runner() -> Optional[RunnerKind]:
    raw = os.getenv("ENCLAVE_PREFERRED_RUNNER", "").strip().lower()
    if not raw:
        return None
    try:
        return RunnerKind(raw)
    except ValueError:
        logger.warning(
            "ENCLAVE_PREFERRED_RUNNER=%r is not a valid runner (%s); ignoring",
            raw,
            [k.value for k in RunnerKind],
        )
        return None


def detect_runners(
    ollama_service: Optional[OllamaService] = None,
    strict: bool = False,
) -> RunnerRegistry:
    """Detect configured inference backends and install the RunnerRegistry
    singleton.

    Args:
        ollama_service: reuse the app's existing OllamaService singleton so we
            don't open a second connection pool. Falls back to a fresh one.
        strict: when True, a configured-but-unreachable vLLM raises RuntimeError
            (STRICT_RUNNER_DETECTION). When False (default), it's registered
            and the unreachable state is logged.

    Returns the populated registry (also installed as the singleton).
    """
    strict = strict or os.getenv("STRICT_RUNNER_DETECTION", "false").lower() == "true"
    registry = RunnerRegistry()

    # 1. Ollama — always present (universal fallback).
    svc = ollama_service or OllamaService()
    registry.register(OllamaRunner(svc))

    # 2. vLLM — opt-in via ENCLAVE_VLLM_BASE_URLS.
    urls = _vllm_base_urls()
    if urls:
        if len(urls) > 1:
            logger.info(
                "ENCLAVE_VLLM_BASE_URLS lists %d servers; Phase 2 wires the "
                "first (%s). Multi-server fleet dispatch is a later phase.",
                len(urls),
                urls[0],
            )
        max_conc = int(os.getenv("ENCLAVE_VLLM_MAX_CONCURRENT", "256"))
        runner = VllmRunner(base_url=urls[0], max_concurrent_requests=max_conc)
        health = runner.health()
        if health.reachable:
            registry.register(runner)
            logger.info(
                "vLLM runner registered: %s (version=%s, serving=%s)",
                runner.base_url,
                health.version or "?",
                health.loaded_models or "[]",
            )
        elif strict:
            raise RuntimeError(
                f"vLLM configured at {runner.base_url} but unreachable, and "
                f"STRICT_RUNNER_DETECTION is enabled. Start the server "
                f"(scripts/vllm-serve.sh) or unset ENCLAVE_VLLM_BASE_URLS."
            )
        else:
            # Register anyway — the server may be starting. Dispatch to it will
            # surface a clear connection error rather than RunnerNotConfigured.
            registry.register(runner)
            logger.warning(
                "vLLM configured at %s but unreachable at startup; registered "
                "optimistically. Models pinned to runner=vllm will fail until "
                "the server is up. See docs/deployment/vllm-backend.md",
                runner.base_url,
            )

    # 3. Preferred-runner escape hatch (recorded for reporting; per-model
    #    dispatch still flows through the MODEL_REGISTRY `runner` field).
    preferred = _preferred_runner()
    if preferred is not None and preferred not in registry.kinds():
        logger.warning(
            "ENCLAVE_PREFERRED_RUNNER=%s but that runner isn't registered "
            "(registered: %s); preference ignored.",
            preferred.value,
            sorted(k.value for k in registry.kinds()),
        )
        preferred = None
    # Stash the preference on the registry for /api/system/runner to report.
    registry.preferred_runner = preferred  # type: ignore[attr-defined]

    _set_current(registry)
    logger.info(
        "Runners detected: %s%s",
        sorted(k.value for k in registry.kinds()),
        f" (preferred: {preferred.value})" if preferred else "",
    )
    return registry
