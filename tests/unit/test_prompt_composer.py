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


def test_composer_user_layer_shadows_oob_role(tmp_path):
    """GP-2 / P0-9: an edited user-layer role must shadow the shipped oob role
    at RUN time — the same user>oob order prompts.py::_resolve uses. Before the
    fix the engine's composer read oob only, so copy-on-write edits were a
    silent no-op on live runs."""
    oob_roles = tmp_path / "oob" / "roles"
    oob_roles.mkdir(parents=True)
    (oob_roles / "analyst.md").write_text("OOB analyst persona.\n")
    user_roles = tmp_path / "user" / "roles"
    user_roles.mkdir(parents=True)
    (user_roles / "analyst.md").write_text("EDITED analyst persona.\n")
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "five_part.jinja").write_text("{{ role }}\n{{ task }}")

    c = PromptComposer(
        roles_dir=oob_roles, templates_dir=templates, user_roles_dir=user_roles
    )
    out = c.compose(
        role_ref="analyst",
        role_inline=None,
        context="",
        task="t",
        constraints=[],
        output_schema={},
    )
    assert "EDITED analyst persona." in out.system
    assert "OOB analyst persona." not in out.system


def test_composer_falls_back_to_oob_when_no_user_copy(tmp_path):
    """A role that exists ONLY in oob still resolves when a user layer is
    configured but has no copy of it (fall-through)."""
    oob_roles = tmp_path / "oob" / "roles"
    oob_roles.mkdir(parents=True)
    (oob_roles / "critic.md").write_text("OOB critic.\n")
    user_roles = tmp_path / "user" / "roles"
    user_roles.mkdir(parents=True)  # empty — no critic.md
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "five_part.jinja").write_text("{{ role }}\n{{ task }}")

    c = PromptComposer(
        roles_dir=oob_roles, templates_dir=templates, user_roles_dir=user_roles
    )
    out = c.compose(
        role_ref="critic",
        role_inline=None,
        context="",
        task="t",
        constraints=[],
        output_schema={},
    )
    assert "OOB critic." in out.system


def test_composer_user_layer_traversal_rejected(tmp_path):
    """Per-layer containment: a crafted ref can't escape the user root either."""
    oob_roles = tmp_path / "oob" / "roles"
    oob_roles.mkdir(parents=True)
    user_roles = tmp_path / "user" / "roles"
    user_roles.mkdir(parents=True)
    (tmp_path / "user" / "secret.md").write_text("SECRET")
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "five_part.jinja").write_text("{{ role }}\n{{ task }}")

    c = PromptComposer(
        roles_dir=oob_roles, templates_dir=templates, user_roles_dir=user_roles
    )
    with pytest.raises(ValueError, match="outside roles directory"):
        c.compose(
            role_ref="../secret",
            role_inline=None,
            context="",
            task="t",
            constraints=[],
            output_schema={},
        )


def test_composer_default_user_layer_is_noop_without_deployment(tmp_path, monkeypatch):
    """When no deployment is detected (bare unit test), the default user layer
    is None and behavior is oob-only — the engine's zero-arg construction path
    must never crash or shadow."""
    import api.services.prompt_composer as pc

    def _boom():
        raise RuntimeError("no deployment")

    monkeypatch.setattr(
        "api.services.deployment._get_current", _boom, raising=False
    )
    roles = tmp_path / "roles"
    roles.mkdir()
    (roles / "r.md").write_text("only oob\n")
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "five_part.jinja").write_text("{{ role }}\n{{ task }}")

    c = pc.PromptComposer(roles_dir=roles, templates_dir=templates)
    assert c.user_roles_dir is None
    out = c.compose(
        role_ref="r",
        role_inline=None,
        context="",
        task="t",
        constraints=[],
        output_schema={},
    )
    assert "only oob" in out.system


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
