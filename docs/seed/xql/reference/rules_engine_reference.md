# Cortex Rules Engine - Reference Documentation

## Overview

This document provides comprehensive documentation of all existing validation rules in the Cortex Rules Engine. The engine analyzes XQL (Cortex Query Language) code for both parsing rules (`[INGEST:]` blocks) and data model rules (`[MODEL:]` blocks), identifying violations, warnings, informational issues, and suggestions to improve code quality, performance, and compliance with Cortex best practices.

### Key Statistics

- **Total Rules**: 61 (59 static + 2 dynamic)
- **Error Rules**: 11 (ERR-001 to ERR-011)
- **Warning Rules**: 28 (WARN-001 to WARN-028)
- **Informational Rules**: 11 (INFO-001 to INFO-011)
- **Suggestion Rules**: 13 (SUG-001 to SUG-013; SUG-011 and SUG-012 generated dynamically from reference log field analysis)
- **Custom Check Rules**: 14 (ERR-006, ERR-007, ERR-009, ERR-010, ERR-011, WARN-010, WARN-019, WARN-020, WARN-021, WARN-022, INFO-007, INFO-010, INFO-011 use dynamic validation)

---

## Analysis Pipeline

### 1. Rule Matching Process

The `analyseCode()` function processes code by:

1. **Splitting input** into lines for per-line analysis
2. **Iterating through all rules** applicable to the rule type (parsing, modeling, or both)
3. **Custom check rules** (ERR-006, ERR-007, ERR-009, ERR-010, ERR-011, WARN-010, WARN-019, WARN-020, WARN-021, WARN-022, INFO-007, INFO-010, INFO-011) execute their `customCheck()` function which performs dynamic validation against the XDM schema (645 fields) and XQL function list (100+ functions), returning per-line violations
4. **Pattern-based rules** test their regex `pattern` against the full code
5. **Validating anti-patterns** (optional negative conditions) -- if antiPattern matches, the rule does NOT fire
6. **Building violations** with line number, rule metadata, and recommendations

### 2. Scoring System

The scoring system calculates a final quality score out of 100:

```
Score = 100 - (errors × 20 + warnings × 10 + info × 3 + suggestions × 1)
Score = max(0, calculated_value)
```

**Weighting**:
- **Error**: -20 points (critical issues that block rule functionality)
- **Warning**: -10 points (potential issues that may affect performance or data quality)
- **Info**: -3 points (good-to-know suggestions for improvement)
- **Suggestion**: -1 point (optional enhancements and best practices)

### 3. Analysis Output

Each analysis produces:
- **violations**: Errors, warnings, and info-level findings
- **suggestions**: Best practice recommendations
- **score**: Numeric quality metric (0-100)
- **summary**: Counts of each severity level

---

## Rules by Category

### Required Fields (ERR-001 to ERR-005)

These rules ensure that parsing and modeling rules contain all mandatory declarations and assignments required for proper Cortex operation.

#### ERR-001: Missing vendor field

| Property | Value |
|----------|-------|
| **ID** | ERR-001 |
| **Name** | Missing vendor field |
| **Severity** | error |
| **Category** | Required Fields |
| **Applies To** | parsing |
| **Pattern** | `\[INGEST:` |
| **Anti-Pattern** | `vendor\s*=` |

**Description**: Parsing rules must declare a vendor using the `vendor=` parameter in the `[INGEST:]` block. This field identifies the data source and is required for data classification and compliance tracking.

**What It Catches**:
- `[INGEST: product="MyProduct" target_dataset="my_raw"]` (missing vendor)

**What It Allows**:
- `[INGEST: vendor="VendorName" product="MyProduct" target_dataset="my_raw"]` (vendor present)

**Recommendation**: Add `vendor="YOUR_VENDOR"` to the INGEST declaration

**Code Snippet**:
```
[INGEST: vendor="VendorName"
  ...
]
```

---

#### ERR-002: Missing product field

| Property | Value |
|----------|-------|
| **ID** | ERR-002 |
| **Name** | Missing product field |
| **Severity** | error |
| **Category** | Required Fields |
| **Applies To** | parsing |
| **Pattern** | `\[INGEST:` |
| **Anti-Pattern** | `product\s*=` |

**Description**: Parsing rules must declare a product using the `product=` parameter in the `[INGEST:]` block. This field identifies the specific product or solution from the vendor.

**What It Catches**:
- `[INGEST: vendor="VendorName" target_dataset="my_raw"]` (missing product)

**What It Allows**:
- `[INGEST: vendor="VendorName" product="ProductName" target_dataset="my_raw"]` (product present)

**Recommendation**: Add `product="YOUR_PRODUCT"` to the INGEST declaration

**Code Snippet**:
```
[INGEST: vendor="VendorName" product="ProductName"
  ...
]
```

---

#### ERR-003: Missing target dataset

| Property | Value |
|----------|-------|
| **ID** | ERR-003 |
| **Name** | Missing target dataset |
| **Severity** | error |
| **Category** | Required Fields |
| **Applies To** | parsing |
| **Pattern** | `\[INGEST:` |
| **Anti-Pattern** | `target_dataset\s*=` |

**Description**: Parsing rules must specify where raw events are stored using the `target_dataset=` parameter in the `[INGEST:]` block. This dataset receives the parsed raw events.

**What It Catches**:
- `[INGEST: vendor="VendorName" product="ProductName"]` (missing target_dataset)

**What It Allows**:
- `[INGEST: vendor="VendorName" product="ProductName" target_dataset="vendor_product_raw"]` (target_dataset present)

**Recommendation**: Add `target_dataset="vendor_product_raw"` to the INGEST declaration

**Code Snippet**:
```
[INGEST: vendor="VendorName" product="ProductName" target_dataset="vendor_product_raw"
  ...
]
```

---

#### ERR-004: Missing dataset in model rule

| Property | Value |
|----------|-------|
| **ID** | ERR-004 |
| **Name** | Missing dataset in model rule |
| **Severity** | error |
| **Category** | Required Fields |
| **Applies To** | modeling |
| **Pattern** | `\[MODEL:` |
| **Anti-Pattern** | `dataset\s*=` |

**Description**: Data model rules must specify the source dataset using the `dataset=` parameter in the `[MODEL:]` block. This identifies which dataset the mapping applies to.

**What It Catches**:
- `[MODEL: filter type = "Login"]` (missing dataset)

**What It Allows**:
- `[MODEL: dataset=vendor_product_raw]` (dataset present)

**Recommendation**: Add `dataset=vendor_product_raw` to the MODEL declaration

**Code Snippet**:
```
[MODEL: dataset=vendor_product_raw
  ...
]
```

---

#### ERR-005: Missing timestamp handling

| Property | Value |
|----------|-------|
| **ID** | ERR-005 |
| **Name** | Missing timestamp handling |
| **Severity** | error |
| **Category** | Required Fields |
| **Applies To** | parsing |
| **Pattern** | `\[INGEST:` |
| **Anti-Pattern** | `_time\s*=` |

**Description**: Parsing rules must assign a timestamp to the `_time` field. Events without proper timestamps cannot be indexed correctly and will not appear in query results.

**What It Catches**:
- `[INGEST: vendor="VendorName" product="ProductName" target_dataset="my_raw"]` (missing _time assignment)

**What It Allows**:
- `[INGEST: ...] _time = to_timestamp(timestamp_str, "%Y-%m-%dT%H:%M:%S")` (_time assigned)

**Recommendation**: Add `_time` assignment using `to_timestamp()` or `timestamp_seconds()`

**Code Snippet**:
```
_time = to_timestamp(timestamp_str, "%Y-%m-%dT%H:%M:%S")
```

---

### Best Practices (WARN-001 to WARN-007, SUG-001 to SUG-005)

These rules promote code quality, performance optimization, and adherence to Cortex best practices.

#### WARN-001: Overly broad regex pattern

| Property | Value |
|----------|-------|
| **ID** | WARN-001 |
| **Name** | Overly broad regex pattern |
| **Severity** | warning |
| **Category** | Performance |
| **Applies To** | both |
| **Pattern** | `regextract\([^)]*"\.\*"` |

**Description**: Using `.*` in `regextract()` can be inefficient, cause excessive backtracking, and match unintended content. More specific patterns improve performance and accuracy.

**What It Catches**:
- `regextract(message, ".*error.*")` (uses .*)
- `| alter my_field = regextract(raw_data, "prefix.*suffix")`

**What It Allows**:
- `regextract(message, "error:\s*(\d+)")` (specific pattern)
- `regextract(message, "[Ee]rror:\s*(.+)")` (bounded pattern)

**Recommendation**: Use a more specific regex pattern to improve performance and accuracy

**Code Snippet**:
```
regextract(message, "error:\s+(\w+)")
```

---

#### WARN-002: Possible missing null check

| Property | Value |
|----------|-------|
| **ID** | WARN-002 |
| **Name** | Possible missing null check |
| **Severity** | warning |
| **Category** | Data Quality |
| **Applies To** | modeling |
| **Pattern** | `xdm\.\w+[\w.]*\s*=\s*(?!coalesce\|if\()\w+(?!\s*!=\s*null)` |
| **Anti-Pattern** | `coalesce\|!= null` |

**Description**: Direct assignments of source fields to XDM fields without null handling can propagate null values. If the source field is null, the entire XDM field becomes null, potentially breaking downstream analytics.

**What It Catches**:
- `xdm.source.ipv4 = src_ip` (no null check; if src_ip is null, xdm.source.ipv4 becomes null)

**What It Allows**:
- `xdm.source.ipv4 = coalesce(src_ip, "0.0.0.0")`
- `xdm.source.ipv4 = if(src_ip != null, src_ip, "unknown")`

**Recommendation**: Consider wrapping in `coalesce()` or adding a null check with `if()`

**Code Snippet**:
```
xdm.source.ipv4 = coalesce(src_ip, "0.0.0.0")
```

---

#### WARN-003: Parsing rule used for field mapping

| Property | Value |
|----------|-------|
| **ID** | WARN-003 |
| **Name** | Parsing rule used for field mapping |
| **Severity** | warning |
| **Category** | Best Practices |
| **Applies To** | parsing |
| **Pattern** | `\[INGEST:[\s\S]*xdm\.` |

**Description**: XDM field mapping should not occur in parsing rules (`[INGEST:]`). Parsing rules should focus on extracting and normalizing raw data. Data model rules (`[MODEL:]`) are responsible for mapping to XDM fields, ensuring clear separation of concerns.

**What It Catches**:
- `[INGEST: ...] xdm.source.ipv4 = src_ip`

**What It Allows**:
- Separate `[INGEST:]` for parsing: `src_ip = regextract(message, "...")`
- Separate `[MODEL:]` for mapping: `xdm.source.ipv4 = src_ip`

**Recommendation**: Move XDM field assignments to a separate `[MODEL:]` data model rule

**Code Snippet**:
```
[MODEL: dataset="vendor_product_raw"]
xdm.source.ipv4 = src_ip
```

---

#### WARN-004: Hardcoded IP address

| Property | Value |
|----------|-------|
| **ID** | WARN-004 |
| **Name** | Hardcoded IP address |
| **Severity** | warning |
| **Category** | Best Practices |
| **Applies To** | both |
| **Pattern** | `(?:filter\|alter).*"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"` |

**Description**: Hardcoded IP addresses reduce rule portability and make maintenance harder. Rules with hardcoded values must be modified for different deployments or network environments.

**What It Catches**:
- `filter src_ip = "192.168.1.1"`
- `alter allowed_ips = ["10.0.0.1", "10.0.0.2"]`

**What It Allows**:
- `filter incidr(src_ip, "192.168.0.0/16")`
- Rule parameters or environment variables for IP ranges

**Recommendation**: Consider using `incidr()` for IP range checks or variables for specific IPs

**Code Snippet**:
```
filter incidr(src_ip, "10.0.0.0/8")
```

---

#### WARN-005: Using json_extract for scalar values

| Property | Value |
|----------|-------|
| **ID** | WARN-005 |
| **Name** | Using json_extract for scalar values |
| **Severity** | warning |
| **Category** | Performance |
| **Applies To** | both |
| **Pattern** | `json_extract\s*\(` |
| **Anti-Pattern** | `json_extract_scalar\|json_extract_array` |

**Description**: `json_extract()` returns an object representation. For extracting single scalar values, `json_extract_scalar()` is more efficient and returns the value directly without object overhead.

**What It Catches**:
- `alter username = json_extract(user_obj, "$.name")`

**What It Allows**:
- `alter username = json_extract_scalar(user_obj, "$.name")`
- `alter roles = json_extract_array(user_obj, "$.roles")`

**Recommendation**: Replace `json_extract()` with `json_extract_scalar()` when extracting single values

**Code Snippet**:
```
json_extract_scalar(field, "$.path")
```

---

#### WARN-006: XQL schema fields in data model rules should be mapped to XDM

| Property | Value |
|----------|-------|
| **ID** | WARN-006 |
| **Name** | XQL schema fields in data model rules should be mapped to XDM |
| **Severity** | warning |
| **Category** | Best Practices |
| **Applies To** | modeling |
| **Pattern** | `\[MODEL:[\s\S]*(?:action_local_ip\|action_remote_ip\|actor_process_image_name\|actor_primary_username\|action_file_path\|action_protocol\|agent_hostname\|event_timestamp\|action_total_upload\|action_total_download)\b` |
| **Anti-Pattern** | `xdm\.\w+[\w.]*\s*=\s*(?:action_local_ip\|action_remote_ip\|actor_process_image_name\|actor_primary_username\|action_file_path\|action_protocol\|agent_hostname\|event_timestamp)` |

**Description**: When XQL schema fields (raw `xdr_data` fields) appear in data model rules but are not mapped to XDM, they remain unmapped. These fields should be explicitly assigned to their corresponding XDM paths to ensure data reaches the normalized schema.

**What It Catches**:
- `[MODEL: ...] filter action_local_ip = "10.0.0.1"` (field present but not mapped to XDM)

**What It Allows**:
- `[MODEL: ...] xdm.source.ipv4 = action_local_ip` (explicitly mapped)

**Recommendation**: Map XQL schema fields to XDM equivalents

**Code Snippet**:
```
xdm.source.ipv4 = action_local_ip,
xdm.source.process.name = actor_process_image_name
```

---

#### WARN-007: Missing xdm.observer.product mapping

| Property | Value |
|----------|-------|
| **ID** | WARN-007 |
| **Name** | Missing xdm.observer.product mapping |
| **Severity** | warning |
| **Category** | Data Quality |
| **Applies To** | modeling |
| **Pattern** | `\[MODEL:` |
| **Anti-Pattern** | `xdm\.observer\.product\s*=` |

**Description**: The `xdm.observer.product` field identifies the source product and is critical for SIEM normalization and correlation. Data model rules should always set this field to enable proper asset identification and event correlation.

**What It Catches**:
- `[MODEL: dataset="vendor_product_raw"] xdm.source.ipv4 = src_ip` (observer.product not set)

**What It Allows**:
- `[MODEL: dataset="vendor_product_raw"] xdm.observer.product = product` (observer.product set)

**Recommendation**: Add `xdm.observer.product = product` to identify the source product

**Code Snippet**:
```
xdm.observer.product = product
```

---

#### SUG-001: Use incidr() for IP range checks

| Property | Value |
|----------|-------|
| **ID** | SUG-001 |
| **Name** | Use incidr() for IP range checks |
| **Severity** | suggestion |
| **Category** | Best Practices |
| **Applies To** | both |
| **Pattern** | `~=\s*"[\d\\.\*]+"` |

**Description**: Regex-based IP matching (using `~=`) is less reliable and less efficient than the dedicated `incidr()` function. `incidr()` properly handles CIDR notation, octet ranges, and wildcards with better performance.

**What It Catches**:
- `filter src_ip ~= "192\.168\.\*\.\*"` (regex IP matching)

**What It Allows**:
- `filter incidr(src_ip, "192.168.0.0/16")` (incidr function)

**Recommendation**: Replace regex IP matching with `incidr(ip_field, "cidr_range")`

**Code Snippet**:
```
incidr(src_ip, "10.0.0.0/8")
```

---

#### SUG-002: Field naming convention

| Property | Value |
|----------|-------|
| **ID** | SUG-002 |
| **Name** | Field naming convention |
| **Severity** | suggestion |
| **Category** | Best Practices |
| **Applies To** | both |
| **Pattern** | `alter\s+\w*[A-Z]\w*\s*=` |

**Description**: Field names should follow snake_case convention (lowercase with underscores) for consistency with Cortex standards. This improves readability and maintains uniformity across rules.

**What It Catches**:
- `| alter myField = extract(data, "...")`
- `| alter userId = actor_primary_username`

**What It Allows**:
- `| alter my_field = extract(data, "...")`
- `| alter user_id = actor_primary_username`

**Recommendation**: Rename fields to use snake_case for consistency

**Code Snippet**:
```
alter my_field = extract(data, "...")
```

---

#### SUG-003: Consider lowercase() for case-insensitive matching

| Property | Value |
|----------|-------|
| **ID** | SUG-003 |
| **Name** | Consider lowercase() for case-insensitive matching |
| **Severity** | suggestion |
| **Category** | Best Practices |
| **Applies To** | both |
| **Pattern** | `filter\s+\w+\s*(?:=\|contains)\s*"[^"]*[A-Z][^"]*"` |

**Description**: String comparisons with mixed-case values are case-sensitive by default. For case-insensitive matching, normalize values using `lowercase()` to ensure consistent matching regardless of input case.

**What It Catches**:
- `filter action = "Allow"` (exact case match)
- `filter message contains "Error"`

**What It Allows**:
- `filter lowercase(action) = "allow"` (case-insensitive)

**Recommendation**: Use `lowercase(field)` for case-insensitive comparisons

**Code Snippet**:
```
filter lowercase(action) = "allow"
```

---

#### SUG-004: Use XDM_CONST for standardised values

| Property | Value |
|----------|-------|
| **ID** | SUG-004 |
| **Name** | Use XDM_CONST for standardised values |
| **Severity** | suggestion |
| **Category** | Best Practices |
| **Applies To** | modeling |
| **Pattern** | `xdm\.event\.(?:type\|outcome)\s*=\s*"(?:NETWORK\|AUTH\|FILE\|PROCESS\|SUCCESS\|FAILURE)"` |

**Description**: Using `XDM_CONST` enums instead of string literals for standardized XDM values ensures forward compatibility. If XDM value definitions change, code using constants updates automatically.

**What It Catches**:
- `xdm.event.type = "NETWORK"`
- `xdm.event.outcome = "SUCCESS"`

**What It Allows**:
- `xdm.event.type = XDM_CONST.EVENT_TYPE_NETWORK`
- `xdm.event.outcome = XDM_CONST.OUTCOME_SUCCESS`

**Recommendation**: Replace string literals with XDM_CONST values

**Code Snippet**:
```
xdm.event.type = XDM_CONST.EVENT_TYPE_NETWORK,
xdm.event.outcome = XDM_CONST.OUTCOME_SUCCESS
```

---

#### SUG-005: Consider incidr6() alongside incidr() for dual-stack

| Property | Value |
|----------|-------|
| **ID** | SUG-005 |
| **Name** | Consider incidr6() alongside incidr() for dual-stack |
| **Severity** | suggestion |
| **Category** | Best Practices |
| **Applies To** | both |
| **Pattern** | `incidr\s*\(` |
| **Anti-Pattern** | `incidr6\s*\(` |

**Description**: In dual-stack IPv4/IPv6 environments, rules using only `incidr()` (IPv4) may miss IPv6 addresses. Including `incidr6()` checks ensures comprehensive IP range validation across both protocols.

**What It Catches**:
- `filter incidr(src_ip, "10.0.0.0/8")` (only IPv4 check)

**What It Allows**:
- `filter if(is_ipv4(ip), incidr(ip, "10.0.0.0/8"), incidr6(ip, "fd00::/8"))`

**Recommendation**: Add `incidr6()` checks alongside `incidr()` to cover IPv6 addresses

**Code Snippet**:
```
if(is_ipv4(ip), incidr(ip, "10.0.0.0/8"), incidr6(ip, "fd00::/8"))
```

---

### Data Quality (INFO-001 to INFO-003)

These rules recommend improvements for better data quality and analysis capabilities.

#### INFO-001: Consider coalesce for fallback values

| Property | Value |
|----------|-------|
| **ID** | INFO-001 |
| **Name** | Consider coalesce for fallback values |
| **Severity** | info |
| **Category** | Best Practices |
| **Applies To** | both |
| **Pattern** | `if\s*\(\s*\w+\s*!=\s*null\s*,\s*\w+\s*,` |

**Description**: A common pattern using `if()` to provide fallback values can be simplified and made more readable using the `coalesce()` function, which returns the first non-null value from its arguments.

**What It Catches**:
- `if(src_ip != null, src_ip, "unknown")`

**What It Allows**:
- `coalesce(src_ip, "unknown")`

**Recommendation**: Use `coalesce(field, fallback)` instead of if-statement fallback pattern

**Code Snippet**:
```
coalesce(src_ip, "0.0.0.0")
```

---

#### INFO-002: Event type not set

| Property | Value |
|----------|-------|
| **ID** | INFO-002 |
| **Name** | Event type not set |
| **Severity** | info |
| **Category** | Data Quality |
| **Applies To** | modeling |
| **Pattern** | `\[MODEL:` |
| **Anti-Pattern** | `xdm\.event\.type\s*=` |

**Description**: Setting `xdm.event.type` improves analytics, correlation, and filtering capabilities. Without a type, events cannot be easily categorized by behavior (network activity, authentication, file operations, etc.).

**What It Catches**:
- `[MODEL: dataset="vendor_product_raw"] xdm.source.ipv4 = src_ip` (event type not set)

**What It Allows**:
- `[MODEL: dataset="vendor_product_raw"] xdm.event.type = "NETWORK"` (event type set)

**Recommendation**: Add `xdm.event.type = "NETWORK"` (or AUTH, FILE, PROCESS, etc.)

**Code Snippet**:
```
xdm.event.type = "NETWORK"
```

---

#### INFO-003: Event outcome not set

| Property | Value |
|----------|-------|
| **ID** | INFO-003 |
| **Name** | Event outcome not set |
| **Severity** | info |
| **Category** | Data Quality |
| **Applies To** | modeling |
| **Pattern** | `\[MODEL:` |
| **Anti-Pattern** | `xdm\.event\.outcome\s*=` |

**Description**: The `xdm.event.outcome` field is important for success/failure analysis. It enables SIEM analysts to quickly identify failed attempts, security incidents, and operational issues.

**What It Catches**:
- `[MODEL: dataset="vendor_product_raw"]` (outcome not set)

**What It Allows**:
- `[MODEL: dataset="vendor_product_raw"] xdm.event.outcome = if(action = "allow", "SUCCESS", "FAILURE")`

**Recommendation**: Add `xdm.event.outcome` using `if()` to map vendor action to SUCCESS/FAILURE

**Code Snippet**:
```
xdm.event.outcome = if(action = "allow", "SUCCESS", "FAILURE")
```

---

## Summary Table

| ID | Name | Severity | Applies To | Category |
|---|---|---|---|---|
| ERR-001 | Missing vendor field | error | parsing | Required Fields |
| ERR-002 | Missing product field | error | parsing | Required Fields |
| ERR-003 | Missing target dataset | error | parsing | Required Fields |
| ERR-004 | Missing dataset in model rule | error | modeling | Required Fields |
| ERR-005 | Missing timestamp handling | error | parsing | Required Fields |
| WARN-001 | Overly broad regex pattern | warning | both | Performance |
| WARN-002 | Possible missing null check | warning | modeling | Data Quality |
| WARN-003 | Parsing rule used for field mapping | warning | parsing | Best Practices |
| WARN-004 | Hardcoded IP address | warning | both | Best Practices |
| WARN-005 | Using json_extract for scalar values | warning | both | Performance |
| WARN-006 | XQL schema fields not mapped to XDM | warning | modeling | Best Practices |
| WARN-007 | Missing xdm.observer.product mapping | warning | modeling | Data Quality |
| INFO-001 | Consider coalesce for fallback values | info | both | Best Practices |
| INFO-002 | Event type not set | info | modeling | Data Quality |
| INFO-003 | Event outcome not set | info | modeling | Data Quality |
| SUG-001 | Use incidr() for IP range checks | suggestion | both | Best Practices |
| SUG-002 | Field naming convention | suggestion | both | Best Practices |
| SUG-003 | Consider lowercase() for case-insensitive matching | suggestion | both | Best Practices |
| SUG-004 | Use XDM_CONST for standardised values | suggestion | modeling | Best Practices |
| SUG-005 | Consider incidr6() alongside incidr() | suggestion | both | Best Practices |

---

## Usage Examples

### Example 1: Parsing Rule with Multiple Violations

```xql
[INGEST: vendor="CiscoASA" product="ASA_FW"
  filter type = "connection"
  | alter src_ip = regextract(message, "from (.*) to"),
          dst_ip = regextract(message, "to ([0-9.]+).*denied"),
          timestamp_str = regextract(message, "^(\d+-\d+-\d+ \d+:\d+:\d+)")
  | xdm.source.ipv4 = src_ip
]
```

**Violations Found**:
- **ERR-003**: Missing `target_dataset=` parameter
- **ERR-005**: Missing `_time` assignment
- **WARN-001**: Overly broad regex pattern in `dst_ip` extraction
- **WARN-003**: XDM field assignment in parsing rule
- **INFO-001**: Null check could use coalesce

### Example 2: Data Model Rule Best Practices

```xql
[MODEL: dataset="ciscoasa_fw_raw"
  | alter src_ip = regextract(message, "from ([\d.]+)"),
          action = lowercase(regextract(message, "(allowed|denied)"))
  | xdm.source.ipv4 = coalesce(src_ip, "0.0.0.0"),
    xdm.target.ipv4 = dst_ip,
    xdm.observer.product = product,
    xdm.event.type = "NETWORK",
    xdm.event.outcome = if(action = "allowed", "SUCCESS", "FAILURE"),
    xdm.event.description = message
  | fields - *tmp
]
```

**Violations Found**:
- **SUG-004**: Consider using XDM_CONST for "SUCCESS"/"FAILURE"

---

## Integration with IDE

The rules engine is integrated into the Cortex IDE with the following features:

1. **Real-time Analysis**: Rules are evaluated as users type
2. **Color-coded Severity**: Errors (red), warnings (yellow), info (blue), suggestions (gray)
3. **Line Numbers**: Violations include the source line for easy navigation
4. **Recommendations**: Each violation includes actionable guidance
5. **Score Display**: Quality score updates dynamically
6. **Filtering**: Users can filter violations by severity or category

---

## Notes for Rule Extensions

When adding new rules to the validation engine:

1. **Unique IDs**: Follow the pattern `[SEVERITY]-[NUMBER]` (e.g., ERR-006, WARN-008)
2. **Clear Names**: Use concise, descriptive names
3. **Complete Documentation**: Include pattern, anti-pattern, what it catches, and examples
4. **Testing**: Validate against both positive and negative test cases
5. **Performance**: Test regex patterns for performance with large files
6. **Safety**: Ensure new rules don't produce false positives on production code

---

## Related Documentation

- `server/data/rules-engine.ts`: Rules implementation
- `server/data/xdm-schema.ts`: XDM field definitions (645 fields)
- `server/data/xql-functions.ts`: XQL function reference
- `PRIVATE_DOCS/all_modeling_rules.txt`: Production data model rules
- `PRIVATE_DOCS/all_parsing_rules.txt`: Production parsing rules

---

## New Rules (ERR-006 to SUG-010) -- Added March 2026

### ERR-006: Invalid XDM category
- **Severity**: error | **Applies To**: modeling | **Type**: customCheck
- **Logic**: Scans for `xdm.<category>.<field>` patterns (3+ segments) and validates the category segment against the 12 known XDM categories: alert, auth, database, email, event, intermediate, logon, network, observer, source, target, session
- **Safety**: Only checks 3+ segment paths to avoid flagging top-level fields like `xdm.session_context_id`; strips inline comments before matching
- **Example violation**: `xdm.sorce.ipv4 = ip` (typo: "sorce" instead of "source")

### ERR-007: Unknown XQL function
- **Severity**: error | **Applies To**: both | **Type**: customCheck
- **Logic**: Matches `word(` patterns and validates against the known function list (100+ functions + 22 stages). Excludes: tmp_ prefixed names, underscore-prefixed identifiers, content inside string literals, content after // comments, arrow notation (->)
- **Safety**: Validated against 40 production rule blocks with zero false positives
- **Example violation**: `| alter x = regextrcat(field, "pattern")` (typo: "regextrcat" instead of "regextract")

### ERR-008: Invalid JSON path with @ prefix in json_extract_scalar
- **Severity**: error | **Applies To**: both
- **Pattern**: `json_extract_scalar(` with a path containing `$.@` (e.g. `"$.@timestamp"`)
- **AntiPattern**: Path uses bracket notation `$['` (e.g. `"$['@timestamp']"`)
- **What it catches**: JSON paths using dot notation for keys containing special characters like `@`. The `$.@timestamp` syntax fails at runtime in Cortex. Keys with special characters must use bracket notation.
- **Example violation**: `json_extract_scalar(_raw_log, "$.@timestamp")`
- **Correct usage**: `json_extract_scalar(_raw_log, "$['@timestamp']")`

### ERR-009: Missing terminal semicolon
- **Severity**: error | **Applies To**: both | **Type**: customCheck
- **What it catches**: Rule blocks (`[MODEL:]` or `[INGEST:]`) that do not end with a terminal semicolon (`;`). The Cortex IDE rejects rules without a semicolon at the end of the block. The check finds each rule block header, extracts the block content up to the next header (or end of file), trims trailing whitespace, and verifies the block ends with `;`.
- **Example violation**: `xdm.event.id = event_id` (no semicolon)
- **Correct usage**: `xdm.event.id = event_id;`
- **Message**: "Rule block starting at line N does not end with a terminal semicolon (;). The Cortex IDE will reject this rule"
- **Recommendation**: Add a semicolon (;) at the very end of the rule block, after the last field assignment

### ERR-010: Trailing comma on final assignment
- **Severity**: error | **Applies To**: both | **Type**: customCheck
- **What it catches**: A trailing comma before the terminal semicolon in a rule block. The pattern `,\s*;` (comma, optional whitespace, semicolon) causes a parse error in the Cortex IDE. This commonly occurs when rearranging or deleting the last field assignment.
- **Example violation**: `xdm.event.id = event_id,\n;`
- **Correct usage**: `xdm.event.id = event_id;`
- **Message**: "Trailing comma detected before the terminal semicolon. This causes a parse error in the Cortex IDE"
- **Recommendation**: Remove the trailing comma before the semicolon on the final assignment line

### ERR-011: Self-referencing XDM field in assignment
- **Severity**: error | **Applies To**: modeling | **Type**: customCheck
- **What it catches**: XDM field assignments where the same field appears on both sides of the `=` operator (e.g. `xdm.target.ipv4 = coalesce(xdm.target.ipv4, _fallback)`). In MODEL rules, XDM fields have no value during assignment, so reading them on the right-hand side is invalid and produces undefined behaviour.
- **Detection logic**: For each non-comment line, extracts the LHS `xdm.*` field and any `xdm.*` reference on the RHS. Fires if they are identical.
- **Example violation**: `xdm.target.ipv4 = coalesce(xdm.target.ipv4, _client_ip)`
- **Correct usage**: `xdm.target.ipv4 = _client_ip`
- **Message**: "'xdm.target.ipv4' references itself on the right-hand side of its own assignment. In MODEL rules, XDM fields cannot be read during assignment"
- **Recommendation**: Use an intermediary _temp variable or assign the fallback value directly instead of wrapping in coalesce() with the same XDM field
- **Origin**: Discovered during Imperva ATO rule development (2026-03-11). The `coalesce(xdm.target.ipv4, _client_ip)` pattern caused "unknown field" errors because the field had no value to coalesce with.

### WARN-008: Missing fields cleanup for tmp_ variables
- **Severity**: warning | **Applies To**: both
- **Pattern**: `/\btmp_\w+/` without antiPattern `/fields\s+-\s*tmp/`
- **What it catches**: Rules that create temporary variables (tmp_*) but forget to clean them up

### WARN-009: Missing no_hit directive
- **Severity**: warning | **Applies To**: parsing
- **Pattern**: `[INGEST:` without `no_hit=drop` or `no_hit=keep`
- **What it catches**: Parsing rules that do not specify what happens to unmatched events

### WARN-010: Unresolved XDM field path
- **Severity**: warning | **Applies To**: modeling | **Type**: customCheck
- **Logic**: Validates `xdm.*` field paths (3+ segments) against the 645-field schema. Accepts any path that starts with a known field prefix (to handle sub-fields like `.issuer` under `xdm.network.tls.server_certificate`)
- **Safety**: 39 production fields were added to the schema first to prevent false positives
- **Example violation**: `xdm.source.procces.name = pname` (typo: "procces" instead of "process")

### WARN-011: Missing xdm.observer.vendor mapping
- **Severity**: warning | **Applies To**: modeling
- **Pattern**: `[MODEL:` without `xdm.observer.vendor =`
- **What it catches**: Data model rules that do not set the observer vendor field

### INFO-004: Missing event description
- **Severity**: info | **Applies To**: modeling
- **Pattern**: `[MODEL:` without `xdm.event.description =`
- **What it catches**: Data model rules without a human-readable event description

### INFO-005: Consider format_timestamp for year in RFC 3164
- **Severity**: info | **Applies To**: parsing
- **Pattern**: RFC 3164 timestamp patterns (`%b %d %H:%M:%S`) without `format_timestamp` or `%Y`
- **What it catches**: Syslog timestamps that lack year information

### INFO-006: Missing fields cleanup
- **Severity**: info | **Applies To**: both
- **Pattern**: `| alter` with assignments but no `| fields -` statement
- **What it catches**: Rules that create intermediary fields but never clean them up

### SUG-006: Consider arraydistinct after arrayconcat
- **Severity**: suggestion | **Applies To**: both
- **Pattern**: `arrayconcat(` without `arraydistinct(`
- **What it catches**: Merged arrays that may contain duplicate values

### SUG-007: Consider arraystring for array-to-string conversion
- **Severity**: suggestion | **Applies To**: both
- **Pattern**: `concat(` used on `regextract` results
- **What it catches**: String concatenation on array results where arraystring() would be cleaner

### SUG-008: Use XDM_CONST for outcome values
- **Severity**: suggestion | **Applies To**: modeling
- **Pattern**: `xdm.event.outcome = "SUCCESS"` or `"FAILURE"` as string literals
- **What it catches**: Hardcoded outcome strings that should use XDM_CONST enums

### SUG-009: Consider %E*S for variable timestamp precision
- **Severity**: suggestion | **Applies To**: parsing
- **Pattern**: `%E3S` or `%E6S` without `%E*S`
- **What it catches**: Fixed-precision timestamp parsing where variable precision would be more robust

### SUG-010: Consecutive alter stages could be combined
- **Severity**: suggestion | **Applies To**: both
- **Pattern**: `| alter` followed by another `| alter` on consecutive lines
- **What it catches**: Multiple alter stages that could be merged into one for readability

### WARN-012: MODEL block in parsing mode
- **Severity**: warning | **Applies To**: parsing
- **Pattern**: `[MODEL:` detected while the IDE is in Parsing Rule mode
- **What it catches**: Users writing data model rules while the IDE is set to analyse parsing rules. The wrong mode means modelling-specific rules (observer.vendor, event.type checks, etc.) will not fire.
- **Example violation**: Typing `[MODEL: dataset="test_raw"]` with the mode toggle set to "Parsing Rule"

### WARN-013: INGEST block in data model mode
- **Severity**: warning | **Applies To**: modeling
- **Pattern**: `[INGEST:` detected while the IDE is in Data Model Rule mode
- **What it catches**: Users writing parsing rules while the IDE is set to analyse data model rules. The wrong mode means parsing-specific rules (vendor, product, _time checks) will not fire.
- **Example violation**: Typing `[INGEST: vendor="Cisco"]` with the mode toggle set to "Data Model Rule"

### WARN-014: Quoted XDM_CONST value
- **Severity**: warning | **Applies To**: modeling
- **Pattern**: `"XDM_CONST.` — string-quoted XDM_CONST reference
- **What it catches**: XDM_CONST enum values wrapped in quotes, treating them as string literals instead of constants. This causes the value to be stored as the literal text "XDM_CONST.OUTCOME_SUCCESS" rather than the resolved enum value.
- **Example violation**: `xdm.event.outcome = "XDM_CONST.OUTCOME_SUCCESS"` (wrong — quotes make it a string literal)
- **Correct usage**: `xdm.event.outcome = XDM_CONST.OUTCOME_SUCCESS` (no quotes — treated as an enum constant)

### WARN-015: Quoted dataset name in MODEL block declaration
- **Severity**: warning | **Applies To**: modeling
- **Pattern**: `dataset="..."` in `[MODEL:]` block headers
- **What it catches**: Dataset names enclosed in quotes within `[MODEL:]` block declarations. MODEL rules expect unquoted dataset identifiers in block headers.
- **Important distinction**: This rule does NOT apply to INGEST rules. INGEST rules correctly use quoted values for vendor, product, and target_dataset (e.g. `[INGEST:vendor="Cisco", product="ASA", target_dataset="cisco_asa_raw", no_hit=keep]`).
- **Example violation**: `[MODEL: dataset="vendor_product_raw"]` (wrong -- dataset name is quoted in MODEL block)
- **Correct usage**: `[MODEL: dataset=vendor_product_raw]` (no quotes around the dataset name in MODEL blocks)

### INFO-007: Unused temporary field
- **Severity**: info | **Applies To**: both
- **Type**: customCheck (multi-line cross-referencing)
- **What it catches**: Temporary fields (variables starting with `_`) that are extracted in an `alter` block but never referenced in any XDM field assignment (`xdm.* = ... _varname ...`). These unused extractions add processing overhead without contributing to the data model.
- **Detection logic**:
  1. Scans all lines for `_varname = ...` definitions (left-hand side assignments with underscore-prefixed names)
  2. Excludes reserved system fields (`_time`, `_raw_log`)
  3. Filters out false positives where `_varname` appears as part of an `xdm.*` field path (e.g. `xdm.target.resource_before`)
  4. Collects all XDM assignment lines (`xdm.* = ...`)
  5. Checks if each defined temp variable appears anywhere in the XDM assignment right-hand sides
  6. Reports each unreferenced variable once (first occurrence)
- **Example violation**: `_unused_field = json_extract_scalar(msg, "$.path")` where `_unused_field` is never used in any `xdm.* =` line
- **Fix**: Either map the field to an appropriate XDM field, or remove the extraction entirely
- **Message**: "Temporary field '_varname' is extracted but never assigned to an XDM field. Remove it or map it to an appropriate XDM field"

### WARN-016: Unguarded parse_epoch or parse_timestamp
- **Severity**: warning | **Applies To**: both
- **Pattern**: `_time = parse_epoch(` or `_time = parse_timestamp(` without an `if(` guard
- **What it catches**: Calls to `parse_epoch` or `parse_timestamp` that are not wrapped in a null/empty check. If the input field is null or an empty string (e.g. when `json_extract_scalar` returns `""` for a missing field), `parse_epoch` throws a runtime error: `format string '' contains no format elements`.
- **Example violation**: `_time = parse_epoch(_timestamp_ms, "MILLIS")` (crashes if `_timestamp_ms` is null or empty)
- **Correct usage**: `_time = if(_timestamp_ms != null and _timestamp_ms != "", parse_epoch(_timestamp_ms, "MILLIS"), null)`
- **AntiPattern**: The rule does NOT fire if the assignment uses `if(` as a guard (e.g. `_time = if(...)`)

### WARN-017: Leading pipe before first stage in MODEL rule
- **Severity**: warning | **Applies To**: modeling
- **Pattern**: `[MODEL:` header followed by `\n| ` (pipe as first non-whitespace on the next line)
- **What it catches**: MODEL rules where the first stage after the block header has a leading pipe character. In Cortex, the first stage after a block header should NOT have a pipe prefix. Only subsequent stages use `| alter`, `| filter` etc.
- **Example violation**: `[MODEL: dataset=vendor_raw]\n| alter\n    xdm.event.id = event_id;`
- **Correct usage**: `[MODEL: dataset=vendor_raw]\nalter\n    xdm.event.id = event_id;`

### WARN-018: _time assignment in data model rule
- **Severity**: warning | **Applies To**: modeling
- **Pattern**: `_time =` assignment (not comparison or read)
- **What it catches**: MODEL rules that attempt to set _time. The _time field must only be set during INGEST (parsing) rules. The parser is responsible for setting the event timestamp; MODEL rules should only map fields to XDM.
- **Message**: "_time must only be set during INGEST (parsing) rules, not in MODEL rules. The parser is responsible for setting the event timestamp"
- **Recommendation**: Remove the _time assignment from this MODEL rule. If _time is not being set correctly, fix it in the upstream INGEST rule instead

### WARN-019: Unused intermediary fields in data model rules
- **Severity**: warning | **Applies To**: modeling | **Type**: customCheck
- **What it catches**: Non-underscore-prefixed intermediary fields created in `alter` blocks that are never referenced in any `xdm.*` assignment. The official Cortex IDE flags these as "Data Model validation error - Data Model Rules contains unused fields". This rule extends INFO-007 (which checks `_`-prefixed temporaries) to catch all intermediary fields such as `http_code`, `http_verb`, `service_runtime_details_process_pid`, etc.
- **Detection logic**:
  1. Finds all `<fieldname> =` assignments in alter blocks, excluding lines starting with `xdm.`, `tmp_`-prefixed, `_`-prefixed fields, and known XQL stage keywords
  2. For each field, checks whether it is directly referenced in an XDM assignment line
  3. Performs transitive usage analysis: if field A is used by field B, and field B is used in an XDM assignment, field A is considered transitively used
  4. Reports violations only for fields that are neither directly nor transitively used in XDM assignments
- **Example violation**: `http_code = to_integer(service_action_k8s_api_call_status_code)` -- extracted but never mapped to `xdm.network.http.response_code`
- **Correct usage**: Add `xdm.network.http.response_code = if(http_code = null, null, http_code = 200, XDM_CONST.HTTP_RSP_CODE_OK, ...)` to the XDM assignment block
- **Message**: "Intermediary field 'http_code' is extracted but never referenced in any XDM field assignment. The Cortex IDE flags this as 'Data Model Rules contains unused fields'"
- **Recommendation**: Map the field to an appropriate XDM field or remove it if not needed

### INFO-008: Empty editor -- parsing boilerplate available
- **Severity**: info | **Applies To**: parsing
- **Type**: pattern-based (empty or whitespace-only code)
- **What it catches**: An empty editor when the rule type is set to "parsing". Nudges the user to search for the "Parsing Rule Boilerplate" snippet to get started quickly.
- **Message**: "Editor is empty. Search for \"Parsing Rule Boilerplate\" in the Snippets panel to get started"
- **Recommendation**: Open the Snippets panel and search for "Parsing Rule Boilerplate" to insert a ready-made INGEST rule template

### INFO-009: Empty editor -- data model boilerplate available
- **Severity**: info | **Applies To**: modeling
- **Type**: pattern-based (empty or whitespace-only code)
- **What it catches**: An empty editor when the rule type is set to "modeling". Nudges the user to search for the "Data Model Rule Boilerplate" snippet.
- **Message**: "Editor is empty. Search for \"Data Model Rule Boilerplate\" in the Snippets panel to get started"
- **Recommendation**: Open the Snippets panel and search for "Data Model Rule Boilerplate" to insert a ready-made MODEL rule template

### SUG-011: Reference log field could map to xdr_data field (dynamic)
- **Severity**: suggestion | **Applies To**: parsing
- **Type**: dynamic (generated in /api/analyse route from reference log field analysis)
- **What it catches**: JSON fields in the pasted reference log that match common field name patterns (timestamp, IP, user, message, severity, etc.) but have no corresponding json_extract_scalar call in the current rule code. Uses the field mapping table in server/data/log-field-mappings.ts.
- **Detection logic**:
  1. Receives parsedLogFields array from frontend (path, type, sampleValue for each JSON field)
  2. Matches field names against 20 pattern groups (timestamp, IP address, username, message, severity, action, hostname, port, URL, user agent, country, status, account ID, etc.)
  3. Checks whether the field path already appears in a json_extract_scalar call in the code
  4. Generates a suggestion for each unmapped field with the recommended xdr_data target and example XQL expression
- **Message**: "Reference log field '$.path' could map to xdr_data field 'field_name'"
- **Example**: "Reference log field '$.src_ip' could map to xdr_data field 'action_remote_ip'"

### SUG-012: Unmapped reference log fields summary (dynamic)
- **Severity**: suggestion | **Applies To**: parsing
- **Type**: dynamic (generated in /api/analyse route)
- **What it catches**: Provides a count of how many reference log fields remain without json_extract_scalar mappings in the current rule.
- **Detection logic**: Counts leaf fields (non-object, non-array) from the parsed reference log that do not appear in any json_extract_scalar call in the code.
- **Message**: "N of M reference log fields have no json_extract_scalar mapping in the current rule"
- **Note**: This fires as a single summary suggestion, not per-field, to avoid noise.

---

## New Rules (WARN-020 to SUG-013) -- Added March 2026

Derived from lessons learned during the AWS GuardDuty data model rule exercise. These rules address real-world Cortex XSIAM validation failures and common pitfalls encountered when building production data model rules.

### WARN-020: String assigned to array-type XDM field
- **Severity**: warning | **Applies To**: modeling
- **Type**: customCheck (cross-references XDM schema)
- **What it catches**: Assignments to XDM fields that have `dataclass: "Array"` in the schema (22 fields including `xdm.source.user.roles`, `xdm.source.user.groups`, `xdm.source.host.ipv4_addresses`, etc.) where the right-hand side does not use an array-producing function.
- **Detection logic**: For each `xdm.*` assignment line, checks if the field path is in the `ARRAY_XDM_PATHS` set. If so, verifies the RHS contains at least one array-producing function (`arraycreate`, `arrayconcat`, `arraydistinct`, `arraymap`, `arrayfilter`, `arraypop`, `arrayrange`, `arrayresize`, `split`, `regextract`, `json_extract_array`) or an array suffix (`[]`). Fires if neither is present.
- **Message**: "'xdm.source.user.roles' expects an array but is being assigned a scalar value. The Cortex IDE will reject this with 'Expected array but received string'"
- **Origin**: Discovered when the GuardDuty rule assigned `coalesce(role_binding, instance_profile_arn)` (a string) to `xdm.source.user.roles` (an array field), causing a Cortex XSIAM validation error in production.

### WARN-021: XDM_CONST field assigned raw string
- **Severity**: warning | **Applies To**: modeling
- **Type**: customCheck (cross-references XDM schema)
- **What it catches**: Assignments to XDM fields typed as `XDM_CONST.*` (e.g. `xdm.event.outcome` expects `XDM_CONST.OUTCOME`, `xdm.source.user.identity_type` expects `XDM_CONST.IDENTITY_TYPE`) where the right-hand side is a bare string literal rather than an `XDM_CONST.*` enum.
- **Detection logic**: For each `xdm.*` assignment line, checks if the field path is in the `XDM_CONST_PATHS` map. If so, verifies the RHS contains `XDM_CONST.`, `if(`, or `coalesce(`. If the RHS is a quoted string literal and none of these are present, fires a warning.
- **Distinction from WARN-014**: WARN-014 catches quoted `XDM_CONST` references (e.g. `"XDM_CONST.OUTCOME_SUCCESS"` in quotes). WARN-021 catches a different pattern: a raw string value like `"SUCCESS"` assigned to a field that expects an XDM_CONST enum.
- **Message**: "'xdm.event.outcome' expects a XDM_CONST.OUTCOME enumeration but is assigned a raw string literal"

### WARN-022: Missing null guard on arraycreate()
- **Severity**: warning | **Applies To**: both
- **Type**: customCheck
- **What it catches**: `arraycreate(field)` calls where `field` is a bare variable (not a literal, not inside an `if()` guard). When the input variable is null at runtime, `arraycreate(null)` produces `[null]` (a single-element array containing null) rather than a proper null value, which can cause unexpected behaviour in XSIAM analytics.
- **Detection logic**: Finds `arraycreate(identifier)` patterns where the line does NOT already contain an `if(` guard. Skips literals (`"string"`, numbers, `null`, `true`, `false`).
- **Message**: "arraycreate(my_field) will produce [null] if 'my_field' is null, rather than returning null"
- **Origin**: Discovered when refactoring the GuardDuty rule to use `arraycreate()` for array-type XDM fields -- the null guard pattern `if(field != null, arraycreate(field))` was identified as essential.

### INFO-010: Arrow notation without defensive coalesce
- **Severity**: info | **Applies To**: modeling
- **Type**: customCheck
- **What it catches**: Arrow notation field access (e.g. `field -> PascalCaseProperty`) in MODEL rules where the line does NOT use `coalesce()` to provide a camelCase fallback. XSIAM parsers may output fields in either PascalCase or camelCase depending on the parser version, configuration, or vendor data format.
- **Detection logic**: For each non-comment line containing `->`, checks if the line already contains `coalesce(`. If not, looks for PascalCase property names (starting with an uppercase letter) and suggests the defensive pattern. Reports at most one violation per line.
- **Vendor-natural exemption (Task #38)**: When the LHS of `->` is itself a PascalCase identifier (e.g. `Request -> Method`, `Source -> IP`, `ThreatInfo -> Category`), the rule skips the finding. Pattern-D vendors like NovaSec CloudSentinel, ExtraHop RevealX and several Microsoft schemas emit their entire top-level column tree in PascalCase; the parser never produces a camelCase variant on these schemas, so the coalesce() suggestion is meaningless and -- unsuppressed -- it drowned out genuine INFO-010 hits on mixed-casing vendors (e.g. AWS GuardDuty `finding_resource -> AccessKeyDetails.UserName`, where the LHS is lowercase). Before this exemption the NovaSec gold rule scored 12/100 with 28 INFO-010 firings; after, it scores 96/100 with 1.
- **Message**: "Arrow notation 'Resource -> AccessKeyDetails.UserName' accesses a PascalCase property without a coalesce() fallback for camelCase"
- **Origin**: The AWS GuardDuty data model rule uses `coalesce(PascalCase, camelCase)` throughout because the XSIAM parser may output either convention. This pattern is recommended for all vendor data model rules.

### INFO-011: One-sided source/target field mapping
- **Severity**: suggestion | **Applies To**: modeling | **Type**: customCheck
- **What it catches**: MODEL rules where `xdm.source.ipv4` is mapped but `xdm.target.ipv4` is not (or vice versa), and similarly for `xdm.source.user.username` / `xdm.target.user.username`. When a payload contains only one entity of a given type, mirroring it to both sides maximises correlation coverage.
- **Detection logic**: Strips comments, then checks for the presence of source/target field pairs. Fires only when one side is mapped but the other is not. Silent when both or neither are present.
- **Checked pairs**: `ipv4` (source/target), `user.username` (source/target)
- **Message**: "xdm.source.ipv4 is mapped but xdm.target.ipv4 is not. If the payload has only one IP address, consider mirroring to both sides for correlation coverage"
- **Recommendation**: Add the missing side with the same value
- **Origin**: Discovered during Imperva ATO rule development (2026-03-11). The ATO payload has only one IP (`client.ip`) and one user (`request_user`), both mapped to source and target for full correlation coverage. See Pattern 8 (Single-Entity Mirroring) in `data_model_rule_building_guide.md`.

### SUG-013: Consider xdm.source.user.identity_type mapping
- **Severity**: suggestion | **Applies To**: modeling
- **Type**: pattern + antiPattern
- **What it catches**: Rules that map `xdm.source.user.user_type` (the raw vendor user type string) but do NOT also map `xdm.source.user.identity_type` (the normalised XDM constant). Mapping identity_type alongside user_type improves cross-vendor correlation in XSIAM since identity_type uses a standardised enumeration (MACHINE, USER, BUILTIN, VIRTUAL, UNKNOWN).
- **Detection logic**: Pattern matches `xdm.source.user.user_type =`; antiPattern matches `xdm.source.user.identity_type =`. Fires only if pattern matches but antiPattern does not.
- **Message**: "Rule maps xdm.source.user.user_type but does not map xdm.source.user.identity_type"
- **Origin**: The GuardDuty rule maps IAM UserType (Root, IAMUser, AssumedRole, etc.) to both user_type and identity_type. The identity_type mapping uses an if() chain to normalise vendor-specific types to XDM_CONST.IDENTITY_TYPE_* enums.

### WARN-023: xdm.alert.mitre_techniques may not be in the selected data model
- **Severity**: warning
- **Category**: Data Model Compatibility
- **Type**: pattern
- **What it catches**: Model rules that assign to `xdm.alert.mitre_techniques`, which is known to cause Cortex IDE internal validation errors on certain datasets (e.g. `_gc_raw` datasets). The IDE returns "There was an internal error while trying to validate mapping" rather than a clean field-level error, making the problem very difficult to diagnose without binary-search testing.
- **Detection logic**: Pattern matches `xdm.alert.mitre_techniques =`.
- **Message**: "xdm.alert.mitre_techniques is known to cause Cortex IDE internal validation errors on certain datasets"
- **Recommendation**: Verify the field is available on the target dataset before using it. `xdm.alert.mitre_tactics` is generally available and unaffected.
- **Origin**: Discovered during Trend Micro Vision One detections rule deployment to `trend_micro_vision_one_gc_raw`. Isolated via binary search across 10 progressive test versions (2026-03-09). See `data_model_rule_building_guide.md` for the full debugging methodology.

### WARN-024: xdm.target.process.integrity_level may crash Cortex IDE validator
- **Severity**: warning
- **Category**: Data Model Compatibility
- **Type**: pattern
- **What it catches**: Model rules that assign to `xdm.target.process.integrity_level` using `XDM_CONST.INTEGRITY_LEVEL_*` if() chains. This causes the same Cortex IDE "internal error" as `xdm.alert.mitre_techniques` on `_gc_raw` datasets.
- **Detection logic**: Pattern matches `xdm.target.process.integrity_level =`.
- **Message**: "xdm.target.process.integrity_level with XDM_CONST.INTEGRITY_LEVEL_* if() chains causes Cortex IDE internal validation errors on _gc_raw datasets"
- **Recommendation**: Remove this field or test it individually on your target dataset. The raw integer value can be stored in a string field as a workaround.
- **Origin**: Discovered during Trend Micro Vision One endpoint activity rule deployment. Isolated via binary search V3 -> V3A -> V3A3 (2026-03-09).

### WARN-025: xdm.session_context_id may not be in the selected data model
- **Severity**: warning
- **Category**: Data Model Compatibility
- **Type**: pattern
- **What it catches**: Model rules that assign to `xdm.session_context_id`, which is known to cause internal validation errors on `_gc_raw` datasets.
- **Detection logic**: Pattern matches `xdm.session_context_id =`.
- **Message**: "xdm.session_context_id is known to cause Cortex IDE internal validation errors on _gc_raw datasets"
- **Recommendation**: Remove it or verify availability on your target dataset.
- **Origin**: Discovered during Trend Micro Vision One endpoint activity rule deployment (2026-03-09).

### WARN-026: xdm.network.direction may not be in the selected data model
- **Severity**: warning
- **Category**: Data Model Compatibility
- **Type**: pattern
- **What it catches**: Model rules that assign to `xdm.network.direction`, which is not part of the selected data model on `_gc_raw` datasets.
- **Detection logic**: Pattern matches `xdm.network.direction =`.
- **Message**: "xdm.network.direction is not part of the selected data model on some datasets"
- **Recommendation**: Remove this field or verify availability on your target dataset.
- **Origin**: Discovered during Trend Micro Vision One detections rule deployment (2026-03-09).

### WARN-027: xdm.source.process.parent_process.* does not exist in XDM schema
- **Severity**: warning
- **Category**: Data Model Compatibility
- **Type**: pattern
- **What it catches**: Model rules that assign to any field under `xdm.source.process.parent_process.*`. These fields do not exist in the XDM schema at all and will cause Cortex IDE internal errors on ALL datasets.
- **Detection logic**: Pattern matches `xdm.source.process.parent_process.<any_path> =`.
- **Message**: "xdm.source.process.parent_process.* fields do not exist in the XDM schema and will cause Cortex IDE internal errors on ALL datasets"
- **Recommendation**: The XDM schema has no parent_process child object under source.process. Remove these assignments entirely.
- **Origin**: Discovered during Trend Micro Vision One endpoint activity rule development. Cross-referenced against xdm-schema.ts (2026-03-09).

### WARN-028: Missing xdm.event.original_event_type mapping for source filter
- **Severity**: warning
- **Category**: Data Quality
- **Type**: pattern + antiPattern
- **What it catches**: Model rules that filter on `source = "..."` but do not map `xdm.event.original_event_type` to preserve the source value in the data model.
- **Detection logic**: Pattern matches `filter ... source = "` without an `xdm.event.original_event_type =` antiPattern match.
- **Message**: "Rule filters on source but does not map xdm.event.original_event_type to preserve the source value"
- **Recommendation**: Add `xdm.event.original_event_type = source` to preserve the original log subtype. This is distinct from `xdm.event.type` which should hold a normalised category.
- **Origin**: Identified as standard practice during Trend Micro Vision One rule development (2026-03-09).

---

## New Rules (WARN-035) -- Added May 2026

### WARN-035: XDM field type mismatch
- **Severity**: warning | **Applies To**: modeling | **Type**: customCheck
- **Origin**: Task #114, Arc C. Builds on the XDM type metadata graph
  added in Task #113 (`getXdmFieldType`, `getXdmFieldEnum`, the
  `XdmTypeMeta` discriminated union). Subsumes the shape-only checks
  WARN-020 (string -> array field) and WARN-030 (array field assigned
  without arraycreate); both stay in the codebase as a safety net but
  the analyser post-pass suppresses them on lines where WARN-035
  already fires (no duplicate noise).
- **What it catches**: For every `xdm.<path> = <rhs>` assignment in a
  MODEL block, looks up the field's declared XDM type and flags:
  - **Scalar -> Array**: a scalar value (literal, scalar-returning
    function call, scalar temp) assigned to an Array-type field.
  - **Array -> Scalar**: an array temp (any name in the dataflow
    `arrayTyped` set) or a top-level array-producing function call
    assigned to a Scalar-type field, with no scalar wrapper.
  - **Enum vocabulary**: a quoted string literal assigned to a field
    whose type is `XDM_CONST.<NAME>` whose value is not one of the
    documented enum values.
  - **Scalar base mismatch**: quoted string literals assigned to
    int / float (non-numeric content), bool (not "true"/"false"),
    ipv4 (not a dotted quad), ipv6 (no colons or non-hex content);
    bare numeric / bool literals assigned to a string scalar.
- **Conservative carve-outs**:
  - Any RHS containing an `XDM_CONST.*` token is trusted (vendor
    enum reference).
  - The bare literal `null` is always allowed.
  - Opaque RHS expressions we cannot prove anything about (a bare
    identifier not in the dataflow `arrayTyped` set, or a function
    we don't model) are skipped.
  - Multi-line `if(...)` / `coalesce(...)` wrappers around
    `arraycreate()` are deferred to WARN-030's heuristic and skipped.
- **Suppression contract**: when WARN-035 fires on a line, the
  analyseCode post-pass removes any WARN-020 / WARN-030 finding on
  the same line so the user sees one canonical, type-aware finding
  instead of two shape-only ones.
- **Tests**: `server/data/rules-engine-warn035.test.ts` covers one
  positive case per category plus negative cases proving the rule
  stays silent on correctly-typed assignments, opaque variables,
  XDM_CONST references, valid enum values, valid IPv4 / numeric /
  bool literals, null, and INGEST blocks.
- **Pack baselines updated**: WARN-035 surfaces real shape mismatches
  in five vendor packs (`cisco_wsa_access_log`, `extrahop_revealx`,
  `imperva_account_takeover`, `microsoft_defender_cloud_apps_alerts`,
  `symantec_endpoint_protection`, `trend_micro_vision_one_detections`,
  `trend_micro_vision_one_endpoint_activity`). These are queued for
  fix in the packs' own refresh tasks; the multiline regression
  baseline captures the current counts so further drift is caught.

---

## Bug Fixes

### Known Functions List: `from_epoch` replaced with `parse_epoch`
- **Date**: 2026-03-01
- **Issue**: `from_epoch` was listed in `KNOWN_XQL_FUNCTIONS` but is not a valid XQL function. The correct function is `parse_epoch` (defined in xql-functions.ts). This meant ERR-007 would not fire on the invalid `from_epoch()` usage, and would incorrectly fire on the valid `parse_epoch()` usage.
- **Fix**: Replaced `"from_epoch"` with `"parse_epoch"` in the KNOWN_XQL_FUNCTIONS set in rules-engine.ts.
- **Impact**: ERR-007 now correctly validates `parse_epoch()` as a known function and flags `from_epoch()` as unknown.
