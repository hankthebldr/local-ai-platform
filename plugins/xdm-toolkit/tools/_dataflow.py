# Derived from gocortex-xql-ide/server/data/rules-engine.ts (AGPL-3.0).
"""
Shared dataflow helpers (analyse_dataflow, stage-statement collector,
expression-type inference). Mirrors rules-engine.ts lines 137-694.

Used by ERR-019, ERR-024, ERR-025, INFO-007, WARN-020, WARN-029, WARN-030,
WARN-035, WARN-036, ERR-012, ERR-013, ERR-018.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set


ARRAY_PRODUCING_FNS: frozenset[str] = frozenset({
    "arraycreate", "arrayconcat", "arraydistinct", "arraymap",
    "arrayfilter", "arraymerge", "arraypop", "arrayrange",
    "arrayresize", "split", "regextract", "json_extract_array",
    "json_extract_scalar_array", "values",
    "object_keys", "object_values",
})

ARRAY_FN_RE = re.compile(
    r"\b(" + "|".join(sorted(ARRAY_PRODUCING_FNS, key=len, reverse=True)) + r")\s*\("
)
ARRAY_SUFFIX_RE = re.compile(r"->\s*\[\s*\]")


@dataclass
class DataflowDef:
    name: str
    line: int
    isUnderscore: bool
    rhsText: str = ""


@dataclass
class DataflowResult:
    defs: List[DataflowDef] = field(default_factory=list)
    reachable: Set[str] = field(default_factory=set)
    arrayTyped: Set[str] = field(default_factory=set)


def split_top_level_args(s: str) -> List[str]:
    """Split function-arg list at top-level commas (paren & string aware)."""
    out: List[str] = []
    depth = 0
    start = 0
    in_str: Optional[str] = None
    i = 0
    while i < len(s):
        ch = s[i]
        if in_str is not None:
            if ch == in_str and (i == 0 or s[i - 1] != "\\"):
                in_str = None
            i += 1
            continue
        if ch == '"' or ch == "'":
            in_str = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(s[start:i])
            start = i + 1
        i += 1
    out.append(s[start:])
    return [a.strip() for a in out if a.strip()]


def rhs_is_array_typed(rhs: str, known_array_vars: Set[str]) -> bool:
    """Decide whether an RHS expression produces an array."""
    t = re.sub(r"[,;]\s*$", "", rhs.strip())
    if not t:
        return False
    if ARRAY_SUFFIX_RE.search(t):
        return True
    # Outermost call?
    fn_match = re.match(r"^([a-zA-Z_]\w*)\s*\(", t)
    if fn_match:
        depth = 0
        close_idx = -1
        in_str: Optional[str] = None
        i = len(fn_match.group(0)) - 1
        while i < len(t):
            ch = t[i]
            if in_str is not None:
                if ch == in_str and t[i - 1] != "\\":
                    in_str = None
                i += 1
                continue
            if ch == '"' or ch == "'":
                in_str = ch
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break
            i += 1
        fn_name = fn_match.group(1).lower()
        wraps_whole = close_idx == len(t) - 1
        if wraps_whole:
            if fn_name in ARRAY_PRODUCING_FNS:
                return True
            if fn_name in ("if", "coalesce"):
                inner = t[len(fn_match.group(0)):close_idx]
                args = split_top_level_args(inner)
                value_args = args[1:] if fn_name == "if" else args
                for a in value_args:
                    cleaned = a.strip()
                    if cleaned == "null" or not cleaned:
                        continue
                    if rhs_is_array_typed(cleaned, known_array_vars):
                        return True
                return False
            return False
    bare = re.match(r"^([a-zA-Z_]\w*)\s*$", t)
    if bare and bare.group(1) in known_array_vars:
        return True
    if ARRAY_FN_RE.search(t):
        return True
    return False


def analyse_dataflow(code: str, lines: List[str]) -> DataflowResult:
    """Port of analyseDataflow (rules-engine.ts lines 265-402)."""
    all_code_parts: List[str] = []
    for raw in lines:
        trimmed = raw.lstrip()
        if trimmed.startswith("//"):
            all_code_parts.append("")
        else:
            all_code_parts.append(raw.split("//", 1)[0])

    # Stage tracking
    cur_stage = ""
    stage_of: List[str] = []
    for cp in all_code_parts:
        sm = re.match(r"^\s*\|\s*(\w+)\b", cp)
        if sm:
            cur_stage = sm.group(1).lower()
        stage_of.append(cur_stage)

    # Paren-aware def detection.
    defs: List[DataflowDef] = []
    def_re = re.compile(r"^\s*([a-zA-Z_][\w]*)\s*=")
    paren_depth = 0
    for i, cp in enumerate(all_code_parts):
        stage = stage_of[i]
        start_depth = paren_depth
        stripped = re.sub(r"'[^']*'", "''", re.sub(r'"[^"]*"', '""', cp))
        for ch in stripped:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
        if stage and stage != "alter":
            continue
        if start_depth > 0:
            continue
        m = def_re.match(cp)
        if not m:
            continue
        name = m.group(1)
        if name in ("_time", "_raw_log"):
            continue
        if name in ("alter", "filter", "comp", "config", "target"):
            continue
        defs.append(DataflowDef(name=name, line=i + 1, isUnderscore=name.startswith("_")))

    if not defs:
        return DataflowResult(defs=[], reachable=set(), arrayTyped=set())

    real_def_lines: Set[int] = {d.line - 1 for d in defs}

    def is_stage_start(cp: str) -> bool:
        return bool(re.match(r"^\s*\|\s*\w+", cp))

    # Multi-line RHS span.
    for d in defs:
        start = d.line - 1
        end = len(all_code_parts) - 1
        for j in range(start + 1, len(all_code_parts)):
            cp = all_code_parts[j]
            if is_stage_start(cp) or j in real_def_lines or re.search(r"xdm\.[\w.]+\s*=", cp):
                end = j - 1
                break
        d.rhsText = "\n".join(all_code_parts[start:end + 1])

    # Locate xdm.* block.
    first_xdm_idx = -1
    for i, cp in enumerate(all_code_parts):
        if re.search(r"xdm\.[\w.]+\s*=", cp):
            first_xdm_idx = i
            break

    reachable: Set[str] = set()
    if first_xdm_idx >= 0:
        for d in defs:
            if d.name in reachable:
                continue
            skip_idx: Set[int] = set()
            for dd in defs:
                if dd.name != d.name:
                    continue
                start = dd.line - 1
                end = len(all_code_parts) - 1
                for j in range(start + 1, len(all_code_parts)):
                    cp = all_code_parts[j]
                    if is_stage_start(cp) or j in real_def_lines or re.search(r"xdm\.[\w.]+\s*=", cp):
                        end = j - 1
                        break
                for k in range(start, end + 1):
                    skip_idx.add(k)
            blob = []
            for k in range(first_xdm_idx, len(all_code_parts)):
                blob.append("" if k in skip_idx else all_code_parts[k])
            cleaned = "\n".join(blob)
            escaped = re.escape(d.name)
            if re.search(r"\b" + escaped + r"\b", cleaned):
                reachable.add(d.name)

        changed = True
        while changed:
            changed = False
            for reach_name in list(reachable):
                for cand in defs:
                    if cand.name in reachable or cand.name == reach_name:
                        continue
                    for d in defs:
                        if d.name != reach_name:
                            continue
                        escaped = re.escape(cand.name)
                        if re.search(r"\b" + escaped + r"\b", d.rhsText):
                            reachable.add(cand.name)
                            changed = True

    # Array-typed BFS.
    array_typed: Set[str] = set()
    changed_arr = True
    while changed_arr:
        changed_arr = False
        for d in defs:
            if d.name in array_typed:
                continue
            rhs = d.rhsText
            eq_idx = rhs.find("=")
            if eq_idx >= 0:
                rhs = rhs[eq_idx + 1:]
            if rhs_is_array_typed(rhs, array_typed):
                array_typed.add(d.name)
                changed_arr = True

    return DataflowResult(defs=defs, reachable=reachable, arrayTyped=array_typed)


# ── Stage-statement collector (rules-engine.ts lines 415-561) ──────────

@dataclass
class StageStatement:
    startLine: int
    text: str
    stage: str
    lineOf: List[int] = field(default_factory=list)


def collect_stage_statements(lines: List[str]) -> List[StageStatement]:
    """Port of collectStageStatements."""
    out: List[StageStatement] = []
    stage = ""
    depth = 0
    cur_start = -1
    cur_buf = ""
    cur_line_of: List[int] = []

    def flush() -> None:
        nonlocal cur_start, cur_buf, cur_line_of
        if cur_start >= 0 and cur_buf.strip():
            out.append(StageStatement(
                startLine=cur_start + 1,
                text=cur_buf,
                stage=stage,
                lineOf=list(cur_line_of),
            ))
        cur_start = -1
        cur_buf = ""
        cur_line_of = []

    for i, raw in enumerate(lines):
        if raw.lstrip().startswith("//"):
            if cur_start >= 0 and cur_buf and not cur_buf[-1].isspace():
                cur_buf += " "
                cur_line_of.append(i + 1)
            continue
        code_part = raw.split("//", 1)[0]
        process_idx = 0
        if depth == 0:
            sm = re.match(r"^\s*\|\s*(\w+)\b", code_part)
            if sm:
                flush()
                stage = sm.group(1).lower()
                process_idx = len(sm.group(0))
            elif cur_start < 0 and stage == "" and re.match(
                r"^\s*(alter|filter|config|fields|dedup|sort|comp|target)\b",
                code_part, re.IGNORECASE,
            ):
                sm2 = re.match(
                    r"^\s*(alter|filter|config|fields|dedup|sort|comp|target)\b",
                    code_part, re.IGNORECASE,
                )
                if sm2:
                    stage = sm2.group(1).lower()
                    process_idx = len(sm2.group(0))

        in_str = False
        str_ch = ""
        j = process_idx
        while j < len(code_part):
            ch = code_part[j]
            if in_str:
                if ch == "\\" and j + 1 < len(code_part):
                    if cur_start < 0:
                        cur_start = i
                    cur_buf += ch
                    cur_line_of.append(i + 1)
                    nxt = code_part[j + 1]
                    cur_buf += nxt
                    cur_line_of.append(i + 1)
                    j += 2
                    continue
                if ch == str_ch:
                    in_str = False
                if cur_start < 0:
                    cur_start = i
                cur_buf += ch
                cur_line_of.append(i + 1)
                j += 1
                continue
            if ch == '"' or ch == "'":
                in_str = True
                str_ch = ch
                if cur_start < 0:
                    cur_start = i
                cur_buf += ch
                cur_line_of.append(i + 1)
                j += 1
                continue
            if ch in ("(", "["):
                depth += 1
                if cur_start < 0:
                    cur_start = i
                cur_buf += ch
                cur_line_of.append(i + 1)
                j += 1
                continue
            if ch in (")", "]"):
                depth = max(0, depth - 1)
                if cur_start < 0:
                    cur_start = i
                cur_buf += ch
                cur_line_of.append(i + 1)
                j += 1
                continue
            if depth == 0 and (ch == "," or ch == ";"):
                flush()
                j += 1
                continue
            if depth == 0 and ch == "|":
                flush()
                rest = code_part[j:]
                sm = re.match(r"^\|\s*(\w+)\b", rest)
                if sm:
                    stage = sm.group(1).lower()
                    j += len(sm.group(0))
                else:
                    j += 1
                continue
            if cur_start < 0 and ch.strip():
                cur_start = i
            if cur_start >= 0:
                cur_buf += ch
                cur_line_of.append(i + 1)
            j += 1

        if cur_start >= 0 and cur_buf and not cur_buf[-1].isspace():
            cur_buf += " "
            cur_line_of.append(i + 1)

    flush()
    return out


def line_at(stmt: StageStatement, pos: int) -> int:
    if pos < 0 or pos >= len(stmt.lineOf):
        return stmt.startLine
    return stmt.lineOf[pos]


def split_assignment(stmt: StageStatement):
    """Return dict {lhs, rhs, rhsStart} or None."""
    depth = 0
    in_str = False
    str_ch = ""
    t = stmt.text
    i = 0
    while i < len(t):
        ch = t[i]
        if in_str:
            if ch == str_ch:
                in_str = False
            i += 1
            continue
        if ch == '"' or ch == "'":
            in_str = True
            str_ch = ch
            i += 1
            continue
        if ch in ("(", "["):
            depth += 1
            i += 1
            continue
        if ch in (")", "]"):
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth != 0:
            i += 1
            continue
        if ch != "=":
            i += 1
            continue
        prev = t[i - 1] if i > 0 else ""
        nxt = t[i + 1] if i + 1 < len(t) else ""
        if prev in ("!", "<", ">", "="):
            i += 1
            continue
        if nxt == "=":
            i += 1
            continue
        return {"lhs": t[:i].strip(), "rhs": t[i + 1:].strip(), "rhsStart": i + 1}
    return None


# ── Scalar type inference (WARN-035 helpers) ─────────────────────────

def as_string_literal(rhs: str) -> Optional[str]:
    """Return content of a quoted literal, else None."""
    t = re.sub(r"[,;]\s*$", "", rhs.strip())
    dq = re.match(r'^"((?:[^"\\]|\\.)*)"$', t)
    if dq:
        return dq.group(1)
    sq = re.match(r"^'([^']*)'$", t)
    if sq:
        return sq.group(1)
    return None


_IPV4_RE = re.compile(
    r"^(?:25[0-5]|2[0-4]\d|[01]?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d?\d)){3}$"
)


def infer_scalar_base(expr: str, defs: List[DataflowDef], seen: Optional[Set[str]] = None) -> Optional[str]:
    """Best-effort inference of scalar base type."""
    if seen is None:
        seen = set()
    t = re.sub(r"[,;]\s*$", "", expr.strip())
    if not t or t == "null":
        return None
    lit = as_string_literal(t)
    if lit is not None:
        if _IPV4_RE.match(lit):
            return "ipv4"
        if ":" in lit and re.match(r"^[0-9a-fA-F:.]+$", lit):
            return "ipv6"
        return "string"
    if re.match(r"^-?\d+$", t):
        return "int"
    if re.match(r"^-?\d+\.\d+$", t):
        return "float"
    if t == "true" or t == "false":
        return "bool"
    fn = re.match(r"^([a-zA-Z_]\w*)\s*\(", t)
    if fn:
        name = fn.group(1).lower()
        if name == "to_string":
            return "string"
        if name in ("to_integer", "to_number"):
            return "int"
        if name == "to_float":
            return "float"
        if name == "to_boolean":
            return "bool"
        return None
    ident = re.match(r"^([a-zA-Z_]\w*)$", t)
    if ident:
        name = ident.group(1)
        if name in seen:
            return None
        seen.add(name)
        d = next((x for x in defs if x.name == name), None)
        if not d:
            return None
        rhs = d.rhsText
        eq = rhs.find("=")
        if eq >= 0:
            rhs = rhs[eq + 1:]
        return infer_scalar_base(rhs, defs, seen)
    return None


def scalar_bases_compatible(inferred: str, declared: str) -> bool:
    if inferred == declared:
        return True
    if inferred in ("int", "float") and declared in ("int", "float"):
        return True
    return False
