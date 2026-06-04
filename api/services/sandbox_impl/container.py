"""Tier-2 sandbox: one hardened container per run. Podman-first (rootless ->
escape lands unprivileged). Strictly harder than typical reference images."""
from __future__ import annotations

import os
import subprocess
import time
from typing import List, Optional

from ...logging_config import logger
from ..sandbox import CodeExecResult, CodeExecSpec, SandboxCapabilities
from ..sandbox_fs import SandboxedFS


class ContainerSandbox:
    name = "container"

    def __init__(self, runtime: str, image: Optional[str] = None) -> None:
        self.runtime = runtime
        self.image = image or os.getenv(
            "SANDBOX_CONTAINER_IMAGE", "enclave-sandbox:latest"
        )

    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            name="container",
            isolation_tier=2,
            network_modes=("none", "allowlist"),
            max_mem_mb=8192,
            languages=("python",),
            can_auto_run=True,
        )

    def _build_cmd(self, spec: CodeExecSpec, scratch_abs: str) -> List[str]:
        net = "none" if spec.network == "none" else "bridge"
        return [
            self.runtime,
            "run",
            "--rm",
            f"--network={net}",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,size=256m",
            f"--memory={spec.mem_mb}m",
            f"--cpus={spec.cpus}",
            f"--pids-limit={spec.pids}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user",
            "65534:65534",
            "-v",
            f"{scratch_abs}:/work:rw",
            "-w",
            "/work",
            self.image,
            "python",
            "-I",
            "/work/__entry__.py",
        ]

    def execute(self, spec: CodeExecSpec) -> CodeExecResult:
        fs = SandboxedFS(spec.scratch_path, max_file_size_mb=50)
        fs.write("__entry__.py", spec.code)
        cmd = self._build_cmd(spec, str(fs.root))
        t0 = time.monotonic()
        try:
            p = subprocess.run(
                cmd,
                input=spec.stdin,
                capture_output=True,
                text=True,
                timeout=spec.timeout_s,
            )
            code, out, err, viol = p.returncode, p.stdout, p.stderr, []
        except subprocess.TimeoutExpired as e:
            code, out, err, viol = (
                -9,
                (e.stdout or ""),
                (e.stderr or ""),
                ["timeout exceeded"],
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("container sandbox failed: %s", e)
            return CodeExecResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                tier_used=2,
                violations=["container spawn failed"],
            )
        produced = [r for r in fs.walk() if r != "__entry__.py"]
        return CodeExecResult(
            exit_code=code,
            stdout=out[:100_000],
            stderr=err[:100_000],
            tier_used=2,
            duration_ms=(time.monotonic() - t0) * 1000,
            files_produced=produced,
            violations=viol,
        )
