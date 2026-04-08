"""
Output Parsers — Structured extraction from LLM responses

Parses raw LLM output into structured data according to the step's
OutputParserConfig. Supports JSON, JSON arrays, markdown sections,
regex extraction, key-value pairs, and CSV.
"""

import csv
import io
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ..logging_config import logger
from ..models.workflow_models import OutputFormat, OutputParserConfig


class OutputParser:
    """
    Parses LLM responses into structured data based on format configuration.

    Chain of responsibility: try primary format → fallback format → raw.
    """

    def parse(
        self,
        content: str,
        output_keys: List[str],
        config: OutputParserConfig,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Parse LLM output into named outputs.

        Returns:
            (parsed_dict, success) where success indicates if primary format worked
        """
        if config.format == OutputFormat.RAW:
            return self._parse_raw(content, output_keys), True

        # Try primary format
        try:
            result = self._dispatch(content, output_keys, config.format, config)
            if result is not None:
                return result, True
        except Exception as e:
            logger.warning(f"Primary parse ({config.format.value}) failed: {e}")

        # Try fallback
        if config.fallback != config.format:
            try:
                result = self._dispatch(content, output_keys, config.fallback, config)
                if result is not None:
                    logger.info(f"Used fallback parser: {config.fallback.value}")
                    return result, False
            except Exception as e:
                logger.warning(f"Fallback parse ({config.fallback.value}) failed: {e}")

        # Last resort: raw
        return self._parse_raw(content, output_keys), False

    def _dispatch(
        self,
        content: str,
        output_keys: List[str],
        fmt: OutputFormat,
        config: OutputParserConfig,
    ) -> Optional[Dict[str, Any]]:
        """Route to the appropriate parser"""
        parsers = {
            OutputFormat.RAW: self._parse_raw,
            OutputFormat.JSON: self._parse_json,
            OutputFormat.JSON_ARRAY: self._parse_json_array,
            OutputFormat.MARKDOWN_SECTIONS: self._parse_markdown_sections,
            OutputFormat.REGEX: self._parse_regex,
            OutputFormat.KEY_VALUE: self._parse_key_value,
            OutputFormat.CSV: self._parse_csv,
        }
        parser = parsers.get(fmt)
        if parser is None:
            return None
        if fmt == OutputFormat.REGEX:
            return parser(content, output_keys, config.regex_pattern)
        elif fmt == OutputFormat.MARKDOWN_SECTIONS:
            return parser(content, output_keys, config.section_delimiter)
        return parser(content, output_keys)

    # ── RAW ───────────────────────────────────────────────────────────────

    def _parse_raw(self, content: str, output_keys: List[str]) -> Dict[str, Any]:
        """Single output: full content. Multiple: all get same content."""
        if len(output_keys) == 1:
            return {output_keys[0]: content}
        return {key: content for key in output_keys}

    # ── JSON ──────────────────────────────────────────────────────────────

    def _parse_json(self, content: str, output_keys: List[str]) -> Optional[Dict[str, Any]]:
        """Parse as JSON object, mapping keys to outputs"""
        parsed = self._extract_json(content)
        if parsed is None or not isinstance(parsed, dict):
            return None

        if len(output_keys) == 1:
            return {output_keys[0]: parsed}

        result = {}
        for key in output_keys:
            result[key] = parsed.get(key, None)
        return result

    def _parse_json_array(self, content: str, output_keys: List[str]) -> Optional[Dict[str, Any]]:
        """Parse as JSON array"""
        parsed = self._extract_json(content)
        if parsed is None:
            return None

        if isinstance(parsed, list):
            if len(output_keys) == 1:
                return {output_keys[0]: parsed}
            # Distribute array elements across output keys
            result = {}
            for i, key in enumerate(output_keys):
                result[key] = parsed[i] if i < len(parsed) else None
            return result

        return None

    def _extract_json(self, content: str) -> Any:
        """Extract JSON from content — tries raw parse, then fenced code blocks"""
        # Try direct parse
        try:
            return json.loads(content.strip())
        except (json.JSONDecodeError, TypeError):
            pass

        # Try fenced JSON block
        patterns = [
            r"```json\s*\n(.*?)\n\s*```",
            r"```\s*\n(.*?)\n\s*```",
            r"\{[\s\S]*\}",
            r"\[[\s\S]*\]",
        ]
        for pattern in patterns[:2]:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except (json.JSONDecodeError, TypeError):
                    continue

        # Try to find the largest valid JSON object/array in the content
        for pattern in patterns[2:]:
            matches = re.findall(pattern, content, re.DOTALL)
            for m in sorted(matches, key=len, reverse=True):
                try:
                    return json.loads(m)
                except (json.JSONDecodeError, TypeError):
                    continue

        return None

    # ── MARKDOWN SECTIONS ─────────────────────────────────────────────────

    def _parse_markdown_sections(
        self,
        content: str,
        output_keys: List[str],
        delimiter: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Split markdown by headings, map to output keys"""
        delim = delimiter or "##"
        pattern = rf"^{re.escape(delim)}\s+(.+)$"
        sections: Dict[str, str] = {}
        current_name = None
        current_lines: List[str] = []

        for line in content.split("\n"):
            match = re.match(pattern, line, re.MULTILINE)
            if match:
                if current_name:
                    sections[current_name] = "\n".join(current_lines).strip()
                current_name = match.group(1).strip().lower().replace(" ", "_")
                current_lines = []
            else:
                current_lines.append(line)

        if current_name:
            sections[current_name] = "\n".join(current_lines).strip()

        if not sections:
            return None

        result = {}
        for key in output_keys:
            # Match by exact key, or by key contained in section name
            if key in sections:
                result[key] = sections[key]
            else:
                matched = None
                for sec_name, sec_content in sections.items():
                    if key.lower() in sec_name.lower() or sec_name.lower() in key.lower():
                        matched = sec_content
                        break
                result[key] = matched if matched else content

        return result

    # ── REGEX ─────────────────────────────────────────────────────────────

    def _parse_regex(
        self,
        content: str,
        output_keys: List[str],
        regex_pattern: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Extract named groups from content via regex"""
        if not regex_pattern:
            return None

        match = re.search(regex_pattern, content, re.DOTALL | re.MULTILINE)
        if not match:
            return None

        groups = match.groupdict()
        result = {}
        for key in output_keys:
            result[key] = groups.get(key, content)
        return result

    # ── KEY-VALUE ─────────────────────────────────────────────────────────

    def _parse_key_value(self, content: str, output_keys: List[str]) -> Optional[Dict[str, Any]]:
        """Parse 'key: value' lines"""
        kv_pattern = re.compile(r"^([A-Za-z_][\w]*)\s*:\s*(.+)$", re.MULTILINE)
        pairs = {}
        for match in kv_pattern.finditer(content):
            key = match.group(1).strip().lower()
            value = match.group(2).strip()
            # Try to parse as JSON value
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
            pairs[key] = value

        if not pairs:
            return None

        result = {}
        for key in output_keys:
            result[key] = pairs.get(key, pairs.get(key.lower(), content))
        return result

    # ── CSV ───────────────────────────────────────────────────────────────

    def _parse_csv(self, content: str, output_keys: List[str]) -> Optional[Dict[str, Any]]:
        """Parse CSV/TSV tabular data"""
        # Detect delimiter
        if "\t" in content:
            delimiter = "\t"
        else:
            delimiter = ","

        # Try to extract CSV from code blocks
        csv_content = content
        csv_match = re.search(r"```(?:csv|tsv)?\s*\n(.*?)\n\s*```", content, re.DOTALL)
        if csv_match:
            csv_content = csv_match.group(1)

        try:
            reader = csv.DictReader(io.StringIO(csv_content.strip()), delimiter=delimiter)
            rows = list(reader)
            if not rows:
                return None

            if len(output_keys) == 1:
                return {output_keys[0]: rows}

            # Map: first key gets headers, second gets rows, etc.
            result = {}
            headers = list(rows[0].keys()) if rows else []
            for i, key in enumerate(output_keys):
                if i == 0:
                    result[key] = headers
                elif i == 1:
                    result[key] = rows
                else:
                    result[key] = rows
            return result
        except Exception:
            return None
