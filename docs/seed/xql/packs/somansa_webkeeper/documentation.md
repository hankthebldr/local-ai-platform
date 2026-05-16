# Somansa WebKeeper -- XDM Data Model Rule Documentation

Companion notes for `somansa_webkeeper_xdm_model_rule.xql`.

## Anchors

`parser.xql` (in this pack) stamps two anchor columns at ingest time
per the convention in `PRIVATE_DOCS/anchor_field_design.md`. The
MODEL gains a one-token `coalesce()` around each so legacy /
replayed / backfilled rows still derive the same value from
`_raw_log`.

| Anchor | Type | Vocabulary | Source | Purpose |
| ------ | ---- | ---------- | ------ | ------- |
| `_payload_shape` | scalar string | 3 closed values: `PROXY_A`, `PROXY_B`, `SYSTEM` | structural markers inside the WebKeeper payload (`@#Loading-Success`, `,scheme://`) | Per-shape discriminator -- already the rule's primary fan-out filter. Smallest possible useful vocabulary; the textbook anchor. |
| `_proxy_action` | scalar string | ~5 closed values: `Allow`, `Block`, `Warn`, `Bypass`, `Quarantine` | CSV position 1 of the proxy payload (the action verb) | Universal proxy-decision filter. **NULL on SYSTEM rows by design** -- a SYSTEM event has no proxy action, and an analyst running `_proxy_action = "Block"` is by intent excluding system housekeeping rows. |

The null-on-SYSTEM convention for `_proxy_action` is preserved by
both code paths. The parser only stamps a value when
`_payload_shape != "SYSTEM"`. The MODEL fall-back wraps its
derivation in the same `if(_payload_shape != "SYSTEM", ..., null)`
gate so a legacy SYSTEM row that bypasses the parser is also NULL,
not the SYSTEM-row's first CSV position (which would be the
`@#Loading-Success` token, not an action verb). The alternative --
stamping a literal `"SYSTEM"` for system rows -- was deliberately
rejected because it conflates "the action is SYSTEM" with "no action
present".

A finer-grained per-shape split (PROXY_A_HTTP vs PROXY_A_HTTPS,
etc.) was considered and deferred: the existing 3-value vocabulary
already captures the only structural discriminator that meaningfully
narrows the dataset, and a finer split would push above the
"two anchors per dataset is the sweet spot" discipline from
`PRIVATE_DOCS/anchor_field_design.md` without earning its keep.

## Relationship to parser

`datamodel.xql` reads both anchors via the keep-in-both convention
from `PRIVATE_DOCS/anchor_field_design.md`:

```
_payload_shape = coalesce(_payload_shape, <same shape regex over _payload>)
_proxy_action  = coalesce(_proxy_action,
                          if(_payload_shape != "SYSTEM",
                             arrayindex(_csv_parts, 1),
                             null))
```

`_payload_shape` then drives every per-shape `if(_payload_shape =
...)` gate in Stage 7 (XDM type, outcome, log_level, description,
and every source / target / network assignment). `_proxy_action`
flows through `_action_upper` (uppercase fold for verb-map clarity)
into `xdm.event.outcome`, `xdm.event.log_level`, and
`xdm.event.outcome_reason`. Both anchors reach XDM via per-shape
gates and `coalesce()` arms (not `concat()` arguments) so the
analyser does not raise ERR-025 on either intermediate.

The `_time` column is set by the parser from the RFC 3164 syslog
header (year-safe via the canonical Cisco-ISE idiom: parse against
`_insert_time`'s year, roll back one year if the reconstructed
timestamp lands in the future). INFO-005 fires on the parser as an
acknowledgement that year-boundary heuristics are inherently
approximate; the alternative (no `_time`) is worse.

## Scope

Maps Somansa WebKeeper (Korean forward web proxy / URL filter) syslog
records to the Cortex XDM schema. Each record is a single brokered HTTP
transaction or an internal housekeeping event, emitted by the
`pssv_sensor` process and wrapped in a syslog prefix:

```
<PRI>MMM DD HH:MM:SS hostname pssv_sensor[PID]: <PAYLOAD>
```

## Payload shapes

The PAYLOAD presents in three structural shapes (the structural marker
is the discriminator -- PRI is corroborating only):

### PROXY-A (8 CSV fields, no URL)

```
[ts],ACTION,policy,user_id,src_ip,dst_ip,category,subcategory
```

PRI observed: `<142>`. Used for category-only verdicts (e.g. `ACCEPT`
to "검색포털 / Google" or `REJECT` to "3|메신져 / 3|WeChat").

### PROXY-B (9 CSV fields, with URL)

```
[ts],ACTION,policy,user_id,src_ip,dst_ip,domain,full_url,category
```

PRI observed: `<166>`. Used when the requested URL is captured;
trailing category may be `-` (no category), a Korean token, or a
pipe-prefixed numeric-id token.

### SYSTEM (housekeeping / loader event, no CSV body)

```
[ts]@#Loading-Success(<token>)
```

PRI observed: `<150>`. Stubbed only -- observer + `event.type` +
`event.description`. No source/target/network fields set.

## Discriminator (Stage 2, priority order)

| Marker                                                  | Shape    |
| ------------------------------------------------------- | -------- |
| `_payload` contains `@#Loading-Success`                 | SYSTEM   |
| `_payload` contains a `,scheme://` URL marker           | PROXY_B  |
| otherwise                                               | PROXY_A  |

The URL-scheme marker is multi-scheme by design. WebKeeper, like every
Squid-family forward proxy, can broker FTP / FTPS / WebSocket / Gopher
requests in addition to HTTP / HTTPS. Limiting the marker to `https?://`
would silently mis-classify every non-HTTP line as PROXY-A and drop its
URL extraction. The accepted scheme alternation is `https?`, `ftps?`,
`wss?`, `gopher` (case-insensitive).

## Action verb -> outcome / log_level mapping (Stage 4)

| Verb(s)                                              | Outcome / log_level |
| ---------------------------------------------------- | -------------------- |
| `ACCEPT` / `PERMIT` / `ALLOW`                        | OUTCOME_SUCCESS / INFO |
| `REJECT` / `BLOCK` / `DENY` / `DROP`                 | OUTCOME_FAILED / WARN |
| `MONITOR` / `LOG` / `OBSERVE`                        | OUTCOME_PARTIAL / NOTICE |
| `WARN` / `COACH` / `OVERRIDE` / `BYPASS` / `REDIRECT`| OUTCOME_PARTIAL / NOTICE |
| anything else                                        | OUTCOME_UNKNOWN / INFO |

The raw verb is always preserved in `xdm.event.outcome_reason` so the
SOC retains the original vendor decision string regardless of the
canonical outcome bucket.

## IP-address handling (Stage 4)

The `src_ip` / `dst_ip` slots accept either dotted-quad IPv4 or
colon-separated IPv6 (with optional `%zone` identifier). The captured
value is routed to `xdm.source.ipv4` / `xdm.target.ipv4` when it
matches the dotted-quad pattern, and to `xdm.source.ipv6` /
`xdm.target.ipv6` otherwise. WebKeeper logs IPv6 destinations bare (no
brackets) per Squid convention; bracketed IPv6 only appears inside the
URL slot itself.

## Vendor documentation

No public Somansa WebKeeper field reference is available at the time of
writing. The grammar above is sample-driven; KB snapshot 2026-04-27 --
public Somansa product pages only, no detailed log-format reference.

## XDM field mapping summary (17 fields)

### Observer (3 -- all shapes)

- `xdm.observer.vendor` = `"Somansa"`
- `xdm.observer.product` = `"WebKeeper"`
- `xdm.observer.name` = syslog hostname (the WebKeeper sensor host, e.g. `localhost` in the lab sample set)

### Event (5 -- PROXY shapes; 3 -- SYSTEM)

- `xdm.event.type` = `"NETWORK"` (PROXY) | `"STATUS"` (SYSTEM)
- `xdm.event.description` = structured summary (action, client, destination, policy, and (PROXY-B) domain / category)
- `xdm.event.outcome` = mapped from the action verb (see action-verb table above)
- `xdm.event.outcome_reason` = raw action verb verbatim
- `xdm.event.log_level` = banded from the outcome (SUCCESS -> INFO, PARTIAL -> NOTICE, FAILED -> WARN, UNKNOWN -> INFO)

### Source (3 -- PROXY only)

- `xdm.source.ipv4` = client IP when dotted-quad
- `xdm.source.ipv6` = client IP when colon-form
- `xdm.source.user.username` = `user_id` verbatim (numeric like `192837`, symbolic like `Regional_HQ_Alpha`, or future tokens such as `미등록 아이피`)

### Target (4 -- PROXY-B; 2 -- PROXY-A)

- `xdm.target.ipv4` = destination IP when dotted-quad
- `xdm.target.ipv6` = destination IP when colon-form
- `xdm.target.host.hostname` = destination domain (PROXY-B only)
- `xdm.target.url` = full requested URL (PROXY-B only)

### Network (3 -- PROXY-B; 1 -- PROXY-A)

- `xdm.network.http.url` = full requested URL (PROXY-B only; mirror of `xdm.target.url` for HTTP-specific query coverage)
- `xdm.network.http.domain` = host extracted from the URL (PROXY-B only; tolerant of bracketed IPv6 hosts and embedded `user:pass@` credentials)
- `xdm.network.rule` = policy name from the WebKeeper URL-filtering policy slot

## Excluded XDM fields -- not applicable or no source data

- `xdm.alert.*` -- not applicable; network-traffic access log, not a security-alert dataset.
- `xdm.network.http.method` -- WebKeeper does not log the HTTP method; do not fabricate a `GET` default.
- `xdm.network.http.response_code` -- WebKeeper does not log the HTTP status; do not fabricate a `200` default.
- `xdm.network.http.content_type` -- WebKeeper does not log the MIME type returned by the upstream server.
- `xdm.network.http.referrer` -- not present in the WebKeeper log format.
- `xdm.network.http.browser` -- the user-agent string is not logged.
- `xdm.network.http.url_category` -- the trailing CSV slot carries Korean-language and pipe-prefixed numeric tokens (e.g. "검색포털", "미디어스트리밍", "컴퓨터_인터넷_IT", "포털_검색", "접속불가", "인터넷방송_공중파_케이블", "콘텐츠 서버", "3|메신져") that do not round-trip to the canonical `XDM_CONST.URL_CATEGORY` numeric IDs. The raw token is preserved verbatim in `xdm.event.description` for manual analysis. A locale-aware crosswalk is a separate sample-driven follow-up if required.
- `xdm.source.port` / `xdm.target.port` -- ports are not logged in either PROXY shape.
- `xdm.target.sent_bytes` / `xdm.event.duration` -- transferred-byte counts and per-request elapsed time are not logged.
- `xdm.network.ip_protocol` -- all WebKeeper traffic is TCP (the proxy only brokers TCP-based schemes); the protocol is implicit.
- `xdm.session_context_id` -- no session identifier in the access log.

## Pitfalls and edge-case notes for future maintainers

1. **URL-comma greediness.** The current sample set contains no URL with
   an embedded comma, but the format does not forbid them. The PROXY-B
   URL extraction uses positional CSV indexing (index 7) and assumes
   the URL is a single comma-free token. If a future sample shows a
   URL with embedded commas, the rule will mis-attribute the URL tail
   and the trailing category. Mitigation: switch to a structural
   URL-anchor regex of the form
   `,((?:https?|ftps?|wss?|gopher)://.+),([^,]*)$` and rely on
   backtracking from the trailing `,([^,]*)$` to recover the category.
   Documented here, not implemented today, to keep extraction simple
   while no real sample exhibits the case.

2. **Bare-host CONNECT tunnels (PROXY-B-TUNNEL).** When WebKeeper
   brokers an opaque TLS / SSH / arbitrary-TCP CONNECT tunnel, the URL
   slot may be a bare `host[:port]` token with no scheme prefix. No
   such sample is yet on file; the PROXY-B detector requires a scheme
   prefix, so a bare-host tunnel line falls through to PROXY-A and
   loses its URL slot. When a sample arrives, add a sibling Stage-2 arm
   gating on a host:port marker without a scheme prefix and route to a
   new `PROXY_B_TUNNEL` shape.

3. **IPv6 in the URL host.** Bracketed forms like
   `http://[2001:db8::1]:8080/path` are captured intact by the URL
   slot. The domain-extraction regex below uses
   `://(?:[^@/]+@)?(\[[^\]]+\]|[^:/]+)` to match either a bracketed
   IPv6 host or a normal hostname (and to skip embedded `user:pass@`
   credentials), then strips the brackets when assigning the domain.

4. **Placeholder `-` values.** The trailing PROXY-B category slot is
   `-` when no category was assigned. Treat any field equal to `-` as
   null at XDM-assignment time so the description does not carry a
   literal hyphen.

5. **PRI / process-tag / hostname variation.** The syslog-stripping
   regex matches `<\d+>` (any PRI, not just the three observed),
   `pssv_sensor\[\d+\]:` (literal process tag -- if a clustered
   deployment uses a different tag, widen this), and `\S+` for the
   hostname (no character-set assumption beyond non-whitespace). All
   current samples report `localhost` (lab quirk); production installs
   will report FQDNs.

6. **User-id variation.** The `user_id` slot holds either a numeric ID
   (`192837`), a symbolic group/region name (`Regional_HQ_Alpha`), or
   per the existing parser comment a localised unregistered-user token
   (`미등록 아이피`). All values pass through verbatim to
   `xdm.source.user.username`. An empty `user_id` (`""`) becomes null
   at assignment time.

7. **Korean / Hangul token preservation.** Korean category and
   subcategory tokens, including pipe-prefixed forms, are preserved
   verbatim in `xdm.event.description`. UTF-8 in the regex byte stream
   is fine for Cortex `regextract`.

8. **Quoted CSV fields.** WebKeeper output appears unquoted today. If a
   future sample shows quoted `policy_name` or category to escape
   embedded commas, document and extend the regex.

9. **Trailing whitespace / BOM / mixed line endings.** The
   syslog-stripping regex anchors on `<\d+>` at line start and
   captures via `(.+)$` -- robust to trailing whitespace and CRLF
   endings that strip the trailing `\r` naturally.

10. **Truncated lines.** When a single record is truncated mid-URL,
    the URL slot is non-null but the domain-extraction regex yields
    null. The rule preserves the raw URL and leaves
    `xdm.network.http.domain` null rather than emitting a corrupt
    domain string.

11. **Action verbs not seen in the current sample set** (`PERMIT`,
    `ALLOW`, `BLOCK`, `DENY`, `DROP`, `MONITOR`, `LOG`, `OBSERVE`,
    `WARN`, `COACH`, `OVERRIDE`, `BYPASS`, `REDIRECT`) are mapped
    pre-emptively to keep the rule scale-tested against the broader
    Squid-family verb vocabulary. Unknown verbs intentionally fall
    through to `OUTCOME_UNKNOWN` / `LOG_LEVEL_INFORMATIONAL` with the
    raw verb in `xdm.event.outcome_reason` -- never default to
    SUCCESS.

12. **URL-scheme prefix written as `:[/][/]`** (character-class form)
    instead of the literal `://` everywhere it appears inside an XQL
    regex string. This is functionally identical to `://` -- the regex
    still matches scheme prefixes like `http://` -- but it avoids a
    literal `//` substring on a non-comment line. The XQL IDE rule
    engine's static analyser strips inline comments via
    `raw.split("//")[0]`; that helper does not respect string
    boundaries, so a literal `://` inside a regex string truncates the
    line at the first `//` and corrupts paren-depth tracking for all
    downstream stages. The character-class form is the least-invasive
    workaround.

## Body stage notes

- **Stage 1 -- syslog wrapper strip.** Extracts `_payload` (everything
  after `pssv_sensor[PID]: `) and `_syslog_host`.
- **Stage 2 -- structural shape discrimination.** Priority order:
  SYSTEM marker first (its `@#` cannot appear in a CSV proxy line),
  then the multi-scheme PROXY-B URL marker, then PROXY-A as the
  default. The PROXY-B marker uses `,scheme://` so it cannot
  false-positive on a scheme-less hostname in the PROXY-A category
  slot.
- **Stage 3 -- CSV split.** Position 0 is the bracketed timestamp;
  positions 1-5 (action through `dst_ip`) are common to PROXY-A and
  PROXY-B. PROXY-A uses positions 6-7 (category, subcategory); PROXY-B
  uses positions 6-8 (domain, url, category). `_csv_parts` is set for
  SYSTEM rows too but is not consumed downstream because every PROXY
  assignment is gated on `_payload_shape != "SYSTEM"`.
- **Stage 4 -- per-position raw fields and the SYSTEM token.** Each
  extraction references `_csv_parts` (defined in Stage 3) -- no
  sibling references inside this stage, so ERR-024 is satisfied.
- **Stage 5 -- URL host decomposition and raw-field normalisation.**
  `_url_host` is extracted from the PROXY-B URL slot only. The domain
  regex tolerates a bracketed IPv6 host and skips an embedded
  `user:pass@` credential prefix. Brackets, if present, are stripped
  at the XDM-assignment step. `_action_upper` folds the action verb
  to upper case so the verb map in Stage 7 reads cleanly without
  per-arm OR chains. The `-` / empty placeholder normalisation for
  category-style slots is inlined at each consumer rather than hoisted
  into a temp so the rule satisfies ERR-025: a temp whose only
  consumer is a `concat()` body is invisible to Cortex's
  unused-field tracer and would be rejected on `_gc_raw` datasets.
  `_user_id` is the only normalised temp kept here -- it is drained
  directly to `xdm.source.user.username` (a non-`concat` sink) in
  Stage 7, so it survives the unused-field check.
- **Stage 6 -- IPv6 bracket strip.** `_url_host_clean` drops the
  leading `[` and trailing `]` when the host is a bracketed IPv6
  literal so `xdm.network.http.domain` receives the bare address.
  ASCII hostnames are left unchanged.
- **Stage 7 -- XDM drain.** All shape-specific assignments are gated
  on `_payload_shape` so PROXY-A, PROXY-B, and SYSTEM rows each receive only
  their applicable field set without polluting the others. The
  IPv4-vs-IPv6 router uses the dotted-quad pattern as the
  discriminator: matching values go to `xdm.source.ipv4` /
  `xdm.target.ipv4`, anything else (colon-form IPv6, optionally with a
  `%zone` suffix) goes to `xdm.source.ipv6` / `xdm.target.ipv6`.
  SYSTEM rows leave every source / target / network field null.
