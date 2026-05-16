# Parser Training Mode - Reusable Prompt

## Purpose

This document is a reusable prompt template for building Cortex XSIAM parsing rules (INGEST) from raw log samples. It codifies the workflow developed and validated across multiple real-world exercises (Imperva Audit Trail, Imperva ATO). Paste this prompt into a new session to enter parser training mode.

---

## Prompt Template

```
You are in Parser Training Mode. Your task is to help me build a Cortex XSIAM
parsing rule (INGEST) from raw log data.

WORKFLOW:
1. ANALYSE - I will provide raw log samples (TSV export from Cortex). Identify
   the log format, all available fields, event types, and timestamp format.
2. BUILD - Construct the parsing rule following the structure below.
3. TEST - I will test the rule in Cortex and report results back.
4. ITERATE - We fix any issues based on test results.
5. CAPTURE - Once validated, we create a snippet and update documentation.

RULES FOR BUILDING PARSERS:

Header format (INGEST rules use quoted values):
[INGEST:vendor="VENDOR", product="PRODUCT", target_dataset="vendor_product_raw", no_hit=keep]

Note: MODEL rules use UNQUOTED dataset values: [MODEL: dataset=vendor_product_raw]

Structure:
filter
    _raw_log != null
    and _raw_log contains "content_guard"
| alter
    <extract all fields from _raw_log using json_extract_scalar>
| alter
    <derive additional fields, set _time, map to xdr_data fields>
| alter
    <pack vendor metadata into action_evtlog_data_fields>

CRITICAL RULES:
- parse_epoch(string_field, "MILLIS") takes a STRING, not a number
- Do NOT wrap in to_integer()
- from_epoch does NOT exist -- always use parse_epoch
- JSON paths use $.fieldname notation (no @ prefix even if raw key has @)
- json_extract_scalar returns strings -- pass directly to parse_epoch
- Every _temp field must be consumed (mapped to xdr_data or packed into data_fields)
- _time must ALWAYS be set from the source timestamp
- Use concat() to build composed action_evtlog_message for triage-friendly summaries
- actor_remote_ip is the correct field for client IP in security events
- Pack vendor-specific metadata into action_evtlog_data_fields using
  to_json_string(object_create("key1", val1, "key2", val2))

VALIDATION QUERY:
dataset = vendor_product_raw
| fields _time, event_id, actor_primary_username, action_evtlog_message, action_evtlog_data_fields
| limit 10

Ready. Please provide the raw log samples.
```

---

## Workflow Phases

### Phase 1: Analysis

**Input**: User provides raw log samples (TSV export or JSON records).

**Tasks**:
- Identify log format (JSON, syslog, CSV, key-value)
- List all top-level fields and nested structures
- Count distinct event types
- Identify timestamp format and field
- Note any fields requiring regextract (free-text messages)

**Output**: Field inventory table and proposed xdr_data mapping.

### Phase 2: Construction

**Input**: Approved field mapping from Phase 1.

**Tasks**:
- Write the INGEST rule header with quoted values
- Build extraction stage (json_extract_scalar for JSON logs)
- Build derivation stage (_time, regextract for sub-fields)
- Build mapping stage (xdr_data field assignments)
- Build metadata packing (action_evtlog_data_fields)
- Ensure content guard filter is specific enough

**Output**: Complete INGEST rule ready for testing.

### Phase 3: Testing

**Input**: User tests rule in Cortex and reports results.

**Common issues**:
- Fields returning null: check JSON path, field name case sensitivity
- _time not populating: check parse_epoch argument is string, check unit (MILLIS vs SECONDS)
- Unmatched events: check content guard filter is not too restrictive
- Missing event types: may need separate filter branches or additional INGEST blocks

**Output**: Iteration notes or validation confirmation.

### Phase 4: Knowledge Capture

**Input**: Validated rule from Phase 3.

**Tasks**:
- Create snippet in server/data/snippets.ts
- Update parsers-completed table below
- Document any new patterns or pitfalls discovered
- Update PRIVATE_DOCS/parsing_rule_building_guide.md if new patterns emerged

**Output**: Snippet added, documentation updated.

---

## Quality Checklist

| Check | Requirement |
|-------|-------------|
| Header format | `[INGEST:vendor="X", product="Y", target_dataset="X_Y_raw", no_hit=keep]` -- all values quoted |
| Content guard | Filter includes `_raw_log contains "identifier"` to avoid processing unrelated logs |
| _time set | `_time` is always assigned from the source timestamp |
| parse_epoch usage | Takes STRING argument, not wrapped in to_integer() |
| parse_epoch guarded | Always wrap in `if(field != null and field != "", parse_epoch(field, "MILLIS"), null)` to prevent runtime crash on empty strings |
| No from_epoch | Use parse_epoch, never from_epoch (does not exist) |
| JSON paths | Use `$.fieldname` for standard keys. For keys with special characters like `@`, use bracket notation: `$['@timestamp']` (NOT `$.@timestamp` which fails at runtime) |
| Temp field cleanup | Every `_temp` variable is consumed in xdr_data mapping or data_fields packing |
| actor_remote_ip | Used for client IP in security events (not actor_primary_ip) |
| Metadata packing | Vendor-specific fields packed into action_evtlog_data_fields as JSON |
| Summary message | action_evtlog_message built with concat() for triage-friendly summaries |
| Validation query | Tested with fields query against the target dataset |

---

## Common Errors Table

| Error | Cause | Fix |
|-------|-------|-----|
| `from_epoch` is not a known function | `from_epoch` does not exist in XQL | Use `parse_epoch(string_field, "MILLIS")` |
| parse_epoch returns null | Passed an integer instead of string | Remove `to_integer()` wrapper; json_extract_scalar already returns string |
| JSON field returns null | Wrong JSON path | Check path with `$.fieldname` notation. For keys with `@` use bracket notation: `$['@timestamp']` |
| `$.@timestamp` runtime error | Dot notation fails for keys with special characters | Use bracket notation: `json_extract_scalar(_raw_log, "$['@timestamp']")` |
| Quoted dataset warning on MODEL | Dataset quoted in MODEL block | Use `[MODEL: dataset=name_raw]` (unquoted). Does not apply to INGEST |
| Events not matching | Content guard too restrictive | Broaden the `_raw_log contains` filter |
| _time not set | Missing _time assignment | Always include `_time = parse_epoch(...)` or `_time = parse_timestamp(...)` |
| parse_epoch runtime crash | `_ts` is null or empty string | Guard: `_time = if(_ts != null and _ts != "", parse_epoch(_ts, "MILLIS"), null)` |
| Temp fields flagged as unused | Field extracted but never mapped | Map to xdr_data field or pack into action_evtlog_data_fields |

---

## Parsers Completed

| Dataset | Vendor | Product | Event Types | Key Fields | Status |
|---------|--------|---------|-------------|------------|--------|
| imperva_audit_raw | Imperva | Cloud WAF Audit | MODIFY_POLICY, ADD_USER, DELETE_SITE, UPDATE_CERTIFICATE | event_id, actor_primary_username, action_evtlog_message, action_evtlog_data_fields | Validated |
| imperva_ato_raw | Imperva | ATO | Suspicious successful login, Account takeover login | event_id, actor_primary_username, actor_remote_ip, action_evtlog_message | Validated |

---

## Quoting Rules Summary

| Block Type | Format | Example |
|------------|--------|---------|
| INGEST | Quoted values | `[INGEST:vendor="Imperva", product="ATO", target_dataset="imperva_ato_raw", no_hit=keep]` |
| MODEL | Unquoted dataset | `[MODEL: dataset=imperva_ato_raw]` |
| RULE | Unquoted name | `[RULE: timestamp_parse]` (data-model RULE blocks called via `\| call`; see Pattern 10) |

---

## Reusable RULE/CALL Pattern (Data Model Rules)

When proposing a data model rule structure for a dataset whose
events fall into two or more distinct shapes (e.g. multiple daemons
behind one syslog dataset, multiple action types behind one cloud
audit dataset), evaluate up-front whether the file should be
written as ONE `[MODEL: ...]` block containing several
`;`-terminated pipelines joined to a shared `[RULE:]` block via
`call`. Cortex permits exactly one MODEL block per
`(dataset, model)` tuple per file -- the per-event-shape branches
are NOT separate `[MODEL:]` headers but separate
`;`-terminated pipelines INSIDE a single MODEL block. The
analyser flags duplicate `[MODEL: dataset=NAME]` headers as
`ERR-026`.

Trigger heuristic for the `[RULE:]` factor-out: two or more
pipelines inside the single MODEL block would share more than ~15
lines of identical header parsing, allow-list filtering, or
common-field extraction. When the heuristic fires, propose the
RULE/CALL structure first rather than four near-identical preludes
-- it is materially cheaper to refactor before the first pipeline
is written than after the fourth. The analyser fires `SUG-017`
once the per-pair shared count crosses 18 normalised lines.

A `[RULE: name]` block has a MODEL-style body (no leading `|` on
the first stage, terminating semicolon) and is called as the first
stage of each pipeline via `call name` (or `| call name` when not
the first stage, e.g. when chaining a second RULE after a
discriminator). The call is normally followed immediately by a
per-pipeline `| filter` that selects the rows that pipeline is
responsible for. Treat the underscore-prefixed intermediates the
RULE produces as its public interface and document them in the
file header.

Full decision rule, syntax notes, and a worked example using the
EfficientIP DDI rule are in the data model rule building guide
under "Pattern 10: Shared logic via [RULE:] + call". Two further
production examples ship in `PRIVATE_DOCS/all_modeling_rules.txt`:
BeyondTrust PRA at lines 286-348, and ESXi at lines 1056-1408.

This pattern only applies to data model rules. INGEST (parsing)
rules generally do not benefit from RULE/CALL because the
per-event-type work is usually small and the ingest pipeline
already separates concerns via distinct INGEST blocks.

---

## Future Enhancements

- Syslog format parser template (non-JSON logs)
- CSV/KV format parser template
- Multi-INGEST block patterns (multiple event types requiring separate blocks)
- Automated field coverage analysis against xdr_data schema
- Parser performance benchmarking patterns
