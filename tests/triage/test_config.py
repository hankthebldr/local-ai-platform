from __future__ import annotations

from triage.config import TriageConfig


def test_defaults_are_safe(monkeypatch):
    for k in (
        "ENABLE_ERROR_REPORTING",
        "ERROR_SINK",
        "ERROR_REPORTING_VENDOR",
        "TRIAGE_ENRICH",
        "TRIAGE_REDACT",
    ):
        monkeypatch.delenv(k, raising=False)
    cfg = TriageConfig.from_env()
    assert cfg.enabled is False
    assert cfg.sink == "none"
    assert cfg.vendor is False
    assert cfg.redact is True  # redaction floor on by default
    assert cfg.enrich is True
    assert cfg.ollama_model.startswith("qwen2.5")


def test_opt_in(monkeypatch):
    monkeypatch.setenv("ENABLE_ERROR_REPORTING", "true")
    monkeypatch.setenv("ERROR_SINK", "webhook")
    monkeypatch.setenv("ERROR_SINK_URL", "https://sink.local/in")
    cfg = TriageConfig.from_env()
    assert (
        cfg.enabled
        and cfg.sink == "webhook"
        and cfg.sink_url == "https://sink.local/in"
    )
