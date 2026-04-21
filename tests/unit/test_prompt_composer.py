import pytest
from api.services.prompt_composer import ComposedPrompt


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
