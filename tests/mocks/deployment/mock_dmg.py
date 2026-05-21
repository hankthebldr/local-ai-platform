"""Mock fixture for DMG (py2app bundled Mac app) deployment."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


@contextlib.contextmanager
def patch_dmg(
    home: str = None,
    bundle_resources: str = None,
    host_memory_gb: float = 48.0,
    ollama_url: str = "http://127.0.0.1:11434",
):
    """Pretend we're inside a py2app DMG bundle on macOS.

    Patches:
        sys.platform                              -> "darwin"
        sys.frozen                                -> True (py2app marker)
        Path.home                                 -> given home or tmp
        psutil.virtual_memory().total             -> host_memory_gb
        api.services.deployment_impl.dmg._bundle_resources_path -> bundle_resources or tmp
        OLLAMA_HOST env                           -> ollama_url
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        home_path = Path(home) if home else Path(tmpdir) / "home"
        home_path.mkdir(parents=True, exist_ok=True)
        bundle_path = (
            Path(bundle_resources) if bundle_resources else Path(tmpdir) / "bundle"
        )
        bundle_path.mkdir(parents=True, exist_ok=True)

        class FakeMem:
            total = int(host_memory_gb * 1024**3)
            available = int(host_memory_gb * 0.7 * 1024**3)
            used = int(host_memory_gb * 0.3 * 1024**3)

        patches = [
            patch("sys.platform", "darwin"),
            patch("sys.frozen", True, create=True),
            patch("pathlib.Path.home", return_value=home_path),
            patch("psutil.virtual_memory", return_value=FakeMem()),
            patch(
                "api.services.deployment_impl.dmg._bundle_resources_path",
                return_value=bundle_path,
            ),
            patch.dict(os.environ, {"OLLAMA_HOST": ollama_url}, clear=False),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            yield {"home": home_path, "bundle": bundle_path}
