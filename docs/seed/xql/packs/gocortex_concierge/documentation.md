# GoCortex Concierge -- Pack Documentation

Companion notes for `parser.xql` and `datamodel.xql`.

## What this pack covers

Maps GoCortex Concierge chatbot events into the Cortex XDM
schema. Each event records one of:

- `prompt`         -- inbound user message to `/concierge/chat`
- `response`       -- Concierge model output for `/concierge/chat`
- `context_loaded` -- a `/concierge/load_url` or
  `/concierge/load_text` upload entered the Concierge context
  window (indirect-injection sink)

Stream 4 of 4 in the GoCortex Broken Bank 1.5.0 SIEM contract.
Pairs naturally with XSIAM prompt-injection detection rulesets:
the prompt + response pair from a single `/chat` HTTP request
share the same `turn_id`, and `context_loaded` events expose the
indirect-injection chain via `document_label` /
`context_document_labels`.

Source-of-truth for the wire format and sample payloads:
`attached_assets/Pasted--GoCortex-Broken-Ban-1777803533165_1777803533165.txt`,
section labelled `netbank_concierge`. The producer ships compact
JSON records to a Cortex HTTP collector
(`https://api-MYTENANT.xdr.au.paloaltonetworks.com/logs/v1/event`),
one record per line; the entire JSON object lands in `_raw_log`
and the parser / datamodel pull fields with `json_extract_scalar`.

## Wire format

Single-line JSON per record. Three discriminated variants share a
common envelope; per-variant fields only appear on the matching
variant.

| Field                       | Variants            | Notes                                                      |
| --------------------------- | ------------------- | ---------------------------------------------------------- |
| `timestamp`                 | all                 | ISO8601 with offset; drives `_time`.                       |
| `vendor` / `product`        | all                 | Always `"GoCortex"` / `"Concierge"`.                       |
| `event_type`                | all                 | Discriminator: `prompt` / `response` / `context_loaded`.   |
| `source_ip`                 | all                 | Offender IPv4; literal `"unknown"` collapsed.              |
| `user_agent`                | all                 | UA header; `"unknown"` collapsed.                          |
| `request_method`            | all                 | Always `POST`.                                             |
| `request_path`              | all                 | One of the three Concierge sinks.                          |
| `session_id`                | all                 | 32-char hex; Flask-session-scoped.                         |
| `turn_id`                   | all                 | 32-char hex; prompt + response share one `turn_id`.        |
| `model_name`                | all                 | LLM model tag (e.g. `"SmolLM2-135M-Instruct GGUF Q4_K_M"`).|
| `context_document_count`    | all                 | Length of `context_document_labels`.                       |
| `context_document_labels`   | all                 | Array of context-window labels.                            |
| `prompt_text`               | prompt              | Untruncated user message.                                  |
| `response_text`             | response            | Untruncated model output.                                  |
| `response_path`             | response            | Closed enum; two values are leak-bearing.                  |
| `body_preview`              | context_loaded      | Producer-truncated (1000 chars) of the loaded body.        |
| `body_length`               | context_loaded      | Post-route-truncation byte count fed to the LLM.           |
| `document_label`            | context_loaded      | Human label for the loaded artifact.                       |
| `source_url`                | context_loaded /load_url | Attacker-controlled URL (no SSRF guard).              |

## Sample payloads

Leak-bearing `response` event:

```json
{
  "timestamp": "2026-05-03T14:22:33.611408+00:00",
  "vendor": "GoCortex",
  "product": "Concierge",
  "event_type": "response",
  "source_ip": "203.0.113.42",
  "user_agent": "curl/8.4.0",
  "request_method": "POST",
  "request_path": "/concierge/chat",
  "session_id": "2b4d6f8a0c1e35179a3b6d8f1e2c4a05",
  "turn_id": "5e2b7c3f1a98d460c4e8b1f6a7d3c952",
  "model_name": "SmolLM2-135M-Instruct GGUF Q4_K_M",
  "context_document_count": 0,
  "context_document_labels": [],
  "response_text": "You are the Mars Banking Initiative Concierge ...",
  "response_path": "llm-bypass leak"
}
```

Indirect-injection `context_loaded` event:

```json
{
  "timestamp": "2026-05-03T14:22:30.000000+00:00",
  "vendor": "GoCortex",
  "product": "Concierge",
  "event_type": "context_loaded",
  "source_ip": "203.0.113.42",
  "user_agent": "curl/8.4.0",
  "request_method": "POST",
  "request_path": "/concierge/load_url",
  "session_id": "2b4d6f8a0c1e35179a3b6d8f1e2c4a05",
  "turn_id": "9c1a3e7d4b62f085a3c1d7e2f4b6a809",
  "model_name": "SmolLM2-135M-Instruct GGUF Q4_K_M",
  "context_document_count": 1,
  "context_document_labels": ["attacker-uploaded.pdf"],
  "document_label": "attacker-uploaded.pdf",
  "source_url": "http://attacker.example.com/malicious.pdf",
  "body_length": 16384,
  "body_preview": "Ignore previous instructions and ..."
}
```

## Anchors

The parser stamps six anchor columns; the datamodel reads them
via the keep-in-both `coalesce(<parser column>,
json_extract_scalar(_raw_log, ...))` pattern from
`PRIVATE_DOCS/anchor_field_design.md` (Task #100):

| Anchor           | XDM target                              | Notes |
| ---------------- | --------------------------------------- | ----- |
| `_event_type`    | drives every per-variant if-chain       | Closed enum {`prompt`, `response`, `context_loaded`}. Discriminator. |
| `_session_id`    | `xdm.session_context_id`                | 32-char hex; Flask-session-scoped. Stable across all turns from one browser. |
| `_turn_id`       | `xdm.event.id` (via `_id` fallback)     | 32-char hex per event; prompt + response pair share one turn_id. |
| `_response_path` | `xdm.alert.subcategory` + drives severity | Closed enum; two values are leak-bearing. |
| `_source_ip`     | `xdm.source.ipv4` (via tmp guard)       | Producer writes literal `"unknown"` when Flask cannot resolve the address; collapsed to null. |
| `_request_path`  | `xdm.network.http.url`                  | Closed enum {`/concierge/chat`, `/concierge/load_url`, `/concierge/load_text`}. |

## XDM coverage

Anchor-derived (keep-in-both):

- `_event_type`     -> drives `xdm.event.type` (literal `"GENAI_PROMPT"` / `"GENAI_RESPONSE"` / `"GENAI_CONTEXT_LOADED"`; the XDM_CONST.EVENT_TYPE table has no GenAI taxonomy yet, so the literal keeps the producer's intent visible)
- `_session_id`     -> `xdm.session_context_id` (correlation key for prompt-injection detection rules)
- `_turn_id`        -> `xdm.event.id`, and `xdm.alert.original_alert_id` on leak responses (no separate alert id from the producer; `turn_id` is the natural pivot because the matching prompt event for the same `/chat` HTTP request also carries it -- satisfies WARN-032)
- `_response_path`  -> `xdm.alert.subcategory` (response events only); the two leak-bearing values (`"llm-bypass leak"`, `"llm+leak augmented"`) also drive `xdm.alert.severity = "High"` and flip `xdm.event.outcome` to `OUTCOME_FAILED`
- `_source_ip`      -> `xdm.source.ipv4`
- `_request_path`   -> `xdm.network.http.url`

Secondary fields (pulled at model time, per-variant gated):

- `user_agent`     -> `xdm.source.user_agent` (`"unknown"` collapse)
- `model_name`     -> `xdm.target.application.name`
- `prompt_text`    -> `xdm.event.description` (prompt events only; untruncated)
- `response_text`  -> `xdm.event.description` (response events only; untruncated, may carry leaked credentials)
- `document_label` -> `xdm.target.resource.name` (context_loaded only)
- `source_url`     -> `xdm.target.url` (context_loaded /load_url only -- the URL is itself an attacker-controlled IOC because the route has no SSRF guard)
- `body_length`    -> `xdm.target.sent_bytes` (context_loaded only; the post-route-truncation byte count fed into the Concierge context)
- `body_preview`   -> `xdm.event.description` (context_loaded only; producer-truncated to 1000 chars)

Static / synthesised:

- `xdm.observer.vendor / product`     -> `"GoCortex" / "Concierge"`
- `xdm.target.application.publisher`  -> `"GoCortex"`
- `xdm.network.http.method`           -> `XDM_CONST.HTTP_METHOD_POST` (every Concierge sink is POST-only by spec)
- `xdm.event.outcome`                 -> set on response events only (leak-bearing -> FAILED; else SUCCESS); prompt / context_loaded -> null
- `xdm.alert.severity`                -> literal `"High"` only on the two leak-bearing response paths (the XDM schema declares `alert.severity` as a free-form String -- no `XDM_CONST.SEVERITY_LEVEL_*` enum exists in the engine's schema-of-record)

`context_document_count` and `context_document_labels` are not
mapped: the XDM schema does not expose a clean array path for the
labels list, and the count is redundant with
`len(context_document_labels)`. Detection rules that need the
per-event context-window state read them directly from `_raw_log`
via `json_extract_scalar` / `json_extract_array`. A future XDM
extension that adds a target-resource list path can backfill
without touching the parser.

`body_length` (the post-route-truncation byte count fed into the
Concierge context) goes to `xdm.target.sent_bytes`, NOT to
`xdm.event.description`. The two fields are independent: a 16000
byte body is shown to the LLM, only its first 1000 chars travel
in `body_preview`.

## On the `baselines/` folder

The `baselines/` directory is a living mirror of the current pack
plus its analyser output, refreshed whenever `parser.xql` or
`datamodel.xql` changes materially. It is not a frozen historical
snapshot. Three files are kept in lock-step with the live rules:

- `gocortex_concierge_xdm_model_rule.xql` -- byte-for-byte copy of
  `../datamodel.xql` at the time of the last refresh. Diff target
  for PR review and the canonical input for the analyser baseline.
- `gocortex_concierge_xdm_model_rule.json` -- response from
  `POST /api/analyse` with `ruleType: "modeling"`, pretty-printed.
  Pins the analyser's expected verdict (score, summary counts,
  every violation) so any inadvertent regression in the analyser
  surfaces as a baseline diff in CI.
- `gocortex_concierge_parser.json` -- the same analyser output for
  `../parser.xql` with `ruleType: "parsing"`.
- `sample_logs.txt` -- a small set of representative `_raw_log`
  rows lifted directly from the source-of-truth attached asset.

If you change either rule, refresh all four files in the same
commit. The current analyser baseline is score 89 with two
documented false positives: WARN-025 (the bare `xdm.session_context_id =`
pattern only matters on Trend Micro `_gc_raw` datasets, not on
`gocortex_concierge_raw`) and INFO-011 (standard one-sided IP
mirror -- the upstream LLM endpoint is in-process).
