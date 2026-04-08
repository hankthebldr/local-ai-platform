"""Tests for PromptRenderer — Jinja2/simple template rendering"""

import pytest
from api.services.prompt_renderer import PromptRenderer, render_simple, BUILTIN_FILTERS


class TestSimpleRenderer:
    def test_basic_variable(self):
        result = render_simple("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_nested_variable(self):
        result = render_simple("{{user.name}}", {"user": {"name": "Alice"}})
        assert result == "Alice"

    def test_deep_nested(self):
        result = render_simple("{{a.b.c}}", {"a": {"b": {"c": "deep"}}})
        assert result == "deep"

    def test_missing_variable(self):
        result = render_simple("Hello {{missing}}", {})
        assert result == "Hello "

    def test_filter_json(self):
        result = render_simple("{{data|json}}", {"data": {"key": "value"}})
        assert '"key": "value"' in result

    def test_filter_upper(self):
        result = render_simple("{{name|upper}}", {"name": "hello"})
        assert result == "HELLO"

    def test_filter_lower(self):
        result = render_simple("{{name|lower}}", {"name": "HELLO"})
        assert result == "hello"

    def test_filter_count(self):
        result = render_simple("{{items|count}}", {"items": [1, 2, 3]})
        assert result == "3"

    def test_filter_join(self):
        result = render_simple("{{items|join}}", {"items": ["a", "b", "c"]})
        assert result == "a, b, c"

    def test_filter_truncate(self):
        result = render_simple("{{text|truncate}}", {"text": "x" * 600})
        assert len(result) == 500

    def test_filter_first(self):
        result = render_simple("{{items|first}}", {"items": [10, 20]})
        assert result == "10"

    def test_filter_last(self):
        result = render_simple("{{items|last}}", {"items": [10, 20]})
        assert result == "20"

    def test_dict_rendered_as_json(self):
        result = render_simple("{{data}}", {"data": {"a": 1}})
        assert '"a": 1' in result

    def test_list_rendered_as_json(self):
        result = render_simple("{{items}}", {"items": [1, 2, 3]})
        assert "[1,2,3]" in result.replace("\n", "").replace(" ", "")

    def test_no_template_passthrough(self):
        result = render_simple("No templates here", {"x": 1})
        assert result == "No templates here"


class TestPromptRenderer:
    def test_plain_text_passthrough(self):
        renderer = PromptRenderer()
        result = renderer.render("No variables", {})
        assert result == "No variables"

    def test_simple_substitution(self):
        renderer = PromptRenderer()
        result = renderer.render("Hello {{name}}", {"name": "Test"})
        assert result == "Hello Test"

    def test_render_step_prompts_with_inputs(self):
        from api.models.workflow_models import AgentStep, WorkflowContext

        renderer = PromptRenderer()
        step = AgentStep(
            id="s1", name="S1",
            system_prompt="You are an analyzer for {{seed.topic}}",
            inputs=["seed.topic"],
            outputs=["result"],
        )
        ctx = WorkflowContext(seed={"topic": "security"})
        prompts = renderer.render_step_prompts(step, ctx)

        assert "security" in prompts["system"]
        assert "seed.topic" in prompts["user"]  # Default user prompt includes input refs

    def test_explicit_user_prompt(self):
        from api.models.workflow_models import AgentStep, WorkflowContext

        renderer = PromptRenderer()
        step = AgentStep(
            id="s1", name="S1",
            system_prompt="System",
            user_prompt="Analyze: {{seed.data}}",
            inputs=["seed.data"],
            outputs=["result"],
        )
        ctx = WorkflowContext(seed={"data": "test data"})
        prompts = renderer.render_step_prompts(step, ctx)

        assert prompts["system"] == "System"
        assert "test data" in prompts["user"]

    def test_extra_vars(self):
        from api.models.workflow_models import AgentStep, WorkflowContext

        renderer = PromptRenderer()
        step = AgentStep(
            id="s1", name="S1",
            system_prompt="Process {{item}} ({{loop_index}}/{{loop_length}})",
            outputs=["result"],
        )
        ctx = WorkflowContext()
        prompts = renderer.render_step_prompts(
            step, ctx,
            extra_vars={"item": "file.py", "loop_index": 2, "loop_length": 5},
        )

        assert "file.py" in prompts["system"]
        assert "2" in prompts["system"]
        assert "5" in prompts["system"]


class TestBuiltinFilters:
    def test_all_filters_exist(self):
        expected = ["json", "truncate", "keys", "values", "count", "upper", "lower", "join", "first", "last", "code"]
        for name in expected:
            assert name in BUILTIN_FILTERS

    def test_keys_filter(self):
        result = BUILTIN_FILTERS["keys"]({"a": 1, "b": 2})
        assert result == ["a", "b"]

    def test_values_filter(self):
        result = BUILTIN_FILTERS["values"]({"a": 1, "b": 2})
        assert result == [1, 2]

    def test_code_filter(self):
        result = BUILTIN_FILTERS["code"]("print('hi')", "python")
        assert result == "```python\nprint('hi')\n```"
