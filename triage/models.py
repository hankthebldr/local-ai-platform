from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

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
    traceback: Optional[str] = None
    test_id: Optional[str] = None
    route: Optional[str] = None
    file: Optional[str] = None
    line: Optional[int] = None
    func: Optional[str] = None
    env: dict[str, str] = Field(default_factory=dict)
    occurred_at: Optional[str] = None
    request_id: Optional[str] = None


class TriageVerdict(BaseModel):
    event: FailureEvent
    severity: Severity
    category: Category
    rule_summary: str
    likely_cause: Optional[str] = None
    first_check: Optional[str] = None
    enriched: bool = False
    seen_count: int = 1
