"""code_exec — chat plugin tool for sandboxed Python execution.

Off by default.  Two gates must pass before code reaches the sandbox:
  1. ENV gate: CODE_EXEC_ENABLED must be "true" (set by the operator).
  2. Profile gate: the active profile must list "code-exec" in allowed_plugins
     (enforced by PluginService / ToolExecutor before this function is called).

The __sandbox parameter is injected by PluginService.call_tool when the
function signature declares it (via inspect.signature); it is never supplied
by the LLM.
"""

import os


def code_exec(code: str, __sandbox=None) -> dict:
    """Execute a short Python snippet in the local sandbox.

    Args:
        code: Python source to execute.
        __sandbox: SandboxedFS injected by PluginService; not LLM-visible.

    Returns:
        dict with keys: exit_code, stdout, stderr, tier_used  — or error.
    """
    if os.getenv("CODE_EXEC_ENABLED", "false").lower() != "true":
        return {"error": "code execution disabled (set CODE_EXEC_ENABLED=true)"}
    if __sandbox is None:
        return {"error": "no sandbox bound to this conversation"}

    from api.services.sandbox import CodeExecSpec
    from api.services.sandbox_registry import get_current_sandbox_registry

    backend = get_current_sandbox_registry().resolve(override=None)
    res = backend.execute(
        CodeExecSpec(
            language="python",
            code=code,
            scratch_path=str(__sandbox.root),
        )
    )
    return {
        "exit_code": res.exit_code,
        "stdout": res.stdout[:8000],
        "stderr": res.stderr[:4000],
        "tier_used": res.tier_used,
    }
