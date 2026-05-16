# Parsing Rule Building Guide

## Overview

This guide documents the end-to-end repeatable process for building a Cortex XSIAM parsing rule (INGEST) from raw log samples. The process has been validated across multiple real-world exercises and is designed to be followed for any new vendor/product.

A parsing rule is the first stage of the Cortex XSIAM data pipeline:
1. **Parsing Rule** (INGEST) -- extracts from `_raw_log` into xdr_data schema fields (schema-on-write)
2. **Data Model Rule** (MODEL) -- maps from xdr_data fields into XDM fields (schema-on-read)

See also: [Data Model Rule Building Guide](data_model_rule_building_guide.md)

## Repeatable Process

### Step 1: Analyse the Raw Log Structure

Export a sample of raw logs (10-100 rows) from the target dataset. Identify:

- **TSV metadata columns**: `_time`, `_raw_log`, `_id`, `_insert_time`, `_product`, `_tag`, `_vendor`
- **Raw log format**: Is `_raw_log` JSON, syslog, CSV, or key-value pairs?
- **Top-level JSON keys**: For JSON logs, identify all top-level fields (e.g. `timestamp`, `message`, `event`, `user`)
- **Nested objects**: Identify nested structures that need `json_extract_scalar` with dot-path navigation
- **Data types**: Distinguish strings from numbers and timestamps
- **Event type distribution**: How many distinct event types exist? (e.g. CONFIG_CHANGE, LOGIN, ALERT)

**Output of this step**: A field inventory listing every available field, its data type, and which event types it appears in.

### Step 2: Map Source Fields to xdr_data

Cross-reference the raw fields against the xdr_data schema (879 fields across 7 actor categories). The xdr_data schema is endpoint-oriented, so cloud SaaS audit logs require creative mapping:

**Standard mappings for audit/config change logs:**

| xdr_data Field | Type | Best Use |
|---|---|---|
| `_time` | timestamp | Event timestamp (mandatory) |
| `event_id` | STRING | Event action code (e.g. "CONFIG_CHANGE") |
| `event_timestamp` | INTEGER | Epoch timestamp as integer |
| `actor_primary_username` | STRING | User who performed the action |
| `actor_remote_ip` | STRING | Client IP for security events |
| `action_evtlog_message` | STRING | Full audit message text or composed summary via concat() |
| `action_evtlog_description` | STRING | Human-readable action description |
| `action_evtlog_provider_name` | STRING | Log provider/source name |
| `action_evtlog_data_fields` | STRING | JSON-packed vendor-specific metadata |

**The `action_evtlog_data_fields` strategy**: For cloud SaaS products with rich metadata that does not fit neatly into standard xdr_data fields (account IDs, resource types, site IDs, event contexts), pack all structured metadata into this field as a JSON string using `to_json_string(object_create(...))`. The downstream data model rule can then unpack it using `json_extract_scalar`.

**Output of this step**: A mapping table showing each source field, its target xdr_data field, and any transformation needed.

### Step 3: Write the Rule

Structure the rule as:

```
[INGEST:vendor="vendor_name", product="product_name", target_dataset="vendor_product_raw", no_hit=keep]
filter
    _raw_log != null
    and _raw_log contains "vendor_identifier"
| alter
    <extract all fields from _raw_log using json_extract_scalar>
| alter
    <derive additional fields using regextract on free-text messages>
| alter
    <map to xdr_data fields>
```

**Header quoting rules:**
- INGEST rules use quoted values: `[INGEST:vendor="name", product="name", target_dataset="dataset_raw", no_hit=keep]`
- MODEL rules use unquoted values: `[MODEL: dataset=vendor_product_raw]`

**Key structural notes:**
- The `no_hit=keep` parameter preserves unmatched logs for troubleshooting
- The filter should include a content guard (e.g. `_raw_log contains "vendor_name"`) to avoid processing unrelated logs
- Use multiple `alter` stages: extraction, derivation, then mapping
- Group related extractions together for readability

### Step 4: Validate

Run the parser through the IDE rules engine, then test in Cortex:

- Every `_temp` variable extracted in stage 1 must be consumed in stage 3 (mapped to xdr_data or packed into data_fields)
- `_time` must always be set from the source timestamp
- `parse_epoch` takes a STRING argument, not a number -- do NOT wrap in `to_integer()`
- JSON paths use `$.fieldname` notation -- no `@` prefix even if the raw JSON key has one
- Test with `dataset = vendor_product_raw | fields _time, event_id, actor_primary_username, action_evtlog_data_fields | limit 10`

**Output of this step**: Confirmation that all mapped fields populate correctly across all event types.

### Step 5: Knowledge Capture

After validation, capture what was learnt:

1. Add the validated parser as a snippet in the IDE snippets library
2. Document any new patterns or pitfalls discovered during the exercise
3. Update the parsers-completed tracking table in the [Parser Training Mode Prompt](parser_training_mode_prompt.md)

---

## Key Patterns

### Pattern 1: Epoch Milliseconds to _time

The most common timestamp format in cloud SaaS logs is epoch milliseconds. Use `parse_epoch` with the string value directly, **always guarded** against null/empty inputs:

```xql
_timestamp_ms = json_extract_scalar(_raw_log, "$.timestamp")
| alter
    _time = if(_timestamp_ms != null and _timestamp_ms != "", parse_epoch(_timestamp_ms, "MILLIS"), null)
```

**Critical pitfall 1**: `parse_epoch` expects a STRING argument. Since `json_extract_scalar` already returns a string, pass it directly. Do NOT wrap in `to_integer()`:

```xql
// WRONG - parse_epoch expects string, not number
_time = parse_epoch(to_integer(_timestamp_ms), "MILLIS")

// CORRECT - pass the string directly, with null guard
_time = if(_timestamp_ms != null and _timestamp_ms != "", parse_epoch(_timestamp_ms, "MILLIS"), null)
```

**Critical pitfall 2**: `parse_epoch` throws a runtime error if the input is null or an empty string. Always wrap in an `if()` guard as shown above. Without the guard, logs with missing timestamps will crash the parser.

**Also note**: The function is `parse_epoch`, NOT `from_epoch`. The latter does not exist in XQL.

### Pattern 2: Structured JSON Extraction from _raw_log

For JSON-formatted raw logs with nested objects, use `json_extract_scalar` with dot-path notation:

```xql
_account_id = json_extract_scalar(_raw_log, "$.vendor.ids.account_id"),
_event_action = json_extract_scalar(_raw_log, "$.vendor.audit.event_action"),
_user_email = json_extract_scalar(_raw_log, "$.user.email")
```

**JSON path rules:**
- Top-level fields: `$.fieldname`
- Nested objects: `$.parent.child.grandchild`
- Array elements: `$.array[0].field`
- NO `@` prefix: Even if the raw JSON has `@timestamp`, the Cortex JSON path is `$.timestamp`

### Pattern 3: Packing Vendor Metadata into data_fields

When the vendor provides rich structured metadata that has no direct xdr_data equivalent, pack it into `action_evtlog_data_fields` as JSON:

```xql
action_evtlog_data_fields = to_json_string(object_create(
    "account_id", _account_id,
    "resource_type", _resource_type,
    "resource_id", _resource_id,
    "resource_name", _resource_name,
    "event_context", _event_context))
```

This preserves all vendor-specific fields in a structured format that the downstream data model rule can unpack using `json_extract_scalar(action_evtlog_data_fields, "$.account_id")`.

### Pattern 4: Regex Sub-extraction from Free-text Messages

Many audit logs contain structured data embedded in free-text message strings. Use `regextract` to pull out specific values:

```xql
// Example message: "OBJECT_TYPE (12345) Before change ({...}) After change ({...})"
_msg_object_type = arrayindex(regextract(_message, "^([A-Z_]+)\s*\("), 0),
_msg_object_id = arrayindex(regextract(_message, "^\w+\s*\((\d+)\)"), 0),
_obj_name = arrayindex(regextract(_message, "\"name\":\"([^\"]+)\""), 0)
```

### Pattern 5: Content Guard Filter

Always include a content-based filter in the INGEST rule to ensure only the correct vendor's logs are processed:

```xql
filter
    _raw_log != null
    and _raw_log contains "vendor_identifier"
```

This prevents the parser from attempting to process logs from other vendors that may be routed to the same dataset.

### Pattern 6: Composed Summary Message with concat()

Build a triage-friendly summary by combining key fields with delimiters:

```xql
action_evtlog_message = concat(_event_type, " | risk=", _risk_level, " | country=", _country)
```

This is especially useful for security events where analysts need to scan summaries quickly.

---

## Common Pitfalls

| Pitfall | Example | Fix |
|---------|---------|-----|
| `from_epoch` does not exist | `_time = from_epoch(ts, "MILLIS")` | Use `parse_epoch(ts, "MILLIS")` |
| `parse_epoch` given a number | `parse_epoch(to_integer(ts), "MILLIS")` | Pass the string directly: `parse_epoch(ts, "MILLIS")` |
| JSON path with `@` in key name | `json_extract_scalar(_raw_log, "$.@timestamp")` | Use bracket notation: `json_extract_scalar(_raw_log, "$['@timestamp']")` — the `$.@` dot notation fails at runtime |
| Missing `_time` assignment | No `_time =` in the parser | Always set `_time` from source timestamp |
| Forgetting `no_hit=keep` | `[INGEST:vendor="x", product="y", target_dataset="x_y_raw"]` | Add `no_hit=keep` to preserve unmatched logs |
| Not packing vendor metadata | Vendor fields lost because no xdr_data equivalent | Pack into `action_evtlog_data_fields` as JSON |
| Unused temp fields | `_unused = json_extract_scalar(...)` never mapped | Remove or map to xdr_data / data_fields |
| Unguarded parse_epoch on empty field | `_time = parse_epoch(_ts, "MILLIS")` crashes if `_ts` is null/empty | Wrap in `if(_ts != null and _ts != "", parse_epoch(_ts, "MILLIS"), null)` |
| Quoted dataset in MODEL header | `[MODEL: dataset="vendor_raw"]` | Use `[MODEL: dataset=vendor_raw]` (no quotes in MODEL blocks). Note: INGEST rules correctly use quoted values |

---

## Illustrative Example: Cloud WAF Audit Trail Parser

This example demonstrates the process applied to a cloud WAF audit trail log source, producing a validated parsing rule.

### Source Log Structure

The `_raw_log` is JSON with nested vendor-specific objects:

```json
{
  "timestamp": 1700000000000,
  "message": "POLICY (100001) Before change ({...}) After change ({...})",
  "event": {
    "provider": "audit",
    "dataset": "AUDIT_TRAIL"
  },
  "vendor_specific": {
    "ids": {
      "account_id": "ACCT-001",
      "account_name": "Example Corp",
      "site_id": "SITE-001"
    },
    "audit_trail": {
      "event_action": "MODIFY_POLICY",
      "event_action_description": "Policy Modified",
      "resource_type": "Site",
      "resource_type_description": "Site",
      "resource_id": "RES-001",
      "resource_name": "Example Resource",
      "event_context": "API",
      "event_context_description": "API"
    }
  },
  "user": {
    "email": "admin@example.com"
  }
}
```

### Field Mapping Table

| Source JSON Path | xdr_data Field | Type | Notes |
|-----------------|---------------|------|-------|
| timestamp | _time | timestamp | via parse_epoch(str, "MILLIS") |
| timestamp | event_timestamp | INTEGER | via to_integer() |
| message | action_evtlog_message | STRING | Full audit trail message |
| event.provider | action_evtlog_provider_name | STRING | Log provider name |
| vendor_specific.audit_trail.event_action | event_id | STRING | Action code |
| vendor_specific.audit_trail.event_action_description | action_evtlog_description | STRING | Human-readable description |
| user.email | actor_primary_username | STRING | User performing action |
| vendor_specific.ids.* + audit_trail.* | action_evtlog_data_fields | STRING | JSON-packed metadata |

### Validated Rule Structure

```xql
[INGEST:vendor="vendor_name", product="audit_trail", target_dataset="vendor_audit_raw", no_hit=keep]
filter
    _raw_log != null
    and _raw_log contains "vendor_identifier"
| alter
    _timestamp_ms = json_extract_scalar(_raw_log, "$.timestamp"),
    _message = json_extract_scalar(_raw_log, "$.message"),
    _event_provider = json_extract_scalar(_raw_log, "$.event.provider"),
    _event_dataset = json_extract_scalar(_raw_log, "$.event.dataset"),
    _account_id = json_extract_scalar(_raw_log, "$.vendor_specific.ids.account_id"),
    _account_name = json_extract_scalar(_raw_log, "$.vendor_specific.ids.account_name"),
    _site_id = json_extract_scalar(_raw_log, "$.vendor_specific.ids.site_id"),
    _event_action = json_extract_scalar(_raw_log, "$.vendor_specific.audit_trail.event_action"),
    _event_action_desc = json_extract_scalar(_raw_log, "$.vendor_specific.audit_trail.event_action_description"),
    _resource_type = json_extract_scalar(_raw_log, "$.vendor_specific.audit_trail.resource_type"),
    _resource_id = json_extract_scalar(_raw_log, "$.vendor_specific.audit_trail.resource_id"),
    _resource_name = json_extract_scalar(_raw_log, "$.vendor_specific.audit_trail.resource_name"),
    _event_context = json_extract_scalar(_raw_log, "$.vendor_specific.audit_trail.event_context"),
    _user_email = json_extract_scalar(_raw_log, "$.user.email")
| alter
    _msg_object_type = arrayindex(regextract(_message, "^([A-Z_]+)\s*\("), 0),
    _msg_object_id = arrayindex(regextract(_message, "^\w+\s*\((\d+)\)"), 0),
    _obj_name = coalesce(
        arrayindex(regextract(_message, "\"name\":\"([^\"]+)\""), 0),
        _resource_name)
| alter
    _time = if(_timestamp_ms != null and _timestamp_ms != "", parse_epoch(_timestamp_ms, "MILLIS"), null),
    event_id = _event_action,
    event_timestamp = to_integer(_timestamp_ms),
    actor_primary_username = _user_email,
    action_evtlog_message = _message,
    action_evtlog_description = _event_action_desc,
    action_evtlog_provider_name = _event_provider,
    action_evtlog_data_fields = to_json_string(object_create(
        "event_dataset", _event_dataset,
        "account_id", _account_id,
        "account_name", _account_name,
        "site_id", _site_id,
        "event_action", _event_action,
        "resource_type", _resource_type,
        "resource_id", _resource_id,
        "resource_name", _resource_name,
        "event_context", _event_context,
        "msg_object_type", _msg_object_type,
        "msg_object_id", _msg_object_id,
        "object_name", _obj_name));
```

### Typical Audit Event Action Types

Cloud WAF/security platforms typically emit these event action categories:
- MODIFY_POLICY, CREATE_POLICY, DELETE_POLICY
- ADD_SITE, DELETE_SITE, MODIFY_SITE
- CREATE_USER, DELETE_USER, MODIFY_USER
- LOGIN, LOGOUT
- MODIFY_CONFIGURATION
- MODIFY_RULE, CREATE_RULE, DELETE_RULE
- MODIFY_CERTIFICATE, ADD_CERTIFICATE, DELETE_CERTIFICATE

All share the same JSON structure; only the action-specific field values change.
