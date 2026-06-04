"""Remove per-run code-exec scratch dirs older than the TTL. Mirrors the
SessionManager archive-then-clean precedent (simplified: log + rmtree)."""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import List

from ..logging_config import logger


def reap_scratch(ttl_hours: int = 24, base: str = "data/sandboxes") -> List[str]:
    root = Path(base)
    if not root.exists():
        return []
    cutoff = time.time() - ttl_hours * 3600
    removed: List[str] = []
    for d in root.iterdir():
        if d.is_dir() and d.name.startswith("wf-") and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
            logger.info("reaped stale sandbox scratch: %s", d.name)
    return removed
