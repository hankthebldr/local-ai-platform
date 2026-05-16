# Anchor field design

## What an anchor is

An **anchor** is a small, high-selectivity field that is lifted out of a
data-model rule and into a parsing rule (`[INGEST: ... target_dataset =
X]`) so that the value becomes a real, indexed column on the
`target_dataset` table at ingest time. The anchor is derived from
`_raw_log` exactly once -- when the row is written -- and Cortex pushes
subsequent `dataset = X | filter <anchor> = "..."` queries down to the
column scan instead of forcing every analyst search to regex-extract the
discriminator on every row, every query, every time.

The classical case is a multi-shape dataset that fans out behind a
single `target_dataset`. The first worked example in this codebase is
EfficientIP DDI (`packs/efficientip_ddi/`): one `efficientip_raw`
dataset carries syslog from four daemons (BIND `named`, ISC `dhcpd`,
OpenSSH `sshd`, `sudo`) in two envelope shapes (RFC 3164 and RFC
5424-in-kernel). Without an anchor every search has to run the daemon
discriminator regex against `_raw_log` for every row. With
`_syslog_proc` pinned as an anchor the same query becomes a
column-equality test.

An anchor is NOT a normalisation or a mapping -- the heavy XDM lifting
still happens in the data-model rule. The parser's only job is to pull
out one or two short, stable strings (or integers) and assign them to
`_anchor_name` columns on the raw-data row.

## When to add an anchor

Add an anchor when **all four** of the following hold:

1. **The dataset is multi-shape.** A single `target_dataset` carries
   meaningfully different event families (different daemons, different
   action verbs, different message families) that analysts routinely
   need to filter between. A dataset with one shape gains nothing -- the
   only filter that would use the anchor is `<anchor> = <its-only-value>`,
   which is a no-op.

2. **The discriminator is selective and stable.** The candidate anchor
   has a small closed vocabulary (think 4 daemons, 8 facility numbers,
   16 priority values), every value is well represented in real ingest,
   and the regex that derives it does not change across firmware
   revisions or vendor major versions. An anchor whose regex breaks
   under a vendor upgrade is worse than no anchor at all -- the column
   silently fills with NULL and historical queries change shape.

3. **It will actually be searched on.** "Pre-extracting in case someone
   wants it" is not a justification. Each anchor adds a column to every
   raw row ingested into the `target_dataset` for the rest of the
   dataset's life; that storage cost only pays off if the column shows
   up in real `| filter` clauses regularly. The discriminator that drives
   the data-model rule's per-shape branching is almost always a winner;
   a verbose vendor metadata field is almost never one.

4. **The data-model rule still reads it from `_raw_log` via
   `coalesce()` -- or, for legacy packs, re-derives it
   independently.** Either way, the data-model rule must never
   depend on the parser-stamped column being present. This is
   the keep-in-both convention -- see "Defence in depth", below.

## Selectivity, not popularity

The right anchor is the one that lets a search land on the smallest
candidate row set in the fewest column tests. That is selectivity, not
popularity. A field that takes only four values (e.g. `_syslog_proc` ->
`{named, dhcpd, sshd, sudo}`) where each value is roughly equally
represented gives an analyst a clean 1-in-4 narrowing on a single
column-equality test. A field that takes eight thousand values
(`_session_id`) is in the limit useless as an anchor -- the analyst
cannot type it, so it never becomes a `| filter` clause.

The selectivity sweet spot is roughly 2-32 distinct values, each
present often enough that the smallest bucket still represents a
meaningful slice of ingest.

## Two anchors per dataset is the sweet spot

One anchor is the bare minimum for a multi-shape dataset (the discriminator
that fans out per-shape). A second anchor is usually justified -- the
canonical second is a small severity / criticality / facility integer
that turns "show me only the high-severity rows" from a `_raw_log`
regex into a numeric column comparison.

Three or more anchors per dataset is almost always wrong. Each anchor
adds a column to every raw row, and the marginal value of the third
anchor is usually small relative to the cost. The discipline is "what
two columns would I most often want to filter on first?", not "what
columns might be useful?".

For EfficientIP DDI the two anchors are:

- `_syslog_proc` -- the four-way daemon discriminator (`named` /
  `dhcpd` / `sshd` / `sudo`). Drives every per-daemon search.
- `_syslog_priority` -- the integer 0-191 from the syslog `<PRI>`
  header. Drives severity / facility filtering without the analyst
  having to think about how to extract it.

## Defence in depth: keep the anchor in the data-model rule too

The parser only sees rows that are ingested AFTER the parser is shipped.
Every row already on disk -- every replayed sample, every backfill, every
historical investigation -- predates the parser and has the anchor
column NULL. If the data-model rule depended on the anchor column
existing, every one of those rows would silently fail to model.

The convention is to keep the anchor extraction in BOTH places. The
preferred shape is:

- Parser: `_syslog_proc = <regex over _raw_log>` (writes the column
  once, at ingest).
- Data-model: `_syslog_proc = coalesce(_syslog_proc, <same regex over
  _raw_log>)` (reads the parser-written column when present, falls back
  to deriving it from `_raw_log` when not).

The data-model `coalesce()` makes the parser column purely additive --
historical and replayed rows still model correctly. The runtime cost on
parser-stamped rows is one column read and one `coalesce` short-circuit;
on un-stamped rows it is exactly the same regex the data-model rule
would have run anyway. The defence-in-depth pattern is therefore
strictly cheaper than the alternative for any non-trivial backfill
scenario.

EfficientIP DDI was the first pack to ship a parser (Task #95) and
adopted the keep-in-both `coalesce()` shape in Task #96. Both anchors
(`_syslog_proc`, `_syslog_priority`) in
`PRIVATE_DOCS/packs/efficientip_ddi/datamodel.xql` now read the
parser-stamped column first, then fall back to the same regex over
`_raw_log` the rule has always run -- so parser-stamped rows pay one
column read and a `coalesce` short-circuit, and un-stamped rows
(legacy ingest, replayed samples, backfills) still model identically.
There is no longer a legacy variant exemption: every new pack should
ship the parser and the data-model coalesce as the same commit.

## Cost trade-off

Adding an anchor is not free. The trade-off:

- **Storage grows.** Each anchor column is stored on every raw row in
  the `target_dataset`. The growth is small for short string columns
  (a four-way daemon discriminator is single-digit bytes per row after
  dictionary encoding) but it is non-zero, and it stacks across
  anchors. The discipline of "two anchors max" exists to bound this.

- **Latency on the indexed column drops by orders of magnitude.** A
  column-equality `| filter _syslog_proc = "named"` skips the
  `_raw_log` scan entirely on parser-stamped rows -- Cortex consults
  the column index instead. For interactive searches against a
  large multi-shape dataset this is the difference between a
  sub-second response and a minute-plus regex scan.

- **Ingest CPU increases marginally.** Each anchor adds one regex
  evaluation per ingested row in the parser. The cost is small
  relative to the rest of parser work and is paid once per row.

The right way to read this trade-off is: anchors trade storage for
search latency. If the dataset is searched often and the anchor fits
the four criteria above, the trade is overwhelmingly worth it. If the
dataset is rarely searched, do not add anchors at all.

## "Ship parser + datamodel as one pack"

The parser, the data-model rule, the per-pack documentation, and (in
future) sample logs all live together under
`PRIVATE_DOCS/packs/<vendor_product>/`. Conventional file names inside
each pack:

```
PRIVATE_DOCS/packs/<vendor_product>/
    parser.xql        # INGEST rule(s); optional, only when anchors exist
    datamodel.xql     # MODEL rule; always present
    documentation.md  # Per-pack notes; optional
    samples/          # Reserved for future raw-ingest samples
```

The folder name is lower-case, vendor + product, joined by an
underscore (e.g. `efficientip_ddi`, `extrahop_revealx`). The parser is
optional -- a pack without anchors simply omits `parser.xql`. The
data-model rule is mandatory.

A pack ships as a unit. When an anchor is added or removed, both
`parser.xql` and the `coalesce()` site in `datamodel.xql` change in the
same commit. Reviewers should refuse a parser change that does not
also update the matching data-model coalesce -- the keep-in-both
convention is what makes anchors backfill-safe, and it only works if
the two files stay in lock-step.

## Future-work hooks

This design note is the authoritative source for the concept. Two
intentional follow-ups remain:

- **Per-pack ingest-cost forecasting.** This note describes the
  trade-off qualitatively. Quantifying the storage growth per anchor
  per pack against a real ingest-rate model is its own follow-up.

- **Folding the concept into the offline modelfile / training prompts.**
  When the offline LLM is taught to author parsing rules from
  scratch, the anchor concept and the keep-in-both convention belong
  in its system prompt. That is a separate training decision; no
  action is taken in this design note.
