# Code-Execution Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Enclave a `kind: code` workflow step + `code_exec` tool that runs agent-authored Python in a tiered, auto-detected isolation sandbox on the operator's own machine, with a human approval gate as the default backstop on the weakest tier and a read-only-until-promoted scratch workspace.

**Architecture:** A host-resolved backend layer (mirroring the existing `runner.py`/`runner_registry.py`/`runner_detection.py` idiom) exposes one uniform `SandboxBackend.execute(CodeExecSpec) -> CodeExecResult` contract over two tiers — Tier-1 subprocess (everywhere, gate-mandatory) and Tier-2 hardened container (where Podman/Docker exists, may auto-run). A new `engine_executors/code.py` wires this into the DAG engine as `kind: code`. Execution and promotion are two separate gates; the HITL gate is a net-new run-level primitive riding the existing `_checkpoint`/`resume` durable-pause substrate.

**Tech Stack:** Python 3.11/3.12 · FastAPI · Pydantic v2 · pytest · `resource.setrlimit` (Tier-1) · Podman/Docker (Tier-2) · the existing `SandboxedFS`, `WorkflowEngine`, `hook_bus`, `MemoryStore`.

**Design spec:** `docs/superpowers/specs/2026-06-03-code-exec-sandbox-design.md`

---

## Deviations from spec (driven by codebase reality — reconcile spec after)

These were discovered while extracting exact signatures. The plan follows reality; the spec should be amended to match.

1. **Spec §6 said the gate is "a `pre_exec` hook on `hook_bus`."** The hook bus has no `pre_exec` stage, and — critically — **the bus is only built/dispatched in the `llm` step path**; composite executors never dispatch it. So the HITL gate is implemented as a **run-level primitive** (`WorkflowRun.pending_gate` + a new non-terminal `"awaiting_approval"` status + a scheduler short-circuit), not a hook. This is actually closer to the spec's stated goal of "a generic `HITLGate` raisable by any step kind."
2. **Spec §5 said the `code_exec` tool is callable mid-reasoning by `llm`/`ralph` steps.** Today the only live `ToolExecutor` driver is the **chat** router; workflow-step tool dispatch goes through the `plugin_tool_invoker` hook, a separate path. **v1 scope:** ship `code_exec` as a plugin tool usable in **chat** (a real, working surface). The workflow-step iterate path (`llm`/`ralph` calling `code_exec` via `plugin_tool_invoker`) is deferred to a clearly-scoped follow-up (Task 17 note).
3. **`SandboxedFS` cannot write binary and has no `mkdir`/recursive-list** — Task 2 adds the missing methods rather than working around them inline.

---

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `api/services/sandbox.py` | Create | `SandboxKind` enum, `SandboxCapabilities`/`CodeExecSpec`/`CodeExecResult` dataclasses, `SandboxBackend` Protocol |
| `api/services/sandbox_impl/__init__.py` | Create | package marker |
| `api/services/sandbox_impl/subprocess.py` | Create | Tier-1 subprocess backend |
| `api/services/sandbox_impl/container.py` | Create | Tier-2 Podman/Docker backend |
| `api/services/sandbox_detection.py` | Create | `detect_sandboxes()` — probe host at startup |
| `api/services/sandbox_registry.py` | Create | `SandboxRegistry` singleton + `SandboxNotAvailable` + `resolve()` |
| `api/services/sandbox_fs.py` | Modify | add `write_bytes`, `mkdir`, `walk` |
| `api/services/engine_executors/code.py` | Create | `kind: code` executor |
| `api/services/engine_executors/code_promote.py` | Create | three-zone staging/capture/promotion helpers |
| `api/services/sandbox_reaper.py` | Create | scratch-dir TTL reaper |
| `api/models/workflow_models.py` | Modify | `CodeStepConfig`, `ResourceLimits`, `kind` Literal, `code` field, `_validate_kind_shape` branch, `StepResult` fields, `GatePending`, `WorkflowRun.pending_gate` |
| `api/services/workflow_engine.py` | Modify | dispatch branch, model-skip tuple, gate pause + scheduler short-circuit |
| `api/routers/workflows.py` | Modify | `POST /runs/{run_id}/approvals/{gate_id}` |
| `api/main.py` | Modify | `detect_sandboxes()` in lifespan |
| `setup/sandbox/Dockerfile` | Create | Tier-2 hardened image |
| `plugins/code-exec/plugin.yaml` + `tool.py` | Create | `code_exec` chat tool |
| `tests/unit/test_sandbox_*.py`, `tests/integration/test_code_step*.py` | Create | per-task tests |

**Phase boundaries (each ships working, tested software):**
- **Phase 0** — sandbox runtime core (Tier-1), no engine coupling.
- **Phase 1** — `kind: code` runs end-to-end, deterministic, no gate.
- **Phase 2** — three-zone workspace + promotion policy.
- **Phase 3** — HITL execution gate + approval endpoint.
- **Phase 4** — Tier-2 container backend.
- **Phase 5** — `code_exec` chat tool + config/telemetry.

---

## Phase 0 — Sandbox runtime core

### Task 1: Backend types + Protocol

**Files:**
- Create: `api/services/sandbox.py`
- Test: `tests/unit/test_sandbox_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sandbox_types.py
from api.services.sandbox import (
    SandboxKind, SandboxCapabilities, CodeExecSpec, CodeExecResult, SandboxBackend,
)


def test_capabilities_and_specs_construct():
    caps = SandboxCapabilities(
        name="subprocess", isolation_tier=1, network_modes=("none",),
        max_mem_mb=2048, languages=("python",), can_auto_run=False,
    )
    assert caps.isolation_tier == 1 and caps.can_auto_run is False

    spec = CodeExecSpec(language="python", code="print(1)", scratch_path="/tmp/x")
    assert spec.timeout_s == 60 and spec.network == "none"

    res = CodeExecResult(exit_code=0, stdout="1\n", stderr="", tier_used=1)
    assert res.exit_code == 0 and res.files_produced == []


def test_backend_protocol_is_runtime_checkable():
    class Dummy:
        name = "dummy"
        def capabilities(self): ...
        def execute(self, spec): ...
    assert isinstance(Dummy(), SandboxBackend)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && pytest tests/unit/test_sandbox_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.sandbox'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/sandbox.py
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
    isolation_tier: int                       # 1=subprocess, 2=container
    network_modes: Tuple[str, ...]            # subset of ("none", "allowlist")
    max_mem_mb: int
    languages: Tuple[str, ...]
    can_auto_run: bool                        # may execute without a gate when hardened


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
    def capabilities(self) -> SandboxCapabilities: ...
    def execute(self, spec: CodeExecSpec) -> CodeExecResult: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sandbox_types.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/sandbox.py tests/unit/test_sandbox_types.py
git commit -m "feat(sandbox): backend Protocol + spec/result types"
```

---

### Task 2: Extend `SandboxedFS` for staging/capture

`SandboxedFS.write()` is str-only and there is no `mkdir` or recursive list. Code-exec must stage binary `files_in`, create the scratch layout, and capture all produced files. Add three methods; keep the traversal guard.

**Files:**
- Modify: `api/services/sandbox_fs.py` (append methods to the class, after `stats()` ~line 111)
- Test: `tests/unit/test_sandbox_fs_ext.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sandbox_fs_ext.py
import pytest
from api.services.sandbox_fs import SandboxedFS, SandboxViolation


def test_write_bytes_mkdir_walk(tmp_path):
    fs = SandboxedFS(str(tmp_path / "sbx"))
    fs.mkdir("work/sub")
    fs.write_bytes("work/sub/data.bin", b"\x00\x01\x02")
    assert fs.exists("work/sub/data.bin")
    # walk returns relative POSIX paths of files only
    rels = set(fs.walk())
    assert "work/sub/data.bin" in rels


def test_write_bytes_blocks_traversal(tmp_path):
    fs = SandboxedFS(str(tmp_path / "sbx"))
    with pytest.raises(SandboxViolation):
        fs.write_bytes("../escape.bin", b"x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sandbox_fs_ext.py -v`
Expected: FAIL — `AttributeError: 'SandboxedFS' object has no attribute 'write_bytes'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/sandbox_fs.py — add inside class SandboxedFS, after stats()

    def write_bytes(self, path: str, data: bytes) -> None:
        abs_path = self.get_absolute_path(path)   # raises SandboxViolation on escape
        self._check_extension(path)
        if len(data) > self.max_file_size:
            raise SandboxQuotaExceeded(f"{path} exceeds {self.max_file_size} bytes")
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)

    def mkdir(self, path: str) -> None:
        abs_path = self.get_absolute_path(path)
        abs_path.mkdir(parents=True, exist_ok=True)

    def walk(self) -> list:
        """Recursive list of file (not dir) paths, relative to root, POSIX style."""
        return [
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file()
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sandbox_fs_ext.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/sandbox_fs.py tests/unit/test_sandbox_fs_ext.py
git commit -m "feat(sandbox): SandboxedFS write_bytes/mkdir/walk for code-exec staging"
```

---

### Task 3: Tier-1 subprocess backend

The security core. Runs Python in a child process: cwd pinned to the scratch root, `setrlimit` for CPU/mem/fsize/nofile, **scrubbed env (allowlist only)**, network denied by default, wall-clock kill of the whole process group. Capture stdout/stderr/exit + peak RSS; collect produced files via `SandboxedFS.walk()`.

**Files:**
- Create: `api/services/sandbox_impl/__init__.py` (empty)
- Create: `api/services/sandbox_impl/subprocess.py`
- Test: `tests/unit/test_sandbox_subprocess.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sandbox_subprocess.py
import os
import pytest
from api.services.sandbox import CodeExecSpec
from api.services.sandbox_impl.subprocess import SubprocessSandbox


def _spec(code, tmp, **kw):
    return CodeExecSpec(language="python", code=code, scratch_path=str(tmp), **kw)


def test_happy_path(tmp_path):
    res = SubprocessSandbox().execute(_spec("print('hi')", tmp_path))
    assert res.exit_code == 0 and "hi" in res.stdout and res.tier_used == 1


def test_timeout_kills(tmp_path):
    res = SubprocessSandbox().execute(_spec("import time; time.sleep(30)", tmp_path, timeout_s=1))
    assert res.exit_code != 0 and "timeout" in " ".join(res.violations).lower()


def test_env_is_scrubbed(tmp_path):
    os.environ["ENCLAVE_SECRET"] = "leak-me"
    try:
        res = SubprocessSandbox().execute(
            _spec("import os; print(os.environ.get('ENCLAVE_SECRET', 'ABSENT'))", tmp_path)
        )
    finally:
        del os.environ["ENCLAVE_SECRET"]
    assert "ABSENT" in res.stdout and "leak-me" not in res.stdout


def test_captures_produced_files(tmp_path):
    res = SubprocessSandbox().execute(
        _spec("open('out.txt','w').write('done')", tmp_path, files_out=["out.txt"])
    )
    assert "out.txt" in res.files_produced
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sandbox_subprocess.py -v`
Expected: FAIL — `ModuleNotFoundError: api.services.sandbox_impl.subprocess`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/sandbox_impl/subprocess.py
"""Tier-1 sandbox: child process + setrlimit + scrubbed env. Available everywhere
incl. the DMG. Weakest ceiling -> gate-mandatory at the policy layer (Task 14)."""
from __future__ import annotations

import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

from ..logging_config import logger
from ..sandbox import CodeExecSpec, CodeExecResult, SandboxCapabilities
from ..sandbox_fs import SandboxedFS


class SubprocessSandbox:
    name = "subprocess"

    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            name="subprocess", isolation_tier=1, network_modes=("none",),
            max_mem_mb=4096, languages=("python",), can_auto_run=False,
        )

    def execute(self, spec: CodeExecSpec) -> CodeExecResult:
        fs = SandboxedFS(spec.scratch_path, max_file_size_mb=50)
        fs.write("__entry__.py", spec.code)
        violations: list = []

        def _preexec():
            # New process group so we can kill children on timeout.
            os.setpgrp()
            mem = spec.mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_CPU, (spec.timeout_s + 1, spec.timeout_s + 1))
            resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))

        env = {k: os.environ[k] for k in spec.env_allowlist if k in os.environ}
        env["TMPDIR"] = str(fs.root)
        if spec.network == "none":
            env["http_proxy"] = env["https_proxy"] = "http://127.0.0.1:1"  # best-effort deny

        t0 = time.monotonic()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "__entry__.py"],
                cwd=str(fs.root), env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, preexec_fn=_preexec,
            )
            try:
                out, err = proc.communicate(input=spec.stdin, timeout=spec.timeout_s)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                out, err = proc.communicate()
                code, violations = -9, ["timeout exceeded"]
        except Exception as e:  # noqa: BLE001
            logger.warning("subprocess sandbox failed: %s", e)
            return CodeExecResult(exit_code=-1, stdout="", stderr=str(e), tier_used=1,
                                  violations=["spawn failed"])

        # Capture produced files (re-validate each declared files_out path).
        produced = []
        for rel in fs.walk():
            if rel == "__entry__.py":
                continue
            produced.append(rel)

        return CodeExecResult(
            exit_code=code, stdout=out[:100_000], stderr=err[:100_000], tier_used=1,
            duration_ms=(time.monotonic() - t0) * 1000, files_produced=produced,
            violations=violations,
        )
```

> **Note (macOS):** `os.setpgrp`/`SIGKILL`/`RLIMIT_AS` work; there is no network namespace, so `--network=none` is best-effort via proxy env. This is the honest Tier-1 ceiling the spec calls out — compensated by the mandatory gate (Task 14). `RLIMIT_AS` on macOS can be flaky for huge allocations; the wall-clock kill is the reliable backstop.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sandbox_subprocess.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/sandbox_impl/ tests/unit/test_sandbox_subprocess.py
git commit -m "feat(sandbox): Tier-1 subprocess backend (rlimits, env-scrub, timeout)"
```

---

### Task 4: Detection + registry (singleton, down-only resolution)

Mirrors `runner_detection.detect_runners()` + `runner_registry.py` exactly: a module-global singleton, `_set_current`, `get_current_sandbox_registry()`, and `SandboxNotAvailable(name)` mirroring `RunnerNotConfigured`. `resolve()` selects the strongest available tier, with override **down-only**.

**Files:**
- Create: `api/services/sandbox_registry.py`
- Create: `api/services/sandbox_detection.py`
- Test: `tests/unit/test_sandbox_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sandbox_registry.py
import pytest
from api.services.sandbox import SandboxKind
from api.services.sandbox_registry import SandboxRegistry, SandboxNotAvailable
from api.services.sandbox_impl.subprocess import SubprocessSandbox


def test_resolve_strongest_then_downgrade():
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    # Only subprocess present -> resolve returns it.
    assert reg.resolve(override=None).name == "subprocess"
    # Override UP to a tier that isn't present -> error (never silently upgrade).
    with pytest.raises(SandboxNotAvailable):
        reg.resolve(override="container")


def test_detection_always_has_subprocess(monkeypatch):
    import api.services.sandbox_detection as det
    monkeypatch.setattr(det.shutil, "which", lambda _: None)  # no podman/docker
    reg = det.detect_sandboxes()
    assert SandboxKind.SUBPROCESS.value in [b.name for b in reg.backends()]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sandbox_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: api.services.sandbox_registry`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/sandbox_registry.py
from __future__ import annotations

from typing import List, Optional

from .sandbox import SandboxBackend


class SandboxNotAvailable(Exception):
    """Raised when a resolution asks for a tier this host can't provide.
    Names the missing backend so the operator sees what to install."""


class SandboxRegistry:
    def __init__(self) -> None:
        self._by_name: dict = {}

    def register(self, backend: SandboxBackend) -> None:
        self._by_name[backend.name] = backend

    def backends(self) -> List[SandboxBackend]:
        # Sorted strongest-first by isolation_tier.
        return sorted(self._by_name.values(),
                      key=lambda b: b.capabilities().isolation_tier, reverse=True)

    def resolve(self, override: Optional[str]) -> SandboxBackend:
        if override is not None:
            b = self._by_name.get(override)
            if b is None:
                raise SandboxNotAvailable(
                    f"sandbox tier '{override}' not available on this host "
                    f"(present: {sorted(self._by_name)})"
                )
            return b
        avail = self.backends()
        if not avail:
            raise SandboxNotAvailable("no sandbox backend available")
        return avail[0]


_current: Optional[SandboxRegistry] = None


def _set_current(reg: SandboxRegistry) -> None:
    global _current
    _current = reg


def get_current_sandbox_registry() -> SandboxRegistry:
    if _current is None:
        raise RuntimeError("sandbox registry not initialized — detect_sandboxes() must run at startup")
    return _current
```

```python
# api/services/sandbox_detection.py
from __future__ import annotations

import shutil

from .logging_config import logger
from .sandbox_registry import SandboxRegistry, _set_current
from .sandbox_impl.subprocess import SubprocessSandbox


def detect_sandboxes() -> SandboxRegistry:
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())            # always available
    runtime = shutil.which("podman") or shutil.which("docker")
    if runtime:
        from .sandbox_impl.container import ContainerSandbox   # Task 15
        reg.register(ContainerSandbox(runtime=runtime))
        logger.info("  📦 Sandbox:      subprocess + container (%s)", runtime)
    else:
        logger.info("  📦 Sandbox:      subprocess only (no container runtime)")
    _set_current(reg)
    return reg
```

> **Note:** `detect_sandboxes` imports `ContainerSandbox` lazily so Phase 0 passes before Task 15 exists; until then `which` is monkeypatched to `None` in tests. The real lazy import only triggers when a runtime is on PATH.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sandbox_registry.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/sandbox_registry.py api/services/sandbox_detection.py tests/unit/test_sandbox_registry.py
git commit -m "feat(sandbox): detection + registry singleton (down-only resolve)"
```

**✅ Phase 0 boundary:** the sandbox runtime works standalone — Tier-1 executes code with isolation, the registry resolves backends. Run `pytest tests/unit/test_sandbox_*.py -v` (all green) before continuing.

---

## Phase 1 — `kind: code` step (deterministic, no gate)

### Task 5: `CodeStepConfig` model + `AgentStep` wiring + validation

**Files:**
- Modify: `api/models/workflow_models.py` — add models; extend `AgentStep.kind` Literal (line 378-380); add `code` field (~after line 459); add `_validate_kind_shape` branch (within 501-779)
- Test: `tests/unit/test_code_step_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_code_step_model.py
import pytest
from pydantic import ValidationError
from api.models.workflow_models import AgentStep, CodeStepConfig


def test_code_step_validates():
    s = AgentStep(id="c1", name="run", kind="code", outputs=["result"],
                  code=CodeStepConfig(code="print(1)"))
    assert s.kind == "code" and s.code.language == "python" and s.code.promote == "gated"


def test_code_step_requires_code_block():
    with pytest.raises(ValidationError):
        AgentStep(id="c1", name="run", kind="code", outputs=["result"])  # no .code


def test_non_code_step_rejects_code_block():
    with pytest.raises(ValidationError):
        AgentStep(id="x", name="n", kind="llm", outputs=["o"],
                  code=CodeStepConfig(code="print(1)"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_code_step_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'CodeStepConfig'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/models/workflow_models.py — add near the other kind configs (~line 260, after RalphConfig)

class ResourceLimits(BaseModel):
    mem_mb: int = 1024
    cpus: float = 1.0
    pids: int = 256


class CodeStepConfig(BaseModel):
    """Config for a `kind: code` step — sandboxed code execution."""
    language: Literal["python"] = "python"
    source: Literal["inline", "from_input"] = "inline"
    code: Optional[str] = None            # required when source == inline
    code_input: Optional[str] = None      # workspace ref when source == from_input
    files_in: List[str] = Field(default_factory=list)
    files_out: List[str] = Field(default_factory=list)
    timeout_s: int = 60
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    network: Literal["none", "allowlist"] = "none"
    approval: Literal["auto", "required", "tier_default"] = "tier_default"
    backend_override: Optional[Literal["subprocess", "container"]] = None
    promote: Literal["gated", "auto_on_green", "never"] = "gated"
    promote_predicate: Optional[str] = None
```

```python
# api/models/workflow_models.py:378-380 — extend the kind Literal
    kind: Literal[
        "llm", "parallel", "loop", "a2a", "orchestrator", "consolidate", "ralph", "code"
    ] = "llm"
```

```python
# api/models/workflow_models.py — add field on AgentStep, after the kind:loop block (~line 459)
    # ── kind: code ────────────────────────────────────────────────────
    code: Optional[CodeStepConfig] = None
```

```python
# api/models/workflow_models.py — in _validate_kind_shape (501-779), add a branch
# mirroring the consolidate/ralph "must / must-not declare" guards:
        if self.kind == "code":
            if self.code is None:
                raise ValueError(f"step {self.id}: kind=code requires a `code` config block")
            if self.code.source == "inline" and not self.code.code:
                raise ValueError(f"step {self.id}: code.source=inline requires code.code")
            if self.code.source == "from_input" and not self.code.code_input:
                raise ValueError(f"step {self.id}: code.source=from_input requires code.code_input")
        elif self.code is not None:
            raise ValueError(f"step {self.id}: `code` block only valid on kind=code")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_code_step_model.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add api/models/workflow_models.py tests/unit/test_code_step_model.py
git commit -m "feat(sandbox): CodeStepConfig + kind=code validation"
```

---

### Task 6: `StepResult` code-exec fields

**Files:**
- Modify: `api/models/workflow_models.py:1006` — append fields after `extension_overhead_ms`
- Test: `tests/unit/test_step_result_code_fields.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_step_result_code_fields.py
from api.models.workflow_models import StepResult


def test_code_fields_default_and_roundtrip():
    r = StepResult(step_id="c1", status="completed")
    assert r.code_exit_code is None and r.files_produced == [] and r.promoted is None
    # Round-trips through checkpoint serialization (no extra="allow").
    again = StepResult.model_validate(r.model_dump())
    assert again.tier_used is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_step_result_code_fields.py -v`
Expected: FAIL — `AttributeError: 'StepResult' object has no attribute 'code_exit_code'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/models/workflow_models.py — after line 1006 (extension_overhead_ms), before class end
    # Code-exec (kind: code) — all optional; None on non-code steps.
    code_exit_code: Optional[int] = None
    tier_used: Optional[int] = None
    peak_rss_mb: Optional[float] = None
    files_produced: List[str] = Field(default_factory=list)
    approval_status: Optional[Literal["auto", "approved", "edited", "rejected"]] = None
    promoted: Optional[bool] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_step_result_code_fields.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/models/workflow_models.py tests/unit/test_step_result_code_fields.py
git commit -m "feat(sandbox): StepResult code-exec telemetry fields"
```

---

### Task 7: `code.py` executor (deterministic core, promote=never stub)

First cut: resolve a backend, build a `CodeExecSpec` from `step.code`, run it, write a result summary into `context.workspace[step.id][<first output>]`, return a populated `StepResult`. Promotion is stubbed (`promoted=False`); Phase 2 adds real promotion. No gate yet (Phase 3).

**Files:**
- Create: `api/services/engine_executors/code.py`
- Test: `tests/integration/test_code_executor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_code_executor.py
from datetime import datetime
from api.models.workflow_models import (
    AgentStep, CodeStepConfig, WorkflowContext, WorkflowDefinition, WorkflowRun,
)
from api.services.sandbox_registry import SandboxRegistry, _set_current
from api.services.sandbox_impl.subprocess import SubprocessSandbox
from api.services.engine_executors import code as code_exec


class _Engine:  # minimal stand-in; code.py only needs these attrs in Phase 1
    pass


def _setup_registry():
    reg = SandboxRegistry(); reg.register(SubprocessSandbox()); _set_current(reg)


def test_code_step_runs_and_writes_workspace(tmp_path):
    _setup_registry()
    step = AgentStep(id="c1", name="run", kind="code", outputs=["result"],
                     code=CodeStepConfig(code="print('forty-two')"))
    ctx = WorkflowContext()
    run = WorkflowRun(run_id="r1", workflow_id="w1", status="running",
                      context=ctx, started_at=datetime.utcnow())
    res = code_exec.execute(_Engine(), step, WorkflowDefinition(id="w1", name="w", steps=[step]),
                            ctx, run)
    assert res.status == "completed" and res.code_exit_code == 0
    assert "forty-two" in ctx.get_workspace("c1", "result")["stdout"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_code_executor.py -v`
Expected: FAIL — `ModuleNotFoundError: api.services.engine_executors.code`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/engine_executors/code.py
"""kind=code executor — sandboxed code execution.

Phase 1: resolve backend, run, write a result summary into the workspace.
Phase 2 adds three-zone staging + promotion; Phase 3 adds the HITL gate.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from ...logging_config import logger
from ...models.workflow_models import (
    AgentStep, StepResult, WorkflowContext, WorkflowDefinition, WorkflowRun,
)
from ..sandbox import CodeExecSpec
from ..sandbox_registry import get_current_sandbox_registry

if TYPE_CHECKING:
    from ..workflow_engine import WorkflowEngine


def _scratch_root(run: WorkflowRun, step: AgentStep) -> str:
    return os.path.join("data", "sandboxes", f"wf-{run.run_id}", step.id)


def execute(engine: "WorkflowEngine", step: AgentStep, definition: WorkflowDefinition,
            context: WorkflowContext, workflow_run: WorkflowRun) -> StepResult:
    if os.getenv("CODE_EXEC_ENABLED", "false").lower() != "true":
        return StepResult(step_id=step.id, status="failed",
                          error="code execution disabled (set CODE_EXEC_ENABLED=true)",
                          started_at=datetime.utcnow(), completed_at=datetime.utcnow())

    cfg = step.code
    code_src = cfg.code if cfg.source == "inline" else str(context.resolve_input(cfg.code_input))
    backend = get_current_sandbox_registry().resolve(override=cfg.backend_override)

    spec = CodeExecSpec(
        language="python", code=code_src, scratch_path=_scratch_root(workflow_run, step),
        files_in=cfg.files_in, files_out=cfg.files_out, timeout_s=cfg.timeout_s,
        mem_mb=cfg.limits.mem_mb, cpus=cfg.limits.cpus, pids=cfg.limits.pids,
        network=cfg.network,
    )
    res = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())
    out = backend.execute(spec)

    res.code_exit_code = out.exit_code
    res.tier_used = out.tier_used
    res.peak_rss_mb = out.peak_rss_mb
    res.files_produced = out.files_produced
    res.promoted = False  # Phase 2 wires real promotion
    res.status = "completed" if out.exit_code == 0 else "failed"
    if out.exit_code != 0:
        res.error = (out.violations or [out.stderr[:500]])[0] if (out.violations or out.stderr) else "non-zero exit"
    context.set_workspace(step.id, step.outputs[0],
                          {"stdout": out.stdout, "exit_code": out.exit_code,
                           "files": out.files_produced})
    res.completed_at = datetime.utcnow()
    res.duration_seconds = (res.completed_at - res.started_at).total_seconds()
    logger.info("code step %s exit=%s tier=%s", step.id, out.exit_code, out.tier_used)
    return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `CODE_EXEC_ENABLED=true pytest tests/integration/test_code_executor.py -v`
Expected: PASS

> Add `monkeypatch.setenv("CODE_EXEC_ENABLED", "true")` at the top of the test so it passes without the env prefix; shown here explicitly for clarity.

- [ ] **Step 5: Commit**

```bash
git add api/services/engine_executors/code.py tests/integration/test_code_executor.py
git commit -m "feat(sandbox): kind=code executor (deterministic core)"
```

---

### Task 8: Wire dispatch + model-skip + end-to-end run

**Files:**
- Modify: `api/services/workflow_engine.py:~1240` — add dispatch branch; `:807` — add `"code"` to model-skip tuple
- Test: `tests/integration/test_code_step_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_code_step_e2e.py
def test_engine_runs_code_workflow(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    from api.services.sandbox_registry import SandboxRegistry, _set_current
    from api.services.sandbox_impl.subprocess import SubprocessSandbox
    reg = SandboxRegistry(); reg.register(SubprocessSandbox()); _set_current(reg)

    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService
    from api.models.workflow_models import WorkflowDefinition, AgentStep, CodeStepConfig

    wf = WorkflowDefinition(id="w-code", name="code", steps=[
        AgentStep(id="c1", name="run", kind="code", outputs=["result"],
                  code=CodeStepConfig(code="print('engine-ran-code')")),
    ])
    eng = WorkflowEngine(OllamaService())
    run = eng.run(wf, seed={})
    assert run.status == "completed"
    sr = [r for r in run.step_results if r.step_id == "c1"][0]
    assert sr.code_exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_code_step_e2e.py -v`
Expected: FAIL — engine raises on resolving a model for the `code` step (KeyError/validation), or dispatch falls through to the `llm` path.

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/workflow_engine.py:807 — add "code" to the skip tuple
        if step.kind in ("a2a", "parallel", "loop", "orchestrator", "consolidate", "ralph", "code"):
            resolved_models[step.id] = ""
            continue
```

```python
# api/services/workflow_engine.py:~1240 — add before the llm fallthrough
        if step.kind == "code":
            from .engine_executors import code as _code
            return _code.execute(self, step, definition, context, workflow_run)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_code_step_e2e.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/workflow_engine.py tests/integration/test_code_step_e2e.py
git commit -m "feat(sandbox): dispatch kind=code through the engine"
```

**✅ Phase 1 boundary:** a `kind: code` step runs end-to-end through the engine on Tier-1, deterministic, no human gate, output in the workspace. Run `pytest tests/ -k "code or sandbox" --ignore=tests/e2e -v`.

---

## Phase 2 — Three-zone workspace + promotion

Realizes the spec's "read-only-until-promoted." A per-run **canonical** dir
(`data/sandboxes/wf-{run_id}/_workspace/`) persists across steps; each step gets an
ephemeral **scratch** dir. `files_in` are staged canonical→scratch; declared
`files_out` are promoted scratch→canonical only when the promotion policy allows.

### Task 9: Staging + promotion helpers

**Files:**
- Create: `api/services/engine_executors/code_promote.py`
- Modify: `api/services/engine_executors/code.py` — call `stage_inputs` before exec, `promote` after
- Test: `tests/integration/test_code_promote.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_code_promote.py
import os
from api.services.sandbox_fs import SandboxedFS
from api.services.engine_executors import code_promote as cp
from api.models.workflow_models import CodeStepConfig


def test_promote_auto_on_green_copies_files_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canon = SandboxedFS("data/sandboxes/wf-r1/_workspace")
    scratch = SandboxedFS("data/sandboxes/wf-r1/c1")
    scratch.write("out.txt", "promoted-content")
    cfg = CodeStepConfig(code="x", files_out=["out.txt"], promote="auto_on_green")
    promoted = cp.promote(scratch, canon, cfg, exit_code=0)
    assert promoted == ["out.txt"] and canon.read("out.txt") == "promoted-content"


def test_promote_never_keeps_canon_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canon = SandboxedFS("data/sandboxes/wf-r2/_workspace")
    scratch = SandboxedFS("data/sandboxes/wf-r2/c1")
    scratch.write("out.txt", "x")
    cfg = CodeStepConfig(code="x", files_out=["out.txt"], promote="never")
    assert cp.promote(scratch, canon, cfg, exit_code=0) == []
    assert not canon.exists("out.txt")


def test_promote_auto_on_green_skips_on_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canon = SandboxedFS("data/sandboxes/wf-r3/_workspace")
    scratch = SandboxedFS("data/sandboxes/wf-r3/c1")
    scratch.write("out.txt", "x")
    cfg = CodeStepConfig(code="x", files_out=["out.txt"], promote="auto_on_green")
    assert cp.promote(scratch, canon, cfg, exit_code=1) == []  # non-zero -> no promote
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_code_promote.py -v`
Expected: FAIL — `ModuleNotFoundError: api.services.engine_executors.code_promote`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/engine_executors/code_promote.py
"""Three-zone workspace helpers for kind=code.

canonical (persisted, per-run)  <--promote--  scratch (ephemeral, per-step)
                                --stage_in-->
Only declared files_out are promotion candidates; gated/auto_on_green/never.
v1: auto_on_green == (exit_code == 0). `promote_predicate` is reserved (deferred).
"""
from __future__ import annotations

from typing import List

from ...logging_config import logger
from ...models.workflow_models import CodeStepConfig
from ..sandbox_fs import SandboxedFS, SandboxViolation


def stage_inputs(canon: SandboxedFS, scratch: SandboxedFS, cfg: CodeStepConfig) -> None:
    for rel in cfg.files_in:
        if not canon.exists(rel):
            logger.warning("files_in '%s' not in canonical workspace; skipping", rel)
            continue
        scratch.write_bytes(rel, canon.open(rel, "rb").read())


def promote(scratch: SandboxedFS, canon: SandboxedFS, cfg: CodeStepConfig,
            exit_code: int) -> List[str]:
    if cfg.promote == "never":
        return []
    if cfg.promote == "auto_on_green" and exit_code != 0:
        return []
    # "gated" reaches here only after the operator approved (Phase 3); copy declared outs.
    promoted: List[str] = []
    for rel in cfg.files_out:
        try:
            scratch.get_absolute_path(rel)   # re-validate: no traversal/abs escape
        except SandboxViolation:
            logger.warning("files_out '%s' failed re-validation; not promoting", rel)
            continue
        if not scratch.exists(rel):
            continue
        canon.write_bytes(rel, scratch.open(rel, "rb").read())
        promoted.append(rel)
    return promoted
```

```python
# api/services/engine_executors/code.py — wire staging + promotion into execute()
# After `backend = ...resolve(...)` and constructing `spec`, before backend.execute:
    from .code_promote import stage_inputs, promote
    from ..sandbox_fs import SandboxedFS
    scratch = SandboxedFS(spec.scratch_path, max_file_size_mb=50)
    canon = SandboxedFS(os.path.join("data", "sandboxes", f"wf-{workflow_run.run_id}", "_workspace"))
    stage_inputs(canon, scratch, cfg)

# After `out = backend.execute(spec)` and setting result fields, replace `res.promoted = False`:
    promoted = promote(scratch, canon, cfg, out.exit_code) if cfg.promote != "gated" else []
    res.promoted = bool(promoted)
    # (gated promotion happens post-approval in Phase 3)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_code_promote.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/engine_executors/code_promote.py api/services/engine_executors/code.py tests/integration/test_code_promote.py
git commit -m "feat(sandbox): three-zone staging + promotion policy"
```

---

### Task 10: Scratch-dir TTL reaper

**Files:**
- Create: `api/services/sandbox_reaper.py`
- Test: `tests/unit/test_sandbox_reaper.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sandbox_reaper.py
import os, time
from pathlib import Path
from api.services.sandbox_reaper import reap_scratch


def test_reaper_removes_old_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = Path("data/sandboxes"); base.mkdir(parents=True)
    old = base / "wf-old"; old.mkdir()
    new = base / "wf-new"; new.mkdir()
    old_time = time.time() - 48 * 3600
    os.utime(old, (old_time, old_time))
    removed = reap_scratch(ttl_hours=24)
    assert "wf-old" in removed and not old.exists() and new.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sandbox_reaper.py -v`
Expected: FAIL — `ModuleNotFoundError: api.services.sandbox_reaper`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/sandbox_reaper.py
"""Remove per-run code-exec scratch dirs older than the TTL. Mirrors the
SessionManager archive-then-clean precedent (simplified: log + rmtree)."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import List

from .logging_config import logger


def reap_scratch(ttl_hours: int = 24, base: str = "data/sandboxes") -> List[str]:
    root = Path(base)
    if not root.exists():
        return []
    cutoff = time.time() - ttl_hours * 3600
    removed: List[str] = []
    for d in root.iterdir():
        if d.is_dir() and d.name.startswith("wf-") and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
            logger.info("reaped stale sandbox scratch: %s", d.name)
    return removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sandbox_reaper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/sandbox_reaper.py tests/unit/test_sandbox_reaper.py
git commit -m "feat(sandbox): scratch-dir TTL reaper"
```

**✅ Phase 2 boundary:** three-zone workspace with promotion policy; stale scratch reaped. (Reaper is invoked from the lifespan in Task 17.)

---

## Phase 3 — HITL execution gate (net-new run-level primitive)

> **Design reality (spec §6 deviation):** the hook bus has no `pre_exec` stage and is
> not dispatched for composite kinds, so the gate is a **run-level** primitive:
> `WorkflowRun.pending_gate` + a non-terminal `"awaiting_approval"` status + a scheduler
> short-circuit. It rides the existing `_checkpoint` (durable write) and `resume`
> (re-dispatch of non-`completed` steps). **Critical:** a paused gated step must NOT be
> recorded `status="completed"`, or `resume` (`workflow_engine.py:650-658`) will skip it.

### Task 11: `GatePending` model + `WorkflowRun.pending_gate`

**Files:**
- Modify: `api/models/workflow_models.py` — add `GatePending`; add `pending_gate` field to `WorkflowRun` (~line 1169)
- Test: `tests/unit/test_gate_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gate_model.py
from api.models.workflow_models import GatePending, WorkflowRun, WorkflowContext


def test_gate_defaults_and_run_field():
    g = GatePending(gate_id="r1:c1", run_id="r1", step_id="c1", step_kind="code",
                    proposed_code="print(1)", network="none", tier=1)
    assert g.decision is None and g.files == []
    run = WorkflowRun(run_id="r1", workflow_id="w1", status="running",
                      context=WorkflowContext())
    assert run.pending_gate is None
    run.pending_gate = g
    assert WorkflowRun.model_validate(run.model_dump()).pending_gate.gate_id == "r1:c1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_gate_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'GatePending'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/models/workflow_models.py — add near StepResult (~line 1010)
class GatePending(BaseModel):
    """A HITL approval gate awaiting an operator decision. Serialized on the run
    so a paused workflow survives restart and resumes by id."""
    gate_id: str
    run_id: str
    step_id: str
    step_kind: str
    proposed_code: str
    network: str
    files: List[str] = Field(default_factory=list)
    tier: int
    question: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # set by the approval endpoint; consumed by the executor on resume
    decision: Optional[Literal["approved", "edited", "rejected"]] = None
    edited_code: Optional[str] = None
    reason: Optional[str] = None
```

```python
# api/models/workflow_models.py — add to WorkflowRun (~line 1169, beside `status`)
    pending_gate: Optional[GatePending] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_gate_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/models/workflow_models.py tests/unit/test_gate_model.py
git commit -m "feat(sandbox): GatePending model + WorkflowRun.pending_gate"
```

---

### Task 12: Gate logic in `code.py` + scheduler short-circuit

Implements the §6 auto-run policy (Tier-1 always gates; Tier-2 auto-runs only when
`network=none ∧ can_auto_run`), raises the gate by setting `pending_gate` + returning an
`awaiting_approval` result, consumes the operator's decision on resume, and teaches the
scheduler to halt-and-checkpoint on `awaiting_approval`.

**Files:**
- Modify: `api/services/engine_executors/code.py` — add `_approval_required`, `_consume_decision`, gate branch in `execute`
- Modify: `api/services/workflow_engine.py` — short-circuit in `_execute_steps` (post-result, ~line 920)
- Test: `tests/integration/test_code_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_code_gate.py
from datetime import datetime
from api.models.workflow_models import (
    AgentStep, CodeStepConfig, WorkflowContext, WorkflowDefinition, WorkflowRun,
)
from api.services.sandbox_registry import SandboxRegistry, _set_current
from api.services.sandbox_impl.subprocess import SubprocessSandbox
from api.services.engine_executors import code as code_exec


def _ctx_run():
    ctx = WorkflowContext()
    return ctx, WorkflowRun(run_id="r1", workflow_id="w1", status="running",
                            context=ctx, started_at=datetime.utcnow())


def test_tier1_required_raises_gate(monkeypatch):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    reg = SandboxRegistry(); reg.register(SubprocessSandbox()); _set_current(reg)
    step = AgentStep(id="c1", name="run", kind="code", outputs=["result"],
                     code=CodeStepConfig(code="print(1)", approval="tier_default"))
    ctx, run = _ctx_run()
    res = code_exec.execute(object(), step, WorkflowDefinition(id="w1", name="w", steps=[step]), ctx, run)
    assert res.status == "awaiting_approval"
    assert run.pending_gate is not None and run.pending_gate.step_id == "c1"


def test_auto_decision_executes(monkeypatch):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    reg = SandboxRegistry(); reg.register(SubprocessSandbox()); _set_current(reg)
    step = AgentStep(id="c1", name="run", kind="code", outputs=["result"],
                     code=CodeStepConfig(code="print('ran')", approval="auto"))
    ctx, run = _ctx_run()
    res = code_exec.execute(object(), step, WorkflowDefinition(id="w1", name="w", steps=[step]), ctx, run)
    assert res.status == "completed" and res.code_exit_code == 0
    assert res.approval_status == "auto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_code_gate.py -v`
Expected: FAIL — `test_tier1_required_raises_gate` fails (step executes instead of pausing).

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/engine_executors/code.py — add helpers + gate branch
from ...models.workflow_models import GatePending  # add to imports


def _approval_required(cfg, backend) -> bool:
    if cfg.approval == "auto":
        return False
    if cfg.approval == "required":
        return True
    caps = backend.capabilities()                    # tier_default
    if caps.isolation_tier == 1:
        return True                                  # subprocess always gates
    return not (cfg.network == "none" and caps.can_auto_run)   # Tier-2: auto iff hardened


def _consume_decision(run: WorkflowRun, step_id: str):
    g = run.pending_gate
    if g and g.step_id == step_id and g.decision is not None:
        run.pending_gate = None
        return g
    return None


# In execute(), AFTER resolving `backend` and BEFORE running:
    decision = _consume_decision(workflow_run, step.id)
    if decision is None and _approval_required(cfg, backend):
        workflow_run.pending_gate = GatePending(
            gate_id=f"{workflow_run.run_id}:{step.id}", run_id=workflow_run.run_id,
            step_id=step.id, step_kind="code", proposed_code=code_src,
            network=cfg.network, files=cfg.files_out,
            tier=backend.capabilities().isolation_tier,
            question=f"Run {len(code_src.splitlines())}-line {cfg.language} in "
                     f"tier-{backend.capabilities().isolation_tier} sandbox?",
        )
        return StepResult(step_id=step.id, status="awaiting_approval",
                          started_at=datetime.utcnow())
    if decision and decision.decision == "rejected":
        return StepResult(step_id=step.id, status="failed", approval_status="rejected",
                          error=f"rejected by operator: {decision.reason or ''}",
                          started_at=datetime.utcnow(), completed_at=datetime.utcnow())
    if decision and decision.decision == "edited" and decision.edited_code:
        code_src = decision.edited_code
        spec.code = code_src
    # ... existing backend.execute(spec) path ...
    # after building res, record approval provenance:
    res.approval_status = ("auto" if decision is None else decision.decision)
```

```python
# api/services/workflow_engine.py — in _execute_steps, immediately AFTER a step's
# StepResult is obtained and BEFORE _checkpoint (~line 920). Adapt the local result
# variable name to the surrounding code (it is the StepResult just returned by
# _execute_one_step for `step`):
            if result.status == "awaiting_approval":
                workflow_run.status = "awaiting_approval"
                workflow_run.step_results.append(result)  # non-completed -> resume re-dispatches
                self._checkpoint(workflow_run)
                logger.info("run %s paused on approval gate (step %s)",
                            workflow_run.run_id, step.id)
                return workflow_run    # halt the scheduler; resume() re-enters after approval
```

> **Why this is correct against `resume`:** the appended result has
> `status="awaiting_approval"` (not `"completed"`), so `resume`'s `completed_ids`
> excludes the step, it drops the non-completed result, and re-runs the step — at which
> point `_consume_decision` finds the operator's recorded decision and proceeds.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_code_gate.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add api/services/engine_executors/code.py api/services/workflow_engine.py tests/integration/test_code_gate.py
git commit -m "feat(sandbox): HITL gate — pause/auto-run policy + scheduler short-circuit"
```

---

### Task 13: Approval endpoint (approve / edit / reject + 409 idempotency)

**Files:**
- Modify: `api/routers/workflows.py` — add `ApprovalRequest` model + `POST /runs/{run_id}/approvals/{gate_id}` (mirror `cancel_run` at :601 for the idempotent-load shape)
- Test: `tests/integration/test_approval_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_approval_endpoint.py
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_approve_unknown_gate_404():
    r = client.post("/api/workflows/runs/does-not-exist/approvals/x", json={"action": "approve"})
    assert r.status_code == 404


# Full approve->resume->execute path is exercised by test_code_gate_resume_e2e
# (Task 13 step 3 wires resume); this asserts the contract + idempotency surface.
def test_approval_request_validation():
    r = client.post("/api/workflows/runs/r/approvals/g", json={"action": "bogus"})
    assert r.status_code in (404, 422)  # 422 if validated before load, 404 after
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_approval_endpoint.py -v`
Expected: FAIL — 404 route not found (endpoint doesn't exist yet) → assertion on 404 may pass spuriously; add the route then confirm behavior. (Run after step 3 to see green.)

- [ ] **Step 3: Write minimal implementation**

```python
# api/routers/workflows.py — module-level request model (BaseModel already imported)
class ApprovalRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_code: Optional[str] = None
    reason: Optional[str] = None


@router.post("/runs/{run_id}/approvals/{gate_id}")
def resolve_approval(run_id: str, gate_id: str, body: ApprovalRequest):
    engine = get_engine()
    snapshot = engine.get_run(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run not found")
    gate = (snapshot.get("pending_gate") or {})
    if not gate or gate.get("gate_id") != gate_id:
        raise HTTPException(status_code=409, detail="no pending gate with that id (already resolved?)")
    if gate.get("decision") is not None:
        raise HTTPException(status_code=409, detail="gate already resolved")

    # Record the decision onto the persisted run, then resume.
    from ..models.workflow_models import WorkflowRun
    run = WorkflowRun.model_validate(snapshot)
    decision = {"approve": "approved", "edit": "edited", "reject": "rejected"}[body.action]
    run.pending_gate.decision = decision
    run.pending_gate.reason = body.reason
    if body.action == "edit":
        run.pending_gate.edited_code = body.edited_code
    if body.action == "reject":
        run.status = "running"   # resume will run the step, which fails fast on rejected
    else:
        run.status = "running"
    engine._checkpoint(run)
    resumed = engine.resume(run_id)
    return {"run_id": run_id, "gate_id": gate_id, "action": body.action,
            "status": resumed.status}
```

> **Imports:** ensure `Literal`/`Optional` are imported in `workflows.py` (add to the
> typing import if missing). `engine._checkpoint(run)` persists the decision before
> `resume` re-reads it from disk.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_approval_endpoint.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routers/workflows.py tests/integration/test_approval_endpoint.py
git commit -m "feat(sandbox): approval endpoint (approve/edit/reject + 409 idempotency)"
```

**✅ Phase 3 boundary:** a Tier-1 code step pauses for approval; the operator
approves/edits/rejects via the endpoint; the run resumes and executes (or fails on
reject). Durable across restart (state is in `run.json`).

---

## Phase 4 — Tier-2 container backend

### Task 14: Container backend (hardened run)

Strictly harder than the cookbook's reference image (which runs as root, no read-only
rootfs, no pids-limit): non-root, `--read-only` + tmpfs, `--cap-drop=ALL`,
`--security-opt=no-new-privileges`, `--network=none` default, resource caps, scratch as
the only writable mount. `can_auto_run=True` (this hardening is what permits Tier-2
auto-run under the §6 policy). Command construction is split into `_build_cmd` so it's
unit-testable without a daemon.

**Files:**
- Create: `api/services/sandbox_impl/container.py`
- Test: `tests/unit/test_sandbox_container.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sandbox_container.py
import shutil
import pytest
from api.services.sandbox import CodeExecSpec
from api.services.sandbox_impl.container import ContainerSandbox


def test_build_cmd_is_hardened():
    sb = ContainerSandbox(runtime="podman", image="enclave-sandbox:latest")
    spec = CodeExecSpec(language="python", code="print(1)", scratch_path="/tmp/s", network="none")
    cmd = sb._build_cmd(spec, "/abs/scratch")
    j = " ".join(cmd)
    for flag in ["--network=none", "--read-only", "--cap-drop=ALL",
                 "--security-opt=no-new-privileges", "--pids-limit=256", "--user"]:
        assert flag in j
    assert "-v /abs/scratch:/work:rw" in j and j.endswith("/work/__entry__.py")
    assert sb.capabilities().isolation_tier == 2 and sb.capabilities().can_auto_run is True


RUNTIME = shutil.which("podman") or shutil.which("docker")


@pytest.mark.skipif(not RUNTIME, reason="no container runtime on PATH")
def test_container_runs_when_image_present(tmp_path):
    # Requires the enclave-sandbox image (Task 15). Skips cleanly in CI without it.
    sb = ContainerSandbox(runtime=RUNTIME)
    res = sb.execute(CodeExecSpec(language="python", code="print('in-container')",
                                  scratch_path=str(tmp_path)))
    if res.exit_code != 0 and "Unable to find image" in res.stderr:
        pytest.skip("enclave-sandbox image not built")
    assert "in-container" in res.stdout and res.tier_used == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sandbox_container.py -v`
Expected: FAIL — `ModuleNotFoundError: api.services.sandbox_impl.container`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/sandbox_impl/container.py
"""Tier-2 sandbox: one hardened container per run. Podman-first (rootless ->
escape lands unprivileged). Strictly harder than the cookbook reference image."""
from __future__ import annotations

import os
import subprocess
import time
from typing import List, Optional

from ..logging_config import logger
from ..sandbox import CodeExecSpec, CodeExecResult, SandboxCapabilities
from ..sandbox_fs import SandboxedFS


class ContainerSandbox:
    name = "container"

    def __init__(self, runtime: str, image: Optional[str] = None) -> None:
        self.runtime = runtime
        self.image = image or os.getenv("SANDBOX_CONTAINER_IMAGE", "enclave-sandbox:latest")

    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            name="container", isolation_tier=2, network_modes=("none", "allowlist"),
            max_mem_mb=8192, languages=("python",), can_auto_run=True,
        )

    def _build_cmd(self, spec: CodeExecSpec, scratch_abs: str) -> List[str]:
        net = "none" if spec.network == "none" else "bridge"
        return [
            self.runtime, "run", "--rm",
            f"--network={net}", "--read-only", "--tmpfs", "/tmp:rw,size=256m",
            f"--memory={spec.mem_mb}m", f"--cpus={spec.cpus}", f"--pids-limit={spec.pids}",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", "65534:65534",
            "-v", f"{scratch_abs}:/work:rw", "-w", "/work",
            self.image, "python", "-I", "/work/__entry__.py",
        ]

    def execute(self, spec: CodeExecSpec) -> CodeExecResult:
        fs = SandboxedFS(spec.scratch_path, max_file_size_mb=50)
        fs.write("__entry__.py", spec.code)
        cmd = self._build_cmd(spec, str(fs.root))
        t0 = time.monotonic()
        try:
            p = subprocess.run(cmd, input=spec.stdin, capture_output=True,
                               text=True, timeout=spec.timeout_s)
            code, out, err, viol = p.returncode, p.stdout, p.stderr, []
        except subprocess.TimeoutExpired as e:
            code, out, err, viol = -9, (e.stdout or ""), (e.stderr or ""), ["timeout exceeded"]
        except Exception as e:  # noqa: BLE001
            logger.warning("container sandbox failed: %s", e)
            return CodeExecResult(exit_code=-1, stdout="", stderr=str(e), tier_used=2,
                                  violations=["container spawn failed"])
        produced = [r for r in fs.walk() if r != "__entry__.py"]
        return CodeExecResult(exit_code=code, stdout=out[:100_000], stderr=err[:100_000],
                              tier_used=2, duration_ms=(time.monotonic() - t0) * 1000,
                              files_produced=produced, violations=viol)
```

> **Note (writable mount):** with rootless **Podman**, `/work` is writable under
> user-namespace mapping. With Docker `--user 65534`, the bind-mounted scratch may need
> `chmod 0777` or `--userns=keep-id`; if the integration test shows permission-denied on
> write, adjust the mapping — this is the Docker/Podman wrinkle, not a logic bug.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sandbox_container.py -v`
Expected: PASS (1 passed, 1 skipped if no runtime/image)

- [ ] **Step 5: Commit**

```bash
git add api/services/sandbox_impl/container.py tests/unit/test_sandbox_container.py
git commit -m "feat(sandbox): Tier-2 hardened container backend"
```

---

### Task 15: Sandbox image + detection registers Tier-2

**Files:**
- Create: `setup/sandbox/Dockerfile`, `setup/sandbox/requirements.txt`
- Test: `tests/unit/test_sandbox_detection_container.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sandbox_detection_container.py
def test_detection_registers_container_when_runtime_present(monkeypatch):
    import api.services.sandbox_detection as det
    monkeypatch.setattr(det.shutil, "which", lambda name: "/usr/bin/podman" if name == "podman" else None)
    reg = det.detect_sandboxes()
    names = [b.name for b in reg.backends()]
    assert "container" in names
    # strongest-first: container (tier 2) resolves ahead of subprocess (tier 1)
    assert reg.resolve(override=None).name == "container"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sandbox_detection_container.py -v`
Expected: FAIL — before Task 14, the lazy `from .sandbox_impl.container import ContainerSandbox` raised; now it imports, so this should pass once Task 14 is merged. If it fails, confirm Task 14's module exists.

- [ ] **Step 3: Write minimal implementation**

```dockerfile
# setup/sandbox/Dockerfile — Tier-2 execution image (Python only; no Node, no agent)
FROM python:3.12-slim
COPY setup/sandbox/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm -rf /root/.cache/pip
USER 65534:65534
WORKDIR /work
# No ENTRYPOINT — the backend passes `python -I /work/__entry__.py` explicitly.
```

```text
# setup/sandbox/requirements.txt — operator-declared sandbox packages (validated at
# step-definition time; NO dynamic pip-install at runtime per spec §4 guardrail).
pandas==2.3.3
numpy==2.3.4
```

Build (documented, not run by CI): `podman build -t enclave-sandbox:latest -f setup/sandbox/Dockerfile .`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sandbox_detection_container.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add setup/sandbox/ tests/unit/test_sandbox_detection_container.py
git commit -m "feat(sandbox): Tier-2 image + detection registers container tier"
```

**✅ Phase 4 boundary:** where Podman/Docker exists, Tier-2 resolves as the strongest tier and runs code in a hardened container.

---

## Phase 5 — `code_exec` chat tool + config + telemetry

### Task 16: `code_exec` plugin tool (chat surface)

Per the spec §5 deviation, v1 exposes `code_exec` through the **chat** `ToolExecutor`
path (a real, working surface). Ships as a plugin tool whose handler declares `__sandbox`
so `PluginService.call_tool` injects the per-conversation `SandboxedFS`. Off by default
(a profile must allow the `code-exec` plugin).

**Files:**
- Create: `plugins/code-exec/plugin.yaml`, `plugins/code-exec/tool.py`
- Test: `tests/unit/test_code_exec_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_code_exec_tool.py
def test_code_exec_handler_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    from api.services.sandbox_registry import SandboxRegistry, _set_current
    from api.services.sandbox_impl.subprocess import SubprocessSandbox
    from api.services.sandbox_fs import SandboxedFS
    reg = SandboxRegistry(); reg.register(SubprocessSandbox()); _set_current(reg)

    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "code_exec_tool", pathlib.Path("plugins/code-exec/tool.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

    result = mod.code_exec(code="print(6*7)", __sandbox=SandboxedFS(str(tmp_path)))
    assert result["exit_code"] == 0 and "42" in result["stdout"]


def test_code_exec_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CODE_EXEC_ENABLED", raising=False)
    from api.services.sandbox_fs import SandboxedFS
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "code_exec_tool2", pathlib.Path("plugins/code-exec/tool.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    out = mod.code_exec(code="print(1)", __sandbox=SandboxedFS(str(tmp_path)))
    assert "disabled" in out.get("error", "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_code_exec_tool.py -v`
Expected: FAIL — `plugins/code-exec/tool.py` does not exist.

- [ ] **Step 3: Write minimal implementation**

```yaml
# plugins/code-exec/plugin.yaml
id: code-exec
name: Code Exec
description: Run Python in the local sandbox.
tools:
  - id: code_exec
    file: tool.py
    function: code_exec
    description: Execute a short Python snippet in an isolated sandbox and return stdout/stderr.
    parameters:
      type: object
      properties:
        code:
          type: string
          description: Python source to execute.
      required: [code]
```

```python
# plugins/code-exec/tool.py
import os


def code_exec(code: str, __sandbox=None) -> dict:
    if os.getenv("CODE_EXEC_ENABLED", "false").lower() != "true":
        return {"error": "code execution disabled (set CODE_EXEC_ENABLED=true)"}
    if __sandbox is None:
        return {"error": "no sandbox bound to this conversation"}
    from api.services.sandbox import CodeExecSpec
    from api.services.sandbox_registry import get_current_sandbox_registry
    backend = get_current_sandbox_registry().resolve(override=None)
    res = backend.execute(CodeExecSpec(language="python", code=code,
                                       scratch_path=str(__sandbox.root)))
    return {"exit_code": res.exit_code, "stdout": res.stdout[:8000],
            "stderr": res.stderr[:4000], "tier_used": res.tier_used}
```

> **Gating:** the tool reaches the model only after a profile lists `code-exec` in its
> `allowed_plugins` (see `profile_service.is_tool_allowed`). Default profiles must NOT
> include it — verify with a profile-filter test mirroring existing
> `tests/**/test_profile*` cases.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_code_exec_tool.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add plugins/code-exec/ tests/unit/test_code_exec_tool.py
git commit -m "feat(sandbox): code_exec chat plugin tool (off by default)"
```

---

### Task 17: Startup wiring — `detect_sandboxes()` + reaper in lifespan

**Files:**
- Modify: `api/main.py` — add a `try/except` block in `lifespan` after the `detect_runners` block (~line 211), before `yield`
- Test: `tests/integration/test_sandbox_lifespan.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_sandbox_lifespan.py
def test_lifespan_initializes_sandbox_registry():
    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app):  # enters the lifespan
        from api.services.sandbox_registry import get_current_sandbox_registry
        reg = get_current_sandbox_registry()
        assert any(b.name == "subprocess" for b in reg.backends())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_sandbox_lifespan.py -v`
Expected: FAIL — `RuntimeError: sandbox registry not initialized` (lifespan doesn't call detect_sandboxes yet).

- [ ] **Step 3: Write minimal implementation**

```python
# api/main.py — inside lifespan(), immediately after the detect_runners try/except (~:211)
    try:
        from .services.sandbox_detection import detect_sandboxes
        from .services.sandbox_reaper import reap_scratch
        sbx = detect_sandboxes()
        logger.info("  📦 Sandbox:      %s", [b.name for b in sbx.backends()])
        reaped = reap_scratch(ttl_hours=int(os.getenv("SANDBOX_SCRATCH_TTL_HOURS", "24")))
        if reaped:
            logger.info("  🧹 Reaped %d stale sandbox scratch dir(s)", len(reaped))
    except Exception as e:  # noqa: BLE001
        logger.warning("Sandbox detection failed: %s", e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_sandbox_lifespan.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/integration/test_sandbox_lifespan.py
git commit -m "feat(sandbox): wire detect_sandboxes + reaper into app lifespan"
```

---

### Task 18: Runs-view code panel + inline approval (UI — preview-verified)

The `StepResult` code fields (Task 6) and `pending_gate` (Task 11) are already
serialized by the run endpoints. This task renders them and adds an approve/edit/reject
control when `run.status == "awaiting_approval"`. **No pytest** — verified via the
`preview_*` workflow because it's `api/static/index.html` (the monolithic UI).

**Files:**
- Modify: `api/static/index.html` — extend the existing per-step Runs-view renderer (the
  one that renders the `warm / N.Ns load` chip — search for `keep_alive_used` or `load`
  in the step-result render function) to add a code panel; add an approval action bar.

- [ ] **Step 1: Locate the renderer**

Run: `grep -n "keep_alive_used\|load_duration_ms\|step-result" api/static/index.html | head`
Find the function that renders a step result row in the Runs view.

- [ ] **Step 2: Add the code panel + approval bar**

In that renderer, when `sr.code_exit_code !== undefined && sr.code_exit_code !== null`, append:

```javascript
// inside the step-result renderer, after the existing telemetry chip
if (sr.code_exit_code !== null && sr.code_exit_code !== undefined) {
  const ok = sr.code_exit_code === 0;
  html += `<div class="code-panel ${ok ? 'ok' : 'fail'}">
    <span>tier ${sr.tier_used ?? '–'}</span>
    <span>exit ${sr.code_exit_code}</span>
    <span>${sr.peak_rss_mb ? sr.peak_rss_mb.toFixed(0)+'MB' : ''}</span>
    <span>${(sr.files_produced||[]).length} files</span>
    <span>${sr.promoted ? 'promoted' : 'in-scratch'}</span>
    <span>approval: ${sr.approval_status ?? '–'}</span>
  </div>`;
}
```

For the awaiting-approval bar (when `run.status === 'awaiting_approval' && run.pending_gate`):

```javascript
function renderGate(run) {
  const g = run.pending_gate; if (!g) return '';
  return `<div class="gate-bar">
    <pre class="gate-code">${escapeHtml(g.proposed_code)}</pre>
    <div class="gate-meta">tier ${g.tier} · net ${g.network} · ${(g.files||[]).length} files out</div>
    <button onclick="resolveGate('${run.run_id}','${g.gate_id}','approve')">Approve</button>
    <button onclick="resolveGate('${run.run_id}','${g.gate_id}','reject')">Reject</button>
  </div>`;
}
async function resolveGate(runId, gateId, action) {
  await fetch(`/api/workflows/runs/${runId}/approvals/${gateId}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action})
  });
  refreshRun(runId);   // re-fetch the run to show resumed state
}
```

- [ ] **Step 3: Verify in the browser (preview workflow)**

Start the API + preview, run a `kind: code` workflow with `approval: required`, confirm:
the Runs view shows the gate bar with the proposed code; clicking **Approve** resumes the
run and the code panel renders exit/tier/promoted. Capture a screenshot.

```bash
# CODE_EXEC_ENABLED=true python api/main.py   # then drive via preview_start / preview_click / preview_screenshot
```

- [ ] **Step 4: Commit**

```bash
git add api/static/index.html
git commit -m "feat(sandbox): Runs-view code panel + inline approval gate"
```

**✅ Phase 5 boundary:** chat can run code via the gated tool; the registry initializes at
startup; the Runs view shows code telemetry and the inline approval gate.

---

## Self-Review

**1. Spec coverage**

| Spec section | Covered by |
|---|---|
| §3 backend registry idiom | Task 1, 4 |
| §4 Tier-1 / Tier-2 + resolution | Task 3, 4, 14, 15 |
| §5 `kind: code` step + `code_exec` tool | Task 5, 7, 8, 16 (tool = chat surface per deviation) |
| §6 execution gate + promotion gate + auto-run policy | Task 9 (promote), 11–13 (exec gate), 12 (policy) |
| §7 data model | Task 1, 5, 6, 11 |
| §8 threat register controls | rlimits/timeout (T3), pids/caps/non-root/read-only (T14), env-scrub (T3), traversal re-validate (T2, T9), network=none (T3, T14), mandatory Tier-1 gate (T12) |
| §9 telemetry + config | Task 6, 17, 18 |
| §10 testing | every task (unit + integration; security asserts in T3/T14) |
| §11 decisions | Podman-first (T14/15), Tier-2 auto-run policy (T12), three-zone (T9) |
| §12 deferred | WASM/grader/multi-lang/browser not implemented; **verification turn** needs no new code — it's authored as a second `kind: code` step (composition), so coverage is satisfied without a task |

No uncovered spec requirement.

**2. Placeholder scan:** No `TBD`/`TODO`/"add error handling". The `# ... existing
backend.execute(spec) path ...` markers in Task 12 are integration references into code
written in Task 7 (shown there), not unwritten logic. `promote_predicate` is an explicit
deferred field, not a placeholder.

**3. Type consistency:** `SandboxBackend.execute(CodeExecSpec) -> CodeExecResult` used
identically in T1/T3/T7/T14/T16. `CodeExecSpec` field names (`scratch_path`, `mem_mb`,
`cpus`, `pids`, `network`) consistent across construction sites. `GatePending`
fields/`decision` values (`approved`/`edited`/`rejected`) consistent T11→T12→T13.
`StepResult.approval_status` values (`auto`/`approved`/`edited`/`rejected`) consistent
T6/T12. `resolve(override=...)`, `get_current_sandbox_registry()`, `can_auto_run`
consistent throughout. The approval-endpoint action→decision map
(`approve→approved`, `edit→edited`, `reject→rejected`) matches the values
`_consume_decision` reads in T12.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-03-code-exec-sandbox.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for this plan given the security-critical surface (each backend/gate task gets an isolated review).

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
