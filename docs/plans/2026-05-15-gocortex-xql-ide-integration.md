# GoCortex XQL IDE → Enclave integration plan

**Status:** Complete. All five gates signed off; PRs #59 + #60 + #62 + #64 + #66 merged to master between 2026-05-15 and 2026-05-16.

**Final merge order on master:**

  | Phase | PR | Merge commit | Description |
  |---|---|---|---|
  | 1+2 | #59 | `7888dcb` | corpus mirror + grounding (17 packs + 706 KB anchors + 112 snippets + few-shot exemplars + RAG ingestion script) |
  | 3a  | #60 | `6df1fbe` | validator framework + 9 rules + 17 fixtures + lookup_xdm_path rewrite |
  | 3b  | #62 | `259e72f` | bulk validator port (75 rules + analyseDataflow + scaffold_xql + 29 more fixtures) |
  | 4   | #64 | `39afbf2` | analyse_xql_gate hook + xdm_snippets + rag_lookup tools + workflow rewire |
  | 5   | #66 | `3ead572` | vendor-pack workflow + curator/reviewer agents + vendor-pack-author skill + CrowdStrike smoke |

**Smoke verification (post-merge):**
- 63/63 XQL unit tests passing (`test_xql_rules.py` + `test_xql_phase5.py`)
- CrowdStrike Falcon DetectionSummaryEvent end-to-end: good rule `READY-TO-DEPLOY` (score 41, 0 BLOCKERs); broken rule `NEEDS-FIXES` with both planted defects caught (ERR-016 + ERR-020)
- RAG corpus: 5,833 chunks across all 17 packs, full metadata, retrieves semantically-relevant chunks for process-tree queries

**Original status preserved below for history.**

---

**Status:** Gate 0 signed off 2026-05-15. Phase 1 in flight.

**Operator decisions:**
- Canonical MAPPED-header: **strict 9-line** (gocortex spec) — vendor / product / dataset / pattern / xdm_const / companion_pairs_complete / omitted / raw_log / notes. `xql-data-model-engineer.yaml` updates in Phase 5 to emit this shape.
- Companion-pair severity: **ERR for strict subset** (IP, MAC, port, user, host) — WARN for the long tail. Analyser's `COMPANION_PAIRS` table tagged accordingly in Phase 3.
- Phase 1 autonomy: proceed without further check-ins, stop at Gate 1.


**Date:** 2026-05-15
**Owner:** Henry Reed
**Source repo:** `~/Github/Github_desktop/brid-ger/gocortex-xql-ide` (AGPL-3.0-or-later)
**Target repo:** `local-ai-platform` (this worktree)
**Scope agreed:** Tier 1 + Tier 2 — corpus mirror + full 84-rule validator port

---

## Objective

Make Enclave's XQL/XDM rule authoring agents production-credible by grounding
them in the gocortex-xql-ide corpus and gating their output through the same
84-rule deterministic linter that the source IDE uses.

End state: any rule emitted by `xdm-rule-from-log.yaml`,
`xsiam-data-model-rules.yaml`, or the future `xdm-vendor-pack.yaml` is
auditable against a published rule ID (ERR/WARN/INFO/SUG) and fails the
workflow run on any BLOCKER.

## Inventory delta — what's new vs. what exists

### From source (gocortex-xql-ide)

| Asset | Lives at | Notes |
|---|---|---|
| 84-rule engine | `server/data/rules-engine.ts` (4496 lines) | Each rule has a `*.test.ts` next to it |
| Scaffold engine | `server/data/scaffold-engine.ts` (614 lines) | Pattern A/B/C/D detection + starter rule |
| Field anchors | `PRIVATE_DOCS/field_anchors.json` (706 KB) | XDM-path → type + evidence lookup DB |
| 17 vendor packs | `PRIVATE_DOCS/packs/<vendor>/{parser.xql,datamodel.xql,documentation.md}` | Gold-standard triples |
| Schema guide | `PRIVATE_DOCS/cortex_data_model_schema_guide.md` (2.4 MB) | Full XDM reference |
| Building guides | `data_model_rule_building_guide.md` (48 K), `parsing_rule_building_guide.md` (15 K), `cortex_xsiam_authoring_rules.md` (33 K), `rules_engine_reference.md` (61 K) | Reference corpus |
| Snippets | `server/data/snippets.ts` (112 entries) | Code templates |
| Eval harness | `scripts/eval-llm-models.ts` + `PRIVATE_DOCS/OLLAMA/eval_manifest.yaml` | Cached + live regression |

### Already in Enclave (no duplication needed)

| Asset | State |
|---|---|
| `workflows/xdm-rule-from-log.yaml` | 4-step; calls `validate_xql` tool — will rewire to new analyser |
| `workflows/xsiam-data-model-rules.yaml` | NICE + ATT&CK pipeline — adds analyser gate in Phase 4 |
| `workflows/xsiam-normalization-pipeline.yaml`, `xdm-bulk-onboarding.yaml`, `data-model-rules.yaml` | Untouched in Phases 1-4 |
| `agents/xql-data-model-engineer.yaml`, `xdm-schema-navigator.yaml`, `xsiam-analyst.yaml` | Untouched; gain richer knowledge by extending the context file |
| `plugins/xdm-toolkit/tools/{validate_xql,lookup_xdm_path}.py` | Both rewritten in Phase 3 |
| `api/hooks/builtins/*` | Gains `analyse_xql_gate.py` in Phase 4 |

## Licensing

- Source corpus is AGPL-3.0-or-later. All copied files keep their original
- New Python ports get fresh SPDX headers:
  with a `# Derived from gocortex-xql-ide/server/data/rules-engine.ts (AGPL-3.0)` provenance line.
- Enclave's top-level licence stays as-is; AGPL only attaches to the
  derivative files in `plugins/xdm-toolkit/` and the mirrored corpus under
  `docs/seed/xql/`. No conflict — both copyleft.
- `ENGINEERING_SPEC.md` conventions (British English, ASCII status tokens
  `[OK] [PASS] [FAIL]`, no marketing language) apply only to the artefacts
  inside `docs/seed/xql/packs/` and the ported tool docstrings. Rest of
  Enclave's house style unchanged.

## Phased delivery

Each phase is a single PR with a named Gate. No Phase N+1 starts before
Gate N is signed off in chat (per global CLAUDE.md).

### Phase 1 — Corpus mirror (read-only adds)

Files added (no edits):

```
docs/seed/xql/packs/{17 vendor packs}/{parser.xql,datamodel.xql,documentation.md}
docs/seed/xql/field_anchors.json
docs/seed/xql/reference/cortex_data_model_schema_guide.md
docs/seed/xql/reference/cortex_xql_schema_reference.md
docs/seed/xql/reference/cortex_xsiam_authoring_rules.md
docs/seed/xql/reference/data_model_rule_building_guide.md
docs/seed/xql/reference/parsing_rule_building_guide.md
docs/seed/xql/reference/rules_engine_reference.md
docs/seed/xql/reference/FIELD_ANCHORS_SCHEMA.md
docs/seed/xql/snippets.json    # converted from snippets.ts
docs/seed/xql/PROVENANCE.md    # SPDX + source-SHA pointer
```

**Gate 1:** Operator reviews `tree docs/seed/xql/` + spot-checks SPDX headers
on three packs and `field_anchors.json`. No code yet.

### Phase 2 — Knowledge expansion + corpus ingestion (revised 2026-05-15)

Scope adjusted to keep changes contained. Dynamic RAG queries from agent
context resolution would require three coordinated changes
(`ContextSource` Pydantic model + `RAGService` multi-collection support +
`agent_service` new branch). Instead, retrieval becomes a dedicated
`rag_lookup` plugin tool in Phase 4 so the agentic loop drives queries
per-turn rather than dumping a fixed RAG block into every system prompt.

Phase 2 deliverables:

- `docs/seed/xql/few_shot_examples.json` — four canonical pattern-A/B/C/D
  exemplars (Imperva ATO / Cisco WSA / EfficientIP DDI / AWS GuardDuty),
  each with input log + gold-standard MODEL block excerpt + key idioms +
  common-failure rule IDs.
- `docs/seed/xql/packs_index.md` — auto-derived index of all 17 packs
  with vendor / product / dataset / heuristic-dominant pattern family /
  line counts.
- `scripts/ingest_xql_corpus.py` — one-shot CLI that walks the corpus,
  chunks via the project Chunker, embeds via the project EmbeddingService,
  and stores chunks in a sibling Chroma collection `xql_corpus`. Idempotent
  re-runs; `--reset` to rebuild; `--dry-run` to walk without embedding.
  Writes `docs/seed/xql/ingest_manifest.json` recording counts + backend.
- `agents/xql-data-model-engineer.yaml` — load `few_shot_examples.json`
  and `packs_index.md` as additional `type: file` context sources.
- `agents/xdm-schema-navigator.yaml` — load `packs_index.md` so the agent
  can route operators to the right pack on follow-up.

Out of Phase 2 (moved to Phase 4): adding `type: rag` to `ContextSource`,
extending `RAGService` to accept a `collection_name` parameter, exposing
a `rag_lookup` plugin tool that any workflow step or agent can call.

**Gate 2:** (a) `python scripts/ingest_xql_corpus.py --dry-run` reports
~15k chunks across `pack`, `reference`, `field_anchors`,
`core_knowledge`, `snippet_index`, `few_shot_examples` categories;
(b) operator inspects `packs_index.md` and at least one example block
in `few_shot_examples.json`; (c) optional — a live ingest run against
the operator's Ollama box produces a non-empty `ingest_manifest.json`.

### Phase 3 — Validator port (substantive)

- Port `server/data/rules-engine.ts` → `plugins/xdm-toolkit/tools/analyse_xql.py`.
  Same rule IDs verbatim. Same severity buckets. Same return shape (translated
  to the dict already produced by `validate_xql.py`).
- Port `server/data/scaffold-engine.ts` → `plugins/xdm-toolkit/tools/scaffold_xql.py`.
- Port the per-rule `.test.ts` files → `tests/unit/test_xql_rules.py`
  (parametrised pytest, one case per rule fixture).
- Replace `plugins/xdm-toolkit/tools/validate_xql.py` with a thin shim that
  delegates to `analyse_xql.py` (preserves the existing `validate_xql` tool
  contract that `xdm-rule-from-log.yaml` already calls).
- Rewrite `plugins/xdm-toolkit/tools/lookup_xdm_path.py` to read
  `docs/seed/xql/field_anchors.json` instead of the hard-coded path list.

**Gate 3:** `pytest tests/unit/test_xql_rules.py -v` — all 84 rule fixtures pass.

### Phase 4 — Workflow rewire + new hook

- Add `api/hooks/builtins/analyse_xql_gate.py` — generic hook that any
  workflow step can declare to fail-on-BLOCKER from the analyser.
- Update `workflows/xdm-rule-from-log.yaml`:
  - `validate_and_revise` step's `before_step` hook switches to
    the full analyser (already calls `validate_xql` — same tool ID, new impl).
  - Add `after_step: analyse_xql_gate` to enforce BLOCKER ⇒ fail.
- Add `plugins/xdm-toolkit/tools/xdm_snippets.py` — looks up snippets by
  pattern-family + vendor-class.
- Add `plugins/xdm-toolkit/tools/rag_lookup.py` — query the Phase 2
  `xql_corpus` Chroma collection by free-text + metadata filters
  (`pack_name`, `category`, `pack_role`). Returns the top-k chunks for
  the agentic loop to inspect.
- Minor extension: extend `RAGService` to accept an optional
  `collection_name` arg (default unchanged) so the new tool can target
  `xql_corpus` without affecting user-doc retrieval.

**Gate 4:** Run `workflows/xdm-rule-from-log.yaml` with an AWS GuardDuty
sample log; verify the `documentation.md`-style header is emitted and the
verdict line reads `READY-TO-DEPLOY`.

### Phase 5 — New agents, workflow, skill

- New agent `agents/xql-snippet-curator.yaml` — fast/small model, retrieves
  nearest vendor pack + relevant snippets, returns a primer block.
- New agent `agents/xql-rules-reviewer.yaml` — adversarial reviewer, takes
  rule + analyser JSON, emits operator-actionable diffs for top-3 findings.
- New workflow `workflows/xdm-vendor-pack.yaml` — full three-artefact pack
  onboarding (parser.xql + datamodel.xql + documentation.md). Composes
  `xdm-rule-from-log.yaml` as a subroutine where useful.
- New skill `plugins/xdm-toolkit/skills/vendor-pack-author.md` covering the
  three-artefact deliverable shape.
- Update `plugins/xdm-toolkit/plugin.yaml` to register new skills/tools.

**Gate 5:** End-to-end smoke — run `xdm-vendor-pack.yaml` against a synthetic
vendor (e.g. one of the existing packs with its `datamodel.xql` stripped),
confirm the regenerated pack roughly matches the original on the analyser
scoring side (>= 80% rule-by-rule parity).

## Out of scope (deferred to a follow-on)

- Tier 3 eval harness (`scripts/eval-llm-models.ts` port). Worth doing once
  Tiers 1+2 settle; would close the regression loop but expands blast radius.
- Web UI changes. Composer + Cortex Console already work with the existing
  workflow YAMLs; new fields propagate via the workflow schema.
- Modifying the source repo. Read-only mirror only.

## Design decisions — resolved 2026-05-15

- **MAPPED-header:** strict 9-line (gocortex spec). See header block above.
- **Companion-pair severity:** ERR for `xdm.source.ipv4 ↔ xdm.source.host.ipv4_addresses`, `xdm.target.ipv4 ↔ xdm.target.host.ipv4_addresses`, MAC pairs, port pairs, user pairs, host pairs. WARN for the remainder of the ~30-pair table. Implemented in `analyse_xql.py` via a per-pair `severity` field on `COMPANION_PAIRS`.

---

## Open questions logged

- Should `xdm_snippets.py` index snippets from the *Cortex Console* UI as
  well, or stay backend-only for Phase 4? — defer to Phase 5.
- Do we want the eval harness's cached responses checked in as fixtures? —
  defer to follow-on.
