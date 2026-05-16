# EfficientIP DDI -- Pack Documentation

Companion notes for the EfficientIP DDI pack at
`PRIVATE_DOCS/packs/efficientip_ddi/`. The pack ships two rule
files that work together:

- `parser.xql` -- INGEST rule. Pre-extracts two anchor columns
  (`_syslog_proc`, `_syslog_priority`) from `_raw_log` once at
  ingest, plus `_time` from the syslog header. See "Parser:
  anchor extraction" below for the analyst-facing impact and
  `PRIVATE_DOCS/anchor_field_design.md` for the underlying
  concept.
- `datamodel.xql` -- MODEL rule. The four-daemon mapping that
  this document covers in full. Its shared
  `[RULE: efficientip_syslog_header]` block derives the two
  anchor fields via `coalesce(<parser column>, <regex over
  _raw_log>)` (the keep-in-both convention from
  `PRIVATE_DOCS/anchor_field_design.md`, adopted in Task #96), so
  parser-stamped rows benefit from the indexed column while legacy
  rows ingested before the parser shipped -- and any sample data
  replayed through XQL -- still model identically by falling back
  to the regex. The parser is therefore purely additive: enabling
  it does not change data-model output.

## Parser: anchor extraction

The parser is the first worked example of the ANCHOR pattern in
this codebase. It writes two anchor columns to every ingested
`efficientip_raw` row:

| Anchor              | Vocabulary                            | What it lets the analyst do          |
| ------------------- | ------------------------------------- | ------------------------------------ |
| `_syslog_proc`      | `{named, dhcpd, sshd, sudo}` (4)      | Filter to one daemon in O(column)    |
| `_syslog_priority`  | `{0..191}` integer (PRI byte)         | Filter on syslog severity / facility |

Analyst search experience changes from:

```
dataset = efficientip_raw
| alter _proc = arrayindex(regextract(_raw_log, "\s(named|dhcpd|sshd|sudo)\["), 0)
| filter _proc = "named"
```

to:

```
dataset = efficientip_raw
| filter _syslog_proc = "named"
```

Cortex pushes the second filter down to a column-equality test on
parser-stamped rows, instead of running the regex over every
row's `_raw_log` text. On an interactively-used multi-shape
dataset this is the difference between sub-second response and a
minute-plus regex scan.

The MODEL rule (`datamodel.xql`) consumes these anchor columns
via the keep-in-both convention (Task #96): its shared
`[RULE: efficientip_syslog_header]` block derives both
`_syslog_proc` and `_syslog_priority` as
`coalesce(<parser-stamped column>, <regex over _raw_log>)`, so
parser-stamped rows skip the regex (one column read plus a
`coalesce` short-circuit) and rows ingested before the parser
shipped -- including replayed sample data and backfills -- still
model identically by falling back to the same regex the rule has
always run. This is the preferred shape described in
`PRIVATE_DOCS/anchor_field_design.md` and applies to both the
RFC 3164 and the RFC 5424-in-kernel envelope arms inside the
shared header rule. The other five header intermediates
(`_syslog_pid`, `_syslog_host`, `_syslog_msg`, `_syslog_facility`,
`_syslog_severity`) are not anchors and are derived from
`_raw_log` only.

## Scope

Maps EfficientIP DDI (SOLIDserver) appliance syslog events to the
Cortex XDM schema. The appliance ships syslog from four daemons
running side-by-side on the same physical box, in two envelope
shapes (see "Log format" below):

| Daemon  | Role                  | Primary XDM destination          |
| ------- | --------------------- | -------------------------------- |
| `named` | BIND DNS server       | `xdm.network.dns.*`              |
| `dhcpd` | ISC DHCP server       | `xdm.network.dhcp.*`             |
| `sshd`  | Operator SSH login    | `xdm.event.*`, `xdm.source.user.*` |
| `sudo`  | Privileged operations | `xdm.target.user.*`, `xdm.target.process.*` |

FreeBSD platform `devd[]` lines, `ipmserver[]` internal RPC, and
unwrapped `kernel:` ipfw rules are dropped at the allow-list
filter inside the shared header rule: anything that is not one of
the four supported daemons (in either envelope shape) cannot
reach a stanza body.

## Dataset

`efficientip_raw`. The file declares a single
`[MODEL: dataset = efficientip_raw]` header (Task #89 refactor:
the four daemons now sit as four `;`-terminated pipelines inside
that one MODEL block, each opening with a `call` to the shared
header rule -- see "Shared header rule" below).

## Shared header rule (`efficientip_syslog_header`)

Sits at the top of the rule file as a standalone `[RULE: ...]`
block. Every daemon pipeline inside the MODEL block begins with
`call efficientip_syslog_header` followed by a single daemon-specific
filter (`| filter _syslog_proc = "named"`, etc.). The shared rule
is responsible for two things:

1. **Allow-list filter.** Drops every line that is not one of the
   four supported daemons in either envelope shape, before the
   header parsing runs. Each daemon pipeline therefore only has
   to defend against the daemons it cares about.
2. **Header field extraction.** Produces the seven canonical
   `_syslog_*` intermediates that all four daemon pipelines consume:
   `_syslog_priority` / `_syslog_facility` / `_syslog_severity`
   (numeric), `_syslog_host` / `_syslog_pid` / `_syslog_proc` /
   `_syslog_msg` (string). Each capture has a primary regex for
   the RFC 3164 shape and a coalesce fallback for the
   RFC 5424-in-kernel shape so a single set of intermediates
   feeds both envelopes. The two anchor intermediates
   (`_syslog_priority`, `_syslog_proc`) additionally coalesce
   the parser-stamped column from `parser.xql` ahead of those
   regex arms (Task #96 keep-in-both convention).

The pattern is borrowed from the BeyondTrust PRA
(`beyondtrust_pra_common_fields_modeling`) and VMware ESXi
(`esxi_general_fields_mapping`) modeling rules in
`PRIVATE_DOCS/all_modeling_rules.txt`. It is the canonical way
to share parsing logic across multiple MODEL stanzas in Cortex
XQL: the `[RULE: name]` block is inlined at every `call name`
site at compile time.

## Sample payloads

EfficientIP appliances usually ship without a syslog hostname
(15 of 16 production samples in the Task #86 corpus omit the host
token). The hostname-less shape is therefore the canonical
example; the hostname-bearing shape is shown as a secondary
variant. The full sample corpus lives in
`PRIVATE_DOCS/packs/efficientip_ddi/baselines/sample_logs.txt`.

```
# named -- query (hostname-less, canonical)
<30>Apr 28 06:29:52 named[67652]: client @0x24da0c7a350 10.96.137.144#39023 (sas-050-2531550752.simondomain.com.au): query: sas-050-2531550752.simondomain.com.au IN A + (10.96.236.53)

# named -- query (with hostname, secondary variant)
<30>Apr 28 04:00:55 simonserver named[18760]: client @0x10590c05710 10.101.96.134#64011 (sigre123.sigre.com.au): query: sigre123.sigre.com.au IN A + (10.101.139.193)

# named -- answer (recursive resolver response with rcode)
<30>Apr 28 06:59:22 ho2kygdds33 named[33020]: client @0x17a0992fb2d0 10.111.72.9#38677 (cdn.samsungcloudsolution.com): answer: cdn.samsungcloudsolution.com IN A + (10.107.255.193) -> NOERROR ...

# named -- dynamic update (RFC 2136)
<30>Apr 28 09:59:07 named[31522]: client @0x21dafb594910 111.16.121.200#39206: updating zone 'simon.com.au/IN': adding an RR at 'cd189252.simondomain.com.au' A 172.27.2.18

# named -- dynamic update denied
<27>Apr 28 09:59:07 named[31522]: client @0x21daf49429d0 10.8.36.1#56531: update '_msdcs.simondomain.com.au/IN' denied

# named -- IXFR zone transfer started
<30>Apr 28 16:54:41 named[31522]: client @0x21daf95c7310 111.16.121.200#12960 (simondomain.com.au): transfer of 'simondomain.com.au/IN': IXFR started (serial 2150543386 -> 2150543387)

# named -- zone transfer completion (zone-keyed, no client triple)
<30>Apr 28 07:02:41 named[31209]: zone 10.in-addr.arpa/IN: transferred serial 18121600

# named -- lame server resolving
<30>Apr 28 17:02:54 named[31491]: lame server resolving 'internetproxy.k8s.au.simogroup.net' (in 'k8s.au.singtelgroup.net'?): 111.16.22.113#53

# named -- sending notifies
<30>Apr 28 17:02:55 named[31491]: zone simon.com.au/IN: sending notifies (serial 2150543647)

# named -- response rate limiting
<30>Apr 28 17:01:33 named[32554]: client @0x1511d8cf1a50 10.222.200.16#41146 (vision-...): would rate limit slip response to 10.120.200.0/24 for vision-... IN A  (138956d9)

# dhcpd -- DHCPACK with relay agent (hostname-bearing)
<30>Apr 28 14:52:47 h22rrgdds33 dhcpd[33036]: DHCPACK on 10.21.196.207 to 2a:00:b4:00:e9:d0 via 10.111.196.1 [14400]

# dhcpd -- DHCPREQUEST ignored (hostname-less)
<30>Apr 28 17:00:18 dhcpd[30107]: DHCPREQUEST for 172.22.81.216 (161.43.151.7) from 08:00:1b:2a:1c:b8 via 172.99.99.253: ignored (unknown subnet).

# sshd -- accepted publickey login
<86>Apr 28 09:14:22 ddi-mgmt sshd[44512]: Accepted publickey for opadmin from 10.10.0.7 port 50642 ssh2

# sudo -- privileged command audit
<85>Apr 28 11:02:47 ddi-mgmt sudo[51331]: opadmin : TTY=pts/0 ; PWD=/home/opadmin ; USER=root ; COMMAND=/usr/sbin/service named restart

# devd[] -- DROPPED by the top-of-stanza allow-list
<14>Apr 28 03:59:06 devd[14570]: Processing event '!system=CAM subsystem=periph type=error device=da0 serial="..."'
```

Every stanza begins with the same allow-list filter
(`\s(named|dhcpd|sshd|sudo)\[\d+\]:`) followed by the daemon-specific
filter, so the `devd[]`, `ipmserver[]`, and `kernel:` lines never
reach any stanza body.

## Log format

RFC 3164 BSD syslog with optional hostname (most appliances omit it):

```
<PRI>MMM DD HH:MM:SS [HOSTNAME] PROC[PID]: BODY
```

`<PRI>` is parsed into `_syslog_priority` (integer) then split into
`_syslog_facility` and `_syslog_severity` using the standard
`floor(divide(.., 8))` / `subtract(.., multiply(.., 8))` formula.

### named -- BIND line-shape discriminator

The DNS stanza does not have one body shape; BIND emits at least
eleven distinct line shapes. The rule classifies each line into
`_dns_action` early, so the body extractions can stay shape-aware
and one shape's null capture cannot poison another's XDM mapping
(see Drift section -- this is the bug that caused the prior
revision to silently drop DNS, DHCP, and SSH events on the user's
tenant).

| `_dns_action`   | Body anchor                                | Operation surface                  |
| --------------- | ------------------------------------------ | ---------------------------------- |
| `QUERY`         | `client ...: query:`                       | dns_question.*, source.*           |
| `ANSWER`        | `client ...: answer: ... -> RCODE`         | dns_question.*, response_code, is_response = TRUE |
| `UPDATE_ADD`    | `client ...: updating zone '<z>': adding`  | dns_question.* (target RR), target.resource.name = zone, opcode = 5 |
| `UPDATE_DELETE` | `client ...: updating zone '<z>': deleting`| dns_question.* (target RR), target.resource.name = zone, opcode = 5 |
| `UPDATE_DENIED` | `client ...: update '<n>' denied`          | dns_question.name = `<n>`, opcode = 5, outcome = FAILED, outcome_reason = "denied" |
| `IXFR`          | `client ...: transfer of '<z>': IXFR`      | target.resource.name = zone, sub_type = "IXFR" |
| `AXFR`          | `client ...: transfer of '<z>': AXFR`      | target.resource.name = zone, sub_type = "AXFR" |
| `RATELIMIT`     | `client ...: would rate limit`             | dns_question.* (response RR), outcome = FAILED, outcome_reason = "slip"\|"drop", optional response_code = NXDOMAIN |
| `XFER_DONE`     | `zone <z>: transferred serial N`           | target.resource.name = zone (serial preserved in description) |
| `NOTIFY`        | `zone <z>: sending notifies (serial N)`    | target.resource.name = zone, opcode = 4 |
| `LAME`          | `lame server resolving '<n>' (in '<z>'?): IP#PORT` | dns_question.name = `<n>`, target.resource.name = zone, intermediate.ipv4/ipv6 = IP, intermediate.port = PORT, outcome = FAILED |
| `OTHER`         | anything that did not match above          | xdm.event.type = "DNS" only        |

`OTHER` is the safety-net branch: even unrecognised BIND lines
still receive `xdm.event.type = "DNS"` and the syslog header
fields, so they show up in dataset breakdowns and are not silently
discarded.

### named -- shared body captures

| Token            | Captured into          | XDM destination                          | Shapes that populate it |
| ---------------- | ---------------------- | ---------------------------------------- | ----------------------- |
| `CLIENT_IP`      | `_client_ip`           | `xdm.source.ipv4` / `xdm.source.ipv6`    | QUERY, ANSWER, UPDATE_*, IXFR, AXFR, RATELIMIT, UPDATE_DENIED |
| `CLIENT_PORT`    | `_client_port`         | `xdm.source.port`                        | same as above           |
| `QNAME`          | `_query_name`          | `xdm.network.dns.dns_question.name`      | QUERY, ANSWER, UPDATE_ADD, UPDATE_DELETE, UPDATE_DENIED, RATELIMIT, LAME |
| `CLASS`          | `_query_class`         | `xdm.network.dns.dns_resource_record.class` | QUERY, ANSWER, UPDATE_*, IXFR, AXFR, RATELIMIT |
| `TYPE`           | `_query_record_type`   | `xdm.network.dns.dns_question.type`      | QUERY, ANSWER, UPDATE_ADD, UPDATE_DELETE, RATELIMIT |
| `FLAGS`          | `_query_flags`         | `xdm.network.ip_protocol`, transport in protocol_layers | QUERY, ANSWER |
| `LISTENER_IP`    | `_dns_listener_ip`     | `xdm.intermediate.ipv4` / `xdm.intermediate.ipv6` | QUERY, ANSWER (trailing `(<ip>)`) |
| `RCODE`          | `_rcode`               | `xdm.network.dns.response_code`, drives outcome | ANSWER (after `->`), RATELIMIT NXDOMAIN |
| `ZONE`           | `_dns_zone`            | `xdm.target.resource.name`               | UPDATE_*, IXFR, AXFR, XFER_DONE, NOTIFY, LAME |
| `DIAG_IP/PORT`   | `_dns_diag_ip` / `_dns_diag_port` | `xdm.intermediate.ipv4/ipv6`, `xdm.intermediate.port` | LAME (the upstream resolver flagged as lame) |
| `RATELIMIT_VERB` | `_dns_ratelimit_verb`  | `xdm.event.outcome_reason` (slip\|drop)  | RATELIMIT               |

`xdm.network.dns.is_response` is `TRUE` for ANSWER lines and
whenever a rcode mnemonic was captured; `FALSE` otherwise.
`xdm.network.dns.opcode` defaults to `0` (QUERY) for QUERY/ANSWER,
`5` (UPDATE) for UPDATE_*, and `4` (NOTIFY) for NOTIFY -- BIND
omits the explicit opcode token for the default cases.

### dhcpd lease lifecycle body

The first whitespace-delimited token of the body is the message
type. The `_dhcp_msg_type` discriminator additionally normalises
`client` -> `DHCPDUPLICATE` and `storm` -> `DHCPSTORM` to match the
upstream DHCP_MESSAGE_TYPE enum naming.

Captured fields and their XDM destinations:

| Capture                       | XDM destination                          |
| ----------------------------- | ---------------------------------------- |
| `_dhcp_acknowledged_ip`       | `xdm.network.dhcp.yiaddr` (DHCPACK arm)  |
| `_dhcp_not_acknowledged_ip`   | `xdm.network.dhcp.yiaddr` (DHCPNAK arm)  |
| `_dhcp_offered_ip`            | `xdm.network.dhcp.yiaddr` (DHCPOFFER arm) |
| `_dhcp_bootstrap_server_ip`   | `xdm.network.dhcp.siaddr`, `xdm.target.ipv4` |
| `_dhcp_client_ip`             | `xdm.source.ipv4`, `xdm.network.dhcp.ciaddr` |
| `_dhcp_expired_lease_ip`      | `xdm.source.ipv4`, `xdm.network.dhcp.ciaddr` |
| `_dhcp_requested_ip`          | `xdm.network.dhcp.requested_address`     |
| `_dhcp_client_mac`            | `xdm.network.dhcp.chaddr`, `xdm.source.host.mac_addresses` |
| `_dhcp_client_hostname`       | `xdm.network.dhcp.client_hostname`       |
| `_dhcp_client_interface`      | `xdm.source.interface`                   |
| `_dhcp_client_uid`            | `xdm.source.host.device_id`              |
| `_dhcp_lease_duration`        | `xdm.network.dhcp.lease`                 |
| `_dhcp_relay_agent_ip`        | `xdm.network.dhcp.giaddr`, `xdm.intermediate.ipv4` |
| `_dhcp_target_network`        | `xdm.target.subnet`                      |
| `_dhcp_msg_suffix`            | `xdm.event.outcome_reason`               |
| `_dhcp_is_renewal`            | `xdm.event.operation_sub_type` ("RENEW") |

`xdm.event.outcome` is mapped from the DHCP message type:
`DHCPACK` / `DHCPLEASEQUERYDONE` -> SUCCESS;
`DHCPDECLINE` / `DHCPNAK` / `DHCPLEASEUNKNOWN` -> FAILED; and any
suffix containing `failed` or `abandoned` -> FAILED. All other types
(state-machine notifications such as DHCPDISCOVER, DHCPREQUEST,
DHCPINFORM) leave `outcome` null because they describe a step in the
exchange rather than its result.

### sshd login body

The first alphabetic word of the body is the action verb (Accepted,
Failed, Connection, Received, Disconnect, Invalid, Disconnected,
Reverse, Error). It is upper-cased into `_ssh_act` and assigned to
`xdm.event.operation_sub_type`. Anchored captures replace the
original rule's broken `[^\:|\d+]+\:\s` character class:

| Capture            | Source pattern                                              | XDM destination          |
| ------------------ | ----------------------------------------------------------- | ------------------------ |
| `_ssh_user`        | `(?:for invalid user|for|user)\s+(\S+)\s+from` then `by ...` then `user=` | `xdm.source.user.username` |
| `_ssh_client_ipv4` | `from\s+(...)` then `by ... (...)\s+port` (IPv4 literal)    | `xdm.source.ipv4`        |
| `_ssh_client_ipv6` | `from\s+(...)` then `by ... (...)\s+port` (IPv6 literal)    | `xdm.source.ipv6`        |
| `_ssh_client_port` | `port\s+(\d+)`                                              | `xdm.source.port`        |

`xdm.event.outcome` is SUCCESS for `ACCEPTED` / `DISCONNECTED` and
FAILED for `FAILED` / `INVALID` / `ERROR` / `REVERSE`.

### sudo command audit body

Standard sudo line:

```
USER : TTY=tty ; PWD=/path ; USER=tgt_user ; COMMAND=/cmd args
```

Captures:

| Capture          | Source pattern                       | XDM destination                          |
| ---------------- | ------------------------------------ | ---------------------------------------- |
| `_sudo_src_user` | `^(\S+)\s+:\s+TTY=`, then `'?[^'\s:]+` | `xdm.source.user.username`               |
| `_sudo_tgt_user` | `USER=(\S+?)\s*;?`                   | `xdm.target.user.username`               |
| `_sudo_pwd`      | `PWD=([^;]+?)\s*;`                   | `xdm.target.process.executable.path`     |
| `_sudo_cmd`      | `COMMAND=(.+)$`                      | `xdm.target.process.command_line`        |
| `_syslog_host`   | from the syslog header               | `xdm.source.host.hostname`, `xdm.observer.name` |

The quoted-string fallback for `_sudo_src_user` keeps compatibility
with non-standard sudo wrappers that quote the body.

## XDM field summary

Across the four stanzas the rule populates the following XDM paths.
Empty cells mean the stanza does not produce that field.

| XDM path                                       | DNS | DHCP | SSH | sudo |
| ---------------------------------------------- |:---:|:----:|:---:|:----:|
| `xdm.observer.vendor`                          |  X  |  X   |  X  |  X   |
| `xdm.observer.product`                         |  X  |  X   |  X  |  X   |
| `xdm.observer.name`                            |  X  |  X   |  X  |  X   |
| `xdm.event.type`                               |  X  |  X   |  X  |  X   |
| `xdm.event.description`                        |  X  |  X   |  X  |  X   |
| `xdm.event.log_level`                          |  X  |  X   |  X  |  X   |
| `xdm.event.outcome`                            |  X  |  X   |  X  |      |
| `xdm.event.outcome_reason`                     |  X  |  X   |     |      |
| `xdm.event.operation_sub_type`                 |  X  |  X   |  X  |      |
| `xdm.network.application_protocol`             |  X  |  X   |  X  |  X   |
| `xdm.network.protocol_layers`                  |  X  |  X   |  X  |  X   |
| `xdm.network.ip_protocol`                      |  X  |      |     |      |
| `xdm.network.dns.dns_question.name`            |  X  |      |     |      |
| `xdm.network.dns.dns_question.type`            |  X  |      |     |      |
| `xdm.network.dns.dns_resource_record.class`    |  X  |      |     |      |
| `xdm.network.dns.opcode`                       |  X  |      |     |      |
| `xdm.network.dns.is_response`                  |  X  |      |     |      |
| `xdm.network.dns.response_code`                |  X  |      |     |      |
| `xdm.network.dhcp.message_type`                |     |  X   |     |      |
| `xdm.network.dhcp.chaddr`                      |     |  X   |     |      |
| `xdm.network.dhcp.ciaddr`                      |     |  X   |     |      |
| `xdm.network.dhcp.giaddr`                      |     |  X   |     |      |
| `xdm.network.dhcp.siaddr`                      |     |  X   |     |      |
| `xdm.network.dhcp.yiaddr`                      |     |  X   |     |      |
| `xdm.network.dhcp.lease`                       |     |  X   |     |      |
| `xdm.network.dhcp.requested_address`           |     |  X   |     |      |
| `xdm.network.dhcp.client_hostname`             |     |  X   |     |      |
| `xdm.source.ipv4` / `xdm.source.ipv6`          |  X  |  X   |  X  |      |
| `xdm.source.port`                              |  X  |      |  X  |      |
| `xdm.source.host.hostname`                     |  X  |      |     |  X   |
| `xdm.source.host.device_id`                    |     |  X   |     |      |
| `xdm.source.host.mac_addresses`                |     |  X   |     |      |
| `xdm.source.interface`                         |     |  X   |     |      |
| `xdm.source.user.username`                     |     |      |  X  |  X   |
| `xdm.source.process.name` / `.pid`             |  X  |  X   |  X  |  X   |
| `xdm.target.ipv4`                              |     |  X   |     |      |
| `xdm.target.subnet`                            |     |  X   |     |      |
| `xdm.target.resource.name`                     |  X  |      |     |      |
| `xdm.target.user.username`                     |     |      |     |  X   |
| `xdm.target.process.command_line`              |     |      |     |  X   |
| `xdm.target.process.executable.path`           |     |      |     |  X   |
| `xdm.intermediate.ipv4` / `.ipv6`              |  X  |  X   |     |      |
| `xdm.intermediate.port`                        |  X  |      |     |      |

## Drift from plan

### Task #86 -- silent runtime drop diagnosis (April 2026)

The Task #83 rewrite scored 97 / 0 errors on the local analyser and
deployed cleanly to the user's tenant, but in production only the
sudo stanza populated `xdm.event.type`. DNS, DHCP, and SSH rows
landed in `efficientip_raw` (so parser routing was correct) but
their entire `alter` blocks were silently discarded by Cortex.

The single high-suspicion line in the DNS stanza:

```
xdm.network.protocol_layers = arraycreate(
    "DNS",
    if(_query_flags ~= "T", "TCP", "UDP"))
```

For every non-`query:` BIND line shape (answer, update, transfer,
notify, lame, ratelimit, etc.) `_query_flags` is null. Cortex XQL
evaluates `null ~= "T"` to null, which makes the inner `if` return
null, which produces `arraycreate("DNS", null)` -- an
`array<string>` with a null element. Cortex then **silently
discards the entire enclosing `alter` statement**, so no XDM field
in that `alter` (including `xdm.event.type`) is ever assigned. The
local analyser does not detect this pattern. The rule now wraps
every `arraycreate(...)` containing a non-literal element in an
explicit `if(... != null, arraycreate(...))` guard:

```
xdm.network.protocol_layers = if(
    _query_flags != null,
    arraycreate("DNS", if(_query_flags ~= "T", "TCP", "UDP")),
    arraycreate("DNS"))
```

The same defensive convention is applied to the DHCP and SSH
stanzas: every `arraycreate` whose element comes from an
extraction is gated behind a `!= null` check (for example
`xdm.source.host.mac_addresses` in the DHCP stanza), and every
`if`-chain comparing a potentially-null intermediate against a
literal uses the `_field != null and _field = "value"` form so a
null comparison cannot return null and poison the enclosing
expression.

### Task #86 -- per-stanza bisect, evidence vs inference

The user could not run live tenant queries during this task, so
the per-stanza diagnosis is based on inference from the rule
source plus the architect review's confirmation that the
arraycreate-with-null-element pattern is the strongest candidate
for the observed symptom. The inference, stanza by stanza:

- **DNS (DIRECT EVIDENCE).** The single offending alter line was
  `xdm.network.protocol_layers = arraycreate("DNS",
  if(_query_flags ~= "T", "TCP", "UDP"))`. For every non-`query:`
  shape (10 of the 11 BIND shapes the rule now recognises)
  `_query_flags` is null, so the inner `if` returns null, so the
  `arraycreate` carries a null element, so Cortex discards the
  enclosing `alter` and `xdm.event.type` is never set. The
  user's symptom ("DNS, DHCP, SSH all silent except sudo") is
  consistent with this offender being present in the DNS stanza
  *and* sibling offenders being present in DHCP and SSH (because
  every BIND query line still has `_query_flags` set, yet even
  query-only lines were silent on the tenant -- so the DNS arm
  must have a separate hazard too, not just the non-query arms).
  The defensive rewrite addresses both possibilities by
  null-guarding *every* `arraycreate` that takes a non-literal
  argument.
- **DHCP (HIGH-CONFIDENCE INFERENCE).**
  `xdm.source.host.mac_addresses = arraycreate(_dhcp_client_mac)`
  is the analogous pattern -- and `_dhcp_client_mac` is null on
  several DHCP message types (DHCPSTORM, DHCPDUPLICATE, server
  startup messages, lease abandonment). The rewrite null-guards
  this `arraycreate` and changes the outcome-suffix `if`-chain
  to `_dhcp_msg_suffix != null and _dhcp_msg_suffix ~= "..."` so
  null suffixes cannot poison the outcome assignment.
- **SSH (HIGH-CONFIDENCE INFERENCE).** SSH uses
  `arraycreate("SSH")` (literal-only) so the SSH stanza has no
  null-array hazard, but the operation-sub-type `if`-chain
  compared the captured action verb against literal arms using
  the unsafe `_ssh_act = "ACCEPTED"` form. Null `_ssh_act`
  values would propagate null through the chain. The rewrite
  guards every comparison with `_ssh_act != null and ...`. (If
  SSH was reaching the tenant before but DNS / DHCP were not,
  this stanza may have been collateral from a different alter
  drop -- the defensive rewrite covers either way.)
- **sudo (BASELINE).** sudo was the only stanza populating XDM
  in production, which confirms the parser routing is correct
  and that the issue is per-stanza alter-drop, not a
  catch-all infrastructure problem. The sudo stanza already
  used null-safe patterns and is unchanged functionally.

After the redeploy, the two verification queries at the end of
this section will confirm or refute the inference; if any shape
still returns zero, the per-stanza section above tells the next
operator exactly which alter to bisect.

### Task #86 -- additional XQL semantic notes for the next rewrite

- `_field = null` does **not** detect nulls in Cortex XQL. The
  comparison evaluates to null (not true), so `if(_field = null,
  ...)` arms never fire. Use `_field != null` plus an explicit
  positive arm, or `is_null(_field)` in tools that support it.
- The `in (...)` operator is null-safe: `null in ("a", "b")`
  returns false, not null.
- `coalesce(...)` skips null arms but propagates an `arraycreate`
  with a null element if you build the array first. Always wrap
  the `arraycreate` itself with a null-guard, not the coalesce.
- Single-token diagnostic lines that do not match any
  `_dns_action` keyword still receive `xdm.event.type = "DNS"`
  via the `OTHER` safety branch -- this is intentional so dataset
  breakdowns surface them rather than silently dropping them.

### Task #86 -- DNS stanza coverage extension

The DNS stanza was extended from one line shape (`query:`) to
eleven via the `_dns_action` discriminator. The `_dns_listener_ip`
regex was tightened from `[\da-fA-F:.]+` to `(IPv4-or-IPv6
literal)` so the BIND internal hash token at the end of rate-limit
lines (e.g. `(138956d9)`) is excluded -- it is a 32-bit RRL hash,
not an IP literal. The `_dns_zone`, `_dns_diag_ip`, and
`_dns_ratelimit_verb` intermediates are new. `xdm.target.resource.name`
is new and carries the BIND zone for UPDATE / TRANSFER / XFER_DONE
/ NOTIFY / LAME shapes; `xdm.intermediate.port` is new and carries
the lame-resolver port for LAME shapes; `xdm.event.operation_sub_type`
is now populated on the DNS stanza (carries the `_dns_action`
discriminator value).

Zone-transfer and notify serial numbers are intentionally not
extracted into dedicated intermediates -- there is no obvious XDM
destination for them and the verbatim values are preserved in
`xdm.event.description` (the full syslog body) for analyst
reference.

### Task #89 -- RFC 5424-in-kernel envelope discovery

A fresh production sample from the user surfaced a second syslog
envelope shape the appliance emits that none of the prior sample
corpus contained:

```
<118>Apr 29 01:41:23 kernel: 2026-04-29T01:41:23.397651+10:00
ho2kasdad34.au.simonsigre.net dhcpd 2722 - - DHCPREQUEST
for 10.44.235.110 from ec:f4:a7:d4:b5:7f via vmx1
```

The outer process tag is `kernel:` (not `dhcpd[2722]:`), the inner
daemon name is space-separated (`dhcpd 2722`, no brackets, no
colon), and the two `- -` tokens are RFC 5424 NILVALUE
placeholders for MSGID and STRUCTURED-DATA. The previous
per-stanza filter `\s(named|dhcpd|sshd|sudo)\[\d+\]:` did not
match this shape, so every kernel-wrapped event was silently
dropped at the filter stage -- the same class of silent-drop as
Task #86, just at a different stage.

### Task #89 -- refactor to `[RULE: efficientip_syslog_header]`

The new envelope shape roughly doubled the complexity of header
parsing (priority, facility, severity, host, pid, proc, msg). It
was the natural moment to refactor the four duplicated header
preludes into a single shared rule using the `[RULE: ...]` +
`| call` pattern that BeyondTrust PRA and ESXi use in
`PRIVATE_DOCS/all_modeling_rules.txt`. The refactor also pays
back on long-term maintainability: a third syslog envelope shape
would now be a one-rule change, not a four-stanza rewrite.

The shape of the file changed as follows:

- **Before.** One `[MODEL: dataset = efficientip_raw]` header at
  the top of the file, four stanzas underneath, each starting
  with the same allow-list filter, the same daemon filter, and
  the same ~20-line header parsing prelude.
- **After.** One `[RULE: efficientip_syslog_header]` block at the
  top of the file (allow-list filter + dual-shape header
  extraction), then four `[MODEL: dataset = efficientip_raw]`
  stanzas each starting with `call efficientip_syslog_header`
  followed by `| filter _syslog_proc = "<daemon>"`.

The seven `_syslog_*` intermediates produced by the shared rule
are all extracted with primary regex + coalesce fallback so a
single set of intermediates feeds both envelopes:

| Intermediate       | RFC 3164 anchor                                | RFC 5424-in-kernel anchor                                            |
| ------------------ | ---------------------------------------------- | -------------------------------------------------------------------- |
| `_syslog_priority` | `^<(\d{1,3})>`                                 | (same)                                                               |
| `_syslog_proc`     | `\s(named\|dhcpd\|sshd\|sudo)\[\d+\]:`         | `\skernel:\s+\S+\s+\S+\s+(named\|dhcpd\|sshd\|sudo)\s+\d+\s+-\s+-`   |
| `_syslog_pid`      | `\s(?:named\|dhcpd\|sshd\|sudo)\[(\d+)\]:`     | `\skernel:\s+\S+\s+\S+\s+(?:named\|dhcpd\|sshd\|sudo)\s+(\d+)\s+-\s+-` |
| `_syslog_host`     | `^<\d+>\w+\s+\d+\s+\d+:\d+:\d+\s+(\S+)\s+...` | `\skernel:\s+\S+\s+(\S+)\s+(?:named\|dhcpd\|sshd\|sudo)\s+\d+\s+-\s+-` |
| `_syslog_msg`      | `(?:...)\[\d+\]:\s*(.+)$`                      | `(?:...)\s+\d+\s+-\s+-\s+(.+)$`                                       |
| `_syslog_facility` | `floor(divide(_syslog_priority, 8))`           | (same)                                                               |
| `_syslog_severity` | `subtract(_syslog_priority, multiply(_syslog_facility, 8))` | (same)                                                  |

### Task #89 -- DHCP noise filter `\bkernel:\s` removal

The DHCP stanza's noise-suppression alternation previously
contained `\bkernel:\s` to drop hypothetical
`dhcpd[X]: kernel: ...` lines. With RFC 5424-in-kernel envelope
support, every kernel-wrapped DHCP line legitimately contains
`kernel: ` as the outer process tag; the suppression pattern
would now drop the entire kernel-wrapped DHCP stream. The
fragment was removed from the alternation as part of the same
refactor. The remaining noise patterns are body-anchored
(balancing-pool, scrubbing-lease, abandoning-IP, etc.) and apply
correctly against both envelope shapes.

### Task #89 -- per-stanza bisect notes are now obsolete

The per-stanza bisect inference table from Task #86 (DNS / DHCP /
SSH / sudo, evidence vs inference) was written before the
refactor. It still applies field-by-field to each MODEL stanza,
but the header-prelude diagnosis at the top of each stanza has
moved out into the shared rule -- so any future header-shape
issue is a one-rule diagnosis, not a four-stanza diagnosis.

### Production verification queries (for the tenant operator)

After deploy, the following two queries confirm Task #86's fix
took hold:

```
dataset = efficientip_raw
| comp count() as n by xdm.event.type
| sort desc n
```

Expected: non-zero counts for `DNS`, `DHCP`, `SSH`, and `SUDO`
(prior to the fix only `SUDO` was non-zero).

```
dataset = efficientip_raw
| filter _raw_log contains "named"
| comp count() as n by xdm.event.type, xdm.event.operation_sub_type
| sort desc n
```

Expected: `DNS` populated for the great majority of named lines,
with the operation_sub_type breakdown showing `QUERY`, `ANSWER`,
`UPDATE_ADD`, `UPDATE_DENIED`, `IXFR`, `AXFR`, `XFER_DONE`,
`NOTIFY`, `LAME`, `RATELIMIT`, and a small `null`/`OTHER` bucket
for unrecognised single-token diagnostic lines.

### Carried over from Task #83

- **Allow-list filter centralised in the shared header rule.** The
  Task #83 implementation prepended the allow-list filter to every
  stanza because Cortex `[MODEL: ...]` blocks have independent
  filter scopes. Task #89's RULE/CALL refactor moved the
  allow-list (extended to cover both envelope shapes) into
  `[RULE: efficientip_syslog_header]`, where it runs once per
  MODEL via `call`. FreeBSD `devd[]`, `ipmserver[]`, unwrapped
  `kernel:` ipfw, and other appliance-internal noise are still
  dropped before any stanza body sees them.
- **`xdm.network.application_protocol` and `protocol_layers` set on
  every stanza.** Originally only DNS and DHCP set them; SSH and
  sudo now set `"SSH"` and `"SUDO"` respectively for consistency.
  DNS additionally exposes the IP transport layer in
  `protocol_layers` (`arraycreate("DNS", "TCP"|"UDP")`) when query
  flags identify the transport, falling back to `arraycreate("DNS")`
  alone otherwise (Task #86 null-guard fix).
- **DNS listener IP regex broadened to IPv4 + IPv6.** Original
  fix-pass regex captured IPv4 only, but the rule maps to both
  `xdm.intermediate.ipv4` and `xdm.intermediate.ipv6`. The capture
  is now `\((IPv4|IPv6)\)\s*$` so an IPv6 listener literal in
  the trailing parens is preserved. Task #86 tightened the regex
  to require a dot or colon (excluding RRL hash tokens like
  `(138956d9)`).
- **`xdm.session_context_id` dropped.** The plan called for mapping
  the DHCP TransID into `xdm.session_context_id`, but the analyser's
  WARN-025 flags this path as known to trigger Cortex IDE internal
  validation errors on `_gc_raw` datasets. The transaction ID is
  therefore not surfaced; it remains visible in
  `xdm.event.description` (the raw syslog body) for analysts who
  need it.
- **`_dhcp_transaction_id` extraction removed.** Once the
  `xdm.session_context_id` mapping was dropped, the
  `_dhcp_transaction_id` temporary became orphaned and would have
  triggered ERR-019 on the `_gc_raw` dataset. The extraction step is
  removed entirely.
- **`xdm.alert.severity = syslog_severity` dropped (every stanza).**
  The original rule reused `xdm.alert.severity` to carry the wire
  syslog severity, which is the wrong layer (alert severity is for
  detection-engine alerts, not transport-layer log severity). The
  syslog severity is preserved in `xdm.event.log_level` only.
- **`xdm.event.log_level` if-chain default removed.** The plan
  preserved the original "fall through to raw `_syslog_severity`"
  default branch, but the analyser's WARN-029 rejects it: the
  `xdm.event.log_level` path requires `XDM_CONST.LOG_LEVEL_*` enum
  values and Cortex silently drops non-enum strings. Out-of-range
  syslog severities (none of `0..7`) now leave `log_level` null.
- **DNS `is_response` and `outcome` semantics corrected.** Original:
  `is_response = if(rcode = null, FALSE)` (ignored TRUE arm) and
  `outcome = if(rcode != null, OUTCOME_FAILED)` (treated NOERROR as
  failed). New: `is_response = TRUE` when `_dns_action = "ANSWER"`
  or any rcode mnemonic appears, `FALSE` otherwise; `outcome =
  SUCCESS` for NOERROR rcode, `FAILED` for any other rcode, FAILED
  for UPDATE_DENIED / RATELIMIT / LAME shapes, null for plain QUERY
  lines.
- **DNS opcode default to 0 (QUERY).** named omits the opcode token
  for the default QUERY opcode, so the original's
  `regextract(...,"Query|IQuery|...")` always returned null on real
  query lines. The rule now sets opcode = 0 for QUERY/ANSWER, 5 for
  UPDATE_*, 4 for NOTIFY based on the discriminator.
- **DNS query class regex anchored.** Original
  `regextract(_raw_log, "IN|CS|CH|HS")` matched anywhere in the line
  (e.g. inside the queried domain name). New regex anchors after the
  shape verb so only the genuine class token is captured.
- **SSH client IP / port extraction rebuilt.** Original
  `[\d+\.]+\d+` matched any digit-or-dot run (PIDs, port numbers,
  even partial IPs). New extractions anchor to `from\s+(...)` and
  `by ... (...) port` patterns and route the IP through `is_ipv4` /
  `is_ipv6`.
- **SSH outcome added.** The original rule never set
  `xdm.event.outcome` for SSH events. The rewrite maps `ACCEPTED` /
  `DISCONNECTED` -> SUCCESS and `FAILED` / `INVALID` / `ERROR` /
  `REVERSE` -> FAILED.
- **sudo extraction rebuilt.** The original chain of nested
  `regextract`-`split`-`arrayindex` calls was brittle and
  off-by-one. New extractions key off the standard sudo line shape
  (`USER : TTY=... ; PWD=... ; USER=... ; COMMAND=...`).
- **DHCP noise filter consolidated.** 30 single-pattern
  `filter not _raw_log ~= "..."` lines collapsed to one grouped
  alternation regex (lease lifecycle, kernel/transport, server
  admin) -- same coverage, much shorter.
- **`xdm.alert.mitre_techniques` and `xdm.alert.risks` dropped.**
  Not part of this rule's mandate; the original rule never had them
  but listing the absence here matches the documentation pattern
  used by sibling rules.

## Excluded XDM fields -- not applicable or no source data

- `xdm.alert.*` -- this is operational telemetry (DNS / DHCP / SSH /
  sudo), not a security-alert dataset. Detection layers run on top.
- `xdm.target.host.hostname` (DNS) -- the trailing `(LISTENER_IP)`
  in the named query log is the local listener IP, not the
  resolution target. The queried name itself goes to
  `dns_question.name`; the BIND zone goes to
  `xdm.target.resource.name` for shapes that carry one.
- `xdm.session_context_id` -- see "Drift from plan" above.

## Analyser scoring

```
score:        97 / 100
errors:       0
warnings:     0
info:         1   (INFO-006: missing `| fields -` cleanup, accepted)
suggestions:  0
```

INFO-006 is accepted in line with the rest of the rule set. Adding
`| fields -` cleanup at the end of every stanza would require
listing every underscore temp explicitly per stanza for negligible
runtime benefit on a `_gc_raw` modeling rule.

## References

- Original vendor rule:
  `attached_assets/Pasted--Efficient-IP-datamodel-MODEL-dataset-efficientip-corp-_1777353862793.txt`
- Production sample corpus (Task #86):
  `attached_assets/Pasted--30-Apr-28-09-59-07-named-31522-client-0x21dafb594910-1_1777360474720.txt`
- Refreshed sample syslog payloads:
  `PRIVATE_DOCS/packs/efficientip_ddi/baselines/sample_logs.txt`
- Refreshed analyser baseline:
  `PRIVATE_DOCS/packs/efficientip_ddi/baselines/efficientip_ddi_xdm_model_rule.json`
- Cortex BIND named query log format:
  https://kb.isc.org/docs/aa-01526 (BIND 9 ARM, Logging chapter)
- ISC DHCP message types: RFC 2131 / RFC 3203 / RFC 4388 / RFC 6926
- BIND response rate limiting (RRL): https://kb.isc.org/docs/aa-01000
- Google SecOps (Chronicle) EfficientIP DDI parser docs (default
  parser CN_EFFICIENTIP, sister implementation we cross-checked
  field semantics against):
  https://cloud.google.com/chronicle/docs/ingestion/default-parsers/efficientip
- EfficientIP SOLIDserver syslog message reference (admin guide):
  https://docs.efficientip.com/display/SOLIDserver/Syslog+Messages

## On the `baselines/` folder

The `baselines/` directory under each pack is a living mirror of the
current rule plus its current analyser output, refreshed whenever the
production `datamodel.xql` changes materially. It is not a frozen
historical snapshot. Two files are kept in lock-step with the live
rule:

- `efficientip_ddi_xdm_model_rule.xql` -- byte-for-byte copy of
  `../datamodel.xql` at the time of the last refresh. Useful as a
  diff target when reviewing a PR that touches the rule, and as the
  canonical input for the analyser baseline below.
- `efficientip_ddi_xdm_model_rule.json` -- response from
  `POST /api/analyse` with `{code: <the rule>, ruleType: "modeling"}`,
  pretty-printed. This pins the analyser's expected verdict (score,
  summary counts, every violation) so any inadvertent regression in
  the analyser surfaces as a baseline diff in CI rather than as a
  silent change in production behaviour.

If you change `datamodel.xql`, refresh both baseline files in the same
commit (Task #98 introduced this convention).
