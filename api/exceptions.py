#!/usr/bin/env python3
"""
Custom Exceptions — OpenAI-compatible error responses
"""

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from .logging_config import logger


# ── Exception Classes ──────────────────────────────────────────────────────


class APIError(Exception):
    """Base exception for API errors"""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_type: str = "api_error",
        code: str = "internal_error",
    ):
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.code = code
        super().__init__(message)


class ModelNotFoundError(APIError):
    """Raised when a requested model is not available"""

    def __init__(self, model: str):
        super().__init__(
            message=f"Model '{model}' not found. Use /v1/models to list available models.",
            status_code=404,
            error_type="invalid_request_error",
            code="model_not_found",
        )


class OllamaConnectionError(APIError):
    """Raised when Ollama backend is unreachable"""

    def __init__(self, detail: str = ""):
        msg = "Ollama service is not responding."
        if detail:
            msg += f" {detail}"
        super().__init__(
            message=msg,
            status_code=503,
            error_type="server_error",
            code="ollama_unavailable",
        )


class GenerationError(APIError):
    """Raised when model generation fails"""

    def __init__(self, detail: str = ""):
        msg = "Failed to generate completion."
        if detail:
            msg += f" {detail}"
        super().__init__(
            message=msg,
            status_code=500,
            error_type="server_error",
            code="generation_failed",
        )


class InvalidRequestError(APIError):
    """Raised for malformed or invalid requests"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=400,
            error_type="invalid_request_error",
            code="invalid_request",
        )


class WorkflowValidationError(APIError):
    """Raised when a workflow definition fails validation"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=422,
            error_type="invalid_request_error",
            code="workflow_validation_failed",
        )


class WorkflowExecutionError(APIError):
    """Raised when a workflow execution fails"""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=500,
            error_type="server_error",
            code="workflow_execution_failed",
        )


class ModelResolutionError(APIError):
    """Raised when a model role cannot be resolved to an available model"""

    def __init__(self, role: str):
        super().__init__(
            message=f"No available model found for role '{role}'. Check that models with this role are installed.",
            status_code=404,
            error_type="invalid_request_error",
            code="model_resolution_failed",
        )


class StepExecutionError(APIError):
    """Raised when a single workflow step fails"""

    def __init__(self, message_or_step_id: str, detail: str = ""):
        if detail:
            # Legacy two-arg form: StepExecutionError("step_id", "detail")
            msg = f"Step '{message_or_step_id}' failed. {detail}"
        else:
            # New single-arg form: StepExecutionError("full message")
            msg = message_or_step_id
        super().__init__(
            message=msg,
            status_code=500,
            error_type="server_error",
            code="step_execution_failed",
        )


# ── Exception Handlers ────────────────────────────────────────────────────


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handler for all APIError subclasses — returns OpenAI-compatible error JSON"""
    logger.warning(
        "APIError %s on %s %s: %s",
        exc.code,
        request.method,
        request.url.path,
        exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.message,
                "type": exc.error_type,
                "code": exc.code,
            }
        },
    )


def _dispatch_report(request: Request, exc: Exception, request_id: str) -> None:
    """Build → classify → report in a daemon thread. Never raises into the request path.

    Reporting is opt-in (ENABLE_ERROR_REPORTING) and operator-owned; redaction is
    applied by the triage collector before anything leaves the process.
    """
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

        ev = from_exception(
            exc,
            route=f"{request.method} {request.url.path}",
            request_id=request_id,
            enclave_version=__version__,
        )
        sev, cat, summary = classify(ev)
        verdict = TriageVerdict(
            event=ev, severity=sev, category=cat, rule_summary=summary
        )
        threading.Thread(target=report, args=(verdict, cfg), daemon=True).start()
    except Exception:
        logger.warning("triage reporting failed", exc_info=True)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for genuinely unhandled exceptions. APIError keeps its own handler
    (FastAPI dispatches the most-specific handler first), so existing error responses
    are unchanged; this only sees what would otherwise be a bare 500."""
    request_id = (
        getattr(getattr(request, "state", None), "request_id", None)
        or uuid.uuid4().hex[:12]
    )
    logger.error(
        "Unhandled %s on %s %s [req=%s]",
        type(exc).__name__,
        request.method,
        request.url.path,
        request_id,
        exc_info=exc,
    )
    _dispatch_report(request, exc, request_id)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": "Internal server error",
                "type": "internal_error",
                "code": "internal_error",
                "request_id": request_id,
            }
        },
    )


def register_exception_handlers(app):
    """Register all custom exception handlers on the FastAPI app"""
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
