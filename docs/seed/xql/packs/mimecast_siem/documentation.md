# Mimecast Secure Email Gateway -- XDM Data Model Rule Documentation

Companion notes for `mimecast_siem_xdm_model_rule.xql`.

## Anchors

`parser.xql` (in this pack) stamps two anchor columns at ingest time
per the convention in `PRIVATE_DOCS/anchor_field_design.md`. The
MODEL gains a one-token `coalesce()` around each so legacy / replayed
/ backfilled rows still derive the same value from the raw payload.

| Anchor | Type | Vocabulary | Source | Purpose |
| ------ | ---- | ---------- | ------ | ------- |
| `_event_type` | scalar string | ~6 closed values: `receipt`, `process`, `delivery`, `url_protect`, `attachment_protect`, `journal` | top-level `eventType` column | Per-event-shape discriminator -- already the rule's primary fan-out filter |
| `_outcome` | scalar string | ~6 closed values: `Allow`, `Hold`, `Block`, `Bounce`, `Defer`, `Reject` | `coalesce(action, status, deliveryStatus)` -- vendor splits the same concept across three columns depending on event shape | Universal mail-flow triage filter -- "did this mail get through?" without forcing analysts to remember which column carries the answer for each event shape |

`_direction` (inbound / outbound) was considered as a third anchor
and deferred: only `receipt` and `delivery` rows carry a direction,
and the marginal selectivity over the existing two anchors is small.
The "two anchors per dataset is the sweet spot" discipline applies.

## Relationship to parser

`datamodel.xql` reads both anchors via the keep-in-both convention
from `PRIVATE_DOCS/anchor_field_design.md`:

```
_event_type = coalesce(_event_type, eventType)
_outcome    = coalesce(_outcome, action, status, deliveryStatus)
```

Both anchors are then sunk into XDM via `coalesce()` arms (not
`concat()` arguments), so the analyser does not raise ERR-025 on
either intermediate:

```
xdm.event.original_event_type = coalesce(_event_type, eventType)
xdm.event.outcome_reason      = coalesce(_outcome_reason, _outcome)
```

`_event_type` wins over the raw `eventType` column when present
(parser-stamped rows pay one column read instead of two). `_outcome`
sits as the back-stop arm of `xdm.event.outcome_reason` so the more
specific free-text reasons (`blockReason`, `holdReason`,
`rejectionType`, `rejectionInfo`) still win when present and the
canonical action label fills in otherwise.

The `_time` column is set by the parser from `Datetime` (ISO-8601
string) with a fall-back to `timestamp` (Unix epoch milliseconds).
When neither field is present the parser leaves `_time` NULL and
Cortex falls back to `_insert_time` automatically.

## Scope

| Attribute   | Value |
| ----------- | ----- |
| Dataset     | `mimecast_siem_raw` |
| Vendor      | Mimecast |
| Product     | Secure Email Gateway |
| Log type    | SIEM (via Mimecast Event Collector v2) |
| Format      | JSON -- fields are top-level columns (direct access). `_raw_log` is EMPTY for this dataset. |

## Event types handled

Discriminated by the `eventType` column:

- `receipt` -- email received by MTA (inbound/outbound)
- `process` -- email policy processing (accept/reject/hold)
- `delivery` -- email delivered to destination
- `url_protect` -- Targeted Threat Protection (URL scanning)
- `attachment_protect` -- Targeted Threat Protection (attachment scanning)
- `journal` -- journalled copy for archive/compliance

## XDM field mapping summary (28 fields)

### Observer (2)

- `xdm.observer.vendor` = `"Mimecast"`
- `xdm.observer.product` = `"Secure Email Gateway"`

### Event (6)

- `xdm.event.type` = `"EMAIL"`
- `xdm.event.id` = processing ID or event ID
- `xdm.event.original_event_type` = `coalesce(_event_type, eventType)` (parser-stamped anchor first, raw column as fallback). Vocabulary: `receipt`, `process`, `delivery`, `url_protect`, `attachment_protect`, `journal`.
- `xdm.event.description` = structured summary via `concat()`
- `xdm.event.outcome` = mapped from `Action` and `Delivered`:
  - `Acc` -> SUCCESS
  - `Block` / `Rej` / `Bnc` -> FAILED
  - `Hld` -> PARTIAL
  - delivery `Delivered=true` -> SUCCESS
  - delivery `Delivered=false` -> FAILED
- `xdm.event.outcome_reason` = `coalesce(_outcome_reason, _outcome)`, where `_outcome_reason = coalesce(blockReason, holdReason, rejectionType, rejectionInfo)` (specific free-text reason wins) and `_outcome` is the parser-stamped action label (`Allow`/`Hold`/`Block`/`Bounce`/`Defer`/`Reject`) used as a back-stop arm.

### Email (8)

- `xdm.email.sender` = header From address (`senderHeader`), falling back to envelope sender
- `xdm.email.recipients` = recipient address (as array via `arraycreate`)
- `xdm.email.subject` = email subject line
- `xdm.email.message_id` = `Message-ID` header
- `xdm.email.return_path` = SMTP envelope sender (`senderEnvelope`)
- `xdm.email.attachment.filename` = attachment filename (`attachment protect` events)
- `xdm.email.attachment.md5` = attachment MD5 hash
- `xdm.email.attachment.sha256` = attachment SHA256 hash

### Source (3)

- `xdm.source.ipv4` = sender IP (coalesce of `senderIp`, `SourceIP`)
- `xdm.source.user.username` = envelope sender address
- `xdm.source.host.hostname` = sender domain

### Target (3)

- `xdm.target.ipv4` = destination IP (delivery events)
- `xdm.target.url` = suspicious URL (`url protect` events)
- `xdm.target.user.username` = recipient address

### Network (2)

- `xdm.network.tls.protocol_version` = TLS version (receipt events)
- `xdm.network.tls.cipher` = TLS cipher suite (receipt events)

### Alert (2)

- `xdm.alert.name` = block reason or URL category (TTP events)
- `xdm.alert.description` = virus found or scan result info

### Intermediate (2)

- `xdm.intermediate.host.hostname` = delivery destination hostname
- `xdm.intermediate.ipv4` = Mimecast reporting device IP

## Excluded XDM fields -- not applicable or no source data

- `xdm.email.attachment.extension` -- available as `fileExtension` but redundant with filename; omitted to keep the rule lean.
- `xdm.email.attachment.size` -- available as `sizeAttachment` (string) but only on `attachment protect` events; omitted for simplicity.
- `xdm.email.attachment.file_type` -- available as `fileMime` but only on `attachment protect` events; omitted for simplicity.
- `xdm.network.http.url` -- the `url` field is better mapped to `xdm.target.url` as it represents the suspicious destination, not an HTTP request.
- `xdm.event.duration` -- `deliveryTime` is only on delivery events and represents latency in an unspecified unit; excluded to avoid incorrect assumptions.
- `xdm.auth.*` -- SPF/DKIM/DMARC results are in `SpamProcessingDetail` nested JSON; would require `json_extract_scalar` on a JSON object column; deferred for a future enhancement.
- `xdm.source.sent_bytes` / `xdm.target.sent_bytes` -- `emailSize` and `totalSizeAttachments` are available but inconsistently populated across event types; excluded.
