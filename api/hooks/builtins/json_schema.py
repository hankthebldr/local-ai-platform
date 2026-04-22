"""
json_schema hook — validates raw model output against a JSON schema.

Stage: validate_output. On success, sets ctx.parsed. On failure, returns
action='fail' with a concise feedback message suitable for retry prompting.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JSONSchemaError

from api.services.hook_bus import HookContext, HookResult


@dataclass
class JsonSchemaHook:
    schema: dict
    strict: bool = False
    strip_fences: bool = True

    name: str = "json_schema"
    stage: str = "validate_output"

    def __call__(self, ctx: HookContext) -> HookResult:
        raw = ctx.output or ""
        if not self.strict:
            candidate = self._extract_json_blob(raw)
        else:
            candidate = raw.strip()

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as e:
            return HookResult(
                action="fail",
                feedback=f"Your response could not be parsed as JSON: {e.msg}. Return a single JSON object only.",
            )

        try:
            Draft202012Validator(self.schema).validate(parsed)
        except JSONSchemaError as e:
            path = ".".join(str(p) for p in e.absolute_path) or "(root)"
            return HookResult(
                action="fail",
                feedback=f"Your response failed JSON schema validation at '{path}': {e.message}",
            )

        ctx.parsed = parsed
        return HookResult(action="continue")

    @staticmethod
    def _extract_json_blob(raw: str) -> str:
        """Pull JSON out of markdown fences or leading prose."""
        m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.DOTALL)
        if m:
            return m.group(1)
        for opener, closer in (("{", "}"), ("[", "]")):
            start = raw.find(opener)
            if start == -1:
                continue
            depth = 0
            for i in range(start, len(raw)):
                ch = raw[i]
                if ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        return raw[start:i+1]
        return raw.strip()
