import pytest
import yaml
from cli.workflow import upgrade_v1_to_v2


V1_YAML = """
id: demo
name: "Demo"
version: "1.0"
defaults:
  role: coding
steps:
  - id: analyze
    name: "Analyze"
    role: reasoning
    system_prompt: |
      You are a senior data architect.
      Analyze source files and extract entities.
    inputs: [seed.files]
    outputs: [entities, relationships]
"""


def test_upgrade_produces_valid_v2(tmp_path):
    src = tmp_path / "demo.yaml"
    src.write_text(V1_YAML)
    dst = tmp_path / "demo.v2.yaml"
    upgrade_v1_to_v2(src, dst)
    data = yaml.safe_load(dst.read_text())
    assert data["schema_version"] == 2
    step = data["steps"][0]
    assert "prompt" in step
    assert step["prompt"]["role_inline"].startswith("You are a senior data architect")
    assert "entities" in step["prompt"]["task"].lower() or "analyze" in step["prompt"]["task"].lower()
    assert "output_schema" in step
    assert step["output_schema"]["type"] == "object"
    assert "entities" in step["output_schema"]["properties"]
    assert "relationships" in step["output_schema"]["properties"]


def test_upgrade_never_overwrites(tmp_path):
    src = tmp_path / "demo.yaml"
    src.write_text(V1_YAML)
    dst = tmp_path / "demo.v2.yaml"
    dst.write_text("# existing\n")
    with pytest.raises(FileExistsError):
        upgrade_v1_to_v2(src, dst)


def test_upgrade_preserves_config_blocks(tmp_path):
    src = tmp_path / "demo.yaml"
    content = V1_YAML + """
    config:
      temperature: 0.3
"""
    src.write_text(content)
    dst = tmp_path / "demo.v2.yaml"
    upgrade_v1_to_v2(src, dst)
    data = yaml.safe_load(dst.read_text())
    assert data["steps"][0]["config"]["temperature"] == 0.3
