# SPDX-FileCopyrightText: ohno llc
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Data classes for the XQL/XDM rules engine.

Mirrors `server/data/rules-engine.ts` types verbatim:
  - Severity         (TS: "error" | "warning" | "info" | "suggestion")
  - RuleAppliesTo    (TS: "parsing" | "modeling" | "both")
  - ValidationRule   (TS: ValidationRule interface)
  - Violation        (TS: Violation interface)
  - AnalysisResult   (TS: AnalysisResult interface)

Derived from gocortex-xql-ide/server/data/rules-engine.ts (AGPL-3.0).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Literal, Optional

Severity = Literal["error", "warning", "info", "suggestion"]
RuleAppliesTo = Literal["parsing", "modeling", "both"]


@dataclass
class Violation:
    """A single rule violation. Mirrors TS Violation interface."""
    ruleId: str
    ruleName: str
    severity: Severity
    category: str
    message: str
    recommendation: str
    codeSnippet: Optional[str] = None
    line: Optional[int] = None


# The customCheck signature mirrors the TS callable:
#   (code: str, lines: List[str]) -> List[Violation]
CustomCheck = Callable[[str, List[str]], List[Violation]]


@dataclass
class ValidationRule:
    """A single validation rule definition. Mirrors TS ValidationRule interface."""
    id: str
    name: str
    severity: Severity
    category: str
    pattern: re.Pattern  # Required — every rule has at least a top-level pattern.
    message: str
    recommendation: str
    appliesTo: RuleAppliesTo
    antiPattern: Optional[re.Pattern] = None
    codeSnippet: Optional[str] = None
    customCheck: Optional[CustomCheck] = None


@dataclass
class AnalysisSummary:
    errors: int
    warnings: int
    info: int
    suggestions: int


@dataclass
class AnalysisResult:
    """Result of running the engine against a rule. Mirrors TS AnalysisResult."""
    violations: List[Violation] = field(default_factory=list)
    suggestions: List[Violation] = field(default_factory=list)
    score: int = 100
    summary: AnalysisSummary = field(default_factory=lambda: AnalysisSummary(0, 0, 0, 0))

    def to_dict(self) -> dict:
        """JSON-friendly dict for the validate_xql tool contract."""
        return {
            "violations": [v.__dict__ for v in self.violations],
            "suggestions": [v.__dict__ for v in self.suggestions],
            "score": self.score,
            "summary": self.summary.__dict__,
        }
