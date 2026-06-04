"""Tier-1 sandbox: child process + setrlimit + scrubbed env. Available everywhere
incl. the DMG. Weakest ceiling -> gate-mandatory at the policy layer (Task 14)."""
from __future__ import annotations

import os
import resource
import signal
import subprocess
import sys
import time

from ...logging_config import logger
from ..sandbox import CodeExecResult, CodeExecSpec, SandboxCapabilities
from ..sandbox_fs import SandboxedFS


class SubprocessSandbox:
    name = "subprocess"

    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            name="subprocess",
            isolation_tier=1,
            network_modes=("none",),
            max_mem_mb=4096,
            languages=("python",),
            can_auto_run=False,
        )

    def execute(self, spec: CodeExecSpec) -> CodeExecResult:
        fs = SandboxedFS(spec.scratch_path, max_file_size_mb=50)
        fs.write("__entry__.py", spec.code)
        violations: list = []

        def _preexec():
            os.setpgrp()
            mem = spec.mem_mb * 1024 * 1024
            # RLIMIT_AS is Linux-reliable; on macOS the kernel hard limit is
            # RLIM_INFINITY and you cannot lower it below the current AS, so
            # we swallow the error rather than crashing the child.  Memory
            # enforcement falls to the container/policy layer on Darwin.
            try:
                resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            except (ValueError, resource.error):
                pass
            resource.setrlimit(
                resource.RLIMIT_CPU, (spec.timeout_s + 1, spec.timeout_s + 1)
            )
            resource.setrlimit(
                resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024)
            )
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))

        env = {k: os.environ[k] for k in spec.env_allowlist if k in os.environ}
        env["TMPDIR"] = str(fs.root)
        if spec.network == "none":
            # Best-effort only: blocks urllib/requests but not raw sockets.
            # True network isolation is the container tier's job (Task 14).
            env["http_proxy"] = env["https_proxy"] = "http://127.0.0.1:1"

        t0 = time.monotonic()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "__entry__.py"],
                cwd=str(fs.root),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=_preexec,
            )
            try:
                out, err = proc.communicate(input=spec.stdin, timeout=spec.timeout_s)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # group already exited; still a timeout
                out, err = proc.communicate()
                code, violations = -9, ["timeout exceeded"]
        except Exception as e:  # noqa: BLE001
            logger.warning("subprocess sandbox failed: %s", e)
            return CodeExecResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                tier_used=1,
                violations=["spawn failed"],
            )

        produced = []
        for rel in fs.walk():
            if rel == "__entry__.py":
                continue
            produced.append(rel)

        return CodeExecResult(
            exit_code=code,
            stdout=out[:100_000],
            stderr=err[:100_000],
            tier_used=1,
            duration_ms=(time.monotonic() - t0) * 1000,
            files_produced=produced,
            violations=violations,
        )
