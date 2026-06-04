"""Tier-2 sandbox: one hardened container per run. Podman-first (rootless ->
escape lands unprivileged). Strictly harder than typical reference images.

Note: file output requires rootless Podman (or a world-writable scratch mount);
with Docker rootful, --user 65534 may be unable to write to the bind-mounted /work."""
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
            network_modes=("none",),
            max_mem_mb=8192,
            languages=("python",),
            can_auto_run=True,
        )

    def _build_cmd(
        self, spec: CodeExecSpec, scratch_abs: str, cidfile=None
    ) -> List[str]:
        # v1: no real egress allowlist exists yet, so deny network unconditionally.
        # A requested "allowlist" is downgraded to deny (fail-safe) until a real
        # allowlist backend lands. Real network policy is a future task.
        if spec.network != "none":
            logger.warning(
                "container sandbox: network=%r requested but egress allowlisting "
                "is not implemented in v1; denying network (--network=none)",
                spec.network,
            )
        cmd = [
            self.runtime,
            "run",
            "--rm",
        ]
        if cidfile is not None:
            cmd += ["--cidfile", cidfile]
        cmd += [
            "--network=none",
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
        return cmd

    def execute(self, spec: CodeExecSpec) -> CodeExecResult:
        fs = SandboxedFS(spec.scratch_path, max_file_size_mb=50)
        fs.write("__entry__.py", spec.code)
        cid_path = os.path.join(str(fs.root), ".enclave.cid")
        cmd = self._build_cmd(spec, str(fs.root), cidfile=cid_path)
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
            try:
                import pathlib

                cid = pathlib.Path(cid_path).read_text().strip()
                if cid:
                    subprocess.run(
                        [self.runtime, "rm", "-f", cid],
                        capture_output=True,
                        timeout=10,
                    )
            except Exception:  # noqa: BLE001
                logger.warning("container timeout: could not force-remove container")
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
        produced = [r for r in fs.walk() if r != "__entry__.py" and r != ".enclave.cid"]
        return CodeExecResult(
            exit_code=code,
            stdout=out[:100_000],
            stderr=err[:100_000],
            tier_used=2,
            duration_ms=(time.monotonic() - t0) * 1000,
            files_produced=produced,
            violations=viol,
        )
