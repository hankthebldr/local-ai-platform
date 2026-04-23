# Local AI Platform — Licensing & Supportability Design

**Date:** 2026-04-18
**Status:** Active — Plan 1 (Worker) implementation complete, Plan 2 (in-app client) queued.
**Target release:** v1.0 (licensing launch)

> **Implementation state (2026-04-22):**
> - Plan 1 — Cloudflare Worker at [hankthebldr/license-service](https://github.com/hankthebldr/license-service): all 18 tasks complete, 92 tests green. Awaiting operator deploy (Cloudflare resources, keypair, secrets, LS webhook wiring).
> - Plan 2 — in-app client (this repo): not yet started. 19 tasks documented in [`../plans/2026-04-19-in-app-licensing-and-support.md`](../plans/2026-04-19-in-app-licensing-and-support.md).
>
> **Implementation constraint:** no real production signing-key material
> commits to this repo. The app ships with a `PLACEHOLDER` public key in
> `api/keys/license_pubkey.pem` until production deploy; tests use the
> committable keypair in `tests/fixtures/test_license_*.pem`; the
> production private key lives only as a Cloudflare Worker Secret.

## 1. Goals and Non-Goals

### Goals
- Sell a **one-time, lifetime** license for Local AI Platform at **$49 USD** to individual users.
- Deliver license enforcement that respects legitimate users: **offline-first, no hardware binding, no phone-home on launch**.
- Give licensed users a **structured support channel** that lands their issue (with diagnostics) directly on the public GitHub repo, with license-id and email kept private.
- Keep the infrastructure footprint tiny: one Cloudflare Worker, one object store, one transactional email provider.
- Design a data model that extends cleanly to a future team tier without rework.

### Non-Goals (explicit YAGNI)
- No team tier, seat management, or license transfer in v1.
- No AI-generated PR automation in v1 (the issue schema is designed for it, but the bot is out of scope).
- No customer web portal or account system — the purchase email is the identity anchor.
- No strong DRM. Soft enforcement only; determined attackers can patch the binary. We do not optimize for them.
- No telemetry or usage analytics reported back to us.

## 2. Business Model

| Attribute | Value |
|---|---|
| Tier | Individual |
| Price | $49 USD |
| Type | One-time purchase, lifetime license |
| Distribution | Lemon Squeezy (Merchant of Record — handles global tax/VAT) |
| Delivery | Signed `.license` file emailed via Postmark on webhook |
| Enforcement posture | Soft (Sublime Text model): nag + feature gate, no hardware binding |

### Free-tier vs Licensed features

**Free tier (no license required):**
- Chat and completions against any installed model (CLI and API)
- Model download & registry management
- OpenAI-compatible API (`/v1/chat/completions`, `/v1/completions`, `/v1/models`) against a single model per request
- Health/status endpoints
- Basic CLI: `cli/chat.py`, `cli/query.py`

**Licensed tier (`tier: individual`) unlocks:**
- `workflow_engine` — multi-agent YAML workflow engine
- `rag` — RAG pipeline (ChromaDB / LangChain)
- `multi_model` — multi-model orchestration
- `desktop_gui` — PyWebView desktop app
- `github_support` — submit issues via the GitHub bridge
- `finetuning` — fine-tuning pipeline (when shipped)

Free-tier users see a **1-in-5 CLI footer nag** (`💡 Support development — license $49 — <url>`) and an `X-LocalAI-License-Status: unlicensed` API response header. Desktop app shows a persistent banner when unlicensed. Nothing is time-bombed or blocked outside the feature list above.

## 3. System Architecture

Three moving parts: the customer's machine (in-app), a Cloudflare Worker we own (`license-service`), and Lemon Squeezy (third-party checkout).

```
┌─────────────────────────┐       ┌───────────────────────────┐
│  Customer's Machine     │       │   Lemon Squeezy (3rd)     │
│  (Local AI Platform)    │       │   - Hosted checkout       │
│                         │       │   - Global tax (MoR)      │
│  ┌───────────────────┐  │       │   - Webhook source        │
│  │ license_service   │  │       └──────────┬────────────────┘
│  │  (in-app, local)  │  │                  │ order_created
│  │  - Verify sig     │  │                  ▼
│  │  - Gate features  │  │       ┌───────────────────────────┐
│  │  - Cache status   │  │       │  license-service (ours)   │
│  └──────┬────────────┘  │       │  Cloudflare Worker        │
│         │               │       │  - Sign license file      │
│  ┌──────┴────────────┐  │       │  - Email via Postmark     │
│  │ support_service   │──┼──────▶│  - /support/issues        │
│  │  - Redact         │  │ POST  │  - Revocation list (R2)   │
│  │  - Attach license │  │       └──────────┬────────────────┘
│  └───────────────────┘  │                  │ creates
│                         │                  ▼
└─────────────────────────┘       ┌───────────────────────────┐
                                  │  GitHub (public repo)     │
                                  │  - Issue + `supported`    │
                                  │  - Private metadata in    │
                                  │    maintainer-only comment│
                                  └───────────────────────────┘
```

### Trust model
- **Public key** (Ed25519, 32 bytes) is checked into the main repo at `api/keys/license_pubkey.pem` and baked into the `.app` bundle / Docker image.
- **Private key** lives exclusively as a Cloudflare Worker Secret (`LICENSE_SIGNING_KEY`).
- License file is self-contained — signature verification works fully offline. No phone-home on launch.
- **Revocation is optional and advisory:** a `revocations.json` list is fetched on startup (non-blocking, cached 7 days). If the fetch fails, the app trusts the local signature.

### Key rotation
If the private key is ever compromised, ship a new app version with a new bundled public key. Old licenses will not verify on the new version; old app versions will continue to accept the old licenses. Acceptable trade-off for a soft-enforcement model.

## 4. License File Format

### Payload (JSON, signed with Ed25519)
```json
{
  "license_id": "laip_01HXYZ...",
  "email": "alice@example.com",
  "product": "local-ai-platform",
  "tier": "individual",
  "issued_at": "2026-04-18T12:00:00Z",
  "version": 1,
  "features": ["workflow_engine", "rag", "multi_model", "desktop_gui", "github_support", "finetuning"]
}
```

Explicitly absent:
- `expires_at` — this is a lifetime license.
- `machine_id` — soft enforcement.
- `max_installs` — honor system.

### On-disk format (`~/.local-ai-platform/license.key`)
```
-----BEGIN LOCAL-AI-PLATFORM LICENSE-----
<base64(json_payload)>
.
<base64(ed25519_signature)>
-----END LOCAL-AI-PLATFORM LICENSE-----
```

Single PEM-style file, human-inspectable, copy-pastable in email.

### Verification flow (`api/services/license_service.py`)
1. Read file from `LICENSE_KEY_PATH` env var or `~/.local-ai-platform/license.key`.
2. Parse the two base64 blocks.
3. Verify signature against bundled public key.
4. Parse payload JSON → `License` Pydantic model.
5. Cross-check `product == "local-ai-platform"` (cross-product licenses do not validate).
6. Cache result in memory for the process lifetime.

### License states
| State | Meaning |
|---|---|
| `licensed` | File present, signature valid, not in revocation list |
| `unlicensed` | No file present |
| `invalid` | File present but signature bad, payload malformed, or wrong product |
| `revoked` | Valid signature, but `license_id` appears in `revocations.json` |

`invalid` and `revoked` behave as `unlicensed` for gating purposes but surface diagnostic info in `/health` and the desktop banner.

## 5. License Enforcement

Goal: **one source of truth, three enforcement points.**

### Source of truth: `api/services/license_service.py`
```python
class LicenseService:
    def load(self) -> LicenseStatus            # at startup
    def status(self) -> LicenseStatus           # cached, instant
    def has_feature(self, feature: str) -> bool
    def require_feature(self, feature: str)    # raises LicenseRequiredError

class LicenseStatus(BaseModel):
    state: Literal["licensed", "unlicensed", "invalid", "revoked"]
    license: License | None
    loaded_at: datetime
    source_path: Path | None
```

Loaded during FastAPI startup, attached to `app.state.license`. CLI tools instantiate directly.

### Feature registry: `api/services/features.py`
```python
PREMIUM_FEATURES = {
    "workflow_engine":   "Multi-agent workflow engine",
    "rag":               "RAG pipeline (ChromaDB + LangChain)",
    "multi_model":       "Multi-model orchestration",
    "desktop_gui":       "PyWebView desktop app",
    "github_support":    "Submit issues via GitHub bridge",
    "finetuning":        "Fine-tuning pipeline (future)",
}
```
Single place to see every gated feature.

### Enforcement points (exactly three)

**1. FastAPI dependency** on premium routers:
```python
@router.post("/run", dependencies=[Depends(require_license_feature("workflow_engine"))])
async def run_workflow(...): ...
```
On failure → `HTTP 402 Payment Required`:
```json
{"error": "license_required", "feature": "workflow_engine", "purchase_url": "https://..."}
```

**2. CLI commands** check at dispatch:
```python
@workflow_cli.command()
def run(...):
    license_svc.require_feature("workflow_engine")
```
On failure → friendly multi-line message, exit code 2.

**3. Desktop app startup** (`desktop/app.py`) — if `desktop_gui` not licensed, window opens with a persistent dismissible-but-returning banner. Nothing blocked.

### Free-tier nag
- CLI chat: 1-in-5 sessions append a one-line footer: `💡 Support development — license $49 — <url>`
- API responses: `X-LocalAI-License-Status: unlicensed` header on every response
- Desktop: persistent banner (returns on restart if dismissed)

### Configuration (`.env`)
```
LICENSE_KEY_PATH=/custom/path/license.key   # optional
LICENSE_ENFORCEMENT=strict                  # strict | permissive
```
`permissive` logs warnings but does not block — used for local development. Not documented externally.

### Unlicensed user experience

CLI:
```
$ python cli/workflow.py run my-workflow.yaml
⚠️  This feature requires a license.

  Feature:     Multi-agent workflow engine
  Tier:        Individual ($49, lifetime)
  Purchase:    https://ohno.lemonsqueezy.com/local-ai-platform

Already purchased? Drop your license.key into ~/.local-ai-platform/
```

API:
```
HTTP/1.1 402 Payment Required
{"error":"license_required","feature":"workflow_engine","purchase_url":"..."}
```

## 6. Support Flow (Issue → GitHub Bridge)

Licensed users submit structured issues through the app; `license-service` creates a public GitHub issue on the main repo with a `supported` label. License-id and email are posted as a **private maintainer-only comment** by the bot — never exposed in the public issue body.

### Client entry points
1. **CLI (primary):** `python cli/support.py file-issue [--attach-logs] [--attach-config]`
2. **Desktop menu:** "Help → Report an Issue"
3. **Local API:** `POST /v1/support/issues` (for tooling)

### Collected data (with user-visible review screen)

| Field | Source | Consent |
|---|---|---|
| Title + description | User-entered | — |
| App version, OS/arch, Python version | Runtime | Always |
| Installed models | `ollama list` | Opt-in (default on) |
| Recent logs (last 200 lines) | `data/logs/*.log` | Opt-in (default on, always redacted) |
| Config snapshot | `.env` minus secrets | Opt-in (default off) |
| License ID, email | License payload | Always (entitlement + reply threading) |

Review screen shows the exact payload before submission. A copy is written to `~/.local-ai-platform/support/last-submission.json`.

### Redaction (mandatory — security boundary)
Applied client-side in `cli/support/redact.py`:
- API keys, license keys, JWT-shaped strings → `[REDACTED]`
- Absolute paths containing `/Users/<name>/` → `/Users/<user>/`
- Email addresses other than the licensee's own → `[email]`

Redaction is **non-optional** because issues land on a public repo.

### Request shape
```http
POST /support/issues HTTP/1.1
Host: license.ohno.dev
Content-Type: application/json
X-Local-AI-License: <base64 of license.key contents>

{
  "title": "...",
  "body": "...",
  "severity": "bug" | "question" | "feature_request",
  "metadata": {
    "app_version": "0.4.2",
    "os": "macOS 15.3 arm64",
    "python": "3.12.7",
    "models": [...]
  },
  "attachments": [
    {"name": "logs.txt", "content_base64": "..."}
  ]
}
```

The license payload + signature in the `X-Local-AI-License` header is the credential. Server verifies signature on every request (stateless, no DB lookup), checks revocation list, applies rate limit.

### Attachment strategy
- **Inline:** up to 256 KB per request.
- **Larger bundles:** client calls `GET /support/upload-url` → receives short-lived R2 signed URL → uploads → includes URL in the issue. Opt-in per-submission.

### GitHub issue template (public body)
```markdown
### Local AI Platform support — v0.4.2 · macOS 15.3 arm64 · Python 3.12.7

#### Description
<user text>

---
#### Environment
<collapsible block with installed models, redacted config, redacted logs>

---
*Reported by a licensed user. Maintainer metadata in hidden comment.*
```
Labels: `support`, `supported`, `tier:individual`, `severity:<user-chosen>`.

Immediately after issue creation, the bot posts a **second API call** creating a comment visible only to repo maintainers (via a GitHub App with fine-grained permissions):
```
<!-- laip-support-metadata-v1 -->
license_id: laip_01HXYZ...
email: alice@example.com
order_id: <ls_order_number>
submitted_at: 2026-04-18T14:22:00Z
payload_hash: sha256:...
```

### Abuse controls
- Per-license rate limit: **10 issues/day, 50/month**.
- Revoked licenses: immediate 403.
- Payload size cap: 256 KB inline; larger via signed upload URL.
- Tampered license header: 401.

### Failure modes
| Scenario | Behavior |
|---|---|
| `license-service` unreachable | Client writes to `~/.local-ai-platform/support/queued/`, exposes `support.py retry-queued` |
| GitHub API 5xx | `license-service` returns 503; client queues |
| Rate limit hit | Friendly 429 message; client does **not** queue |
| Forged license header | 401, audit-logged by license-service |

### Future (out of scope)
The `laip-support-metadata-v1` hidden comment is structured to support future automation:
- **Phase 2a:** GitHub Action on `supported` label → ack + ETA email via `license-service`.
- **Phase 2b:** Claude Code reproducer against the attached logs.
- **Phase 2c:** Auto-draft PR referencing the issue.

None of these are in scope for v1. Schema will not require changes.

## 7. Payment & Fulfillment (Lemon Squeezy → license-service)

### Product configuration (Lemon Squeezy, one-time manual setup)
- Product: *Local AI Platform — Individual Lifetime*
- Price: $49 USD, one-time
- Built-in digital delivery: **disabled** (we deliver via webhook for signed file)
- Webhook URL: `https://license.ohno.dev/webhooks/lemonsqueezy`
- Events: `order_created`, `order_refunded`

### `license-service` endpoints
```
POST /webhooks/lemonsqueezy     ← Lemon Squeezy → create & email license
POST /support/issues            ← App → create GitHub issue
GET  /support/upload-url        ← App → R2 signed URL for large attachments
GET  /revocations.json          ← App → optional revocation list poll
POST /admin/revoke              ← Maintainer (token-auth) → chargeback handling
POST /admin/reissue             ← Maintainer (token-auth) → lost-license recovery
GET  /recover                   ← Customer self-serve reissue (signed link)
```

### Order → license critical path
```
1. POST /webhooks/lemonsqueezy
   ├─ Verify X-Signature HMAC-SHA256 against LEMONSQUEEZY_WEBHOOK_SECRET
   └─ 401 if invalid

2. If order_created && product_id == LAIP_PRODUCT_ID:
   ├─ Extract: customer_email, order_id, order_number
   ├─ Idempotency: if R2 has licenses/by-order/{order_id}.json, re-use it
   ├─ Otherwise:
   │   ├─ license_id = "laip_" + ulid()
   │   ├─ payload = { license_id, email, product, tier:"individual",
   │   │             issued_at: now(), version: 1, features: [...] }
   │   ├─ signature = Ed25519.sign(LICENSE_SIGNING_KEY, json(payload))
   │   ├─ license_file = format_pem(payload, signature)
   │   ├─ Write licenses/{license_id}.json and licenses/by-order/{order_id}.json to R2
   │   └─ Postmark → email with license.key attached + install instructions + reissue link
   └─ 200

3. If order_refunded:
   ├─ Look up license_id by order_id
   ├─ Mark revoked, append to revocations.json
   └─ 200
```

### Email (Postmark transactional)
- From: `licenses@ohno.dev`
- Subject: "Your Local AI Platform license"
- Body: thanks + install instructions + self-serve reissue link + support link
- Attachment: `license.key`
- Sender domain must have SPF + DKIM + DMARC configured on `ohno.dev`.

### Lost-license recovery (three tiers, ascending effort)
1. **Self-serve reissue link** in original email. Signed, 90-day TTL, re-sends the same license file.
2. **Web form** at `license.ohno.dev/recover` — email + order number → triggers reissue email.
3. **Maintainer manual** via `POST /admin/reissue` with admin token.

No accounts, no passwords. The purchase email is the identity anchor.

### Chargeback / refund
`order_refunded` → license auto-revoked → appears in `revocations.json` within 7 days (client cache TTL). Running app continues to function until next startup (acceptable for soft enforcement).

### Secrets (Cloudflare Worker Secrets)
```
LICENSE_SIGNING_KEY          Ed25519 private key (base64)
LEMONSQUEEZY_WEBHOOK_SECRET  HMAC verification
LEMONSQUEEZY_API_KEY         Customer lookup
POSTMARK_SERVER_TOKEN        Email sending
GITHUB_APP_ID
GITHUB_APP_PRIVATE_KEY       GitHub App token minting
GITHUB_APP_INSTALLATION_ID
ADMIN_TOKEN                  /admin/* endpoints
```

### Cost estimate (≤1000 sales/mo)
| Component | Cost |
|---|---|
| Cloudflare Workers | $0 (within free tier) |
| Cloudflare R2 | $0 (license records ~1 KB each) |
| Postmark | $15/mo starter (10k emails) |
| Domain `ohno.dev` | assumed owned |
| Lemon Squeezy | 5% + $0.50 per transaction |
| **Fixed infra / month** | **~$15** |

### Test-mode validation (pre-launch)
Lemon Squeezy **Test Mode** sends real webhooks for test-card orders. Test licenses include `"test": true` in payload — app displays a "Test License" banner when seen. Flip LS to Live Mode at launch.

## 8. Repo Structure

### Main repo changes (`local-ai-platform/`)
```
api/
├── services/
│   ├── license_service.py         NEW  Load & verify, cache status, feature gating
│   ├── features.py                NEW  PREMIUM_FEATURES registry
│   └── support_service.py         NEW  Redact + submit to license-service
├── routers/
│   └── support.py                 NEW  POST /v1/support/issues
├── middleware.py                  EDIT require_license_feature dependency
├── main.py                        EDIT startup hook loads license into app.state
└── keys/
    └── license_pubkey.pem         NEW  Ed25519 public key (committed)

cli/
├── support.py                     NEW  file-issue, retry-queued commands
├── license.py                     NEW  install, show, verify commands
└── chat.py                        EDIT Nag footer (1-in-5) for unlicensed

desktop/
└── app.py                         EDIT desktop_gui feature check + banner

docs/
├── LICENSING.md                   NEW  User-facing purchase & install guide
└── SUPPORT.md                     NEW  How to file issues

tests/
├── test_license_service.py        NEW
├── test_features_gating.py        NEW
├── test_support_redaction.py      NEW
└── fixtures/
    ├── valid_license.key          NEW  Signed with test key
    ├── tampered_license.key       NEW
    ├── revoked_license.key        NEW
    └── test_pubkey.pem            NEW  Parallel test keypair
```

### New repo: `ohno/license-service` (TypeScript, Cloudflare Worker)
```
license-service/
├── src/
│   ├── index.ts                   Worker entry + router
│   ├── crypto.ts                  Ed25519 signing
│   ├── webhooks/lemonsqueezy.ts
│   ├── support/issues.ts          GitHub issue creation
│   ├── support/upload.ts          R2 signed-URL minting
│   ├── admin/{revoke,reissue}.ts
│   ├── storage/r2.ts
│   ├── email/postmark.ts
│   └── github/app.ts              GitHub App token minting
├── test/                          Vitest + Miniflare
├── wrangler.toml
└── package.json
```
Estimated ~500 LOC TypeScript.

## 9. Error Handling Matrix

| Scenario | Behavior |
|---|---|
| No license file | `state=unlicensed`, free tier, no error |
| Bad signature | `state=invalid`, log WARN, treat as unlicensed |
| Wrong `product` field | `state=invalid` |
| `license_id` in revocations list | `state=revoked`, banner shown |
| Revocation fetch fails | Trust local signature, retry next startup |
| `license-service` down on support submit | Queue to `~/.local-ai-platform/support/queued/`, exit 0 |
| 429 from `license-service` | Friendly message, do **not** queue |
| GitHub API 5xx | 503 returned to client, client queues |
| System clock skewed | No-op (signature not time-dependent) |
| Premium feature via API, unlicensed | 402 with `{error, feature, purchase_url}` |
| Premium feature via CLI, unlicensed | Friendly message, exit 2 |

### Logging
- Events: `license.log` with JSON lines — `load`, `verify_fail`, `feature_gate_hit`.
- No PII — only opaque `license_id`.
- `feature_gate_hit` counts live in `~/.local-ai-platform/gate_hits.json` for local "you'd save time licensing" messaging. **Never reported to us.**

## 10. Testing Strategy

### In-app (pytest)
- **Unit:** signature verification with valid/tampered/wrong-key fixtures. Redaction rules with golden-file inputs → expected outputs. Feature gate across all four states.
- **Integration:** FastAPI TestClient against premium endpoints (402 without license, 200 with fixture). CLI commands with and without `LICENSE_KEY_PATH` set.
- **Property-based (hypothesis):** redaction never leaks strings from a known-secrets set. Critical because redaction is now a security boundary.

### license-service (vitest + miniflare)
- Webhook replay: fixture payload → asserts R2 record, mock Postmark call, idempotency on replay.
- Signature forgery: reject invalid HMAC.
- Issue submission: valid → GitHub mock called correctly; revoked → 403; rate limit → 429.

### End-to-end manual (pre-launch checklist, documented in `docs/LICENSING.md`)
1. LS Test Mode: buy with `4242 4242…` card.
2. Receive email with `license.key`.
3. Install file; run premium CLI command → succeeds.
4. `POST /admin/revoke` with admin token.
5. Restart app → banner shows `revoked`.

### Out-of-scope tests (explicit YAGNI)
- Load tests on `license-service` (Cloudflare scales trivially).
- Cross-platform desktop UI tests.
- Email rendering tests (Postmark preview UI).

## 11. Release Sequence

1. Deploy `license-service` to Cloudflare (worker + R2 + secrets).
2. Configure Lemon Squeezy in Test Mode.
3. Configure Postmark with verified sender domain (SPF/DKIM/DMARC on `ohno.dev`).
4. Configure GitHub App with repo permissions on `local-ai-platform`.
5. Merge in-app changes behind `LICENSING_ENABLED` env flag (default off).
6. Manual end-to-end run-through with test card.
7. Flip `LICENSING_ENABLED` default to on.
8. Cut `v1.0` release.
9. Flip Lemon Squeezy to Live Mode.

## 12. Out of Scope (Future Work)

- **Team tier:** multi-seat licenses, transfer/revoke individual seats, shared license file. License data model already supports this via `tier` field and per-feature gating.
- **AI-assisted PR generation** (Phase 2a/2b/2c from §6).
- **Customer web portal** with purchase history, multiple licenses, download history.
- **Upgrade path** individual → team (probably "credit the $49 toward team tier").
- **Subscription tier** for ongoing updates (if ever) — current design is truly lifetime, no update cutoff.
- **Multi-currency pricing display** — Lemon Squeezy handles display; receipts stay USD.

## 13. Open Questions

None remaining at design close. Two calls made during brainstorming that may warrant revisiting post-launch:
- **Domain:** `license.ohno.dev` chosen; swap is a DNS change, not code.
- **Support repo placement:** issues on the main public repo with `supported` label (chose transparency over gated repo). Reversible by swapping `GITHUB_TARGET_REPO` in `license-service`.
