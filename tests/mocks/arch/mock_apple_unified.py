"""Mock fixtures for apple_unified architecture.

Patches the platform/memory probes that UnifiedArchitecture.detect() uses,
so tests can simulate a Mac of any size without running on one.
"""

from __future__ import annotations

import contextlib
from unittest.mock import patch


@contextlib.contextmanager
def patch_apple_unified(
    total_gb: float = 48.0,
    used_gb: float = 10.0,
    swap_active: bool = False,
):
    """Pretend we're running on Apple Silicon with the given memory profile.

    Patches:
        sys.platform -> "darwin"
        api.services.arch_impl.unified._read_psutil_memory -> (total_bytes, used_bytes)
        api.services.arch_impl.unified._read_vm_stat_swap -> swap_active
    """
    total_bytes = int(total_gb * 1024**3)
    used_bytes = int(used_gb * 1024**3)
    with patch("sys.platform", "darwin"):
        with patch(
            "api.services.arch_impl.unified._read_psutil_memory",
            return_value=(total_bytes, used_bytes),
        ):
            with patch(
                "api.services.arch_impl.unified._read_vm_stat_swap",
                return_value=swap_active,
            ):
                yield
