#!/usr/bin/env python3
"""
Custom Exceptions — OpenAI-compatible error responses
"""

from fastapi import Request
from fastapi.responses import JSONResponse


# ── Exception Classes ──────────────────────────────────────────────────────


class APIError(Exception):
    """Base exception for API errors"""

    def __init__(self, message: str, status_code: int = 500, error_type: str = "api_error", code: str = "internal_error"):
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


def register_exception_handlers(app):
    """Register all custom exception handlers on the FastAPI app"""
    app.add_exception_handler(APIError, api_error_handler)
