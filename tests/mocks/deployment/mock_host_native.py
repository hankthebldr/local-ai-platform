"""Mock fixture for host_native deployment (bare python api/main.py)."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


@contextlib.contextmanager
def patch_host_native(
    cwd: str = None,
    home: str = None,
    host_memory_gb: float = 96.0,
    platform: str = None,  # None = use the actual host platform (avoids psutil import issues)
    ollama_url: str = "http://127.0.0.1:11434",
):
    """Pretend we're running `python api/main.py` directly on a bare host.

    Patches:
        os.getcwd                         -> cwd
        Path.home                         -> home
        sys.platform                      -> "linux" or "darwin"
        sys.frozen                        -> not set (key absence)
        os.path.exists("/.dockerenv")     -> False
        psutil.virtual_memory().total     -> host_memory_gb
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd_path = Path(cwd) if cwd else Path(tmpdir) / "cwd"
        cwd_path.mkdir(parents=True, exist_ok=True)
        # Pre-create data/logs/ so the logging RotatingFileHandler can write
        # if anything triggers logging during the test (FastAPI middleware, etc.)
        (cwd_path / "data" / "logs").mkdir(parents=True, exist_ok=True)
        home_path = Path(home) if home else Path(tmpdir) / "home"
        home_path.mkdir(parents=True, exist_ok=True)

        class FakeMem:
            total = int(host_memory_gb * 1024**3)
            available = int(host_memory_gb * 0.7 * 1024**3)
            used = int(host_memory_gb * 0.3 * 1024**3)

        real_exists = os.path.exists

        def fake_exists(path):
            if path == "/.dockerenv":
                return False
            if path == "/proc/1/cgroup":
                return False
            return real_exists(path)

        # Force-remove sys.frozen if present
        import sys

        had_frozen = hasattr(sys, "frozen")
        original_frozen = getattr(sys, "frozen", None)
        if had_frozen:
            del sys.frozen

        patches = [
            patch("os.path.exists", side_effect=fake_exists),
            patch("os.getcwd", return_value=str(cwd_path)),
            patch("pathlib.Path.home", return_value=home_path),
            patch("psutil.virtual_memory", return_value=FakeMem()),
            patch.dict(os.environ, {"OLLAMA_HOST": ollama_url}, clear=False),
        ]
        if platform is not None:
            patches.insert(0, patch("sys.platform", platform))
        try:
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                yield {"cwd": cwd_path, "home": home_path}
        finally:
            # Restore sys.frozen if it was originally set
            if had_frozen:
                sys.frozen = original_frozen
