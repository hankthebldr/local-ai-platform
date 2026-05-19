# Supporting & Adjacent Data Sources / Capabilities

**Companion to:** `2026-05-16-roadmap-spec.md`,
`2026-05-16-implementation-plan.md`, `2026-05-16-ui-flows.md`
**Date:** 2026-05-16

The roadmap spec scopes what 1.2 ships. This doc maps the *adjacent* surface
area: data sources we could ingest, capabilities we could expose, and
integration touchpoints we could honor. The purpose is not to fold them all
into 1.2 — most are 1.3+ — but to ensure 1.2's architecture leaves *room*
for them, and to identify the strategic bets early.

## Thesis

The platform's defensibility grows with the breadth of credible
integrations. Open WebUI's moat is none of its features individually; it's
that anything that speaks "files + chat + RAG" plugs in. We need the same
property: every relevant data source, every relevant tool, can be reached.

**Two architectural decisions enable this without scope blowup:**

1. **MCP-host posture.** Treat MCP as the *outside-in* protocol. Anything
   we want to integrate, we wire as an MCP server (existing or new) rather
   than building a custom integration in our codebase. This is consistent
   with the 1.0 design and the catalog work in 1.2.
2. **Watched-source primitive.** Generalize the "watched folder" idea from
   UX flows §15 into a `WatchedSource` abstraction — folder, mailbox, git
   repo, API endpoint — that pulls deltas on a schedule and feeds the RAG
   pipeline. 1.2 ships folders; the abstraction supports the rest.

With those two in place, adding any new source or capability becomes a
plugin/catalog/MCP entry, not a code change to the core engine.

## Five categories

| # | Category | What it adds |
|---|----------|--------------|
| 1 | **Personal knowledge** sources | Your notes, mail, bookmarks, calendars — all become RAG-able |
| 2 | **Work & code** sources | Repos, issues, docs, design files — become agentic-coder context |
| 3 | **Live capabilities** (do something) | Browser automation, shell, DB queries, OCR, voice, image gen |
| 4 | **Platform capabilities** (we build) | Scheduling, notifications, voice mode, mobile, sync |
| 5 | **Trust & ops** capabilities | PII scanning, output filters, air-gap mode, audit, encryption |

Each category gets a section below: what's in it, what fits 1.2, what
fits 1.3+, what's never.

## 1. Personal knowledge sources

These become RAG corpora or live-query sources. Each is one of: folder-like
(file watcher works), API-like (needs an MCP), or hybrid.

| Source | Type | Effort | 1.2 / 1.3 / never |
|--------|------|--------|------------------|
| **Obsidian / markdown vault** | folder | Already supported via watched folders (UX flows §15) | **1.2** |
| **Apple Notes** (macOS) | API (SQLite at `~/Library/Group Containers/group.com.apple.notes/`) | medium — read-only SQLite reader | **1.3** |
| **Notion** | API + MCP | Existing community MCPs available; needs auth + rate-limit handling | **1.3** |
| **OneNote / Office 365** | API | Microsoft Graph + MCP | 1.3 |
| **Email — IMAP / mbox** | API | small Python lib + chunker per message | **1.3** |
| **Gmail** | API + MCP | Existing official MCP; sensitive auth path | 1.3 |
| **Calendar — iCal / CalDAV** | API | small lib; events as RAG chunks | 1.3 |
| **Browser bookmarks + history** | SQLite (Chrome/Firefox/Safari local) | small reader per browser | 1.3 |
| **Pocket / Pinboard / readwise** | API | small fetcher | 1.3 |
| **RSS / Atom feeds** | API | trivial; one tool already exists | **1.2-stretch** |
| **iCloud / Dropbox / Google Drive** | folder (local sync) | works *if* user has local sync enabled — falls under watched folders | **1.2** (implicit) |
| **Pixelated/SMS / Signal-cli** | API | Signal CLI integration | 1.3+ |
| **Voice memos / podcasts** | files + transcription | needs whisper.cpp integration (see §3) | 1.3 |
| **YouTube transcripts** | API | yt-dlp subtitles or a small fetcher | 1.3 |
| **Wikipedia / Wikidata dumps** | static | one-time index | 1.3 |
| **arXiv / Semantic Scholar** | API | HF MCP partially covers this | **1.2-stretch** |

**1.2 strategic bet:** Obsidian + RSS, both via the watched-source primitive
or the existing folder watcher. The marginal addition over 1.0 is one RSS
fetcher + the watch UI from UX flows §15.

**1.3 strategic bet:** the "personal knowledge" pack — Apple Notes, Email
(IMAP first), Calendar, browser history. These represent ~80% of a
knowledge-worker's actual personal data. Ship as a "Personal" plugin
bundle with one-toggle enable.

## 2. Work & code sources

Mostly relevant to Enclave Code, but also for non-coding research.

| Source | Type | Effort | 1.2 / 1.3 / never |
|--------|------|--------|------------------|
| **Local git repo** | folder + git CLI | Enclave Code uses worktrees; doc plan covers this | **1.2** |
| **GitHub / GitLab / Gitea** | API + MCP | github-mcp pre-registered (UX flows §14) | **1.2** |
| **Jira / Linear / GitHub Issues** | API + MCP | Linear has an official MCP; Jira via OpenAPI | 1.3 |
| **Slack / Discord** (work conversations) | API + MCP | sensitive permissions; defer until vertical-pack demand | 1.3+ |
| **Confluence / Notion (work)** | API | same as personal | 1.3 |
| **Figma** | API + MCP | the Figma MCP we already saw is canonical | 1.3 |
| **Sentry / Datadog** | API + MCP | Sentry MCP named in Enclave Code additions | **1.2-stretch** |
| **Postgres / MySQL / SQLite / Mongo** | DB connector or MCP | DB MCPs exist; useful for "query the prod schema" | 1.3 |
| **Stripe / Salesforce / HubSpot** | API + MCP | enterprise pattern; defer | 1.3+ |
| **Cloud infra (AWS/GCP/Azure)** | CLI + MCP | high-risk; needs careful permission model | 1.3+ |
| **Package registries (PyPI, npm, crates.io)** | API | small fetcher per registry; partial value via Context7 | 1.3 |
| **Language docs (Python stdlib, MDN, etc.)** | static + MCP | Context7 MCP pre-registered in Enclave Code | **1.2** |
| **Code search engines** (Sourcegraph) | API + MCP | nice for large orgs; small-team value unclear | 1.3+ |

**1.2 strategic bet:** github-mcp + context7. These two unlock "fix bug
from issue #123" and "use the current version of FastAPI's API" — the
biggest two annoyances developers have with local-only LLMs today.

## 3. Live capabilities (call out to do something)

| Capability | Vector | Effort | 1.2 / 1.3 / never |
|-----------|--------|--------|------------------|
| **Browser automation** | Playwright MCP | low (existing MCP) | **1.2-stretch** for Enclave Code verifier |
| **SSH to remote box** | MCP (sshmcp exists) | medium — auth + risk | 1.3 |
| **Docker / container ops** | MCP | low | 1.3 |
| **Kubernetes** | MCP or kubectl wrapping | medium | 1.3+ |
| **Database queries** | MCP per engine | low–medium per DB | 1.3 |
| **HTTP / REST** | generic OpenAPI MCP | low | **1.2** (via context7 / existing) |
| **OCR (PDF, images)** | local Tesseract or PaddleOCR | medium | 1.3 |
| **Whisper.cpp** (STT) | local | medium — bundle + load | 1.3 — enables voice mode |
| **Piper / Coqui** (TTS) | local | low — small models | 1.3 |
| **Image generation** (local Stable Diffusion) | API to a local SD server | medium — heavy compute | 1.3+ — only if hardware tier supports |
| **Mermaid / Graphviz rendering** | local | trivial — node + dot binaries | **1.2-stretch** |
| **Spreadsheet manipulation** (openpyxl, sheets) | local | low | 1.3 |
| **PDF generation** (weasyprint / pandoc) | local | low | 1.3 |
| **Math (sympy, wolfram-alpha-mcp)** | local + MCP | low | 1.3 |
| **Code execution sandbox** (Jupyter-like for non-code agents) | local container | medium — RC nightmare without containers | 1.3+ |
| **Background scraping** (with robots.txt etiquette) | local | medium | 1.3 |

**1.2 strategic bet:** Playwright MCP as the Enclave Code verifier's
front-end smoke-test capability. Add Mermaid rendering if the dashboard
ends up showing workflow DAGs as diagrams.

## 4. Platform capabilities we build

These are not data sources — they're new platform capabilities the team
ships. Each is a 1.3+ direction with strategic implication.

| Capability | Effort | Why it matters |
|-----------|--------|----------------|
| **Background workers / scheduled workflows** | medium — needs a small scheduler + UI | "Run my morning briefing every day at 7am" is a killer-app pattern for a personal LLM. Cron-shaped UI in Runs tab. |
| **Notifications** | small per channel — system-native, email, push | Pairs with scheduled workflows. macOS Notification Center is trivial. Mobile push is harder. |
| **Voice mode** (Whisper + chat + Piper) | medium — bundle models + capture/playback | Mac DMG users especially benefit. Becomes the killer feature for Mobile Companion (brainstorm direction #4). |
| **Mobile companion** | large — separate codebase + app store distribution | Brainstorm direction #4. 1.3 at earliest. |
| **Multi-device sync** (encrypted, p2p, opt-in) | large — non-trivial crypto + conflict resolution | Required if mobile ships seriously. Could use Tailscale or wormhole-style transfer. |
| **Local web scraper** (with TTLs, robots.txt) | small — beautifulsoup4 + Pydantic | Adjacent to the research workflow. Saves chunked pages to RAG. |
| **LLM judge / consensus** | small — pure orchestration | "Run my prompt against 3 models, show me the differences." Aligns with brainstorm direction #7 (model lab). |
| **Diff / merge UI** | medium — frontend work | Enclave Code's M3 IDE integration depends on this. Worth pre-building for the dashboard. |
| **Active learning loop** (user corrects → LoRA delta) | very large — fine-tuning infra | Long-tail; defer until quality plateau forces it. |
| **Workflow templates marketplace** | small infra + medium curation | Direction #2 (vertical packs) gets the curation surface from this. |

**1.3 strategic bet:** scheduled workflows + notifications. Cheapest path
to "Enclave runs *for* me, not just on me." Foundation for "your morning
brief: news + email summary + calendar" type flows.

## 5. Trust & ops capabilities

These are the privacy/positioning capabilities that defend the brand.
Several are de facto required by the prosumer-privacy direction
(brainstorm #6).

| Capability | Effort | 1.2 / 1.3 / never |
|-----------|--------|------------------|
| **PII / PHI / secrets scan on RAG ingest** | medium — small classifier or regex pack | **1.2-stretch** — high-value for vertical packs |
| **Output filter** (block secrets in answers) | medium — same scanner inline | 1.3 |
| **Encrypted-at-rest local stores** | medium — sqlcipher / libsodium | 1.3 — pairs with prosumer build |
| **Air-gap mode** | small — block all egress | **1.2-stretch** — toggle in Privacy panel; disables MCPs that need network |
| **Tor / VPN routing for web fetches** | medium — proxy config + UX | 1.3 — niche but loud audience |
| **Tamper-evident audit log** | small — append-only signed log | 1.3 — table stakes for Teams direction |
| **Provenance ledger** | (already in 1.2 via ProvenanceEdge) | **1.2** |
| **Backup / restore** | small — export everything to a single bundle | 1.3 |
| **Disaster recovery** (cloud-backed encrypted backups) | medium — opt-in obviously | 1.3+ |
| **Differential privacy** for any future telemetry | small if no telemetry; medium if we add it | never — keeps brand sharp |
| **Reproducible builds** for the DMG | medium — supply-chain hygiene | 1.3 |

**1.2 strategic bet:** air-gap toggle + secrets scan on RAG ingest.
Both are <1 week each. Both translate directly into the privacy-positioning
story.

## How 1.2 ships *room* for the rest

Two specific design decisions in 1.2 keep the door open:

### Decision 1 — Generalize "watched folder" to `WatchedSource`

Instead of:
```python
class WatchedFolder:
    path: str
    ...
```

Ship as:
```python
class WatchedSource:
    kind: Literal["folder", "feed", "mailbox", "repo", "api"]
    config: dict   # kind-specific
    schedule: str  # cron-like or "on_change"
    ...
```

In 1.2 only `kind="folder"` is implemented. The abstraction costs almost
nothing extra now and saves a refactor later when Email, RSS, Notion ship.

### Decision 2 — The MCP catalog is the integration surface

Every category-1/2/3 item above should land as an MCP, not a custom
service. The MCP catalog UI (UX flows §14) is the integration surface
*and* the marketing surface ("Connect your Notion / Gmail / Linear").
Curation = pick which MCPs land in the default catalog; user can register
any MCP manually.

This implies one small extension to the MCP catalog data shape:

```json
{
  "id": "gmail-mcp",
  "name": "Gmail",
  "category": "personal-knowledge",   // groups in UI
  "auth_kind": "oauth",               // tells UI which auth flow to launch
  "data_kind": ["mailbox"],           // signals to watched-source which
                                      // schedule shape is appropriate
  ...
}
```

These three fields (`category`, `auth_kind`, `data_kind`) make the catalog
expressible enough for 1.3 to add 20 entries without UI changes.

## Prioritization summary

### Land in 1.2 (with the existing scope)

- ✓ Watched folders (UX flows §15)
- ✓ github-mcp + context7 + sequential-thinking + git-mcp (MCP catalog seed)
- ✓ Provenance ledger (already in scope)
- — Generalize the watched-source abstraction (minor work; protects 1.3+)
- — Extend MCP catalog schema with `category` / `auth_kind` / `data_kind` (one
  JSON change; protects 1.3+)

### 1.2-stretch (ship if slack from current-state corrections holds up)

- RSS feed source as a second `WatchedSource.kind`
- Playwright MCP pre-registered for Enclave Code verifier
- Mermaid rendering helper
- PII / secrets scan on RAG ingest (regex pack, ~3 days)
- Air-gap toggle in Privacy panel (~1 day)

### 1.3 commit candidates

- Personal knowledge pack: Apple Notes, Email/IMAP, Calendar, browser
  bookmarks — packaged as one bundle install
- Voice mode (Whisper + Piper)
- Scheduled workflows + notifications
- Sentry, Linear, Postgres MCPs as a "Work" pack
- Encrypted-at-rest stores (sqlcipher migration of existing SQLite files)
- Audit log for the Teams direction

### Strategic deferrals (1.4+ or never)

- Mobile companion (large undertaking; brainstorm direction with its own
  scope decision pending)
- Multi-device sync
- Active-learning fine-tuning loop
- Cloud-managed anything

## Why this matters now

If 1.2 ships *without* the two preparatory decisions above (generalize
watched-source, extend MCP catalog schema), each 1.3+ integration becomes a
small-but-real refactor of the surface area. Spending ~1 engineer-day in
1.2 to prep these costs nothing visible and saves cumulative ~10
engineer-days across the next year.

The platform's competitive position improves with *every* credible
integration. The strategic priority is not which integration to ship — it's
making sure adding the 50th integration is the same shape as adding the 5th.

## Risks

| Risk | Mitigation |
|------|------------|
| Scope creep — every team member has a favorite source they want in 1.2 | The 1.2-stretch list above is the maximum stretch; non-stretch is non-negotiable. New asks become 1.3 candidates. |
| Integration debt — third-party APIs break and orphan our integrations | Catalog entries declare a `last_verified` date. Background job rechecks weekly. Surface staleness in the UI. |
| Auth complexity — OAuth flows per source | Centralize via a small `AuthProviders` service. OAuth-by-MCP first, custom only if forced. |
| Bloat — pulling 5GB of email into RAG | Per-source quotas, retention TTLs, and the Doc Audit panel (UX flows §15) all keep this manageable. |
| Privacy regression — third-party MCP leaks data | Catalog entry flags `requires_network`; air-gap toggle blocks them; the MCP usage analytics panel surfaces unexpected outbound calls. |

## Open questions

1. **The "Personal" pack as a 1.3 commit.** Is the personal-knowledge pack
   a strategic bet or a feature pile? My read: bet. Frames Enclave as
   "your personal data stays personal" — sharpens vs. Apple Intelligence,
   Microsoft Copilot, etc.
2. **MCP host vs. MCP client.** Today we are an MCP *client* (consume
   tools). Should we also publish *our own* MCP server (so Claude Desktop,
   Cursor with MCP, etc. can use our skills/RAG)? Strategic upside; can
   slot in at 1.3 with one new router.
3. **Air-gap mode** as a default in some installs (e.g., a "Hospital"
   project template that disables all network MCPs). Worth checking with
   any healthcare-adjacent design partners.
4. **Which voice models** (Whisper variants, Piper voices) are credible
   in a CPU-only world. Needs an eval pass before 1.3 scoping.
5. **Where Apple Intelligence sits.** macOS users will increasingly compare
   us to Apple Intelligence. We win on privacy (Apple processes on-device
   sometimes, in their cloud sometimes; we're always local) and on
   capability breadth (more models, more sources). Our marketing copy
   needs to address this directly by 1.3.
