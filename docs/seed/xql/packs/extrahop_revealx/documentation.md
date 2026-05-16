# ExtraHop RevealX -- XDM Data Model Rule Documentation

Companion notes for `extrahop_revealx_xdm_model_rule.xql`.

## Anchors

`parser.xql` (in this pack) stamps two anchor columns at ingest time per
the convention in `PRIVATE_DOCS/anchor_field_design.md`. These exist for
analyst-side anchor coverage on enriched rows; the data model rule does
NOT read them (see "Backward compatibility with pre-enrichment datasets"
below for why -- Cortex compiles the rule against the dataset schema, so
a bare reference to a column absent from the schema fails to save even
inside `coalesce()`).

| Anchor | Type | Vocabulary | Purpose |
| ------ | ---- | ---------- | ------- |
| `_detection_category` | **array** of strings | ~10 values: `lateral_movement`, `command_and_control`, `exploitation`, `reconnaissance`, `actions_on_objective`, `hardening`, `caution`, `database`, `network_infrastructure`, `unknown` | Multi-valued MITRE-aligned classifier; analysts query with `arraycontains(_detection_category, "lateral_movement")` |
| `_risk_band`          | scalar string         | `LOW` (`risk_score < 30`), `MEDIUM` (30-69), `HIGH` (>=70) | Bucketed risk score for "show me only high-risk" triage filters |

`_detection_category` is the FIRST array-typed anchor in the codebase --
a deliberate doctrine deviation. The default anchor shape is scalar (a
short discriminator string with a small closed vocabulary), but a
RevealX detection can legitimately belong to several categories at
once, and any scalar projection (first element, joined string, hashed
bag) would either drop information or break column-equality. The
trade-off is paid in two places:

- **Storage:** the column is wider than a scalar would be -- still
  small in practice (at most a handful of short strings per row), but
  bigger than a single byte after dictionary encoding.
- **Query syntax:** analysts use `arraycontains(_detection_category,
  "...")` rather than `_detection_category = "..."`. Cortex still
  pushes the predicate down to the indexed column.

Both costs are small relative to the alternative (analysts re-deriving
the array from the JSON `categories` column on every query). The
doctrine in `PRIVATE_DOCS/anchor_field_design.md` is explicitly
extended here: array anchors ARE allowed when the underlying
discriminator is genuinely multi-valued. They remain rare; do not
reach for an array anchor when a scalar will do.

Sample analyst queries:

```
// Only the high-risk lateral-movement detections from the last day
dataset = extrahop_revealx_raw
| filter _risk_band = "HIGH"
       and arraycontains(_detection_category, "lateral_movement")
| filter _time > to_timestamp(subtract(to_epoch(current_time()), 86400), "SECONDS")

// All exfiltration-adjacent detections regardless of severity
dataset = extrahop_revealx_raw
| filter arraycontains(_detection_category, "actions_on_objective")
       or arraycontains(_detection_category, "command_and_control")
```

## Relationship to parser

`datamodel.xql` derives both helper values inline from the raw
`categories` and `risk_score` columns:

```
_categories_arr = categories
_risk_band      = if(_risk_score >= 70, "HIGH",
                     _risk_score >= 30, "MEDIUM",
                     _risk_score != null, "LOW")
```

The parser keeps stamping `_detection_category` and `_risk_band` for
analyst-side anchor coverage on enriched rows (see the section
"Backward compatibility with pre-enrichment datasets" below for why the
data model rule cannot read them). The MODEL drives
`xdm.alert.severity` off the four-band `_severity` derivation
(Critical/High/Medium/Low) -- `_risk_band` is the smaller three-band
string and is sunk into `xdm.alert.risks` for downstream consumers that
want the bucketed value as a separate XDM field, plus appended to
`xdm.event.description` so the SOC analyst sees the band inline. The
asymmetry is intentional: `xdm.alert.severity` is the canonical
four-band severity vocabulary; `_risk_band` (and the matching parser
anchor) is the three-band triage-filter aid.

`_time` is set by the parser from `start_time` (epoch milliseconds via
`to_timestamp(start_time, "MILLIS")`); the MODEL no longer needs to
worry about timestamp reconstruction for parser-stamped rows.

## Scope

Maps ExtraHop RevealX detection events to the Cortex XDM schema.

`_raw_log` is null for this dataset (Pattern D); events arrive as
pre-parsed top-level columns. The producer schema
(`PRIVATE_DOCS/OLLAMA/benchmark_test_extrahop.md`) describes every
nested column as a native Cortex Array, but the live tenant disagrees
on all four of them: `categories`, `participants`, `mitre_tactics`
and `mitre_techniques` arrive as JSON STRINGS, not native Arrays.
The pack therefore applies a uniform rule:

- **JSON string columns** (`categories`, `participants`,
  `mitre_tactics`, `mitre_techniques`): MUST go through the `-> []`
  JSON-array cast before any array function call. A bare
  `arraymap(<col>, ...)` is rejected at save time with "Field <col>
  for function arraymap is invalid. Expected array but received
  string". The cast desugars to `json_extract_array(<col>, "$[*]")`
  and yields the typed Array the inner `"@element" -> <field>`
  accessor needs. Every nested-column read in this pack applies
  this cast at the point of first use, including the
  `_categories_arr` assignment, the per-role participant
  projections, and the two MITRE id `arraymap` calls. The same
  cast is applied to `categories` in `parser.xql` when stamping
  the `_detection_category` anchor.

`properties` is the only nested column that arrives as the type the
producer schema claims -- a typed Object. It is read with the scalar
`->` field accessor (e.g. `properties -> risk_event_name`).

## Patterns demonstrated

The rule exercises three patterns from the offline knowledge file:

- **Section 9.7 (revised) -- per-scalar projection of role-tagged object
  arrays.** `participants` is filtered by role and ONE scalar at a time
  is extracted. Binding the whole struct element to an alter target is
  illegal in Cortex (alter outputs must be scalar or primitive-array
  typed).
- **Section 9.8 -- `arraymap` with an inner if-chain.** Converts MITRE
  ids (`TA*`/`T*`) to `XDM_CONST` enum members and assigns directly to
  `xdm.alert.mitre_*` (no `arraycreate` wrapper -- the input is already
  an array).
- **Section 9.9 -- conditional source/target mirroring.** Earlier
  doctrine assumed RevealX detections were strictly one-sided. In
  practice the `participants[]` array carries six payload shapes (see
  "Body stage notes" below): single offender + single victim, multi-
  offender no victim, multi-victim, victim-only, missing `object_value`
  on device-typed rows, and sibling `hostname` field carrying a DNS
  name independently of `object_value`. The MODEL projects each role
  into its own array of typed scalars, then drives target.* from the
  victim when one exists and only mirrors the offender into target.*
  when no victim row is present. Source.* is always offender-driven
  and stays empty for victim-only payloads.

## Cortex parser notes (verified against the live tenant 2026-04)

- Arithmetic in alter must use the function form
  (`subtract`/`add`/`multiply`/`divide`). Infix `-` `+` `*` `/` cause
  cascade parse errors.
- All four nested non-object columns (`categories`, `participants`,
  `mitre_tactics`, `mitre_techniques`) arrive as JSON strings on the
  live tenant despite the producer schema doc claiming native
  `Array<...>` types. They MUST be cast with `-> []` before any
  array-function call (`arraymap`, `arrayfilter`, `array_length`,
  `arraystring`); a bare reference fails save with "Field <col> for
  function arraymap is invalid. Expected array but received string".
  Once cast, downstream temps hold typed Arrays and need no further
  casting (`_categories_arr` is fed to `arraymap`/`arraystring` in
  later stages, and the per-role participant projections feed array
  temps to `arrayfilter`/`arrayindex`/`array_length`).
- The typed-Object column `properties` is read with the scalar
  `-> field` accessor (e.g. `properties -> risk_event_name`).
- Boolean equality with bareword `true`/`false` is rejected when the
  column is string-typed. Either quote the literals (`"true"`/`"false"`)
  or cast the column with `to_boolean()` and compare against unquoted
  `true`/`false`. This rule uses the cast form because
  `participants[].external` is a real boolean in the payload.
- `to_number()` returns float; `xdm.event.duration` is integer-typed
  so the result must be wrapped in `to_integer()`.
- `xdm.event.start_time` and `xdm.event.end_time` do NOT exist in the
  XDM schema. Fold start/end millisecond pairs into
  `xdm.event.duration` via `subtract()`.
- `xdm.{source,target}.is_external` does NOT exist. The only canonical
  sink for an external/internal boolean is
  `xdm.{source,target}.is_internal_ip`; invert before assigning.
- All derived computations (severity, log_level, description) live in a
  dedicated derive stage so each underscore temp reaches a single-line
  `xdm.*` drain. This satisfies the validator's chain-tracer
  (ERR-019 / Section 11.8) without relying on it tracing through
  multi-line `if()` / `concat()` bodies.

## Alert field mapping

| Detection field             | XDM mapping |
| --------------------------- | ----------- |
| Detection ID                | `xdm.event.id`, `xdm.alert.original_alert_id` |
| Detection title             | `xdm.alert.name`, `xdm.alert.original_threat_name` |
| Detection type              | `xdm.event.original_event_type` |
| Detection description       | `xdm.alert.description` |
| Detection URL               | `xdm.alert.source_url` |
| Risk score (0-100)          | `xdm.alert.severity` (banded), `xdm.event.log_level` |
| `risk_event_name`           | `xdm.alert.subcategory` |
| `categories[]`              | `xdm.alert.category` (heuristic `XDM_CONST.THREAT_CATEGORY_*` mapping over the FULL array; first matched constant wins). Full joined text also placed in `xdm.event.description`. |
| `mitre_tactics[].id`        | `xdm.alert.mitre_tactics` (`arraymap` + if-chain) |
| `mitre_techniques[].id`     | `xdm.alert.mitre_techniques` (`arraymap` + if-chain) |
| `participants[role=offender]` | drives `xdm.source.*`; mirrored into `xdm.target.*` only when no victim row is present (Section 9.9) |
| `participants[role=victim]`   | drives `xdm.target.*` when present; never mirrored into `xdm.source.*` |
| `.object_value` (IPv4-shaped) | `xdm.{source,target}.ipv4` (deterministic first element), `xdm.{source,target}.host.ipv4_addresses` (full per-role array). Routing is by regex shape -- both `object_type = "ipaddr"` and `object_type = "device"` rows are accepted when `object_value` matches the dotted-quad form. |
| `.object_value` (`object_type = hostname`) | `xdm.{source,target}.host.hostname` (combined with the sibling `hostname` field, see next row) |
| `.hostname` (sibling field) | `xdm.{source,target}.host.hostname` -- carries the DNS name independently of `object_value` so an (IP, hostname) pair lands in both `*.ipv4` and `*.host.hostname` |
| `.object_id` (when `object_value` and `hostname` are both null) | `xdm.{source,target}.host.device_id = to_string(object_id)` -- device-typed rows that the appliance has not yet resolved still surface a stable identifier |
| `.username`                 | `xdm.{source,target}.user.username`, `xdm.{source,target}.user.upn` (per-role, mirror-gated) |
| `.external` (negated)       | `xdm.{source,target}.is_internal_ip` (per-role, mirror-gated; null when the role row is absent) |
| `_reporting_device_ip`      | `xdm.intermediate.ipv4` |
| `appliance_id`              | `xdm.intermediate.host.device_id` |
| `end_time - start_time`     | `xdm.event.duration` (`subtract` + `to_integer`; null-propagating) |

NOT MAPPED:

- `xdm.observer.action` -- RevealX detections do not record a normalised
  action verb; the status field is null.
- `xdm.event.start_time` -- no such XDM path; folded into
  `xdm.event.duration` via `_duration_ms`.
- `xdm.event.end_time` -- no such XDM path; folded into
  `xdm.event.duration` via `_duration_ms`.
- `xdm.{source,target}.is_external` -- no such XDM path; the external
  boolean is inverted into `is_internal_ip`.
- `_time` -- Cortex sets `_time` automatically.

## Backward compatibility with pre-enrichment datasets

The parser stamps two helper columns at ingest -- `_detection_category`
(an `Array<String>` mirror of the raw `categories` column) and
`_risk_band` (a 3-value bucket derived from the numeric `risk_score`).
These exist for analyst-side anchor coverage so XQL queries can use
`arraycontains(_detection_category, "...")` and `_risk_band = "HIGH"`
on enriched rows. They are NOT used by the data model rule.

Cortex compiles a data model rule against the dataset schema before any
row is evaluated; a bare reference to a column that is not in the
schema fails to save with an "unknown field" error even when the
reference sits inside `coalesce(...)`. The `coalesce` fallback only
runs when the column EXISTS but the value is null, never when the
column is absent from the schema. Because the parser only stamps
`_detection_category` and `_risk_band` on rows ingested AFTER the
parsing rule was deployed, any tenant with historical RevealX data
ingested before the parser update has a dataset schema that omits both
columns.

To stay save-able on those tenants, the data model rule derives
`_categories_arr` from the raw `categories` column directly and derives
`_risk_band` from the numeric `risk_score` directly via the same 3-value
bucket the parser uses. A single derivation path runs for both legacy
and enriched rows -- behaviour is uniform regardless of whether the
parser stamped the helper columns. The downstream XDM sinks
(`xdm.alert.risks`, the categories segment of `xdm.event.description`,
and the category-driven `xdm.alert.category` lookup) are unchanged.

## Body stage notes

- **Stage 1 -- per-role array projections.** `participants` is read
  as a native `Array<Object>` column (no `-> []` cast). Each
  field-of-interest is projected per role into its own typed array via
  `arrayfilter(arraymap(participants, if("@element" -> role = "<role>",
  ...)), "@element" != null)`. Twelve sequences are built: for each of
  the two roles (`offender`, `victim`) we project `_role_marks` (a
  per-row "1" used purely for counting), `_ip_seq` (regex-shape
  filtered to dotted-quad IPv4), `_hostname_seq` (sibling `hostname`
  field unioned with `object_value` where `object_type = "hostname"`),
  `_username_seq`, `_external_seq`, and `_object_id_seq`. The empty
  array is the canonical "no rows" sentinel; `arrayindex([], 0)` returns
  null so the *_first scalars defined in stage 2a fall out cleanly.
- **Six payload shapes handled.** (1) single offender + single victim;
  (2) multi-offender no victim; (3) multi-victim with one offender;
  (4) victim-only zero-offender; (5) row with `object_value = null` --
  the `object_id` is stamped into `*.host.device_id` instead of
  fabricating null IP / hostname assertions; (6) sibling `hostname`
  field carrying a DNS name even when `object_value` is an IP.
- **IP routing is shape-based, not type-based.** RevealX uses
  `object_type = "ipaddr"` and `object_type = "device"` interchangeably
  for IP-bearing rows. The IP filter regex
  `^[0-9]{1,3}([.][0-9]{1,3}){3}$` accepts both. IPv6 detection is out
  of scope (no fixtures exercise it; the regex would need a separate
  alternative branch).
- **Stage 2a -- leaf temps only.** No target may reference a sibling
  defined in the same stage. Per-role *_first scalars (`arrayindex(_seq,
  0)`) and *_count (`array_length(_role_marks)`) come from stage-1
  outputs only. `_duration_ms` uses `subtract()` (infix `-` is
  rejected) and wraps in `to_integer()` because `xdm.event.duration`
  is integer-typed. `_severity`, `_log_level`, `_category_const`, and
  the two MITRE if-chains are pre-derived so each temp drains into a
  single-line `xdm.*` assignment, satisfying ERR-019 reach analysis
  inside a single paren depth.
- **Stage 2b -- mirror-gated temps and description.** Per-role
  `_source_is_internal` / `_target_is_internal` invert `external` only
  when the role row exists. `_target_*` scalars and `_target_ip_arr`
  (the IP array) prefer the victim when present and fall back to the
  offender otherwise. `_source_device_id` / `_target_device_id` only
  fire when their role row exists AND has neither IP nor hostname --
  the `to_string(object_id)` fallback is a last-resort identifier.
  `_description` is built in this stage so the validator's reach
  analyser can credit references made outside `concat()` and
  `arraystring()` bodies (Section 11.x / ERR-025).
- **Drain stage.** Source-side fields are populated from the offender
  projections directly. Target-side reads the 2b-derived `_target_*`
  temps which already encode the victim-or-mirror gating. Each XDM
  field is a single-line drain; no inline conditionals here.
- **Hostname routing is shape-based, not type-based.** The hostname
  union prefers the participant's sibling `hostname` field; otherwise
  it accepts `object_value` whenever it is non-null AND NOT IP-shaped,
  regardless of `object_type`. So a `device`-typed row carrying a DNS
  name lands in the hostname sink, and a `hostname`-typed row carrying
  an IP literal lands in the IP sink. Both branches respect the same
  `^[0-9]{1,3}([.][0-9]{1,3}){3}$` shape regex used for IP routing,
  so a single row never dual-routes.
- **Multi-row roles with sparse fields (cross-row composite).** The
  six per-role array projections each filter independently, so when a
  role has multiple rows with different non-null fields the `*_first`
  scalar drains may pick the IP from one row and the hostname from
  another. This is accepted: the array sinks
  (`xdm.{source,target}.host.ipv4_addresses`) hold the full per-role
  aggregate, and the scalar sinks degrade to "first non-null per
  dimension" rather than "first complete row". Refactor to row-coherent
  extraction is reserved for a future task if downstream analytics
  need it.
