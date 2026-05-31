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
        if cfg.vendor and cfg.vendor_url:  # Phase 3 path (opt-in)
            WebhookEmitter(url=cfg.vendor_url).emit([verdict])
    except Exception:
        pass  # reporting must never raise into the caller
