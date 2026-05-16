# Imperva Account Takeover Protection -- XDM Data Model Rule Documentation

Companion notes for `imperva_account_takeover_xdm_model_rule.xql`.

## Anchors

`parser.xql` (in this pack) stamps two anchor columns at ingest time per
the convention in `PRIVATE_DOCS/anchor_field_design.md`. Both anchors
already use the underscore names the MODEL has always used, so the
parser just hoists the same `json_extract_scalar()` extraction one
stage earlier and the MODEL gains a one-token `coalesce()` around each.

| Anchor | Type | Vocabulary | Purpose |
| ------ | ---- | ---------- | ------- |
| `_event_type` | scalar string | 6 closed values: `LOGIN_FAILURE`, `LOGIN_SUCCESS`, `ACCOUNT_TAKEOVER`, `SUSPICIOUS_LOGIN`, `MFA_CHALLENGE`, `MFA_SUCCESS` | Universal per-event-type filter; drives all downstream branching |
| `_risk_level` | scalar string | 4 closed values (vendor lowercase): `low`, `medium`, `high`, `critical` | Universal triage filter; tiny vocabulary |

Sample analyst queries:

```
// Confirmed account-takeover events from the last day
dataset = imperva_accounttakeover_raw
| filter _event_type = "ACCOUNT_TAKEOVER"
       and _time > to_timestamp(subtract(to_epoch(current_time()), 86400), "SECONDS")

// Anything Imperva flagged as critical risk, regardless of event type
dataset = imperva_accounttakeover_raw
| filter _risk_level = "critical"
```

`_risk_level` keeps the vendor's lowercase form rather than
case-normalising at ingest. The MODEL already compares against the
lowercase form when normalising to `xdm.alert.severity`, so stamping
verbatim keeps the parser-stamped and legacy code paths identical.
Case-folding at the parser would force a coordinated MODEL change for
no functional benefit.

## Relationship to parser

`datamodel.xql` reads both anchors via the keep-in-both convention from
`PRIVATE_DOCS/anchor_field_design.md`:

```
_event_type = coalesce(_event_type,
                       json_extract_scalar(to_string(imperva), "$.event_type"))
_risk_level = coalesce(_risk_level,
                       json_extract_scalar(to_string(imperva), "$.risk_level"))
```

Parser-stamped rows pay one column read and a `coalesce` short-circuit;
legacy / replayed / backfilled rows fall through to the same
`json_extract_scalar()` the rule has always run. The MODEL never
depends on the anchor column being present.

`_time` is set by the parser from `event.timestamp` /
`imperva.timestamp` (ISO-8601, two zone-suffix variants tried); when
neither is present the parser leaves `_time` NULL and Cortex falls
back to `_insert_time` automatically. No year-boundary reconstruction
is required (compare with the EfficientIP DDI parser, which has to
derive the year from `_insert_time`).

## Scope

Maps Imperva ATO SIEM event payloads to the Cortex XDM schema. Imperva
Account Takeover Protection detects and mitigates account takeover
attempts -- including volumetric brute-force and low-and-slow credential
stuffing attacks -- as part of the broader Imperva WAF product suite.

## Payload structure

A flat JSON structure with three top-level objects:

| Object       | Purpose |
| ------------ | ------- |
| `event{}`    | Provider/dataset metadata (not mapped) |
| `client{}`   | Attacker IP address |
| `imperva{}`  | All detection fields (risk, user, login counts, etc.) |

The `_raw_log` column is empty for this dataset. The XSIAM parser
produces three top-level columns (`client`, `event`, `imperva`)
containing JSON strings. All field extractions use
`json_extract_scalar()` on these parsed columns.

The `imperva.ids{}` sub-object is optional and only present when the
site has been onboarded with explicit account/site identifiers.

## Severity

Taken from `imperva.risk_level`, the vendor-provided risk assessment.
The API documents three values (`low`, `medium`, `high`) but real
ingest also produces `critical` on takeover-confirmed events, so the
anchor vocabulary in the "Anchors" section above lists all four. The
`xdm.alert.severity` if-chain explicitly normalises the three
documented values to proper case (`Low`, `Medium`, `High`); `critical`
and any other forward-compatible value falls through the catch-all
arm and is passed verbatim.

## User identity

The `request_user` field carries a hashed or encrypted form of the
username. The plaintext username is only available when the PII
password was specified and matches the Imperva configuration.

## Folded contextual fields

Several valuable contextual fields (login counts, bot classification,
credentials leaked status, additional risk factors) lack direct XDM
mappings and are folded into `xdm.alert.description` as a structured
summary string.

## MITRE ATT&CK mapping

Derived from `risk_reason`. All ATO detections map to `TA0006`
(Credential Access). The technique is determined by the specific attack
type:

| risk_reason value(s)                                | Technique |
| --------------------------------------------------- | --------- |
| `Brute_Force` / `Password_Brute_Force`              | T1110 Brute Force |
| `Credential_Stuffing`                               | T1110.004 Credential Stuffing |
| `Common_Password`                                   | T1110.001 Password Guessing |
| `Common_User`                                       | T1110 Brute Force (common usernames, not passwords) |
| `Abnormal_Behavior_By_Profile`                      | T1110 Brute Force (heuristic) |
| `Dynamic_Bot_Signatures`                            | T1110 Brute Force (heuristic) |
| `Scripting_Tool`                                    | T1110 Brute Force (heuristic) |
| `Suspicious_Number_Of_Users`                        | T1110 Brute Force (heuristic) |
| (any unknown future value)                          | T1110 Brute Force (safe default; all ATO alerts are credential attacks by definition) |

`xdm.alert.mitre_techniques` uses `XDM_CONST.MITRE_TECHNIQUE_*`
constants in an `if()` chain. This pattern has caused internal errors
on `_gc_raw` datasets. This is a different dataset type and should be
unaffected, but the field is flagged for testing on the live dataset.
If it causes errors, remove the `mitre_techniques` mapping and document
the failure in the excluded fields section.

## Vendor documentation

- SIEM integration: https://docs-cybersec.thalesgroup.com/bundle/account-takeover/page/account-takeover/ato-siem-integration.htm
- API specification: https://docs-cybersec.thalesgroup.com/bundle/api-docs/page/ato-api-definition.htm

## XDM field mapping summary (21 fields)

### Observer

- `xdm.observer.vendor` = `"Imperva"`
- `xdm.observer.product` = `"Account Takeover Protection"`

### Event

- `xdm.event.type` = `"ALERT"`
- `xdm.event.id` = `imperva.request_id`
- `xdm.event.original_event_type` = `imperva.event_type`

### Alert

- `xdm.alert.name` = `imperva.risk_reason`
- `xdm.alert.original_threat_name` = `imperva.risk_reason`
- `xdm.alert.subcategory` = `imperva.risk_reason`
- `xdm.alert.severity` = `imperva.risk_level` (proper case)
- `xdm.alert.description` = constructed summary of classified client, login counts (24h), creds leaked, and additional risk factors
- `xdm.alert.mitre_tactics` = `XDM_CONST.MITRE_TACTIC_CREDENTIAL_ACCESS` (hardcoded -- all ATO = `TA0006`)
- `xdm.alert.mitre_techniques` = `risk_reason` mapped to `XDM_CONST.MITRE_TECHNIQUE_BRUTE_FORCE*`

### Source (attacker)

- `xdm.source.ipv4` = `client.ip`
- `xdm.source.location.country` = `imperva.country` (ISO code)
- `xdm.source.user.username` = `imperva.request_user` (mirrors `xdm.target.user.username`; only user in payload)

### Target (victim / protected resource)

- `xdm.target.ipv4` = `client.ip` (only IP in payload; mirrors `xdm.source.ipv4`)
- `xdm.target.user.username` = `imperva.request_user` (hashed)
- `xdm.target.host.hostname` = `imperva.ids.site_name` (nullable)
- `xdm.target.url` = `imperva.path`

### Network

- `xdm.network.http.browser` = `imperva.declared_client`
- `xdm.network.http.referrer` = `imperva.referrer`

## Excluded XDM fields -- no mapping available

- `xdm.alert.original_threat_id` -- no unique threat identifier in the payload. `risk_reason` is a category label, not an ID.
- `xdm.event.description` -- contextual data folded into `xdm.alert.description` instead (alert-level context, not event-level).
- `xdm.observer.action` -- mitigation actions (`NONE`, `CAPTCHA`, `BLOCK`, `TARPIT`) exist in the API configuration but are not included in the SIEM event payload.
- `xdm.observer.type` -- no observer type data in the payload.
- `xdm.observer.version` -- no version data in the payload.
- `xdm.source.host.*` -- no source host metadata; only IP and country.
- `xdm.source.process.*` -- not applicable (web-based ATO alert, no process telemetry).
- `xdm.source.user.domain` -- no domain data in the payload.
- `xdm.target.file.*` -- not applicable (web-based ATO alert, no file telemetry).
- `xdm.session_context_id` -- `imperva.request_session_id` is available but this field has caused internal errors on some datasets. Omitted for safety; can be added after testing on the live dataset.

## Excluded payload fields -- folded or no XDM target

- `imperva.classified_client` -- Imperva's own bot classification (e.g. `Bot`). Folded into `xdm.alert.description`. Distinct from `declared_client` which reflects the User-Agent header.
- `imperva.failed_logins_last_24h` -- count of failed logins in the last 24 hours. Folded into `xdm.alert.description`.
- `imperva.successful_logins_last_24h` -- count of successful logins in the last 24 hours. Folded into `xdm.alert.description`.
- `imperva.credentials_leaked` -- boolean indicating whether the credentials were found in known breach databases. Folded into `xdm.alert.description`.
- `imperva.additional_factors` -- array of additional risk factors (e.g. `Client Classification Mismatch`, `Site under risk`). Folded into `xdm.alert.description`.
- `imperva.fingerprint` -- client device fingerprint hash. No direct XDM field mapping.
- `imperva.device_reputation` -- IP reputation array as classified by the proxy. Empty in all sample payloads. No standard XDM field.
- `imperva.ids.account_id` -- internal Imperva account identifier. No standard XDM field.
- `imperva.ids.site_id` -- internal Imperva site identifier. No standard XDM field. Site name is used for `xdm.target.host.hostname` instead.
- `event.provider` / `event.dataset` -- dataset metadata, not mapped to XDM fields.
