import json
import pytest
from api.services.hook_bus import HookContext
from api.services.prompt_composer import ComposedPrompt
from api.hooks.builtins.few_shot_injector import FewShotInjectorHook


class FakeStep:
    def __init__(self, sid):
        self.id = sid


def _prompt_with_output_format():
    system = "ROLE\n\n## Context\nc\n\n## Task\nt\n\n## Constraints\n- x\n\n## Output Format\n{}\n"
    return ComposedPrompt(system=system, user="u", params={})


def test_injects_example_from_directory(tmp_path):
    ex_dir = tmp_path / "analyze"
    ex_dir.mkdir()
    (ex_dir / "01.json").write_text(json.dumps({
        "input": "sample input",
        "output": {"result": "ok"},
    }))
    hook = FewShotInjectorHook(example_dir=tmp_path, max_examples=1)
    ctx = HookContext(step=FakeStep("analyze"), prompt=_prompt_with_output_format())
    result = hook(ctx)
    assert result.action == "continue"
    assert "## Example" in ctx.prompt.system
    assert "sample input" in ctx.prompt.system
    assert '"result": "ok"' in ctx.prompt.system


def test_skip_when_no_examples(tmp_path):
    hook = FewShotInjectorHook(example_dir=tmp_path, max_examples=1)
    ctx = HookContext(step=FakeStep("unknown"), prompt=_prompt_with_output_format())
    original = ctx.prompt.system
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.prompt.system == original


def test_respects_max_examples(tmp_path):
    ex_dir = tmp_path / "sid"
    ex_dir.mkdir()
    for i in range(5):
        (ex_dir / f"{i:02}.json").write_text(json.dumps({"input": f"in{i}", "output": {"n": i}}))
    hook = FewShotInjectorHook(example_dir=tmp_path, max_examples=2)
    ctx = HookContext(step=FakeStep("sid"), prompt=_prompt_with_output_format())
    hook(ctx)
    system = ctx.prompt.system
    assert system.count("## Example") == 2


def test_name_and_stage():
    hook = FewShotInjectorHook(example_dir="/tmp", max_examples=1)
    assert hook.name == "few_shot_injector"
    assert hook.stage == "transform_prompt"
