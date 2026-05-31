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
