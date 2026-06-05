"""Three-zone workspace helpers for kind=code.

canonical (persisted, per-run)  <--promote--  scratch (ephemeral, per-step)
                                --stage_in-->
Only declared files_out are promotion candidates; gated/auto_on_green/never.
v1: auto_on_green == (exit_code == 0). `promote_predicate` is reserved (deferred).
"""
from __future__ import annotations

from typing import List

from ...logging_config import logger
from ...models.workflow_models import CodeStepConfig
from ..sandbox_fs import SandboxedFS, SandboxViolation, SandboxQuotaExceeded


def stage_inputs(canon: SandboxedFS, scratch: SandboxedFS, cfg: CodeStepConfig) -> None:
    for rel in cfg.files_in:
        if not canon.exists(rel):
            logger.warning("files_in '%s' not in canonical workspace; skipping", rel)
            continue
        scratch.write_bytes(rel, canon.open(rel, "rb").read())


def promote(
    scratch: SandboxedFS, canon: SandboxedFS, cfg: CodeStepConfig, exit_code: int
) -> List[str]:
    if cfg.promote == "never":
        return []
    if cfg.promote == "auto_on_green" and exit_code != 0:
        return []
    promoted: List[str] = []
    for rel in cfg.files_out:
        try:
            abs_path = scratch.get_absolute_path(
                rel
            )  # re-validate: no traversal/abs escape
        except SandboxViolation:
            logger.warning("files_out '%s' failed re-validation; not promoting", rel)
            continue
        if not abs_path.exists():
            continue
        try:
            canon.write_bytes(rel, abs_path.read_bytes())
        except SandboxQuotaExceeded:
            logger.warning("files_out '%s' exceeds canon quota; not promoting", rel)
            continue
        promoted.append(rel)
    return promoted
