# Imperva Audit Trail -- XDM Data Model Rule Documentation

Companion notes for `imperva_audit_trail_xdm_model_rule.xql`.

## Anchors

`parser.xql` (in this pack) stamps two anchor columns at ingest time per
the convention in `PRIVATE_DOCS/anchor_field_design.md`. The MODEL
gains a one-token `coalesce()` around each so legacy / replayed /
backfilled rows still derive the same value from
`imperva.audit_trail.*`.

| Anchor | Type | Vocabulary | Purpose |
| ------ | ---- | ---------- | ------- |
| `_action_class` | scalar string | ~7 closed values: `SITE`, `USER`, `SSL`, `POLICY`, `LOGIN`, `ACCOUNT`, `SYSTEM` | Coarse-grained action discriminator; how analysts actually pivot |
| `_resource_type` | scalar string | ~8 closed values: `Site`, `User`, `Policy`, `SSL`, `Account`, `Rule`, `System` (NULL on system-initiated rows) | "What was touched" filter |

### Why the prefix, not the raw verb

Raw `event_action` runs to ~30-60 distinct verb codes (the full set is
unpublished; only 267 `event_action_description` strings are
documented). At that cardinality the column is borderline too sparse
to be a useful anchor -- each value only narrows the firehose to
~1-3% of rows and analysts have to know the exact verb code spelling.

The prefix collapses that into a 7-value class an analyst can type
from memory:

```
// "Show me all SSL ops in the last day."
dataset = imperva_audittrail_raw
| filter _action_class = "SSL"
       and _time > to_timestamp(subtract(to_epoch(current_time()), 86400), "SECONDS")

// Drill from class to verb by stacking a second filter on the
// granular event_action verb (for example, SSL class plus SSL_RENEW).
```

The MODEL's keep-in-both fall-back must NOT simply coalesce to the raw
`_event_action` -- it re-derives the prefix independently with the
same `arrayindex(split(_event_action, "_"), 0)` expression the parser
runs. This is what keeps legacy and parser-stamped rows behaving
identically.

## Relationship to parser

`datamodel.xql` reads both anchors via the keep-in-both convention from
`PRIVATE_DOCS/anchor_field_design.md`:

```
_action_class  = coalesce(_action_class,
                           if(_event_action != null,
                              arrayindex(split(_event_action, "_"), 0)))
_resource_type = coalesce(_resource_type,
                           json_extract_scalar(to_string(imperva),
                                               "$.audit_trail.resource_type"))
```

`_action_class` is also folded into `xdm.event.description` so the
class is visible to analysts in the smart-grouping pane without
forcing them back to the raw row. Without that sink the MODEL would
derive `_action_class` only to drop it again -- harmless, but the
analyser would (correctly) flag the intermediate as
unused-after-derivation.

`_time` is set by the parser from `event.timestamp` /
`imperva.audit_trail.timestamp` (ISO-8601, two zone-suffix variants
tried); when neither is present the parser leaves `_time` NULL and
Cortex falls back to `_insert_time` automatically. No year-boundary
reconstruction is required (compare with the EfficientIP DDI parser).

## Scope

Maps Imperva Audit Trail SIEM event payloads to the Cortex XDM schema.
The Audit Trail records administrative actions performed in the Imperva
Cloud Application Security console -- site configuration changes, user
management, SSL operations, policy modifications, login events, and
system-initiated background jobs.

## Payload structure

A flat JSON structure with three top-level objects:

| Object       | Purpose |
| ------------ | ------- |
| `event{}`    | Provider/dataset metadata (`audit` / `AUDIT_TRAIL`) |
| `imperva{}`  | All audit fields (action, resource, context, account IDs) |
| `user{}`     | Email of the account user who performed the action |

The `_raw_log` column is empty for this dataset. The XSIAM parser
produces three top-level columns (`event`, `imperva`, `user`) containing
JSON strings. All field extractions use `json_extract_scalar()` on
these parsed columns.

The `imperva.ids{}` sub-object contains `account_id`, `account_name`,
and optionally `site_id`. These are internal Imperva identifiers.
`account_id` is mapped to `xdm.target.resource.parent_id` as the owning
account.

The `imperva.audit_trail{}` sub-object contains the core audit fields:

| Field                       | Description |
| --------------------------- | ----------- |
| `event_action`              | Machine-readable action code (e.g. `SITE_REMOVE`) |
| `event_action_description`  | Human-readable description (e.g. `Site removed`) |
| `assumed_by`                | Nullable; present when Imperva Support or another user performs the action on behalf of the account user |
| `resource_type`             | Type of resource acted upon (e.g. `Site`) |
| `resource_id`               | Internal ID of the resource |
| `resource_name`             | Display name of the resource |
| `event_context`             | How the action was initiated: `UI`, `API`, `INTERNAL_API`, `JOB`, `NA` |
| `event_context_description` | Human-readable context label |

## Operation mapping

Uses contains-based keyword matching on the `event_action` code to
mapped to `XDM_CONST.OPERATION_TYPE` enums. The full list of
`event_action` machine codes is not published by the vendor; only 267
`event_action_description` values are documented. The mapping infers
code patterns from known examples (`SITE_REMOVE`, `API_UPDATED`,
`ACCOUNT_LOGIN`) and the descriptions. The contains-based approach is
deliberately broad to catch future action codes. The default fallback
is `AUDIT` for any unmatched action.

## Event type

This is NOT an alert/threat dataset -- there are no severity, MITRE, or
alert fields. The event type is `AUDIT` throughout.

## Vendor documentation

- Audit Trail overview: https://docs-cybersec.thalesgroup.com/bundle/cloud-application-security/page/audit-trail-siem-integration.htm
- Audit Trail event types: https://docs-cybersec.thalesgroup.com/bundle/cloud-application-security/page/audit-trail-types.htm
- API specification: https://api.imperva.com/audit-trail (Swagger)

## XDM field mapping summary (14 fields)

### Observer

- `xdm.observer.vendor` = `"Imperva"`
- `xdm.observer.product` = `"Cloud Application Security"`

### Event

- `xdm.event.type` = `"AUDIT"`
- `xdm.event.description` = structured summary: action description, context, `assumed_by`, account, site (via `concat`)
- `xdm.event.original_event_type` = `audit_trail.event_action` (raw vendor action code)
- `xdm.event.operation` = `event_action` mapped to `XDM_CONST.OPERATION_TYPE` via contains-based keyword matching
- `xdm.event.operation_sub_type` = `audit_trail.event_action` (raw vendor action code for granularity)

### Source (who performed the action)

- `xdm.source.user.username` = `user.email`

### Target Resource (what was acted upon)

- `xdm.target.resource.type` = `audit_trail.resource_type`
- `xdm.target.resource.name` = `audit_trail.resource_name`
- `xdm.target.resource.id` = `audit_trail.resource_id`
- `xdm.target.resource.parent_id` = `ids.account_id` (owning account)

### Target Host

- `xdm.target.host.hostname` = `audit_trail.resource_name` (only when `resource_type = "Site"`; `resource_name` is the FQDN)

### Target User

- `xdm.target.user.username` = `user.email` (mirrored from source; Pattern 8 -- only one user in payload)

## Excluded XDM fields -- not applicable or no source data

- `xdm.alert.*` -- not applicable; this is an administrative audit log, not a security alert dataset. No severity, MITRE, or threat data.
- `xdm.event.id` -- no unique event identifier in the payload. The API returns events by time range without per-event IDs.
- `xdm.event.outcome` -- the audit trail does not include success/failure status for actions. All logged events are completed actions.
- `xdm.observer.version` -- no version data in the payload.
- `xdm.source.ipv4` -- no source IP address in the audit trail payload. The API authenticates via API key headers, not per-event IP logging.
- `xdm.source.host.*` -- no source host metadata in the payload.
- `xdm.source.process.*` -- not applicable (console/API actions, no process telemetry).
- `xdm.target.file.*` -- not applicable (administrative actions, no file telemetry).
- `xdm.target.url` -- `resource_name` may contain a domain but is not a full URL. Mapped to `xdm.target.host.hostname` when appropriate.
- `xdm.network.*` -- not applicable (administrative audit events, no network traffic metadata).
- `xdm.session_context_id` -- no session identifier in the payload. Known to cause internal errors on some datasets. Omitted for safety.

## Excluded payload fields -- folded or no XDM target

- `imperva.audit_trail.event_action_description` -- human-readable action label. Folded into `xdm.event.description`. The machine-readable `event_action` is mapped to `xdm.event.operation_sub_type`.
- `imperva.audit_trail.resource_type_description` -- human-readable resource type label. Generally identical to `resource_type`. The machine-readable `resource_type` is mapped to `xdm.target.resource.type`.
- `imperva.audit_trail.event_context` -- how the action was initiated (`UI`, `API`, `INTERNAL_API`, `JOB`, `NA`). Folded into `xdm.event.description`.
- `imperva.audit_trail.event_context_description` -- human-readable context label. Folded into `xdm.event.description`.
- `imperva.audit_trail.assumed_by` -- the user who performed the action on behalf of the account user (e.g. `Imperva Support`). Folded into `xdm.event.description`. No dedicated XDM field for impersonation.
- `imperva.ids.account_name` -- account email address. Folded into `xdm.event.description`.
- `imperva.ids.site_id` -- internal Imperva site identifier. Folded into `xdm.event.description` when present.
- `event.provider` / `event.dataset` -- dataset metadata (`audit` / `AUDIT_TRAIL`), not mapped to XDM fields.
- `message` -- top-level event summary string. Equivalent to `event_action_description`. Not extracted separately as the description is already sourced from the `imperva` column.
