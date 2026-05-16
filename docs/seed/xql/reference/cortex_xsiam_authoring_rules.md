<!--
SPDX-FileCopyrightText: GoCortexIO
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Forty-Five Rules for Authoring Cortex XSIAM Data Model and Parsing Rules

A practitioner's guide for engineers who write XQL data-model and parsing
rules against Palo Alto Networks Cortex XSIAM. Opinions baked in. British
informal English. Aimed at the engineer who has to ship a working vendor
integration on Friday and not be paged on Saturday.

---

## Background you need before any of this makes sense

Skip this section if you live in Cortex day to day. Read it if you have not.

**Cortex XSIAM** is Palo Alto Networks' SIEM/XDR platform. Raw vendor logs
(syslog, JSON, key-value, CSV) land in **datasets**. Every dataset is a
table you can query with **XQL**, the platform's SQL-shaped query language.

Two kinds of rule shape what arrives in those datasets and how it looks:

- A **parsing rule** (`[INGEST: vendor = X, product = Y, target_dataset = Z]`)
  runs once at ingest. It can extract columns out of the raw payload,
  rename things, drop unwanted rows, and stamp the canonical `_time`
  field. The columns it writes are *real columns on the dataset* and are
  cheap to filter on later.
- A **data-model rule** (`[MODEL: dataset = X]`) runs every time someone
  queries the dataset. It reads the raw row and emits **XDM (Cortex Data
  Model)** fields -- a vendor-agnostic schema like `xdm.source.ipv4`,
  `xdm.event.outcome`, `xdm.alert.name`. XDM is what the platform's
  analytics, correlations and "smart grouping" features read from.

XDM is not just shape. Cortex's correlation, threat-intel matching and
incident-grouping features all read XDM. A row with no XDM fields is
visible to search but invisible to detection content. A row with patchy
XDM is the worst of both worlds: it shows up in dashboards but never
clusters with related events.

The forty-five rules below are split into five parts:

| Part | Topic | Rules |
| ---- | ----- | ----- |
| A    | Methodology of building a data-model rule | 1-10 |
| B    | Refactoring for shared headers and brevity | 11-20 |
| C    | The ANCHORING concept: parser-side extraction | 21-30 |
| D    | Testing methodology and coverage | 31-36 |
| E    | Smart-grouping XDM fields and pragmatic field-bending | 37-45 |

Every rule has a worked XQL example.

---

## Part A -- Methodology of building a data-model rule (1-10)

### Rule 1: Start from a real ingest sample, never from documentation

The ingest payload is the contract. Vendor docs are an approximation of
the contract. You will discover hostname omission, severity inversion,
multi-line payloads, alternative delimiters and undocumented event
subtypes only by looking at what actually lands in the dataset.

```
dataset = vendor_raw
| limit 100
| fields _raw_log
```

Read the hundred rows. If the vendor sends ten event shapes you will
spot at least eight of them in the first hundred. Code from there.

### Rule 2: Identify the dataset name and the wire format before writing a single line of XQL

Wire formats roughly cluster as: RFC 3164 syslog, RFC 5424 syslog,
JSON-per-line, key-value, CSV, or a vendor-specific binary-ish text.
Each format has a canonical "open the envelope" snippet. Get the
envelope right before you touch any field.

```
// JSON-per-line: parse once at the top of the rule
| alter _msg = json_extract(_raw_log, "$")

// RFC 3164 syslog: pull the priority byte and the body
| alter
    _syslog_priority = to_integer(arrayindex(regextract(_raw_log, "^<(\d{1,3})>"), 0)),
    _syslog_msg      = arrayindex(regextract(_raw_log, "^<\d{1,3}>[A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+(.*)$"), 0)
```

### Rule 3: Catalogue every field in the raw payload once, in a sibling markdown file

Future maintainers should not have to re-derive the field list. A simple
table of "vendor field -> sample value -> notes" pays for itself by the
second person who reads it.

```markdown
| Vendor field    | Example value       | Notes                       |
|-----------------|---------------------|-----------------------------|
| event.code      | 4625                | Windows event id            |
| TargetUserName  | jane.doe            | NULL on machine-account auth|
| IpAddress       | 10.0.4.18           | NULL on local logon         |
```

### Rule 4: Map each vendor field to a canonical XDM path before you guess

Maintain (or use) a reverse-indexed library that says "for vendor field
`SourceUserName`, the canonical XDM path is `xdm.source.user.username`".
This stops three engineers each picking a slightly different XDM target
for the same vendor concept.

```
// Wrong: invented field names
| alter xdm.src.user = SourceUserName

// Right: canonical XDM path from the library
| alter xdm.source.user.username = SourceUserName
```

### Rule 5: Decide each field's bucket: directly mappable, derived, or noise

Three buckets keep the rule honest:

```
// Directly mappable -- straight assignment
| alter xdm.source.ipv4 = client_ip

// Derived -- coalesce, if-chain, regex, or computation
| alter xdm.event.outcome = if(action_code = 1, "SUCCESS", "FAILURE")

// Noise -- explicitly drop so a future reader sees the decision
| fields - debug_blob, internal_seq, vendor_pad_byte
```

### Rule 6: Pick the data-model family up front

Cortex XDM is shaped around event families: process, network, file,
alert, audit, identity. Each family has a sibling-field set you should
populate together. A "network connection" event with no `xdm.target.ipv4`
is a half-mapped event.

| Family   | Headline fields you must populate                                     |
| -------- | --------------------------------------------------------------------- |
| Process  | `xdm.source.process.name`, `xdm.source.process.command_line`, `xdm.source.user.username` |
| Network  | `xdm.source.ipv4`, `xdm.target.ipv4`, `xdm.network.application_protocol` |
| File     | `xdm.target.file.path`, `xdm.target.file.hash.sha256`                   |
| Alert    | `xdm.alert.name`, `xdm.alert.severity`, `xdm.event.type`                |
| Audit    | `xdm.source.user.username`, `xdm.event.operation`, `xdm.event.outcome`  |
| Identity | `xdm.source.user.username`, `xdm.target.user.username`, `xdm.event.outcome` |

### Rule 7: Draft the `[MODEL: dataset = X]` header. One header per dataset per file

Cortex rejects duplicate `[MODEL: dataset = X]` headers in the same
content file. They look like they should compose; they do not. Fan-out
between event shapes lives *inside* the single MODEL block, not across
multiple MODEL blocks.

```
[MODEL: dataset = vendor_raw]

call vendor_envelope
| filter event_kind = "auth"
| alter ...;

call vendor_envelope
| filter event_kind = "network"
| alter ...;
```

### Rule 8: Write the alter block field by field, simplest mappings first

Get five XDM fields working before you touch the if-chains. A working
five-field rule is shippable; a half-built fifteen-field rule is not.

```
// First pass: five direct mappings, ship-ready
| alter
    xdm.observer.vendor  = "Acme",
    xdm.observer.product = "Acme Firewall",
    xdm.source.ipv4      = src_ip,
    xdm.target.ipv4      = dst_ip,
    xdm.network.application_protocol = lowercase(proto)
```

### Rule 9: Add `xdm.event.outcome` with an `if()` mapping vendor action codes

`xdm.event.outcome` is the single highest-leverage field for analytics.
The Cortex enum is `SUCCESS | FAILURE | PARTIAL | UNKNOWN`. Every event
should land in one of those buckets.

```
| alter xdm.event.outcome = if(
    action in ("allow", "permit", "accept"), "SUCCESS",
    action in ("deny", "drop", "block"),     "FAILURE",
    action in ("reset", "rst-both"),         "PARTIAL",
    "UNKNOWN")
```

### Rule 10: Add `xdm.event.description` last, built with `concat()` or `format_string()`

The description is what the SOC analyst reads first. Spend two minutes
making it scannable. Do not include row-unique values like sequence
numbers -- they break grouping (see Rule 42).

```
| alter xdm.event.description = format_string(
    "%s %s connection from %s to %s:%d",
    xdm.observer.product,
    xdm.event.outcome,
    coalesce(xdm.source.ipv4, "unknown"),
    coalesce(xdm.target.ipv4, "unknown"),
    coalesce(xdm.target.port, 0))
```

---

## Part B -- Refactoring efficiencies (11-20)

### Rule 11: When two or more event shapes share more than ~15 lines of header parsing, refactor

Repetition above ~15 lines of identical alter / regex header work is the
threshold where a shared header rule starts paying for itself. Below
that, in-line is fine.

```
// Smell: the same six-line envelope copy-pasted across four pipelines
| alter
    _ts   = arrayindex(regextract(_raw_log, "^<\d+>(\S+ \d+ [\d:]+)"), 0),
    _host = arrayindex(regextract(_raw_log, "^<\d+>\S+ \d+ [\d:]+ (\S+)"), 0),
    _proc = arrayindex(regextract(_raw_log, " (\w+)\["), 0),
    _pid  = arrayindex(regextract(_raw_log, "\[(\d+)\]"), 0),
    _msg  = arrayindex(regextract(_raw_log, "\]: (.*)$"), 0),
    _time = parse_timestamp("%b %d %H:%M:%S", _ts)
```

### Rule 12: Lift the shared envelope into a `[RULE: vendor_syslog_header]` block

A `[RULE: ...]` block is a named, callable fragment. Define it once at
the top of the file, call it from every pipeline.

```
[RULE: vendor_syslog_header]
alter
    _ts   = arrayindex(regextract(_raw_log, "^<\d+>(\S+ \d+ [\d:]+)"), 0),
    _host = arrayindex(regextract(_raw_log, "^<\d+>\S+ \d+ [\d:]+ (\S+)"), 0),
    _proc = arrayindex(regextract(_raw_log, " (\w+)\["), 0),
    _pid  = arrayindex(regextract(_raw_log, "\[(\d+)\]"), 0),
    _msg  = arrayindex(regextract(_raw_log, "\]: (.*)$"), 0),
    _time = parse_timestamp("%b %d %H:%M:%S", _ts);
```

### Rule 13: Each per-shape branch becomes a `;`-terminated pipeline inside the single MODEL block

The shared block fan-out pattern. One MODEL header, many pipelines, each
opening with `call` and a discriminator filter.

```
[MODEL: dataset = vendor_raw]

call vendor_syslog_header
| filter _proc = "named"
| alter xdm.event.type = "DNS Query", ...;

call vendor_syslog_header
| filter _proc = "dhcpd"
| alter xdm.event.type = "DHCP Lease", ...;

call vendor_syslog_header
| filter _proc = "sshd"
| alter xdm.event.type = "Authentication", ...;
```

### Rule 14: Validate exactly one `[MODEL:]` header per (dataset, model) tuple

Multiple MODEL headers for the same tuple are a structural error. They
look like they should compose. They do not. They silently shadow each
other.

```
// Wrong -- second MODEL block shadows the first at runtime
[MODEL: dataset = vendor_raw]
| filter event = "auth"
| alter ...;

[MODEL: dataset = vendor_raw]
| filter event = "network"
| alter ...;

// Right -- one MODEL block, two `;`-terminated pipelines inside it
[MODEL: dataset = vendor_raw]

| filter event = "auth"
| alter ...;

| filter event = "network"
| alter ...;
```

### Rule 15: Replace `if(field != null, field, default)` with `coalesce(field, default)`

Same semantics, shorter, faster, easier to grep.

```
// Wrong
| alter xdm.source.host = if(host_field != null, host_field, syslog_host)

// Right
| alter xdm.source.host = coalesce(host_field, syslog_host)
```

`coalesce` accepts any number of arms and returns the first non-NULL.
That is most of what defensive XDM mapping needs.

### Rule 16: When you see an unfamiliar vendor field, check the field-anchor library first

The same vendor concept (source IP, source user) shows up under fifty
different vendor field names. A reverse-indexed library that says
"`src_ip`, `client_ip`, `SourceIP`, `srcaddr` all map to
`xdm.source.ipv4`" is the difference between two minutes and forty.

```
// Library lookup result: src_ip -> xdm.source.ipv4 (high confidence)
| alter xdm.source.ipv4 = src_ip
```

### Rule 17: End the rule with `| fields - tmp_*, _syslog_*` to drop intermediates

Underscore-prefixed and `tmp_`-prefixed fields are conventionally
intermediate. Drop them before the modelled row goes downstream so
correlation rules see only XDM.

```
| alter
    _proc = arrayindex(regextract(_raw_log, "(\w+)\["), 0),
    xdm.source.process.name = _proc
| fields - _proc, tmp_*
```

### Rule 18: Keep each MODEL pipeline short -- one event shape, end to end

A 200-line pipeline is almost always two event shapes glued together. If
you cannot describe the pipeline in one sentence ("models successful and
failed sshd auth events"), it is two pipelines.

```
// Smell: one pipeline trying to model both DNS query and DNS answer
| filter _proc = "named"
| alter
    xdm.event.type = if(_msg contains "query:", "DNS Query", "DNS Answer"),
    ... fifty more conditional alters

// Better: split into two pipelines, each end-to-end for one shape
| filter _proc = "named" and _msg contains "query:"
| alter xdm.event.type = "DNS Query", ...;

| filter _proc = "named" and _msg contains "answer:"
| alter xdm.event.type = "DNS Answer", ...;
```

### Rule 19: Run a static analyser over the rule before shipping

A lint pass over your rule should find: missing required XDM fields,
invalid coalesce shapes, scalar wrappers around array temps,
unreferenced intermediates, and any structural duplications. Treat
errors as blocking, warnings as worth fixing, hints as advisory.

```
// Pre-flight gate -- typical pass criteria
errors:      0   (blocking)
warnings:    0   (should-fix; only ship with a written exception)
hints/info:  *   (advisory)
```

### Rule 20: Pre-flight against real samples in the Reference Log workbench

Cortex's in-product workbench surfaces field-coverage gaps a static
analyser cannot see -- silent NULLs in fields the analyser thinks you
populated, and shapes the analyser has no test fixture for.

```
// Workbench paste: feed 50 raw rows, inspect the modelled rows
// Look for: NULL in any of the smart-grouping mandatory five
//           (see Rule 37) and any unexpected field-cardinality jumps
```

---

## Part C -- The ANCHORING concept: parser-side extraction (21-30)

### Rule 21: Data-model rules are schema on read -- cheap to store, slow to filter

The MODEL rule fires every time someone runs a query. A regex over
`_raw_log` inside a MODEL rule is paid for, in CPU, on every search of
that dataset by every analyst. Multiply that.

```
// Every analyst search over vendor_raw pays for this regex once per row
[MODEL: dataset = vendor_raw]
| alter _proc = arrayindex(regextract(_raw_log, "\s(\w+)\["), 0)
| filter _proc = "named"
```

### Rule 22: Parser rules are schema on write -- extra storage, but the columns become real

A parsing rule writes columns at ingest. The columns are real on the
dataset, like any other vendor field. Filtering on them is a cheap
column lookup, not a regex over the payload.

```
[INGEST: vendor = "acme", product = "ddi", target_dataset = vendor_raw]
alter _proc = arrayindex(regextract(_raw_log, "\s(\w+)\["), 0)
```

After this parser ships, every row in `vendor_raw` has a `_proc`
column already populated. Searches do not pay for the regex.

### Rule 23: The trade-off is real -- payload size grows by column width times row count

Cortex bills storage. A six-byte column added to a billion-row dataset
is six gigabytes you did not ingest before. Pick anchors that pay for
themselves in query volume; do not pre-extract "in case someone needs
it".

```
// Storage cost back-of-envelope
new_column_bytes_per_row * rows_per_day * 30 = monthly_storage_increment
```

### Rule 24: An anchor field is a small, high-cardinality, high-selectivity discriminator

The right anchor is one that an analyst will use as a `| filter` clause
multiple times per day, and that splits the dataset into useful slices.
Verbose vendor-metadata strings, opaque session ids, and free-text
descriptions are not anchor candidates.

```
// Good anchor: narrow the firehose to one event family per filter
| filter _proc = "named"

// Bad anchor: every row has a different value, so the column never narrows
| filter _session_id = "8a1f...3b2"
```

### Rule 25: A four-value process discriminator is the canonical anchor

The textbook example: a syslog feed carrying four daemons (DNS, DHCP,
SSH, sudo) all into one dataset. An anchor on the daemon name turns
"show me only DNS" from a regex over `_raw_log` into a single column
filter.

```
// Before the anchor parser ships
dataset = ddi_raw
| alter _proc = arrayindex(regextract(_raw_log, "\s(named|dhcpd|sshd|sudo)\["), 0)
| filter _proc = "named"

// After
dataset = ddi_raw
| filter _proc = "named"
```

### Rule 26: Lift the anchor into a parser; Cortex pushes the filter down to the indexed column

Once `_proc` is a real column, Cortex's query planner does the right
thing automatically. You do not have to teach the planner; it spots
the column-equality.

```
[INGEST: vendor = "acme", product = "ddi", target_dataset = ddi_raw]
alter _proc = arrayindex(regextract(_raw_log, "\s(named|dhcpd|sshd|sudo)\["), 0)
```

### Rule 27: Keep the anchor extraction in the data-model rule too -- belt and braces

The parser only sees rows ingested *after* it ships. Backfills, replayed
samples and historical investigations all predate the parser and have
the anchor column NULL. The MODEL rule should fall back so those rows
still model.

The preferred shape is `coalesce(<parser-stamped column>, <regex over _raw_log>)`:

```
[MODEL: dataset = ddi_raw]

call ddi_envelope
| filter coalesce(_proc, arrayindex(regextract(_raw_log, "\s(\w+)\["), 0)) = "named"
| alter ...;
```

The acceptable variant is to re-derive the column independently in the
MODEL rule, which is slightly more CPU on parser-stamped rows but is
trivially safe against backfills. Either way: the MODEL rule must never
*depend* on the parser column being present.

### Rule 28: Pick anchors by selectivity, not popularity

A four-value field that splits 50/30/15/5 is excellent. A four-value
field that splits 99/1/0/0 is not -- you are paying storage for a
column that practically never narrows results.

```
// Selectivity probe before promoting a candidate to an anchor
dataset = vendor_raw
| comp count() as rows by candidate_field
| sort rows desc
```

If the top bucket is more than ~80% of the dataset and the others are
in the noise, the field will not pay for its storage.

### Rule 29: Two anchors per dataset is the sweet spot

The first anchor carves the dataset into event families. The second
anchor narrows within a family (e.g. an integer severity). A third
anchor is almost always paying for indexing you will not use; the
discipline question is "which two columns would I most often want to
filter on first?", not "which columns might be useful?".

```
// Two anchors: process discriminator + severity priority byte
[INGEST: ... target_dataset = ddi_raw]
alter
    _proc     = arrayindex(regextract(_raw_log, "\s(named|dhcpd|sshd|sudo)\["), 0),
    _priority = to_integer(arrayindex(regextract(_raw_log, "^<(\d{1,3})>"), 0))
```

### Rule 30: Ship parser and data-model together as a content pack

One folder per vendor product. Parser, data-model, documentation,
sample logs, and any baseline fixtures all live in one place. Reviewers
read one folder; maintainers update one folder.

```
packs/<vendor_product>/
    parser.xql        # INGEST rule -- anchor columns and _time
    datamodel.xql     # MODEL rule -- XDM mapping
    documentation.md  # what the rule does and why it bends which rules
    samples/
        sample_logs.txt
        sample_output.json
```

---

## Part D -- Testing methodology and coverage (31-36)

### Rule 31: Always know your row count *in* and your row count *out*, per shape

Every change to a model rule should be accompanied by two numbers per
shape: how many raw rows went in, and how many came out the other side
with the headline XDM fields stamped. Coverage is the number that
matters; "did it parse" is not enough.

```
dataset = vendor_raw
| call vendor_envelope
| comp
    raw_rows       = count(),
    has_event_type = countif(xdm.event.type != null),
    has_alert_name = countif(xdm.alert.name != null)
  by _proc
```

If `has_event_type` is below ~95% of `raw_rows` for any non-discarded
shape, you have a coverage hole.

### Rule 32: Test the unhappy path before you ship

The happy path always works. The unhappy path is what bites: NULL
hostnames, missing PRI bytes, kernel ringbuffer chatter, IPv6 where you
assumed IPv4, multi-line payloads, undocumented event subtypes. List
the four or five weird shapes from the raw corpus and prove the rule
either models or drops each one on purpose.

```
// Find rows your rule currently does not handle
dataset = vendor_raw
| call vendor_model_rule
| filter xdm.event.type = null
| comp count() by _proc, lowercase(arrayindex(regextract(_raw_log, "(\w+):"), 0))
```

### Rule 33: Run a shape census *before* you write a single `alter`

A shape census tells you how many distinct event shapes you must model,
their realistic frequencies (so you know where to spend effort), and
whether your discriminator regex has a hole (the NULL bucket).

```
dataset = vendor_raw
| alter _shape = arrayindex(regextract(_raw_log, "<your discriminator regex>"), 0)
| comp count() as rows by _shape
| sort rows desc
```

The `_shape = null` bucket is the one to worry about. If it is more
than 1% of ingest, your regex is missing a shape.

### Rule 34: Diff old vs new mapping field by field on the same rows

When refactoring, run both rule versions over the exact same window and
compare every interesting field. Eyeball comparisons miss silent
regressions.

```
dataset = vendor_raw
| call vendor_model_old as old, vendor_model_new as new
| filter old.xdm.event.type    != new.xdm.event.type
       or old.xdm.alert.name   != new.xdm.alert.name
       or old.xdm.source.ipv4  != new.xdm.source.ipv4
| comp count() by old.xdm.event.type, new.xdm.event.type
```

Every divergent row is either an intentional improvement or a
regression. If you cannot tell which, you are not ready to merge.

### Rule 35: Two-row smoke test before merge -- rarest shape and commonest shape

Pick the rarest shape from your shape census (catches unhappy-path
bugs) and the commonest shape (catches performance and cardinality
bugs). Model both end to end, paste the input and output into the
review. The median always works; do not waste time on the median.

```
// Rarest shape -- e.g. a kernel-wrapped RFC 5424 row that fires twice a week
// Commonest shape -- e.g. a plain RFC 3164 query line that fires twice a second
```

### Rule 36: Freeze a per-pack baseline and wire it into a regression script

Sample 50-200 rows of raw input per pack, freeze them as
`samples/sample_logs.txt`, and freeze the modelled output as
`samples/sample_output.json`. A regression script checks the hash of
both on every commit. Every change must either match the hash or be
re-blessed with a deliberate commit message that says why.

```
// Pseudocode regression script: fail loudly on silent drift
const seen   = sha256(read("samples/sample_logs.txt"));
const golden = sha256(read("samples/sample_output.json"));
assert(seen === recordedSeen,   "raw sample drifted -- did the vendor change format?");
assert(golden === recordedGolden, "modelled output drifted -- which field moved?");
```

---

## Part E -- Smart-grouping XDM fields and pragmatic field-bending (37-45)

Cortex's smart-grouping ("similar incidents", correlation, threat-intel
overlay) reads XDM. A row with patchy XDM is invisible to grouping and
visible to search -- the worst possible state, because it shows up in
dashboards but never clusters with related events.

This part is the cheeky bit. The XDM dictionary has a precise definition
for every field. Smart grouping does not read the dictionary; it reads
what is in the columns. Sometimes you make the columns lie, on purpose,
because the lie produces better incidents. Document the lie.

### Rule 37: Five XDM fields are mandatory for smart grouping

Five fields are non-negotiable on every alert-bearing event:

```
xdm.event.type            -- e.g. "Network Connection", "DNS Query", "Login"
xdm.event.outcome         -- "SUCCESS" | "FAILURE" | "PARTIAL" | "UNKNOWN"
xdm.alert.name            -- short, human-readable, *stable* across same-kind events
xdm.alert.severity        -- "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
xdm.observer.product      -- vendor product string, hard-coded literal
```

NULL on any one of them and the row silently drops out of grouping.
Treat NULL on these as a P1 bug.

```
// Coverage probe -- the five mandatory fields, broken out
dataset = vendor_raw
| call vendor_model_rule
| comp
    rows                = count(),
    missing_event_type  = countif(xdm.event.type      = null),
    missing_outcome     = countif(xdm.event.outcome   = null),
    missing_alert_name  = countif(xdm.alert.name      = null),
    missing_severity    = countif(xdm.alert.severity  = null),
    missing_product     = countif(xdm.observer.product = null)
```

### Rule 38: The identity backbone is the next tier

After the mandatory five, the identity backbone is what grouping uses
to decide *who and what* an alert is about:

```
xdm.source.ipv4 / xdm.source.ipv6
xdm.source.host
xdm.source.user.username
xdm.target.ipv4 / xdm.target.ipv6
xdm.target.host
xdm.target.user.username
xdm.network.application_protocol
```

You do not need all of them on every event -- DNS queries usually have
no `xdm.target.user.username` -- but on every from/to-shaped event you
should have at minimum one source identifier and one target identifier.
A network-connection event with no target is invisible to grouping.

```
// Identity-coverage probe
| comp
    missing_src_id = countif(
        xdm.source.ipv4 = null and xdm.source.host = null and xdm.source.user.username = null),
    missing_tgt_id = countif(
        xdm.target.ipv4 = null and xdm.target.host = null and xdm.target.user.username = null)
```

### Rule 39: Stamp `xdm.observer.{vendor, product, type}` as hard-coded literals at the top of every MODEL block

These three fields are the cheap join keys grouping uses to bucket
events before identity matching. Three string literals at the top of
the rule, never derived, never coalesced, never shape-conditional.

```
| alter
    xdm.observer.vendor  = "Acme",
    xdm.observer.product = "Acme DDI",
    xdm.observer.type    = "DNS"
```

Two pipelines disagreeing on the vendor string ("Acme" vs "ACME" vs
"Acme Inc") become two different products to the grouping engine.
Silent correctness bug.

### Rule 40: Backfill `xdm.target.ipv4` from a sensible source when the event has no protocol-level target

Some event shapes -- DNS queries, sshd auth, sudo -- have a "source"
(the client / user / process) but no obvious target IP at the protocol
level. Strict XDM says leave `xdm.target.ipv4` NULL. Smart grouping then
clumps every targetless event into a single useless mega-incident.

The cheeky fix: backfill from the resolved-answer field if you have
it, otherwise from the source IP (so the event groups by who *asked*).

```
| alter
    xdm.source.ipv4 = client_ip,
    xdm.target.ipv4 = coalesce(resolved_ip, client_ip)
// Why: DNS queries with NXDOMAIN have no answer; we group by client
//      so all queries from one host cluster together rather than
//      forming one global "no target" mega-incident.
```

Document the backfill in the rule comment so the next maintainer knows
the lie is deliberate.

### Rule 41: Promote the "best available host" into `xdm.source.host` via a coalesce chain

Vendors are wildly inconsistent about which field carries the source
host. A coalesce chain in trust order ("most-trustworthy first") gets
the most useful value into the column.

```
| alter xdm.source.host = coalesce(
    device_hostname,
    agent_name,
    syslog_host,
    relay_agent_host,
    arrayindex(regextract(_raw_log, "from\s+([\w\.-]+)"), 0))
```

The XDM dictionary has a strict source-host definition. The grouping
engine just wants any non-NULL string in the column. Give it the best
string you can find.

### Rule 42: Synthesise `xdm.alert.name` when the vendor does not ship one

Many vendors send raw audit records with no friendly alert name. Build
one. It must be human-readable and *stable across events of the same
kind*.

```
| alter xdm.alert.name = concat(
    xdm.observer.product,
    ": ",
    coalesce(event_subtype, event_code, "unknown event"))
```

Never include row-specific values (IPs, usernames, message ids, sequence
numbers). Row-specific values make every event its own group, which is
the same as no grouping.

```
// Wrong -- per-row uniqueness defeats grouping
| alter xdm.alert.name = concat("Failed login from ", source_ip)

// Right -- stable category
| alter xdm.alert.name = "Acme: failed login"
```

### Rule 43: Derive `xdm.event.outcome` from a banded vendor severity number when that is all you have

Some vendors send only an integer severity. XDM wants
`xdm.event.outcome` as one of the four strings. A documented banding
always beats NULL; NULL means the event does not group.

```
| alter xdm.event.outcome = if(
    severity_number >= 7, "FAILURE",
    severity_number >= 4, "PARTIAL",
    severity_number >= 1, "SUCCESS",
    "UNKNOWN")
// Why: vendor X uses syslog severity inverted -- 7 is fatal, 0 is debug.
//      Bands are a judgement call; documented in the rule comment.
```

### Rule 44: Keep the original vendor field as `_<field>_original` whenever you bend its value

Whenever you remap a vendor value to make grouping happy, keep the
original alongside it. Audit trail for the next maintainer; if grouping
behaves oddly, the analyst can see both what the vendor said and what
we decided it meant.

```
| alter
    _alert_severity_original = vendor_severity_string,
    xdm.alert.severity = if(
        lowercase(vendor_severity_string) in ("crit", "critical", "fatal"), "CRITICAL",
        lowercase(vendor_severity_string) in ("err",  "error",    "high"),  "HIGH",
        lowercase(vendor_severity_string) in ("warn", "warning",  "med"),   "MEDIUM",
        lowercase(vendor_severity_string) in ("info", "notice",   "low"),   "LOW",
        "INFO")
```

The underscore-prefixed original survives in the modelled row. No
magic, no "where did this value come from".

### Rule 45: Soft-fail at extraction; never drop a row just because a regex missed

When a regex misses, write a tagged value rather than filtering the row
out. Dropped rows are invisible. Tagged rows are countable.

```
| alter
    _query_name = arrayindex(regextract(syslog_msg, "<query name regex>"), 0),
    xdm.alert.name = coalesce(
        concat("DNS query: ", _query_name),
        "DNS query: unparsed")
```

Pair this with the coverage probe in Rule 31 and you will spot the
"unparsed" bucket the moment it grows past 1% of ingest.

---

## Quick reference: the one query you should run on every change

```
// Coverage census per shape, before and after any model-rule change
dataset = vendor_raw
| call vendor_model_rule
| comp
    rows                = count(),
    missing_event_type  = countif(xdm.event.type        = null),
    missing_outcome     = countif(xdm.event.outcome     = null),
    missing_alert_name  = countif(xdm.alert.name        = null),
    missing_severity    = countif(xdm.alert.severity    = null),
    missing_product     = countif(xdm.observer.product  = null),
    missing_src_id      = countif(
        xdm.source.ipv4 = null and xdm.source.host = null and xdm.source.user.username = null),
    missing_tgt_id      = countif(
        xdm.target.ipv4 = null and xdm.target.host = null and xdm.target.user.username = null)
  by <shape_discriminator>
```

If any of the five mandatory-field counters is non-zero on a non-trivial
bucket, you have work to do before merge.

---

## Cheat sheet of the forty-five rules

**Methodology (1-10)**: real samples; identify wire format; catalogue
fields; map to XDM via a library; bucket each field; pick a family;
one MODEL header; simplest mappings first; outcome with `if()`;
description last.

**Refactoring (11-20)**: 15-line repetition triggers a shared header;
lift to `[RULE: ...]`; one MODEL block, many `;` pipelines; never two
MODELs per tuple; prefer `coalesce`; check the field-anchor library;
drop intermediates; one shape per pipeline; analyser must be clean;
pre-flight in the workbench.

**Anchoring (21-30)**: schema-on-read versus schema-on-write; storage
costs real money; an anchor is small / selective / queried; the canonical
anchor is a process discriminator; lift to a parser; keep in both via
coalesce; selectivity beats popularity; two anchors is the sweet spot;
ship parser and data-model together as a pack.

**Testing (31-36)**: rows in vs rows out per shape; test the unhappy
path; shape census before mapping; diff old vs new on the same window;
two-row smoke test (rarest + commonest); freeze a baseline.

**Smart grouping (37-45)**: the mandatory five (event.type, outcome,
alert.name, severity, observer.product); the identity backbone; hard-code
observer.{vendor,product,type}; backfill `xdm.target.ipv4` from a sensible
source; coalesce the best available host; synthesise alert.name from
stable categories; band severity numbers into outcome strings; keep
`_<field>_original` whenever you bend a value; soft-fail at extraction.
