"""Mock fixture: NVML+platform probes all fail. Detector must degrade to UNKNOWN."""

from __future__ import annotations

import contextlib
from unittest.mock import patch


@contextlib.contextmanager
def patch_no_detection():
    """Force every detection probe to fail."""
    patches = [
        patch("sys.platform", "freebsd11"),  # not darwin, not linux
        patch(
            "api.services.arch_impl.unified._read_psutil_memory",
            side_effect=Exception("psutil unavailable"),
        ),
        patch(
            "api.services.arch_impl.unified._read_proc_meminfo",
            side_effect=Exception("/proc unavailable"),
        ),
    ]
    try:
        import pynvml

        patches.append(
            patch(
                "pynvml.nvmlInit",
                side_effect=pynvml.NVMLError(pynvml.NVML_ERROR_LIBRARY_NOT_FOUND),
            )
        )
    except ImportError:
        pass

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield
