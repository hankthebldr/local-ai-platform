"""
Prompt Renderer — Jinja2-based prompt templating with context injection

Renders system_prompt and user_prompt templates with full context access.
Supports filters, conditionals, loops, and custom functions for
building sophisticated multi-agent prompts.
"""

import json
import re
from typing import Any, Dict, List, Optional

from ..logging_config import logger
from ..models.workflow_models import AgentStep, WorkflowContext, dot_walk


# Lightweight template engine — no Jinja2 dependency required.
# Supports: {{var}}, {{var.nested.key}}, {{var|filter}}, {% if %}, {% for %}
# Falls back gracefully if Jinja2 is installed.

try:
    from jinja2 import Environment, BaseLoader, StrictUndefined, UndefinedError
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False


# ── Built-in Filters ─────────────────────────────────────────────────────

def _json_filter(value: Any, indent: int = 2) -> str:
    """Serialize value to formatted JSON string"""
    try:
        return json.dumps(value, indent=indent, default=str)
    except (TypeError, ValueError):
        return str(value)


def _truncate_filter(value: str, length: int = 500, suffix: str = "...") -> str:
    """Truncate string to max length"""
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= length:
        return value
    return value[:length - len(suffix)] + suffix


def _keys_filter(value: Any) -> List[str]:
    """Extract keys from a dict"""
    if isinstance(value, dict):
        return list(value.keys())
    return []


def _values_filter(value: Any) -> list:
    """Extract values from a dict"""
    if isinstance(value, dict):
        return list(value.values())
    return []


def _count_filter(value: Any) -> int:
    """Count items in a collection"""
    try:
        return len(value)
    except TypeError:
        return 0


def _upper_filter(value: str) -> str:
    return str(value).upper()


def _lower_filter(value: str) -> str:
    return str(value).lower()


def _join_filter(value: Any, separator: str = ", ") -> str:
    """Join a list into a string"""
    if isinstance(value, (list, tuple)):
        return separator.join(str(v) for v in value)
    return str(value)


def _first_filter(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) > 0:
        return value[0]
    return value


def _last_filter(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) > 0:
        return value[-1]
    return value


def _markdown_code_filter(value: str, lang: str = "") -> str:
    """Wrap value in a markdown code block"""
    return f"```{lang}\n{value}\n```"


BUILTIN_FILTERS = {
    "json": _json_filter,
    "truncate": _truncate_filter,
    "keys": _keys_filter,
    "values": _values_filter,
    "count": _count_filter,
    "upper": _upper_filter,
    "lower": _lower_filter,
    "join": _join_filter,
    "first": _first_filter,
    "last": _last_filter,
    "code": _markdown_code_filter,
}


# ── Simple Template Engine (no Jinja2 dependency) ────────────────────────

# Matches {{variable}}, {{variable.nested}}, {{variable|filter}}
_VAR_PATTERN = re.compile(r"\{\{\s*(.+?)\s*\}\}")
# Matches {{var|filter}} and {{var|filter(arg)}}
_FILTER_PATTERN = re.compile(r"^(.+?)\|(\w+)(?:\((.+?)\))?$")


def _resolve_var(path: str, variables: Dict[str, Any]) -> Any:
    """Resolve a dotted variable path against the variables dict"""
    return dot_walk(variables, path.strip())


def _apply_filter(value: Any, filter_name: str, filter_arg: Optional[str] = None) -> Any:
    """Apply a named filter to a value"""
    func = BUILTIN_FILTERS.get(filter_name)
    if not func:
        return value
    try:
        if filter_arg is not None:
            return func(value, filter_arg)
        return func(value)
    except Exception:
        return value


def render_simple(template: str, variables: Dict[str, Any]) -> str:
    """
    Simple template renderer using regex substitution.
    Supports {{var.path}} and {{var|filter}} syntax.
    """
    def replacer(match: re.Match) -> str:
        expr = match.group(1).strip()

        # Check for filter
        filter_match = _FILTER_PATTERN.match(expr)
        if filter_match:
            var_path = filter_match.group(1).strip()
            filter_name = filter_match.group(2)
            filter_arg = filter_match.group(3)
            value = _resolve_var(var_path, variables)
            value = _apply_filter(value, filter_name, filter_arg)
        else:
            value = _resolve_var(expr, variables)

        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, indent=2, default=str)
        return str(value)

    return _VAR_PATTERN.sub(replacer, template)


# ── Jinja2 Template Engine ────────────────────────────────────────────────

def _create_jinja_env() -> "Environment":
    """Create a Jinja2 environment with custom filters"""
    env = Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(BUILTIN_FILTERS)
    return env


# Module-level singleton — Jinja2 Environment is thread-safe for rendering
_JINJA_ENV: Optional["Environment"] = None


def _get_jinja_env() -> "Environment":
    global _JINJA_ENV
    if _JINJA_ENV is None:
        _JINJA_ENV = _create_jinja_env()
    return _JINJA_ENV


def render_jinja2(template: str, variables: Dict[str, Any]) -> str:
    """Render a template using Jinja2 (full power: loops, conditionals, macros)"""
    env = _get_jinja_env()
    try:
        tmpl = env.from_string(template)
        return tmpl.render(**variables)
    except UndefinedError as e:
        logger.warning(f"Template undefined variable: {e}")
        # Fall back to simple renderer which is more forgiving
        return render_simple(template, variables)
    except Exception as e:
        logger.warning(f"Jinja2 render failed, falling back to simple: {e}")
        return render_simple(template, variables)


# ── Public API ────────────────────────────────────────────────────────────


class PromptRenderer:
    """
    Renders workflow step prompts with context variable injection.

    Uses Jinja2 if available, falls back to simple {{var}} substitution.
    """

    def __init__(self):
        self.use_jinja2 = HAS_JINJA2
        if self.use_jinja2:
            logger.debug("PromptRenderer using Jinja2 engine")
        else:
            logger.debug("PromptRenderer using simple template engine (install jinja2 for full power)")

    def render(self, template: str, variables: Dict[str, Any]) -> str:
        """Render a template string with the given variables"""
        # Detect if template uses Jinja2 features ({% %} blocks)
        has_jinja_blocks = "{%" in template
        if has_jinja_blocks and self.use_jinja2:
            return render_jinja2(template, variables)
        elif "{{" in template:
            if self.use_jinja2:
                return render_jinja2(template, variables)
            return render_simple(template, variables)
        else:
            return template

    def render_step_prompts(
        self,
        step: AgentStep,
        context: WorkflowContext,
        extra_vars: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """
        Render both system_prompt and user_prompt for a step.

        Returns dict with 'system' and 'user' keys.
        """
        variables = context.to_template_vars()
        if extra_vars:
            variables.update(extra_vars)

        system = self.render(step.system_prompt, variables)

        if step.user_prompt:
            user = self.render(step.user_prompt, variables)
        else:
            user = self._build_default_user_prompt(step, context)

        return {"system": system, "user": user}

    def _build_default_user_prompt(
        self,
        step: AgentStep,
        context: WorkflowContext,
    ) -> str:
        """Build a structured user prompt from declared inputs (backward compat)"""
        input_data: Dict[str, Any] = {}
        for input_ref in step.inputs:
            value = context.resolve_input(input_ref)
            if value is not None:
                input_data[input_ref] = value

        if not input_data:
            return "Complete your assigned task."

        sections = ["## Context\n"]
        for ref, value in input_data.items():
            if isinstance(value, (dict, list)):
                sections.append(f"### {ref}\n```json\n{json.dumps(value, indent=2, default=str)}\n```\n")
            else:
                sections.append(f"### {ref}\n{value}\n")

        sections.append("## Task\n\nBased on the context above, complete your assigned task.")
        return "\n".join(sections)
