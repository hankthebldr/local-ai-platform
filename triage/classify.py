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
