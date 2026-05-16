<!--
SPDX-FileCopyrightText: ohno llc
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Provenance — XQL/XDM corpus

This tree (`docs/seed/xql/packs/`, `docs/seed/xql/reference/`,
`docs/seed/xql/field_anchors.json`, `docs/seed/xql/snippets.json`) is a
verbatim mirror of artefacts from the upstream **gocortex-xql-ide**
repository, lifted on 2026-05-15 to ground Enclave's XQL/XDM rule
authoring agents.

## Source

- Repository: `https://github.com/<gocortexio>/gocortex-xql-ide` (working
  copy at `~/Github/Github_desktop/brid-ger/gocortex-xql-ide`).
- Source SHA at copy time: `b2e7f3936dca67647a6eeb365741ae6d85d9a584`.
- Source paths mirrored:
  - `PRIVATE_DOCS/packs/`            → `docs/seed/xql/packs/`
  - `PRIVATE_DOCS/field_anchors.json`→ `docs/seed/xql/field_anchors.json`
  - `PRIVATE_DOCS/FIELD_ANCHORS_SCHEMA.md` and ten more reference
    markdown files → `docs/seed/xql/reference/`
  - `server/data/snippets.ts`        → `docs/seed/xql/snippets.json`
    (converted; structure preserved, comments stripped).

## Licence

The source repository is licensed under **GNU Affero General Public
License v3.0 or later** (`SPDX-License-Identifier: AGPL-3.0-or-later`).
All copied files retain that licence. Any downstream code that
incorporates this corpus — directly or as RAG-indexed text — is bound
by the same terms.

The ported Python tools that will land in Phase 3
(`plugins/xdm-toolkit/tools/analyse_xql.py`, `scaffold_xql.py`) are
derivative works and carry the same licence with explicit attribution
to `gocortex-xql-ide/server/data/`.

## SPDX header coverage

| File type | Headers present | Notes |
|---|---|---|
| `.xql` | 25 / 37 | Twelve files lack SPDX at source (`gocortex_concierge`, `apache_tomcat_brokenbank`, `gocortex_bbwaf`, `gocortex_brokenbank_auth` packs and their `baselines/` siblings). Mirrored verbatim; not modified here. Tracked as a source-side gap. |
| `.md` | 3 / 30 | Source author opted not to add markdown comment SPDX in most reference files. Licence inheritance is via repository LICENSE + this PROVENANCE.md. |
| `.json` | n/a | JSON does not support comments per the source `ENGINEERING_SPEC.md`. Licence inheritance is via this file and the `_meta` block inside `snippets.json`. |
| `.yaml` | n/a | Two API-schema YAMLs mirrored from third-party vendors (Imperva); their original third-party licences apply. |

## Style conventions (per source `ENGINEERING_SPEC.md`)

Artefacts under `docs/seed/xql/` retain the source's editorial
conventions:

- British English throughout reference text.
- ASCII status tokens only: `[OK]`, `[ERROR]`, `[INFO]`, `[PASS]`,
  `[FAIL]`. No Unicode symbols, no emoji.
- Professional, factual tone. No marketing language. No stylistic
  highlighting.

These conventions apply **only** inside `docs/seed/xql/`. Enclave's
broader house style (allowed marketing copy, sentence-case headings,
emoji in UI strings) is unchanged elsewhere.

## What we did NOT modify

- File contents (byte-identical mirror).
- Comment headers, including the `// SPDX-...` lines.
- Directory structure inside `packs/` (kept the original `baselines/`
  subdirectories and the vendor-specific extras like
  `imperva-cloud-ato-api.yaml`).

## What we did add

- This `PROVENANCE.md`.
- A `_meta` block at the top of the converted `snippets.json` with
  SPDX fields, source path, and snippet count.

## Refresh procedure

To resync against a newer source SHA:

```
cd ~/Github/Github_desktop/brid-ger/gocortex-xql-ide
git pull
# In local-ai-platform worktree:
docs/seed/xql/_resync.sh        # to be added in Phase 5
```

Until the resync script lands, repeat the Phase 1 copy commands and
update the source SHA above.

## Open items

- `gocortex_*` and `apache_tomcat_brokenbank` packs lack SPDX headers
  in source. Filed as a source-side gap; consider upstreaming a patch
  rather than fixing locally.
- Markdown reference files would benefit from HTML-comment SPDX blocks
  (`<!-- SPDX-... -->`). Same call as above — fix upstream, not here.
