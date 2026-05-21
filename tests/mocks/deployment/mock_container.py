"""Mock fixture for container deployment (Docker/Podman + cgroup-aware)."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


@contextlib.contextmanager
def patch_container(
    cgroup_memory_max_gb: float = None,  # None = "no limit set" inside cgroup
    host_memory_gb: float = 96.0,
    user_data_dir: str = None,
    ollama_url: str = "http://ollama:11434",
    cgroup_version: int = 2,
):
    """Pretend we're running inside a Docker container.

    Patches:
        os.path.exists("/.dockerenv")                        -> True
        /proc/1/cgroup                                       -> includes "docker"
        api.services.deployment_impl.container._read_cgroup_memory_max
                                                             -> cgroup_memory_max_gb bytes (or None)
        psutil.virtual_memory().total                        -> host_memory_gb
        OLLAMA_HOST                                          -> ollama_url
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        user_path = Path(user_data_dir) if user_data_dir else Path(tmpdir) / "app_data"
        user_path.mkdir(parents=True, exist_ok=True)

        cgroup_bytes = (
            int(cgroup_memory_max_gb * 1024**3)
            if cgroup_memory_max_gb is not None
            else None
        )

        class FakeMem:
            total = int(host_memory_gb * 1024**3)
            available = int(host_memory_gb * 0.7 * 1024**3)
            used = int(host_memory_gb * 0.3 * 1024**3)

        # Patch os.path.exists to claim /.dockerenv exists
        real_exists = os.path.exists

        def fake_exists(path):
            if path == "/.dockerenv":
                return True
            return real_exists(path)

        patches = [
            patch("os.path.exists", side_effect=fake_exists),
            patch(
                "api.services.deployment_impl.container._read_cgroup_memory_max",
                return_value=cgroup_bytes,
            ),
            patch(
                "api.services.deployment_impl.container._cgroup_version",
                return_value=cgroup_version,
            ),
            patch(
                "api.services.deployment_impl.container._user_storage_root",
                return_value=user_path,
            ),
            patch("psutil.virtual_memory", return_value=FakeMem()),
            patch.dict(os.environ, {"OLLAMA_HOST": ollama_url}, clear=False),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            yield {"user_data": user_path, "cgroup_bytes": cgroup_bytes}
