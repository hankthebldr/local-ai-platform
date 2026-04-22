import json
import pytest
from api.services.hook_bus import HookContext
from api.hooks.builtins.json_schema import JsonSchemaHook


SCHEMA = {
    "type": "object",
    "required": ["name", "age"],
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
    },
}


def test_accepts_valid_json():
    hook = JsonSchemaHook(schema=SCHEMA)
    ctx = HookContext(output=json.dumps({"name": "x", "age": 9}))
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.parsed == {"name": "x", "age": 9}


def test_rejects_missing_required_key():
    hook = JsonSchemaHook(schema=SCHEMA)
    ctx = HookContext(output=json.dumps({"name": "x"}))
    result = hook(ctx)
    assert result.action == "fail"
    assert "age" in (result.feedback or "")


def test_rejects_wrong_type():
    hook = JsonSchemaHook(schema=SCHEMA)
    ctx = HookContext(output=json.dumps({"name": "x", "age": "nine"}))
    result = hook(ctx)
    assert result.action == "fail"


def test_rejects_malformed_json():
    hook = JsonSchemaHook(schema=SCHEMA)
    ctx = HookContext(output="{ not valid json")
    result = hook(ctx)
    assert result.action == "fail"
    assert "parse" in (result.feedback or "").lower() or "json" in (result.feedback or "").lower()


def test_strips_markdown_fences_when_configured():
    hook = JsonSchemaHook(schema=SCHEMA, strip_fences=True)
    wrapped = "```json\n" + json.dumps({"name": "x", "age": 9}) + "\n```"
    ctx = HookContext(output=wrapped)
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.parsed == {"name": "x", "age": 9}


def test_strips_leading_prose_when_configured():
    hook = JsonSchemaHook(schema=SCHEMA, strip_fences=True)
    prefixed = 'Sure, here is your JSON:\n{"name": "x", "age": 9}\n'
    ctx = HookContext(output=prefixed)
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.parsed == {"name": "x", "age": 9}


def test_strict_mode_rejects_wrapped_fences():
    hook = JsonSchemaHook(schema=SCHEMA, strip_fences=False, strict=True)
    wrapped = "```json\n" + json.dumps({"name": "x", "age": 9}) + "\n```"
    ctx = HookContext(output=wrapped)
    result = hook(ctx)
    assert result.action == "fail"


def test_hook_has_name_and_stage():
    hook = JsonSchemaHook(schema=SCHEMA)
    assert hook.name == "json_schema"
    assert hook.stage == "validate_output"
