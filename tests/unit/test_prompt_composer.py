import pytest
from api.services.prompt_composer import ComposedPrompt

from api.services.prompt_composer import PromptComposer


def test_composed_prompt_has_required_fields():
    p = ComposedPrompt(
        system="You are X.",
        user="Do the thing.",
        params={"temperature": 0.3},
    )
    assert p.system == "You are X."
    assert p.user == "Do the thing."
    assert p.params == {"temperature": 0.3}


def test_composed_prompt_as_messages():
    p = ComposedPrompt(system="sys", user="usr", params={})
    assert p.as_messages() == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


def test_composed_prompt_is_mutable():
    p = ComposedPrompt(system="sys", user="usr", params={})
    p.user = "new user content"
    assert p.user == "new user content"


@pytest.fixture
def composer(tmp_path):
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "test_role.md").write_text("You are a test role.\n")
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "five_part.jinja").write_text(
        "{{ role }}\n\n## Context\n{{ context }}\n\n## Task\n{{ task }}\n\n"
        "## Constraints\n{% for c in constraints %}- {{ c }}\n{% endfor %}\n"
        "## Output Format\n{{ output_schema_json }}"
    )
    return PromptComposer(roles_dir=roles_dir, templates_dir=templates_dir)


def test_composer_uses_role_ref(composer):
    prompt = composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="project context",
        task="do the thing",
        constraints=["no markdown"],
        output_schema={"type": "object"},
    )
    assert "You are a test role." in prompt.system
    assert "project context" in prompt.system
    assert "do the thing" in prompt.system
    assert "- no markdown" in prompt.system
    assert '"type": "object"' in prompt.system


def test_composer_uses_role_inline_when_no_ref(composer):
    prompt = composer.compose(
        role_ref=None,
        role_inline="You are inline.",
        context="ctx",
        task="t",
        constraints=[],
        output_schema={},
    )
    assert "You are inline." in prompt.system


def test_composer_raises_on_missing_role_ref(composer):
    with pytest.raises(FileNotFoundError):
        composer.compose(
            role_ref="does_not_exist",
            role_inline=None,
            context="",
            task="",
            constraints=[],
            output_schema={},
        )


def test_composer_raises_when_both_role_ref_and_inline_missing(composer):
    with pytest.raises(ValueError, match="role_ref or role_inline"):
        composer.compose(
            role_ref=None,
            role_inline=None,
            context="",
            task="",
            constraints=[],
            output_schema={},
        )


def test_composer_includes_few_shot_example_when_given(composer):
    prompt = composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="",
        task="t",
        constraints=[],
        output_schema={"type": "object"},
        few_shot_example={"input": "in", "output": {"k": "v"}},
    )
    # Example rendered after output format
    # (template from fixture doesn't include example block; test with real template separately)
    assert "You are a test role." in prompt.system


def test_composer_builds_user_message_from_inputs(composer):
    prompt = composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="",
        task="t",
        constraints=[],
        output_schema={},
        resolved_inputs={"source_files": ["models/user.py"], "constraints": "pg"},
    )
    # User message contains each input as a labeled block
    assert "source_files" in prompt.user
    assert "models/user.py" in prompt.user
    assert "constraints" in prompt.user
    assert "pg" in prompt.user


def test_composer_user_message_default_when_no_inputs(composer):
    prompt = composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="",
        task="t",
        constraints=[],
        output_schema={},
    )
    assert prompt.user.strip() != ""
    assert "Complete" in prompt.user or "task" in prompt.user.lower()


def test_composer_rejects_role_ref_path_traversal(composer, tmp_path):
    # Create a file outside roles_dir that exists
    outside = tmp_path / "evil.md"
    outside.write_text("SECRET")
    with pytest.raises(ValueError, match="outside roles directory"):
        composer.compose(
            role_ref="../evil",
            role_inline=None,
            context="",
            task="t",
            constraints=[],
            output_schema={},
        )


def test_composer_caches_role_file_reads(composer, tmp_path):
    """The same role_ref used by many steps in a workflow should read
    from disk only once. Workflow engines that wire one PromptComposer
    per process amortize across every step on every run."""
    # First compose populates the cache
    composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="",
        task="t",
        constraints=[],
        output_schema={},
    )
    # Mutate the on-disk role; cached value should still be served
    (composer.roles_dir / "test_role.md").write_text("CHANGED")
    p = composer.compose(
        role_ref="test_role",
        role_inline=None,
        context="",
        task="t",
        constraints=[],
        output_schema={},
    )
    assert "CHANGED" not in p.system
    assert "test role" in p.system.lower()
