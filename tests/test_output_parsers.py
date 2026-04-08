"""Tests for OutputParser — structured extraction from LLM responses"""

import pytest
from api.models.workflow_models import OutputFormat, OutputParserConfig
from api.services.output_parsers import OutputParser


@pytest.fixture
def parser():
    return OutputParser()


class TestRawParser:
    def test_single_output(self, parser):
        result, ok = parser.parse("hello world", ["result"], OutputParserConfig())
        assert result == {"result": "hello world"}
        assert ok is True

    def test_multiple_outputs(self, parser):
        result, ok = parser.parse("hello", ["a", "b"], OutputParserConfig())
        assert result["a"] == "hello"
        assert result["b"] == "hello"


class TestJsonParser:
    def test_direct_json(self, parser):
        content = '{"entities": ["user", "order"], "count": 5}'
        config = OutputParserConfig(format=OutputFormat.JSON)
        result, ok = parser.parse(content, ["entities", "count"], config)
        assert result["entities"] == ["user", "order"]
        assert result["count"] == 5
        assert ok is True

    def test_fenced_json(self, parser):
        content = "Here is the analysis:\n```json\n{\"key\": \"value\"}\n```\nDone."
        config = OutputParserConfig(format=OutputFormat.JSON)
        result, ok = parser.parse(content, ["data"], config)
        assert result["data"]["key"] == "value"

    def test_json_single_output(self, parser):
        content = '{"a": 1, "b": 2}'
        config = OutputParserConfig(format=OutputFormat.JSON)
        result, ok = parser.parse(content, ["data"], config)
        assert result["data"] == {"a": 1, "b": 2}

    def test_invalid_json_falls_back(self, parser):
        config = OutputParserConfig(format=OutputFormat.JSON, fallback=OutputFormat.RAW)
        result, ok = parser.parse("not json at all", ["result"], config)
        assert result["result"] == "not json at all"
        assert ok is False

    def test_strict_mode(self, parser):
        # Strict mode is handled by StepExecutor, parser just returns success flag
        config = OutputParserConfig(format=OutputFormat.JSON, strict=True)
        result, ok = parser.parse("not json", ["result"], config)
        assert ok is False


class TestJsonArrayParser:
    def test_array(self, parser):
        content = '[1, 2, 3]'
        config = OutputParserConfig(format=OutputFormat.JSON_ARRAY)
        result, ok = parser.parse(content, ["items"], config)
        assert result["items"] == [1, 2, 3]


class TestMarkdownSectionsParser:
    def test_sections(self, parser):
        content = "## Entities\nUser, Order\n\n## Relationships\nUser has Orders"
        config = OutputParserConfig(format=OutputFormat.MARKDOWN_SECTIONS)
        result, ok = parser.parse(content, ["entities", "relationships"], config)
        assert "User, Order" in result["entities"]
        assert "User has Orders" in result["relationships"]


class TestRegexParser:
    def test_named_groups(self, parser):
        content = "Score: 95/100\nGrade: A+"
        config = OutputParserConfig(
            format=OutputFormat.REGEX,
            regex_pattern=r"Score: (?P<score>\d+)/\d+\nGrade: (?P<grade>\S+)",
        )
        result, ok = parser.parse(content, ["score", "grade"], config)
        assert result["score"] == "95"
        assert result["grade"] == "A+"

    def test_no_match(self, parser):
        config = OutputParserConfig(format=OutputFormat.REGEX, regex_pattern=r"(?P<x>NOPE)")
        result, ok = parser.parse("nothing here", ["x"], config)
        assert ok is False


class TestKeyValueParser:
    def test_kv_lines(self, parser):
        content = "status: healthy\ncount: 42\nname: test"
        config = OutputParserConfig(format=OutputFormat.KEY_VALUE)
        result, ok = parser.parse(content, ["status", "count", "name"], config)
        assert result["status"] == "healthy"
        assert result["count"] == 42  # Auto-parsed as int
        assert result["name"] == "test"


class TestCsvParser:
    def test_csv(self, parser):
        content = "name,value\nalpha,1\nbeta,2"
        config = OutputParserConfig(format=OutputFormat.CSV)
        result, ok = parser.parse(content, ["rows"], config)
        assert len(result["rows"]) == 2
        assert result["rows"][0]["name"] == "alpha"

    def test_csv_in_code_block(self, parser):
        content = "```csv\nname,value\nalpha,1\n```"
        config = OutputParserConfig(format=OutputFormat.CSV)
        result, ok = parser.parse(content, ["rows"], config)
        assert len(result["rows"]) == 1
