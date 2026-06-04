"""Sandbox backend abstraction — host-resolved code-execution isolation.

Mirrors the runner.py / runner_registry.py / runner_detection.py idiom:
one Protocol, per-tier impls, detected at startup, selected by a registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Literal, Optional, Protocol, Tuple, runtime_checkable


class SandboxKind(str, Enum):
    SUBPROCESS = "subprocess"
    CONTAINER = "container"


@dataclass
class SandboxCapabilities:
    name: str
    isolation_tier: int  # 1=subprocess, 2=container
    network_modes: Tuple[str, ...]  # subset of ("none", "allowlist")
    max_mem_mb: int
    languages: Tuple[str, ...]
    can_auto_run: bool  # may execute without a gate when hardened


@dataclass
class CodeExecSpec:
    language: Literal["python"]
    code: str
    scratch_path: str
    stdin: str = ""
    files_in: List[str] = field(default_factory=list)
    files_out: List[str] = field(default_factory=list)
    timeout_s: int = 60
    mem_mb: int = 1024
    cpus: float = 1.0
    pids: int = 256
    network: Literal["none", "allowlist"] = "none"
    env_allowlist: Tuple[str, ...] = ("PATH", "LANG", "LC_ALL", "HOME", "TMPDIR")


@dataclass
class CodeExecResult:
    exit_code: int
    stdout: str
    stderr: str
    tier_used: int
    duration_ms: float = 0.0
    peak_rss_mb: Optional[float] = None
    files_produced: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)


@runtime_checkable
class SandboxBackend(Protocol):
    name: str

    def capabilities(self) -> SandboxCapabilities:
        ...

    def execute(self, spec: CodeExecSpec) -> CodeExecResult:
        ...
