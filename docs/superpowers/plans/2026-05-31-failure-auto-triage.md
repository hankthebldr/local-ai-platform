# Failure Auto-Triage & Operator-Owned Error Telemetry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn CI test failures and live runtime errors into deduplicated, severity-labelled GitHub output (annotations, run-summary table, auto-filed Issues), via one shared triage core, with opt-in operator-owned error reporting.

**Architecture:** A self-contained top-level `triage/` package (zero FastAPI imports) implements `normalize → fingerprint → classify → enrich → emit`. CI runs it via `python -m triage ci`; the live app calls the same core from a catch-all exception handler. Classification is deterministic rules + best-effort local-Ollama enrichment that degrades silently where Ollama is absent (always, in hosted CI). Reporting from the running app is opt-in, off by default, redaction-mandatory, operator-owned by default.

**Tech Stack:** Python 3.12/3.13, Pydantic v2, `requests` (core dep), `defusedxml` (hardened JUnit parsing — one tiny pure-Python dep), `gh` CLI (CI), pytest.

**Spec:** [docs/superpowers/specs/2026-05-31-failure-auto-triage-design.md](../specs/2026-05-31-failure-auto-triage-design.md)

---

## File Structure

```
triage/                         # NEW top-level package, no api/ imports
  __init__.py
  __main__.py                   # CLI: python -m triage ci --junit … --emit …
  models.py                     # FailureEvent, TriageVerdict, Severity, Category
  fingerprint.py                # app_frames(), fingerprint_event(), compute()
  classify.py                   # classify() — operator-tuned rule body
  enrich.py                     # enrich() — local Ollama, best-effort
  redact.py                     # redact(), redact_event() — mandatory scrub
  config.py                     # TriageConfig.from_env()
  reporting.py                  # report() — enrich + emit to configured sink (runtime)
  collectors/
    __init__.py
    junit.py                    # parse_junit() -> (events, total)   [CI]
    runtime.py                  # from_exception() -> FailureEvent    [runtime]
  emitters/
    __init__.py
    base.py                     # Emitter Protocol
    annotations.py              # ::error:: / ::warning:: to stdout    [CI]
    step_summary.py             # markdown table → $GITHUB_STEP_SUMMARY [CI]
    github_issues.py            # deduped gh issue create/comment       [CI + runtime sink]
    webhook.py                  # POST redacted JSON to operator sink   [runtime]
tests/triage/                   # mirrors the package, test-first
  test_models.py test_fingerprint.py test_classify.py test_junit.py
  test_annotations.py test_step_summary.py test_github_issues.py
  test_redact.py test_enrich.py test_runtime.py test_webhook.py
  test_cli.py test_runtime_handler.py
tests/fixtures/junit/           # sample JUnit XML inputs
  pass.xml single_failure.xml mass_failure.xml
```

Modified later (Phase 2): `api/exceptions.py`, `api/main.py` (handler registration only), `.env.example`, `CLAUDE.md` (conventions line), `README` privacy copy.

---

# PHASE 1 — CI path (no app changes, no new deps, no egress)

### Task 1: Package skeleton + core data model

**Files:**
- Create: `triage/__init__.py`, `triage/collectors/__init__.py`, `triage/emitters/__init__.py`
- Create: `triage/models.py`
- Test: `tests/triage/__init__.py`, `tests/triage/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_models.py
from __future__ import annotations

from triage.models import FailureEvent, TriageVerdict, Severity, Category


def test_failure_event_defaults():
    ev = FailureEvent(source="ci", exception_type="AssertionError", message="boom")
    assert ev.fingerprint == ""
    assert ev.env == {}
    assert ev.traceback is None


def test_triage_verdict_roundtrip():
    ev = FailureEvent(source="runtime", exception_type="ValueError", message="bad")
    v = TriageVerdict(event=ev, severity=Severity.high, category=Category.unhandled, rule_summary="x")
    assert v.seen_count == 1
    assert v.enriched is False
    assert v.model_dump(mode="json")["severity"] == "high"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/__init__.py
"""Self-contained failure-triage core. MUST NOT import the FastAPI app."""
```

```python
# triage/collectors/__init__.py  (empty)
# triage/emitters/__init__.py    (empty)
# tests/triage/__init__.py       (empty)
```

```python
# triage/models.py
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class Category(str, Enum):
    assertion = "assertion"
    import_error = "import_error"
    timeout = "timeout"
    connection = "connection"
    flaky = "flaky"
    config = "config"
    unhandled = "unhandled"
    unknown = "unknown"


class FailureEvent(BaseModel):
    source: Literal["ci", "runtime"]
    fingerprint: str = ""
    exception_type: str
    message: str
    traceback: str | None = None
    test_id: str | None = None
    route: str | None = None
    file: str | None = None
    line: int | None = None
    func: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    occurred_at: str | None = None
    request_id: str | None = None


class TriageVerdict(BaseModel):
    event: FailureEvent
    severity: Severity
    category: Category
    rule_summary: str
    likely_cause: str | None = None
    first_check: str | None = None
    enriched: bool = False
    seen_count: int = 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/__init__.py triage/collectors/__init__.py triage/emitters/__init__.py triage/models.py tests/triage/__init__.py tests/triage/test_models.py
git commit -m "feat(triage): core data model (FailureEvent, TriageVerdict)"
```

---

### Task 2: Fingerprint & dedup key

**Files:**
- Create: `triage/fingerprint.py`
- Test: `tests/triage/test_fingerprint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_fingerprint.py
from __future__ import annotations

from triage.fingerprint import app_frames, fingerprint_event
from triage.models import FailureEvent

TB = '''Traceback (most recent call last):
  File "/repo/api/services/foo.py", line 40, in handle
    do_thing()
  File "/usr/lib/python3.12/site-packages/lib/x.py", line 9, in do_thing
    raise ValueError("x")
ValueError: x'''


def test_app_frames_skips_libs_and_normalizes():
    frames = app_frames(TB, repo_root="/repo")
    assert frames == [("api/services/foo.py", 40, "handle")]


def test_fingerprint_stable_across_line_shifts():
    tb_shifted = TB.replace("line 40", "line 57")
    a = FailureEvent(source="ci", exception_type="ValueError", message="x", traceback=TB, test_id="t::a")
    b = FailureEvent(source="ci", exception_type="ValueError", message="x", traceback=tb_shifted, test_id="t::a")
    assert fingerprint_event(a, repo_root="/repo") == fingerprint_event(b, repo_root="/repo")


def test_fingerprint_differs_on_exception_type():
    a = FailureEvent(source="ci", exception_type="ValueError", message="x", traceback=TB, test_id="t::a")
    b = FailureEvent(source="ci", exception_type="KeyError", message="x", traceback=TB, test_id="t::a")
    assert fingerprint_event(a, repo_root="/repo") != fingerprint_event(b, repo_root="/repo")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_fingerprint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.fingerprint'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/fingerprint.py
from __future__ import annotations

import hashlib
import re

from .models import FailureEvent

_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
_NOISE = [
    re.compile(r"0x[0-9a-fA-F]+"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"),
]


def app_frames(traceback: str | None, repo_root: str = "") -> list[tuple[str, int, str]]:
    """Return (relpath, line, func) for frames inside the repo; skip stdlib/site-packages."""
    out: list[tuple[str, int, str]] = []
    for path, line, func in _FRAME_RE.findall(traceback or ""):
        if "/site-packages/" in path or "/lib/python" in path:
            continue
        rel = path
        if repo_root and path.startswith(repo_root):
            rel = path[len(repo_root):].lstrip("/")
        out.append((rel, int(line), func))
    return out


def _scrub(text: str) -> str:
    for rx in _NOISE:
        text = rx.sub("", text)
    return text


def compute(*, source: str, exception_type: str, location: str) -> str:
    basis = _scrub(f"{source}|{exception_type}|{location}")
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def fingerprint_event(event: FailureEvent, repo_root: str = "") -> str:
    frames = app_frames(event.traceback, repo_root)
    # frame signature drops line numbers (kept only for display/annotation)
    sigs = [f"{rel}:{func}" for rel, _line, func in frames]
    if event.source == "ci":
        location = event.test_id or (sigs[-1] if sigs else (event.func or ""))
    else:
        location = (event.route or "") + "|" + "|".join(sigs[:3])
    return compute(source=event.source, exception_type=event.exception_type, location=location)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_fingerprint.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/fingerprint.py tests/triage/test_fingerprint.py
git commit -m "feat(triage): stable fingerprint with line-number-insensitive grouping"
```

---

### Task 3: Rules classifier  ⟵ operator refinement point

> **Learning-mode note (for the execution session):** this task ships a complete, passing baseline so the plan is executable end-to-end. The **rule ordering**, the **mass-failure thresholds** (`total >= 4`, `> 0.5`), and the `_CORE_MODULES` set are operator judgment calls. When executing this task, present the baseline to Henry and invite a ~8-line refinement of the rule body before committing. Do not block — the baseline is correct as written.

**Files:**
- Create: `triage/classify.py`
- Test: `tests/triage/test_classify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_classify.py
from __future__ import annotations

import pytest

from triage.classify import classify
from triage.models import FailureEvent, Severity, Category


def _ev(etype, msg="", source="ci", route=None):
    return FailureEvent(source=source, exception_type=etype, message=msg, route=route)


@pytest.mark.parametrize("etype,msg,sev,cat", [
    ("OllamaConnectionError", "connection refused", Severity.high, Category.connection),
    ("AssertionError", "assert 1 == 2", Severity.medium, Category.assertion),
    ("ModuleNotFoundError", "No module named 'api.services.x'", Severity.critical, Category.import_error),
    ("ModuleNotFoundError", "No module named 'thirdparty'", Severity.high, Category.import_error),
    ("TimeoutError", "timed out", Severity.low, Category.timeout),
])
def test_classify_rules(etype, msg, sev, cat):
    s, c, _summary = classify(_ev(etype, msg))
    assert (s, c) == (sev, cat)


def test_mass_failure_escalates_to_critical():
    s, c, _ = classify(_ev("AssertionError", "x"), total=10, failed=8)
    assert s == Severity.critical and c == Category.import_error


def test_runtime_unhandled_default():
    s, c, _ = classify(_ev("RuntimeError", "boom", source="runtime", route="POST /v1/chat"))
    assert s == Severity.high and c == Category.unhandled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.classify'`

- [ ] **Step 3: Write minimal implementation (baseline — operator may refine)**

```python
# triage/classify.py
from __future__ import annotations

from .models import FailureEvent, Severity, Category

# Modules whose import failure is fatal to boot. Operator-tunable.
_CORE_MODULES = ("api.", "fastapi", "pydantic", "uvicorn", "starlette")


def classify(event: FailureEvent, *, total: int = 1, failed: int = 1) -> tuple[Severity, Category, str]:
    """Deterministic, dependency-free. First match wins; fallback (medium, unknown)."""
    etype = event.exception_type
    msg = (event.message or "").lower()

    # Mass failure smells like a collection-time import break.
    if total >= 4 and failed / max(total, 1) > 0.5:
        return Severity.critical, Category.import_error, f"{failed}/{total} failing — likely a collection-time import break"

    if etype in ("ImportError", "ModuleNotFoundError"):
        is_core = any(m in msg for m in _CORE_MODULES)
        sev = Severity.critical if is_core else Severity.high
        return sev, Category.import_error, f"Import failure ({etype})"

    if etype.endswith("ConnectionError") or "connection refused" in msg:
        return Severity.high, Category.connection, "Infra dependency unreachable"

    if etype == "TimeoutError" or "timed out" in msg:
        return Severity.low, Category.timeout, "Timeout — flaky candidate"

    if etype == "AssertionError":
        return Severity.medium, Category.assertion, "Logic/assertion regression"

    if event.source == "runtime":
        return Severity.high, Category.unhandled, f"Unhandled {etype} in {event.route or 'app'}"

    return Severity.medium, Category.unknown, f"Unclassified {etype}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_classify.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/classify.py tests/triage/test_classify.py
git commit -m "feat(triage): rules classifier (severity + category)"
```

---

### Task 4: JUnit collector + fixtures

**Files:**
- Create: `triage/collectors/junit.py`
- Modify: `setup/requirements-core.txt` (add `defusedxml>=0.7.1`)
- Create: `tests/fixtures/junit/single_failure.xml`, `tests/fixtures/junit/pass.xml`, `tests/fixtures/junit/mass_failure.xml`
- Test: `tests/triage/test_junit.py`

- [ ] **Step 1: Write the fixtures + failing test**

```xml
<!-- tests/fixtures/junit/single_failure.xml -->
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="3" failures="1" errors="0">
    <testcase classname="tests.unit.test_math" name="test_add" time="0.01"/>
    <testcase classname="tests.unit.test_math" name="test_divide" time="0.01">
      <failure message="assert 1 == 2" type="AssertionError">Traceback (most recent call last):
  File "/repo/tests/unit/test_math.py", line 12, in test_divide
    assert divide(4, 2) == 2
AssertionError: assert 1 == 2</failure>
    </testcase>
    <testcase classname="tests.unit.test_io" name="test_read" time="0.01"/>
  </testsuite>
</testsuites>
```

```xml
<!-- tests/fixtures/junit/pass.xml -->
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="2" failures="0" errors="0">
    <testcase classname="tests.unit.test_a" name="test_x" time="0.01"/>
    <testcase classname="tests.unit.test_a" name="test_y" time="0.01"/>
  </testsuite>
</testsuites>
```

```xml
<!-- tests/fixtures/junit/mass_failure.xml -->
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="5" failures="0" errors="4">
    <testcase classname="tests.unit.test_a" name="test_1"><error message="No module named 'api.services.gone'" type="ModuleNotFoundError">ModuleNotFoundError: No module named 'api.services.gone'</error></testcase>
    <testcase classname="tests.unit.test_b" name="test_2"><error message="No module named 'api.services.gone'" type="ModuleNotFoundError">x</error></testcase>
    <testcase classname="tests.unit.test_c" name="test_3"><error message="No module named 'api.services.gone'" type="ModuleNotFoundError">x</error></testcase>
    <testcase classname="tests.unit.test_d" name="test_4"><error message="No module named 'api.services.gone'" type="ModuleNotFoundError">x</error></testcase>
    <testcase classname="tests.unit.test_e" name="test_5" time="0.01"/>
  </testsuite>
</testsuites>
```

```python
# tests/triage/test_junit.py
from __future__ import annotations

from pathlib import Path

from triage.collectors.junit import parse_junit

FIX = Path(__file__).parent.parent / "fixtures" / "junit"


def test_parse_single_failure():
    events, total = parse_junit(str(FIX / "single_failure.xml"), repo_root="/repo")
    assert total == 3
    assert len(events) == 1
    ev = events[0]
    assert ev.source == "ci"
    assert ev.exception_type == "AssertionError"
    assert ev.test_id == "tests.unit.test_math::test_divide"
    assert ev.file == "tests/unit/test_math.py" and ev.line == 12
    assert ev.fingerprint  # populated


def test_parse_pass_yields_no_events():
    events, total = parse_junit(str(FIX / "pass.xml"))
    assert events == [] and total == 2


def test_parse_mass_failure():
    events, total = parse_junit(str(FIX / "mass_failure.xml"))
    assert total == 5 and len(events) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_junit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.collectors.junit'`

- [ ] **Step 3: Write minimal implementation**

First add the hardened XML parser dependency (stdlib `xml.etree` is vulnerable to XXE and billion-laughs entity expansion; `defusedxml` is the standard, pure-Python fix):

```bash
echo "defusedxml>=0.7.1" >> setup/requirements-core.txt
pip install "defusedxml>=0.7.1"
```

```python
# triage/collectors/junit.py
from __future__ import annotations

import platform

import defusedxml.ElementTree as ET  # XXE + billion-laughs hardened (drop-in for xml.etree)

from ..fingerprint import app_frames, fingerprint_event
from ..models import FailureEvent


def _etype_from_message(message: str) -> str:
    head = (message or "").strip().split(":", 1)[0]
    return head.split()[-1] if head else "Failure"


def parse_junit(path: str, *, repo_root: str = "", enclave_version: str = "unknown") -> tuple[list[FailureEvent], int]:
    root = ET.parse(path).getroot()
    env = {
        "python_version": platform.python_version(),
        "os": platform.system(),
        "enclave_version": enclave_version,
    }
    events: list[FailureEvent] = []
    total = 0
    for tc in root.iter("testcase"):
        total += 1
        node = tc.find("failure")
        if node is None:
            node = tc.find("error")
        if node is None:
            continue
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        test_id = f"{classname}::{name}" if classname else name
        message = node.get("message", "") or ""
        tb = node.text or ""
        etype = node.get("type") or _etype_from_message(message)
        ev = FailureEvent(
            source="ci",
            exception_type=etype,
            message=(message.splitlines()[0][:300] if message else etype),
            traceback=tb,
            test_id=test_id,
            env=dict(env),
        )
        frames = app_frames(tb, repo_root)
        if frames:
            ev.file, ev.line, ev.func = frames[-1]
        ev.fingerprint = fingerprint_event(ev, repo_root=repo_root)
        events.append(ev)
    return events, total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_junit.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/collectors/junit.py setup/requirements-core.txt tests/fixtures/junit/ tests/triage/test_junit.py
git commit -m "feat(triage): JUnit XML collector + fixtures (defusedxml-hardened)"
```

---

### Task 5: Annotation emitter

**Files:**
- Create: `triage/emitters/base.py`, `triage/emitters/annotations.py`
- Test: `tests/triage/test_annotations.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_annotations.py
from __future__ import annotations

from triage.emitters.annotations import AnnotationEmitter
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v(sev, file=None, line=None):
    ev = FailureEvent(source="ci", exception_type="AssertionError", message="boom", file=file, line=line)
    return TriageVerdict(event=ev, severity=sev, category=Category.assertion, rule_summary="regression")


def test_error_annotation_with_location(capsys):
    AnnotationEmitter().emit([_v(Severity.high, file="api/x.py", line=12)])
    out = capsys.readouterr().out
    assert out.startswith("::error ")
    assert "file=api/x.py,line=12" in out
    assert "title=high: assertion" in out


def test_low_severity_is_warning(capsys):
    AnnotationEmitter().emit([_v(Severity.low)])
    assert capsys.readouterr().out.startswith("::warning")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_annotations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.emitters.annotations'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/emitters/base.py
from __future__ import annotations

from typing import Protocol

from ..models import TriageVerdict


class Emitter(Protocol):
    def emit(self, verdicts: list[TriageVerdict]) -> None: ...
```

```python
# triage/emitters/annotations.py
from __future__ import annotations

from ..models import TriageVerdict, Severity


def _level(sev: Severity) -> str:
    return "warning" if sev == Severity.low else "error"


class AnnotationEmitter:
    def emit(self, verdicts: list[TriageVerdict]) -> None:
        for v in verdicts:
            ev = v.event
            params: list[str] = []
            if ev.file:
                params.append(f"file={ev.file}")
                if ev.line:
                    params.append(f"line={ev.line}")
            params.append(f"title={v.severity.value}: {v.category.value}")
            param_str = ",".join(params)
            msg = f"{v.rule_summary} — {ev.message}"
            print(f"::{_level(v.severity)} {param_str}::{msg}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_annotations.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/emitters/base.py triage/emitters/annotations.py tests/triage/test_annotations.py
git commit -m "feat(triage): GitHub annotation emitter"
```

---

### Task 6: Step-summary emitter

**Files:**
- Create: `triage/emitters/step_summary.py`
- Test: `tests/triage/test_step_summary.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_step_summary.py
from __future__ import annotations

from triage.emitters.step_summary import StepSummaryEmitter
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v():
    ev = FailureEvent(source="ci", exception_type="AssertionError", message="boom", test_id="t::a")
    return TriageVerdict(event=ev, severity=Severity.medium, category=Category.assertion, rule_summary="regression")


def test_writes_markdown_table(tmp_path):
    path = tmp_path / "summary.md"
    StepSummaryEmitter(path=str(path)).emit([_v()])
    text = path.read_text()
    assert "## " in text and "| Severity |" in text
    assert "`t::a`" in text and "medium" in text


def test_no_path_is_noop(tmp_path):
    StepSummaryEmitter(path=None).emit([_v()])  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_step_summary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.emitters.step_summary'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/emitters/step_summary.py
from __future__ import annotations

import os

from ..models import TriageVerdict


class StepSummaryEmitter:
    def __init__(self, path: str | None = None):
        self.path = path if path is not None else os.getenv("GITHUB_STEP_SUMMARY")

    def emit(self, verdicts: list[TriageVerdict]) -> None:
        if not self.path:
            return
        lines = ["## 🔎 Triage summary", "", "| Severity | Category | Test / Route | Summary |", "|---|---|---|---|"]
        if not verdicts:
            lines.append("| — | — | — | No failures 🎉 |")
        for v in verdicts:
            loc = v.event.test_id or v.event.route or "—"
            lines.append(f"| {v.severity.value} | {v.category.value} | `{loc}` | {v.rule_summary} |")
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_step_summary.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/emitters/step_summary.py tests/triage/test_step_summary.py
git commit -m "feat(triage): step-summary markdown emitter"
```

---

### Task 7: Deduplicating, rate-limit-safe GitHub Issue emitter

> **Operator guardrail (Henry, 2026-05-31): do NOT blow up the GitHub API.** GitHub's *search* API caps at **30 req/min** and content creation has secondary abuse limits. This emitter therefore: makes **one** `gh issue list` call per run (core REST, never `--search`), builds a fingerprint→issue map in memory, **dedupes verdicts before any API call**, **caps issues per run** (default 10, suppressed count logged), **throttles** between writes, and **hard-stops on the first API error** (no retry storm).

**Files:**
- Create: `triage/emitters/github_issues.py`
- Test: `tests/triage/test_github_issues.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_github_issues.py
from __future__ import annotations

import json

from triage.emitters.github_issues import GitHubIssueEmitter, MARKER
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v(fp="abc123", sev=Severity.high):
    ev = FailureEvent(source="ci", exception_type="AssertionError", message="boom", test_id="t::a", fingerprint=fp)
    return TriageVerdict(event=ev, severity=sev, category=Category.assertion, rule_summary="regression")


class FakeGh:
    """Records gh calls. `existing` maps fingerprint -> issue number (pre-existing open issues)."""

    def __init__(self, existing=None):
        self.calls = []
        self._existing = existing or {}

    def __call__(self, args):
        self.calls.append(args)
        if "list" in args:
            return json.dumps([{"number": n, "body": MARKER.format(fp=fp)} for fp, n in self._existing.items()])
        return ""


def test_lists_once_then_creates_no_per_fingerprint_search():
    gh = FakeGh(existing={})
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0).emit([_v()])
    # Exactly ONE list call, and NO --search (the search API caps at 30/min — must avoid).
    assert sum(1 for c in gh.calls if "list" in c) == 1
    assert not any("--search" in c for c in gh.calls)
    create = [c for c in gh.calls if "create" in c]
    assert len(create) == 1 and "--label" in create[0]


def test_recurrence_comments_not_duplicates():
    gh = FakeGh(existing={"abc123": 7})
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0).emit([_v()])
    assert any("comment" in c for c in gh.calls)
    assert not any("create" in c for c in gh.calls)


def test_dedupe_collapses_same_fingerprint_to_one_create():
    gh = FakeGh(existing={})
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0).emit([_v(fp="dup"), _v(fp="dup"), _v(fp="dup")])
    assert sum(1 for c in gh.calls if "create" in c) == 1   # 3 same-fp verdicts -> 1 issue


def test_caps_issues_per_run_and_warns(capsys):
    gh = FakeGh(existing={})
    verdicts = [_v(fp=f"fp{i}") for i in range(5)]
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0, max_issues=2).emit(verdicts)
    assert sum(1 for c in gh.calls if "create" in c) == 2   # capped at 2
    assert "3 more distinct failures not filed" in capsys.readouterr().out


def test_api_error_stops_without_retry_storm(capsys):
    class BoomGh(FakeGh):
        def __call__(self, args):
            if "create" in args:
                raise RuntimeError("API rate limit exceeded")
            return super().__call__(args)

    gh = BoomGh(existing={})
    GitHubIssueEmitter(repo="o/r", runner=gh, throttle_s=0).emit([_v(fp="a"), _v(fp="b")])
    assert sum(1 for c in gh.calls if "create" in c) == 1   # stop after first error, no storm
    assert "stopped" in capsys.readouterr().out


def test_dry_run_emits_nothing(capsys):
    gh = FakeGh()
    GitHubIssueEmitter(repo="o/r", dry_run=True, runner=gh).emit([_v()])
    assert gh.calls == []
    assert "dry-run" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_github_issues.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.emitters.github_issues'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/emitters/github_issues.py
from __future__ import annotations

import json
import re
import subprocess
import time

from ..models import TriageVerdict, Severity

MARKER = "<!-- fp:{fp} -->"
_FP_RE = re.compile(r"<!-- fp:([0-9a-f]+) -->")
_SEVERITY_ORDER = {Severity.critical: 0, Severity.high: 1, Severity.medium: 2, Severity.low: 3}


class GitHubIssueEmitter:
    """Files deduplicated GitHub issues while staying well under GitHub API rate limits:
    ONE `issue list` per run (core REST, never the 30/min search API), in-memory
    fingerprint dedup, a per-run issue cap, throttling between writes, and a hard stop
    on the first API error (no retry storm)."""

    def __init__(self, *, repo: str | None = None, dry_run: bool = False, runner=None,
                 max_issues: int = 10, throttle_s: float = 1.0):
        self.repo = repo
        self.dry_run = dry_run
        self.max_issues = max_issues
        self.throttle_s = throttle_s
        self._run = runner or self._default_run

    def _default_run(self, args: list[str]) -> str:
        return subprocess.run(args, capture_output=True, text=True, check=True).stdout

    def _gh(self, *args: str) -> str:
        cmd = ["gh", *args]
        if self.repo:
            cmd += ["--repo", self.repo]
        return self._run(cmd)

    def emit(self, verdicts: list[TriageVerdict]) -> None:
        deduped = self._dedupe(verdicts)
        if self.dry_run:
            for v in deduped:
                print(f"[dry-run] would emit issue for fp={v.event.fingerprint} ({v.severity.value})")
            return
        existing = self._existing_map()  # ONE list call — never per-fingerprint search
        ranked = sorted(deduped, key=lambda v: _SEVERITY_ORDER.get(v.severity, 9))
        capped, suppressed = ranked[: self.max_issues], ranked[self.max_issues:]
        for i, v in enumerate(capped):
            try:
                self._emit_one(v, existing)
            except Exception as exc:  # rate limit / API failure → stop, don't retry-storm
                print(f"::warning::triage issue emit stopped after {i} issue(s) (GitHub API error: {exc})")
                return
            if self.throttle_s and i < len(capped) - 1:
                time.sleep(self.throttle_s)
        if suppressed:
            fps = ", ".join(v.event.fingerprint for v in suppressed)
            print(f"::warning::{len(suppressed)} more distinct failures not filed this run "
                  f"(cap={self.max_issues}, avoids GitHub rate limits): {fps}")

    def _dedupe(self, verdicts: list[TriageVerdict]) -> list[TriageVerdict]:
        by_fp: dict[str, TriageVerdict] = {}
        for v in verdicts:
            fp = v.event.fingerprint
            if fp in by_fp:
                by_fp[fp].seen_count += 1
            else:
                by_fp[fp] = v
        return list(by_fp.values())

    def _existing_map(self) -> dict[str, int]:
        out = self._gh("issue", "list", "--label", "triage:auto", "--state", "open",
                       "--json", "number,body", "--limit", "100")
        mapping: dict[str, int] = {}
        for issue in json.loads(out or "[]"):
            m = _FP_RE.search(issue.get("body") or "")
            if m:
                mapping[m.group(1)] = issue["number"]
        return mapping

    def _emit_one(self, v: TriageVerdict, existing: dict[str, int]) -> None:
        fp = v.event.fingerprint
        if fp in existing:
            self._gh("issue", "comment", str(existing[fp]), "--body", self._recurrence_body(v))
        else:
            self._gh("issue", "create", "--title", self._title(v), "--body", self._body(v),
                     "--label", self._labels(v))

    def _title(self, v: TriageVerdict) -> str:
        return f"[{v.severity.value}] {v.category.value}: {v.event.message[:80]}"

    def _labels(self, v: TriageVerdict) -> str:
        return f"bug,triage:auto,severity:{v.severity.value},category:{v.category.value}"

    def _recurrence_body(self, v: TriageVerdict) -> str:
        run = v.event.env.get("run_url", "a recent run")
        return f"Recurred in {run}. Severity `{v.severity.value}`."

    def _body(self, v: TriageVerdict) -> str:
        ev = v.event
        enr = ""
        if v.enriched:
            enr = f"\n**Likely cause:** {v.likely_cause}\n**First check:** {v.first_check}\n"
        return (
            f"{MARKER.format(fp=ev.fingerprint)}\n\n"
            f"### Description\nAuto-filed by triage. {v.rule_summary}\n{enr}\n"
            f"### Location\n`{ev.test_id or ev.route or '—'}` ({ev.file or '?'}:{ev.line or '?'})\n\n"
            f"### Environment\n```\n{ev.env}\n```\n\n"
            f"### Logs\n```\n{(ev.traceback or '')[-2000:]}\n```\n"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_github_issues.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/emitters/github_issues.py tests/triage/test_github_issues.py
git commit -m "feat(triage): deduplicating GitHub Issue emitter"
```

---

### Task 8: CLI entrypoint (`python -m triage ci`)

**Files:**
- Create: `triage/__main__.py`
- Test: `tests/triage/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_cli.py
from __future__ import annotations

from pathlib import Path

from triage.__main__ import main

FIX = Path(__file__).parent.parent / "fixtures" / "junit"


def test_ci_annotations_and_summary(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "sum.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc = main(["ci", "--junit", str(FIX / "single_failure.xml"), "--emit", "annotations,summary", "--repo-root", "/repo"])
    assert rc == 0
    assert "::error" in capsys.readouterr().out
    assert "| Severity |" in summary.read_text()


def test_fail_on_critical_returns_nonzero(monkeypatch):
    rc = main(["ci", "--junit", str(FIX / "mass_failure.xml"), "--emit", "annotations", "--fail-on", "critical"])
    assert rc == 2


def test_fork_pr_skips_issues(monkeypatch, capsys):
    monkeypatch.setenv("TRIAGE_FORK_PR", "true")
    rc = main(["ci", "--junit", str(FIX / "single_failure.xml"), "--emit", "issues"])
    assert rc == 0
    assert "fork PR" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.__main__'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/__main__.py
from __future__ import annotations

import argparse
import os
import sys

from .classify import classify
from .collectors.junit import parse_junit
from .emitters.annotations import AnnotationEmitter
from .emitters.github_issues import GitHubIssueEmitter
from .emitters.step_summary import StepSummaryEmitter
from .models import TriageVerdict


def _run_url() -> str:
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}" if run_id else "local run"


def _is_fork_pr() -> bool:
    return os.getenv("TRIAGE_FORK_PR", "false").strip().lower() == "true"


def _run_ci(args) -> int:
    version = os.getenv("ENCLAVE_VERSION", "unknown")
    events, total = parse_junit(args.junit, repo_root=args.repo_root, enclave_version=version)
    run_url = _run_url()
    verdicts: list[TriageVerdict] = []
    for ev in events:
        ev.env["run_url"] = run_url
        sev, cat, summary = classify(ev, total=total, failed=len(events))
        verdicts.append(TriageVerdict(event=ev, severity=sev, category=cat, rule_summary=summary))

    emit = {e.strip() for e in args.emit.split(",") if e.strip()}
    if "annotations" in emit:
        AnnotationEmitter().emit(verdicts)
    if "summary" in emit:
        StepSummaryEmitter().emit(verdicts)
    if "issues" in emit and not args.dry_run:
        if _is_fork_pr():
            print("::notice::fork PR — skipping issue creation (read-only token)")
        else:
            GitHubIssueEmitter(repo=args.repo, max_issues=args.max_issues).emit(verdicts)

    if args.fail_on == "critical" and any(v.severity.value == "critical" for v in verdicts):
        return 2
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="triage")
    sub = p.add_subparsers(dest="cmd", required=True)
    ci = sub.add_parser("ci", help="triage a JUnit XML report")
    ci.add_argument("--junit", required=True)
    ci.add_argument("--emit", default="annotations,summary,issues")
    ci.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"))
    ci.add_argument("--repo-root", default=os.getcwd())
    ci.add_argument("--dry-run", action="store_true")
    ci.add_argument("--fail-on", choices=["none", "critical"], default="none")
    ci.add_argument("--max-issues", type=int, default=10,
                    help="cap issues filed per run (GitHub rate-limit guard)")
    args = p.parse_args(argv)
    if args.cmd == "ci":
        return _run_ci(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/__main__.py tests/triage/test_cli.py
git commit -m "feat(triage): CLI entrypoint (python -m triage ci)"
```

---

### Task 9: Wire triage into CI (`ci.yml`)

**Files:**
- Modify: `.github/workflows/ci.yml` (the `test` job: lines 10–53)

- [ ] **Step 1: Add `permissions` + `--junitxml`, run triage always, enforce real result**

Replace the `test` job's `permissions` (add it) and the "Run tests" / "Upload coverage" region. The full edited `test` job header and steps:

```yaml
  test:
    name: Test (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write          # required for the issue emitter; fork PRs get read-only anyway
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r setup/requirements-core.txt
          pip install -r setup/requirements-dev.txt
          pip install pytest-cov

      - name: Run tests
        id: pytest
        run: |
          set +e
          pytest tests/ -v --tb=short \
            -k "not Integration and not TestAuthentication and not TestMultiKeyAuth" \
            -m "not rag" \
            --cov=api --cov-report=term --cov-report=xml \
            --junitxml=reports/junit.xml
          echo "rc=$?" >> "$GITHUB_OUTPUT"
          exit 0

      - name: Auto-triage failures
        if: always()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ENCLAVE_VERSION: ${{ github.sha }}
          # Issues only on mainline pushes; PRs get annotations + summary (PR failures are expected).
          # Fork PRs cannot create issues (read-only token) — detected and skipped.
          TRIAGE_FORK_PR: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name != github.repository }}
        run: |
          EMIT="annotations,summary"
          if [ "${{ github.event_name }}" = "push" ] && [ "${{ github.ref }}" = "refs/heads/master" ]; then
            EMIT="annotations,summary,issues"
          fi
          echo "Triage emit set: $EMIT"
          python -m triage ci --junit reports/junit.xml --emit "$EMIT"

      - name: Upload coverage artifact
        if: matrix.python-version == '3.12'
        uses: actions/upload-artifact@v4
        with:
          name: coverage-xml
          path: coverage.xml
          if-no-files-found: warn

      - name: Enforce test result
        if: always()
        run: exit ${{ steps.pytest.outputs.rc }}
```

- [ ] **Step 2: Validate the workflow YAML locally**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ci.yml valid')"`
Expected: `ci.yml valid`

- [ ] **Step 3: Dry-run the CLI against a real local run to prove wiring**

Run:
```bash
pytest tests/triage -q --junitxml=/tmp/jx.xml || true
python -m triage ci --junit /tmp/jx.xml --emit annotations,summary --repo-root "$(pwd)"
```
Expected: no failures → no `::error` lines; if you force a failure, an `::error` line prints. No exceptions.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: auto-triage test failures (annotations + summary always, issues on master push)"
```

---

### Task 10: Bootstrap triage labels (one-time, idempotent)

**Files:**
- Create: `scripts/triage-labels.sh`

- [ ] **Step 1: Create the idempotent label-bootstrap script**

```bash
# scripts/triage-labels.sh
#!/usr/bin/env bash
# Idempotently create the labels the triage issue emitter applies.
# Usage: ./scripts/triage-labels.sh [owner/repo]
set -euo pipefail
REPO_ARG=()
[ "${1:-}" != "" ] && REPO_ARG=(--repo "$1")

create() { gh label create "$1" --color "$2" --description "$3" "${REPO_ARG[@]}" --force; }

create "triage:auto"      "ededed" "Auto-filed by the triage system"
create "severity:critical" "b60205" "Triage: critical"
create "severity:high"     "d93f0b" "Triage: high"
create "severity:medium"   "fbca04" "Triage: medium"
create "severity:low"      "0e8a16" "Triage: low"
for c in assertion import_error timeout connection flaky config unhandled unknown; do
  create "category:${c}"   "1d76db" "Triage category: ${c}"
done
echo "triage labels ensured"
```

- [ ] **Step 2: Make executable + smoke-check syntax**

Run: `chmod +x scripts/triage-labels.sh && bash -n scripts/triage-labels.sh && echo "syntax ok"`
Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/triage-labels.sh
git commit -m "chore(triage): idempotent label bootstrap script"
```

> **Run once manually** (not in this plan's automated steps): `./scripts/triage-labels.sh hankthebldr/<repo>`. The issue emitter applies labels; `gh issue create` auto-creates missing labels only in some versions, so this guarantees consistent colors/descriptions.

---

### ✅ Phase 1 Gate

- [ ] All `tests/triage/` pass: `pytest tests/triage -v`
- [ ] Full suite still green: `pytest tests/ --ignore=tests/e2e -q`
- [ ] Seed a deliberately failing test and **open a PR** (CI triggers on PRs to `master`) → CI shows an inline annotation + a summary-table row, and **no** issue is filed (PR runs emit `annotations,summary` only).
- [ ] Merge/push that failure to `master` → exactly one issue filed; a second `master` run files **no** duplicate, adds a comment instead.
- [ ] Only one tiny dep added (`defusedxml`, security-justified); CI wall-clock increase < ~5s.

---

# PHASE 2 — runtime path (opt-in, operator-owned)

### Task 11: Triage configuration from env

**Files:**
- Create: `triage/config.py`
- Test: `tests/triage/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_config.py
from __future__ import annotations

from triage.config import TriageConfig


def test_defaults_are_safe(monkeypatch):
    for k in ("ENABLE_ERROR_REPORTING", "ERROR_SINK", "ERROR_REPORTING_VENDOR", "TRIAGE_ENRICH", "TRIAGE_REDACT"):
        monkeypatch.delenv(k, raising=False)
    cfg = TriageConfig.from_env()
    assert cfg.enabled is False
    assert cfg.sink == "none"
    assert cfg.vendor is False
    assert cfg.redact is True          # redaction floor on by default
    assert cfg.enrich is True
    assert cfg.ollama_model.startswith("qwen2.5")


def test_opt_in(monkeypatch):
    monkeypatch.setenv("ENABLE_ERROR_REPORTING", "true")
    monkeypatch.setenv("ERROR_SINK", "webhook")
    monkeypatch.setenv("ERROR_SINK_URL", "https://sink.local/in")
    cfg = TriageConfig.from_env()
    assert cfg.enabled and cfg.sink == "webhook" and cfg.sink_url == "https://sink.local/in"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/config.py
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class TriageConfig:
    enabled: bool
    sink: str
    sink_url: str | None
    sink_token: str | None
    vendor: bool
    vendor_url: str | None
    enrich: bool
    ollama_url: str
    ollama_model: str
    redact: bool

    @classmethod
    def from_env(cls) -> "TriageConfig":
        return cls(
            enabled=_bool("ENABLE_ERROR_REPORTING", False),
            sink=os.getenv("ERROR_SINK", "none"),
            sink_url=os.getenv("ERROR_SINK_URL"),
            sink_token=os.getenv("ERROR_SINK_TOKEN"),
            vendor=_bool("ERROR_REPORTING_VENDOR", False),
            vendor_url=os.getenv("ERROR_VENDOR_URL"),
            enrich=_bool("TRIAGE_ENRICH", True),
            ollama_url=os.getenv("TRIAGE_OLLAMA_URL", "http://localhost:11434"),
            ollama_model=os.getenv("TRIAGE_OLLAMA_MODEL", "qwen2.5:14b-instruct-q5_K_M"),
            redact=_bool("TRIAGE_REDACT", True),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/config.py tests/triage/test_config.py
git commit -m "feat(triage): env-driven config (opt-in, off by default)"
```

---

### Task 12: Redaction (mandatory scrub before egress)

**Files:**
- Create: `triage/redact.py`
- Test: `tests/triage/test_redact.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_redact.py
from __future__ import annotations

import os

from triage.redact import redact, redact_event
from triage.models import FailureEvent


def test_scrubs_secrets_and_keys():
    text = "key sk-ABCDEF0123456789ABCD and Authorization: Bearer abc.def.ghi and password=hunter2"
    out = redact(text)
    assert "sk-ABCDEF" not in out
    assert "hunter2" not in out
    assert "Bearer abc.def.ghi" not in out


def test_scrubs_email_pii():
    assert "henry@example.com" not in redact("contact henry@example.com")


def test_rewrites_home_path():
    home = os.path.expanduser("~")
    out = redact(f"opened {home}/.ssh/id_rsa")
    assert home not in out and "~/.ssh" in out


def test_redact_event_scrubs_message_and_traceback():
    ev = FailureEvent(source="runtime", exception_type="ValueError",
                      message="token=sk-AAAAAAAAAAAAAAAA", traceback="password=hunter2")
    out = redact_event(ev)
    assert "sk-AAAA" not in out.message
    assert "hunter2" not in (out.traceback or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_redact.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.redact'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/redact.py
from __future__ import annotations

import os
import re

from .models import FailureEvent

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email (PII)
]


def redact(text: str | None, *, extra: list[re.Pattern] | None = None) -> str | None:
    if not text:
        return text
    home = os.path.expanduser("~")
    if home and home != "~":
        text = text.replace(home, "~")
    for rx in _PATTERNS + (extra or []):
        text = rx.sub("[REDACTED]", text)
    return text


def redact_event(event: FailureEvent, *, extra: list[re.Pattern] | None = None) -> FailureEvent:
    return event.model_copy(update={
        "message": redact(event.message, extra=extra) or "",
        "traceback": redact(event.traceback, extra=extra),
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_redact.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/redact.py tests/triage/test_redact.py
git commit -m "feat(triage): mandatory redaction of secrets, PII, home paths"
```

---

### Task 13: Local-Ollama enrichment (best-effort)

**Files:**
- Create: `triage/enrich.py`
- Test: `tests/triage/test_enrich.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_enrich.py
from __future__ import annotations

from unittest.mock import patch

from triage.enrich import enrich
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v():
    ev = FailureEvent(source="runtime", exception_type="ValueError", message="bad", traceback="...")
    return TriageVerdict(event=ev, severity=Severity.high, category=Category.unhandled, rule_summary="x")


def test_enrich_parses_two_lines():
    fake = {"response": "LIKELY CAUSE: a null value\nFIRST CHECK: inspect the request body"}
    with patch("triage.enrich.requests.post") as post:
        post.return_value.json.return_value = fake
        post.return_value.raise_for_status.return_value = None
        out = enrich(_v(), url="http://x", model="m")
    assert out.enriched is True
    assert out.likely_cause == "a null value"
    assert out.first_check == "inspect the request body"


def test_enrich_degrades_silently_on_error():
    with patch("triage.enrich.requests.post", side_effect=Exception("connection refused")):
        out = enrich(_v(), url="http://x", model="m")
    assert out.enriched is False and out.likely_cause is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_enrich.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.enrich'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/enrich.py
from __future__ import annotations

import requests

from .models import TriageVerdict

_PROMPT = """You are triaging a software failure. Be terse and concrete.

Exception: {etype}
Message: {message}
Traceback (tail):
{tb}

Respond in exactly two lines:
LIKELY CAUSE: <one sentence>
FIRST CHECK: <one concrete thing to inspect>"""


def _parse(text: str) -> tuple[str | None, str | None]:
    cause = check = None
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith("LIKELY CAUSE:"):
            cause = s.split(":", 1)[1].strip()
        elif s.upper().startswith("FIRST CHECK:"):
            check = s.split(":", 1)[1].strip()
    return cause, check


def enrich(verdict: TriageVerdict, *, url: str, model: str, timeout: int = 60) -> TriageVerdict:
    ev = verdict.event
    prompt = _PROMPT.format(etype=ev.exception_type, message=ev.message, tb=(ev.traceback or "")[-1500:])
    try:
        resp = requests.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}},
            timeout=timeout,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
    except Exception:
        return verdict  # enriched stays False
    cause, check = _parse(text)
    return verdict.model_copy(update={"likely_cause": cause, "first_check": check, "enriched": bool(cause or check)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_enrich.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/enrich.py tests/triage/test_enrich.py
git commit -m "feat(triage): best-effort local-Ollama enrichment"
```

---

### Task 14: Runtime collector (live exception → redacted event)

**Files:**
- Create: `triage/collectors/runtime.py`
- Test: `tests/triage/test_runtime.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_runtime.py
from __future__ import annotations

from triage.collectors.runtime import from_exception


def test_from_exception_builds_redacted_event():
    try:
        raise ValueError("token=sk-AAAAAAAAAAAAAAAA")
    except ValueError as exc:
        ev = from_exception(exc, route="POST /v1/chat", request_id="r1", enclave_version="1.1.1")
    assert ev.source == "runtime"
    assert ev.exception_type == "ValueError"
    assert ev.route == "POST /v1/chat" and ev.request_id == "r1"
    assert ev.fingerprint
    assert ev.occurred_at
    assert "sk-AAAA" not in ev.message     # redacted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_runtime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.collectors.runtime'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/collectors/runtime.py
from __future__ import annotations

import traceback as tb_mod
from datetime import datetime, timezone

from ..fingerprint import app_frames, fingerprint_event
from ..models import FailureEvent
from ..redact import redact_event


def from_exception(exc: BaseException, *, route: str | None = None, request_id: str | None = None,
                   enclave_version: str = "unknown", repo_root: str = "") -> FailureEvent:
    tb = "".join(tb_mod.format_exception(type(exc), exc, exc.__traceback__))
    ev = FailureEvent(
        source="runtime",
        exception_type=type(exc).__name__,
        message=(str(exc)[:300] or type(exc).__name__),
        traceback=tb,
        route=route,
        request_id=request_id,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        env={"enclave_version": enclave_version},
    )
    frames = app_frames(tb, repo_root)
    if frames:
        ev.file, ev.line, ev.func = frames[-1]
    ev.fingerprint = fingerprint_event(ev, repo_root=repo_root)
    return redact_event(ev)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_runtime.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/collectors/runtime.py tests/triage/test_runtime.py
git commit -m "feat(triage): runtime collector (exception -> redacted event)"
```

---

### Task 15: Webhook emitter (operator sink)

**Files:**
- Create: `triage/emitters/webhook.py`
- Test: `tests/triage/test_webhook.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_webhook.py
from __future__ import annotations

from unittest.mock import patch

from triage.emitters.webhook import WebhookEmitter
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v():
    ev = FailureEvent(source="runtime", exception_type="ValueError", message="bad", route="POST /x")
    return TriageVerdict(event=ev, severity=Severity.high, category=Category.unhandled, rule_summary="x")


def test_posts_json_with_token():
    with patch("triage.emitters.webhook.requests.post") as post:
        WebhookEmitter(url="https://sink/in", token="t").emit([_v()])
        args, kwargs = post.call_args
        assert args[0] == "https://sink/in"
        assert kwargs["headers"]["Authorization"] == "Bearer t"
        assert kwargs["json"]["severity"] == "high"


def test_unreachable_sink_is_swallowed():
    with patch("triage.emitters.webhook.requests.post", side_effect=Exception("down")):
        WebhookEmitter(url="https://sink/in").emit([_v()])  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_webhook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.emitters.webhook'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/emitters/webhook.py
from __future__ import annotations

import requests

from ..models import TriageVerdict


class WebhookEmitter:
    def __init__(self, *, url: str, token: str | None = None, timeout: int = 10):
        self.url = url
        self.token = token
        self.timeout = timeout

    def emit(self, verdicts: list[TriageVerdict]) -> None:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for v in verdicts:
            try:
                requests.post(self.url, json=v.model_dump(mode="json"), headers=headers, timeout=self.timeout)
            except Exception:
                pass  # operator sink unreachable → swallow; caller logs the warning
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_webhook.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/emitters/webhook.py tests/triage/test_webhook.py
git commit -m "feat(triage): webhook emitter for operator-owned sinks"
```

---

### Task 16: Reporting orchestrator (enrich → sink select → emit)

**Files:**
- Create: `triage/reporting.py`
- Test: `tests/triage/test_reporting.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_reporting.py
from __future__ import annotations

from unittest.mock import patch

from triage.config import TriageConfig
from triage.reporting import report, _sink
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _cfg(**kw):
    base = dict(enabled=True, sink="webhook", sink_url="https://s/in", sink_token=None,
                vendor=False, vendor_url=None, enrich=False,
                ollama_url="http://x", ollama_model="m", redact=True)
    base.update(kw)
    return TriageConfig(**base)


def _v():
    ev = FailureEvent(source="runtime", exception_type="ValueError", message="x")
    return TriageVerdict(event=ev, severity=Severity.high, category=Category.unhandled, rule_summary="x")


def test_sink_selection_webhook():
    assert _sink(_cfg()).__class__.__name__ == "WebhookEmitter"


def test_sink_none_returns_none():
    assert _sink(_cfg(sink="none", sink_url=None)) is None


def test_report_emits_to_sink():
    with patch("triage.reporting.WebhookEmitter") as We:
        report(_v(), _cfg())
        We.return_value.emit.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_reporting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage.reporting'`

- [ ] **Step 3: Write minimal implementation**

```python
# triage/reporting.py
from __future__ import annotations

from .config import TriageConfig
from .emitters.github_issues import GitHubIssueEmitter
from .emitters.webhook import WebhookEmitter
from .enrich import enrich
from .models import TriageVerdict


def _sink(cfg: TriageConfig):
    if cfg.sink in ("webhook", "sentry") and cfg.sink_url:
        return WebhookEmitter(url=cfg.sink_url, token=cfg.sink_token)
    if cfg.sink == "github" and cfg.sink_url:
        return GitHubIssueEmitter(repo=cfg.sink_url)  # sink_url == "owner/repo"
    return None


def report(verdict: TriageVerdict, cfg: TriageConfig) -> None:
    """Enrich (best-effort) then emit to the configured sink. Never raises."""
    try:
        if cfg.enrich:
            verdict = enrich(verdict, url=cfg.ollama_url, model=cfg.ollama_model)
        sink = _sink(cfg)
        if sink is not None:
            sink.emit([verdict])
        if cfg.vendor and cfg.vendor_url:                 # Phase 3 path (opt-in)
            WebhookEmitter(url=cfg.vendor_url).emit([verdict])
    except Exception:
        pass  # reporting must never raise into the caller
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_reporting.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add triage/reporting.py tests/triage/test_reporting.py
git commit -m "feat(triage): reporting orchestrator (enrich + sink dispatch)"
```

---

### Task 17: Catch-all exception handler in the app

**Files:**
- Modify: `api/exceptions.py:135-152` (add logging to existing handler + new catch-all + register it)
- Test: `tests/triage/test_runtime_handler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_runtime_handler.py
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.exceptions import register_exception_handlers


def _app():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


def test_unhandled_returns_500_envelope_and_request_id(monkeypatch):
    monkeypatch.delenv("ENABLE_ERROR_REPORTING", raising=False)
    client = TestClient(_app(), raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["type"] == "internal_error"
    assert body["error"]["request_id"]
    assert "kaboom" not in body["error"]["message"]   # internals not leaked


def test_reporting_skipped_when_disabled(monkeypatch):
    monkeypatch.delenv("ENABLE_ERROR_REPORTING", raising=False)
    client = TestClient(_app(), raise_server_exceptions=False)
    with patch("triage.reporting.report") as rep:
        client.get("/boom")
        rep.assert_not_called()


def test_reporting_invoked_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_ERROR_REPORTING", "true")
    monkeypatch.setenv("ERROR_SINK", "webhook")
    monkeypatch.setenv("ERROR_SINK_URL", "https://sink/in")
    client = TestClient(_app(), raise_server_exceptions=False)
    with patch("api.exceptions._dispatch_report") as disp:
        client.get("/boom")
        disp.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/triage/test_runtime_handler.py -v`
Expected: FAIL — `AttributeError` / 500 envelope missing `request_id`, `_dispatch_report` undefined

- [ ] **Step 3: Write minimal implementation**

Replace `api/exceptions.py` lines 132–152 (the handler section) with:

```python
# ── Exception Handlers ────────────────────────────────────────────────────

import uuid

from .logging_config import logger


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handler for all APIError subclasses — returns OpenAI-compatible error JSON."""
    logger.warning("APIError %s on %s %s: %s", exc.code, request.method, request.url.path, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"message": exc.message, "type": exc.error_type, "code": exc.code}},
    )


def _dispatch_report(request: Request, exc: Exception, request_id: str) -> None:
    """Build → classify → report in a daemon thread. Never raises into the request path."""
    try:
        from triage.config import TriageConfig

        cfg = TriageConfig.from_env()
        if not cfg.enabled or cfg.sink == "none":
            return
        import threading

        from triage.classify import classify
        from triage.collectors.runtime import from_exception
        from triage.models import TriageVerdict
        from triage.reporting import report
        from . import __version__

        ev = from_exception(exc, route=f"{request.method} {request.url.path}",
                            request_id=request_id, enclave_version=__version__)
        sev, cat, summary = classify(ev)
        verdict = TriageVerdict(event=ev, severity=sev, category=cat, rule_summary=summary)
        threading.Thread(target=report, args=(verdict, cfg), daemon=True).start()
    except Exception:
        logger.warning("triage reporting failed", exc_info=True)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for genuinely unhandled exceptions. APIError keeps its own handler."""
    request_id = getattr(getattr(request, "state", None), "request_id", None) or uuid.uuid4().hex[:12]
    logger.error("Unhandled %s on %s %s [req=%s]", type(exc).__name__,
                 request.method, request.url.path, request_id, exc_info=exc)
    _dispatch_report(request, exc, request_id)
    return JSONResponse(
        status_code=500,
        content={"error": {"message": "Internal server error", "type": "internal_error",
                           "code": "internal_error", "request_id": request_id}},
    )


def register_exception_handlers(app):
    """Register all custom exception handlers on the FastAPI app."""
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
```

(No change needed in `api/main.py` — it already calls `register_exception_handlers(app)` at line 241.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/triage/test_runtime_handler.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the broader API tests to confirm no regression**

Run: `pytest tests/test_api.py tests/test_workflow_exceptions.py -q`
Expected: PASS (existing `APIError` behavior unchanged)

- [ ] **Step 6: Commit**

```bash
git add api/exceptions.py tests/triage/test_runtime_handler.py
git commit -m "feat(api): catch-all exception handler with opt-in triage reporting"
```

---

### Task 18: Operator docs + `.env` example

**Files:**
- Modify: `.env.example` (add triage block)
- Create: `docs/deployment/error-reporting.md`

- [ ] **Step 1: Append the triage config block to `.env.example`**

```bash
# ── Error reporting & triage (opt-in, off by default) ───────────────────────
# Master switch. When false (default) the app behaves exactly as before:
# unhandled errors are logged locally and nothing leaves the box.
ENABLE_ERROR_REPORTING=false
# Where reports go: none | github | webhook | sentry  (operator-owned by default)
ERROR_SINK=none
# For ERROR_SINK=github use "owner/repo"; for webhook/sentry use the URL.
ERROR_SINK_URL=
ERROR_SINK_TOKEN=
# Optional vendor phone-home (Phase 3) — off by default, requires disclosure.
ERROR_REPORTING_VENDOR=false
ERROR_VENDOR_URL=
# Local-Ollama enrichment (best-effort; auto-skips if unreachable).
TRIAGE_ENRICH=true
TRIAGE_OLLAMA_URL=http://localhost:11434
TRIAGE_OLLAMA_MODEL=qwen2.5:14b-instruct-q5_K_M
# Redaction floor — prompts/secrets/home-paths are always scrubbed; cannot be disabled.
TRIAGE_REDACT=true
```

- [ ] **Step 2: Write `docs/deployment/error-reporting.md`**

```markdown
# Error reporting & auto-triage

Enclave can automatically triage failures and report them to a sink **you control**.
It is **opt-in and off by default** — out of the box, nothing leaves the machine.

## What gets reported
Unhandled runtime exceptions, normalized into a deduplicated, severity-labelled event.
Test failures in CI are triaged separately by `python -m triage ci` (see CI workflow).

## Turning it on
Set in `.env`:

    ENABLE_ERROR_REPORTING=true
    ERROR_SINK=github            # or webhook | sentry
    ERROR_SINK_URL=youruser/yourrepo

## Privacy guarantees
- **Redaction is mandatory.** Prompt text and request bodies are dropped; secrets,
  API keys, and `$HOME` paths are scrubbed before anything is sent. This cannot be disabled.
- **Operator-owned by default.** Reports go to *your* GitHub repo / collector / webhook.
- **Vendor phone-home is separate, off by default,** and requires `ERROR_REPORTING_VENDOR=true`.

## How it scales bug reporting
The same fingerprint/dedup/severity machinery powers CI and runtime, so distinct bugs
become one tracked issue each (recurrences add a comment, never a duplicate).
```

- [ ] **Step 3: Commit**

```bash
git add .env.example docs/deployment/error-reporting.md
git commit -m "docs(triage): operator error-reporting guide + .env example"
```

---

### Task 19: Reconcile the telemetry-stance doc-debt

> The spec's "telemetry stance" section commits to reconciling docs that contradict the new opt-in direction. Do this in Phase 2 so shipped copy doesn't lie.

**Files:**
- Modify: `CLAUDE.md` (the `## Conventions` "No telemetry" line)
- Modify: `README.md` (privacy/positioning copy — locate the "no telemetry"/"all data local" claim)

- [ ] **Step 1: Update the CLAUDE.md conventions line**

Find: `- **No telemetry. No cloud. All data local.**`
Replace with:

```markdown
- **No telemetry by default. No cloud inference. All data local.** Error reporting is **opt-in and off by default**; when enabled it is **operator-owned** (your sink) and **redaction is mandatory**. Optional vendor phone-home is separate, explicit, and disabled by default. See `docs/superpowers/specs/2026-05-31-failure-auto-triage-design.md`.
```

- [ ] **Step 2: Update README privacy copy**

Run to locate the claim: `grep -rn "no telemetry\|All data local\|zero-telemetry\|No telemetry" README.md`
For each hit, soften "no telemetry" → "no telemetry by default; opt-in operator-owned error reporting available" with a link to `docs/deployment/error-reporting.md`. (Edit the specific lines the grep surfaces; do not blanket-replace.)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: reconcile telemetry stance — opt-in operator-owned reporting"
```

---

### ✅ Phase 2 Gate

- [ ] All `tests/triage/` pass: `pytest tests/triage -v`
- [ ] Reporting **off** (default): hitting a failing route returns the 500 envelope, logs locally, emits nothing (`test_reporting_skipped_when_disabled`).
- [ ] Reporting **on** + mock sink: the same route delivers a **redacted** payload without delaying the response (`test_reporting_invoked_when_enabled` + redaction asserts).
- [ ] Ollama unreachable → rules-only verdict, no raise (`test_enrich_degrades_silently_on_error`).
- [ ] Existing API tests unchanged: `pytest tests/test_api.py -q`.
- [ ] `.env.example`, `docs/deployment/error-reporting.md`, CLAUDE.md, README reconciled.

---

# PHASE 3 — vendor phone-home (DEFERRED — do not implement without explicit go-ahead)

> The plumbing already exists: `triage/reporting.py` emits to `cfg.vendor_url` when `ERROR_REPORTING_VENDOR=true`. Phase 3 only adds the **consent UX, disclosure, and privacy policy** — and must not ship before those exist.

### Task 20 (deferred): Disclosure + privacy policy gate

**Files (when activated):**
- Create: `docs/legal/error-reporting-privacy.md` (what's sent, redaction guarantees, retention, opt-out)
- Modify: setup/onboarding UI — a one-time disclosure shown when `ERROR_REPORTING_VENDOR` is first enabled, requiring explicit acknowledgement before the first vendor send.
- Add: a startup log line on first vendor-enabled boot: `"Vendor error reporting ENABLED — see docs/legal/error-reporting-privacy.md"`.

**Acceptance (when activated):** vendor send only occurs after acknowledgement is recorded; redaction identical to Phase 2; privacy policy published and linked from the disclosure.

---

## Cross-cutting: run the whole triage suite before any phase gate

```bash
source venv/bin/activate
pytest tests/triage -v
pytest tests/ --ignore=tests/e2e -q   # full regression
```
