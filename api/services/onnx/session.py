"""Build ONNX Runtime InferenceSessions using the host architecture's
recommended execution providers.

The OnnxExecutionPlan validator already guarantees a CPU floor
(CPUExecutionProvider last) and parallel provider_options, so this module owns
only runtime EP-availability fallback: if the installed wheel can't supply a
requested provider, ORT drops it and we log; CPU always remains.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import onnxruntime as ort  # module-level so tests can monkeypatch `ort`

from ..architecture import Architecture, _get_current
from ...logging_config import logger


def build_session(
    model_path: str, arch: Optional[Architecture] = None
) -> Tuple["ort.InferenceSession", List[str]]:
    """Construct an InferenceSession for `model_path`.

    Reads the architecture's recommended_onnx_providers() (validated: CPU is
    always the last provider, provider_options is parallel). Reports which
    providers actually activated. A requested provider the installed wheel
    can't supply is logged and dropped — the session still runs on the CPU
    floor. Returns (session, active_providers).
    """
    arch = arch or _get_current()
    plan = arch.recommended_onnx_providers()
    try:
        session = ort.InferenceSession(
            model_path,
            providers=plan.providers,
            provider_options=plan.provider_options,
        )
    except Exception as e:  # some EPs raise on construction rather than dropping
        logger.warning(
            f"ONNX session with providers {plan.providers} failed ({e}); "
            f"retrying CPU-only"
        )
        session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])

    active = session.get_providers()
    dropped = [p for p in plan.providers if p not in active]
    if dropped:
        logger.warning(
            f"ONNX providers requested but unavailable, fell back: {dropped}; "
            f"active={active}. Install the matching onnxruntime wheel "
            f"(onnxruntime-gpu / onnxruntime-openvino) to enable them."
        )
    return session, active
