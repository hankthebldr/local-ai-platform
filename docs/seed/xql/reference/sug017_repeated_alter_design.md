# SUG-017 design notes -- repeated alter content across pipelines in a MODEL block

Task #91 added a local-analyser rule, `SUG-017`, that flags rule
files where two or more `;`-terminated pipelines INSIDE a single
`[MODEL: ...]` block share enough alter content that Pattern 10
(extract a `[RULE:]` block, `call` it from each pipeline -- see
`data_model_rule_building_guide.md`) is the right refactor. Pattern
10 used to be a write-time judgement call; before SUG-017 the
duplication was usually only noticed after a fourth pipeline was
written and a fifth envelope shape arrived.

> **Re-baseline note (April 2026):** the original Task #91
> implementation walked multiple `[MODEL:]` blocks within a file,
> on the (mistaken) premise that a Pattern 10 file would have one
> MODEL block per event shape. That was wrong: Cortex permits
> exactly one MODEL block per `(dataset, model)` tuple per file,
> and the per-event-shape branches are `;`-terminated pipelines
> INSIDE a single MODEL block. SUG-017 has been re-baselined to
> walk those pipelines instead. Detection of duplicate
> `[MODEL: ...]` headers (the structural error that motivated the
> re-baseline) is now its own rule, `ERR-026`. The two rules are
> orthogonal: ERR-026 catches the file shape, SUG-017 looks for
> Pattern-10 candidates inside a correctly-shaped file.

These notes record the metric, the threshold, and the
false-positives we accepted. Re-read this file before tuning the
rule.

## Pipelines, not stanzas

A "pipeline" in this rule means one `;`-terminated statement
inside a MODEL block. The body of the MODEL block is split into
pipelines by walking the (comment- and string-stripped) text and
splitting on `;` at paren-depth 0 outside of `"..."` string
literals and outside of `// ...` comments. Each pipeline gets its
own anchor line number (the first non-blank, non-comment line of
its body) which is used as the violation location.

Cross-MODEL-block comparison is intentionally NOT done. The few
legitimate cases where the same dataset appears with different
`model=Audit` / `model=Network` qualifiers are designed to be
independent views of the dataset, and conflating their alter
content with another model's would be misleading. Same for two
unrelated datasets in one file.

## Similarity metric: normalised line equality

For each pipeline we keep ONLY the rows that live inside an
`alter` stage. Each kept row is normalised:

  * line comments (`// ...`) stripped,
  * leading and trailing whitespace trimmed,
  * runs of internal whitespace collapsed to a single space,
  * trailing commas and semicolons dropped.

For each pair of pipelines we count the multiset intersection of
these normalised lines. The multiset (not set) form is deliberate:
a 50-branch `XDM_CONST.LOG_LEVEL_*` if-chain that is byte-identical
across two pipelines should contribute 50 to the count, because
that 50-line block is exactly the kind of bulky duplication
Pattern 10 was written for.

### Metrics we considered and rejected

  * **AST equality.** XQL has no in-tree AST in this codebase, and
    building one for the analyser was out of scope. The
    `analyseDataflow` helper in `rules-engine.ts` is the closest
    thing to a parser we have and it is line-oriented. Adding an
    AST just for SUG-017 would dwarf the rule.

  * **Normalised-token Jaccard.** Token Jaccard would tolerate
    cosmetic differences (different whitespace, swapped argument
    order) but at the cost of fuzzy matches that are hard to
    explain in the violation message. The "you can see this
    duplication with your eyes" argument vanishes. We chose
    exact-line equality so the IDE annotation can say `share 22
    lines of identical alter content` and the engineer can verify
    by scrolling.

## Threshold: 18 shared normalised lines

The doc heuristic is `more than ~15 lines`. We picked 18 (slightly
above the doc number) after running the rule against the live
`PRIVATE_DOCS/packs/<vendor>/datamodel.xql` corpus. The reasoning:

  * 15-16 shared lines often shows up between sibling pipelines in
    files that already use Pattern 10 -- it is just the
    common XDM mapping (observer.vendor, observer.product,
    event.description, the LOG_LEVEL if-chain) the author kept
    inline because it does not feel duplicative when reading. The
    canonical "after Pattern 10" shape of EfficientIP DDI hits
    this band: 15-16 lines per pair of its four daemon pipelines.
    Firing there would mean every shipped Pattern-10 file is
    permanently noisy.

  * 18+ shared lines is the band where the duplication gets
    bulky enough to actually hurt readability: a full envelope
    header (priority/proc/host/pid/msg + facility + severity)
    plus its observer/event boilerplate.

  * The doc heuristic is approximate (`~15`); 18 is within the
    fuzz of "around 15".

The current calibration corpus (April 2026): every
`packs/<vendor>/datamodel.xql` file is clean at threshold 18 (this
corpus moved out of the now-removed `PRIVATE_DOCS/datamodel_rules/`
into `PRIVATE_DOCS/packs/<vendor>/` under Task #95). The known
"before Pattern 10" shape of EfficientIP DDI (its in-git history
copy from before Task #89) is the bad-shape fixture and fires as
expected at threshold 18.

Other reference files informally checked:

  * BeyondTrust PRA (`PRIVATE_DOCS/all_modeling_rules.txt:286-348`)
    and ESXi (`:1056-1408`): both already use Pattern 10 and the
    duplicated content lives inside `[RULE:]` blocks, not
    pipelines. SUG-017 sees those files as clean.

  * Single-pipeline vendors (Aruba Central, Tippingpoint, MongoDB
    Atlas, Forcepoint Firewall, etc.): SUG-017 is a no-op because
    fewer than two pipelines exist inside the MODEL block.

## Accepted false-positive shapes

We treat SUG-017 as advisory (`severity: suggestion`) so the
following shapes can fire without becoming editor noise:

  1. **Two pipelines that legitimately share a long XDM_CONST
     if-chain** (LOG_LEVEL_*, DNS_RECORD_TYPE_*, IP_PROTOCOL_*).
     Even when the if-chain is the only duplicated content, lifting
     it into a `[RULE:]` block is still a valid maintainability
     win: a new constant is added in one place, not N. We let
     SUG-017 fire here on purpose.

  2. **An author who deliberately keeps two pipelines independent
     for clarity.** Pattern 10 explicitly says it does not buy
     runtime performance, so the author is allowed to disagree
     with the rule. Suggestion-severity means the violation does
     not block deployment; it is a hint, not a gate.

## Shapes we deliberately do NOT flag

  * **A short shared allow-list filter (~5 lines).** Below
    threshold; the indirection of a `[RULE:]` block costs more
    than the duplication it removes.

  * **`[RULE:]` blocks themselves.** SUG-017 only walks pipelines
    inside MODEL blocks, so duplication WITHIN an already-factored
    RULE has no second target to compare against. (If two RULE
    blocks duplicate each other, that is its own design smell --
    not Pattern 10.)

  * **Cross-file duplication.** SUG-017 is per-file. Two
    independently-shipped vendor rule files that happen to share
    20 lines of generic syslog parsing are not a Pattern 10 case;
    Pattern 10 explicitly factors WITHIN a file or vendor.

  * **Cross-MODEL-block duplication within a file.** A file may
    legitimately contain two MODEL blocks for the same dataset
    with different `model=` qualifiers (e.g. `model=Auth` vs
    `model=Network`). Those are independent views and SUG-017 does
    NOT compare pipelines across MODEL blocks.

## Output shape

  * At most ONE violation per pipeline-after-the-first (within
    each MODEL block). A 4-pipeline MODEL block with cross-the-
    board duplication therefore raises 3 findings (anchored on
    pipelines 2/3/4), not C(4,2)=6. Per-pair output was the first
    design but produced too much noise on real files; per-pipeline
    dedupe still tells the engineer "pipeline X duplicates earlier
    pipeline Y" without repeating the same finding for every pair
    X belongs to.

  * For each later pipeline, the violation cites the SINGLE
    earlier pipeline that produced the maximum overlap, not the
    earliest qualifying one. So the two anchor line numbers in the
    message and the shared-line count in the message always
    describe the same pair (no risk of "A and B share X" where X
    actually came from B's overlap with a different earlier
    pipeline). Ties go to the earliest such pipeline (deterministic
    and predictable for users).

  * The IDE annotation lands on the duplicating pipeline's anchor
    (its first non-comment, non-blank line), so the user sees the
    marker on the pipeline they are likely to edit and not on the
    one they would use as the source for a `[RULE:]` block
    extraction.

  * Each violation message includes both anchor line numbers and
    the maximum shared-line count, so the engineer can decide
    whether the count crossed the threshold legitimately
    (~50-line if-chain, refactor it) or accidentally (the
    threshold needs another look).

## Regression coverage

`server/data/sug017-repeated-headers.test.ts` pins:

  1. A stripped-down EfficientIP-style fixture with one MODEL
     block and 3 pipelines that each carry the same envelope-
     header + common-XDM block (well above the 18-line threshold).
     SUG-017 MUST fire on pipelines 2 and 3 (two findings total,
     not three).

  2. A clean fixture with one MODEL block and two pipelines whose
     only shared content is the `xdm.observer.vendor` /
     `xdm.observer.product` pair (3 lines, well below threshold).
     SUG-017 MUST NOT fire.

  3. An already-factored fixture that uses a `[RULE:]` block and
     `call`. SUG-017 MUST NOT fire because the duplicated content
     lives inside the RULE body.

  4. A single-pipeline MODEL block. SUG-017 MUST NOT fire (no
     second pipeline to compare against).

  5. A "best-pair anchoring" fixture with three pipelines where
     pipeline 3's best-overlap match is pipeline 2 (not the
     earliest qualifying pipeline 1). SUG-017's finding for
     pipeline 3 MUST cite pipeline 2's anchor and the 35+ shared
     line count, not pipeline 1's.

  6. Parsing-mode invocation. The rule's `appliesTo: modeling`
     gate must keep it off the parsing pipeline even when the
     same source text is passed in.

The same test file also pins ERR-026 (duplicate `[MODEL:]` header
for the same `(dataset, model)` tuple) coverage:

  7. Two MODEL headers with the same plain dataset must produce
     ONE ERR-026 finding citing line 1 of the first occurrence.

  8. Three duplicates must produce TWO ERR-026 findings, both
     citing the FIRST occurrence (not the immediately preceding
     one).

  9. Same dataset with different `model=` qualifiers must NOT
     fire ERR-026.

  10. Same `(dataset, model)` tuple repeated MUST fire ERR-026.

  11. The corrected EfficientIP shape (one MODEL header, multiple
      `;`-terminated pipelines inside) must NOT fire ERR-026.

  12. Parsing-mode invocation must keep ERR-026 off the parsing
      pipeline (`appliesTo: modeling`).

If you tune the threshold or the normalisation, those fixtures are
the first thing to update.
