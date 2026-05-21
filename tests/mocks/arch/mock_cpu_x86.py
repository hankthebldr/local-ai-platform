"""Mock fixtures for cpu_x86 architecture (Linux CPU-only)."""

from __future__ import annotations

import contextlib
from unittest.mock import patch


@contextlib.contextmanager
def patch_cpu_x86(
    total_gb: float = 96.0,
    available_gb: float = 80.0,
    no_nvidia: bool = True,
):
    """Pretend we're running on Linux x86 without NVIDIA.

    Patches:
        sys.platform -> "linux"
        api.services.arch_impl.unified._read_proc_meminfo -> (total_bytes, available_bytes)
        pynvml.nvmlInit -> raises NVMLError("Shared Library Not Found") if no_nvidia
    """
    total_bytes = int(total_gb * 1024**3)
    available_bytes = int(available_gb * 1024**3)

    patches = [
        patch("sys.platform", "linux"),
        patch(
            "api.services.arch_impl.unified._read_proc_meminfo",
            return_value=(total_bytes, available_bytes),
        ),
    ]

    if no_nvidia:
        # Make pynvml.nvmlInit raise as it does on a real no-NVIDIA host
        import pynvml

        patches.append(
            patch(
                "pynvml.nvmlInit",
                side_effect=pynvml.NVMLError(pynvml.NVML_ERROR_LIBRARY_NOT_FOUND),
            )
        )

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield
