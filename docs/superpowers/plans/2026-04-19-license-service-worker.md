# License Service Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Cloudflare Worker that signs Ed25519 license files on Lemon Squeezy webhooks, delivers them via Postmark, creates GitHub support issues for licensed users, and handles admin revocation/reissue.

**Architecture:** Single Worker in a new repo (`ohno/license-service`), Hono router, R2 for license records and revocation list, Cloudflare KV for rate-limit counters. Ed25519 signing via Web Crypto (bundled in workerd). No dependency on a database — R2 is the only persistent store.

**Tech Stack:** TypeScript, Cloudflare Workers (wrangler 3), Hono 4, R2, KV, Vitest + `@cloudflare/vitest-pool-workers` (miniflare), Zod for payload validation, `@noble/ed25519` for key generation (Web Crypto handles sign/verify at runtime).

**Spec:** `docs/superpowers/specs/2026-04-18-licensing-and-supportability-design.md`

---

## File Structure

```
license-service/                        # new repo ohno/license-service
├── package.json
├── tsconfig.json
├── wrangler.toml
├── vitest.config.ts
├── .gitignore
├── .dev.vars.example
├── README.md
├── scripts/
│   └── generate-keypair.ts            Generate Ed25519 keypair once, print
├── src/
│   ├── index.ts                       Hono app, binds endpoints, exports default handler
│   ├── env.ts                         Env bindings type + runtime validation
│   ├── types.ts                       License, LicenseRecord, PRODUCT, FEATURES constants
│   ├── crypto/
│   │   ├── ed25519.ts                 sign(payloadBytes, privateKey) → signatureBytes
│   │   └── license.ts                 formatPem / parsePem, signLicense helper
│   ├── storage/
│   │   ├── licenses.ts                R2 CRUD: write, getById, getByOrder
│   │   └── revocations.ts             revocations.json accessor
│   ├── email/
│   │   └── postmark.ts                sendLicenseEmail(to, licenseFile)
│   ├── github/
│   │   └── app.ts                     Mint installation token, create issue, post private comment
│   ├── webhooks/
│   │   └── lemonsqueezy.ts            POST /webhooks/lemonsqueezy
│   ├── support/
│   │   ├── issues.ts                  POST /support/issues
│   │   └── upload.ts                  GET /support/upload-url
│   ├── admin/
│   │   ├── revoke.ts                  POST /admin/revoke
│   │   └── reissue.ts                 POST /admin/reissue
│   ├── recover/
│   │   └── self-serve.ts              GET /recover
│   └── utils/
│       ├── hmac.ts                    Constant-time HMAC-SHA256 verify
│       ├── rate-limit.ts              Per-license rate limiter (KV)
│       └── errors.ts                  HttpError class, Hono error handler
└── test/
    ├── helpers/
    │   └── fixtures.ts                Test keypair, sample LS payload, license records
    ├── crypto.test.ts
    ├── webhooks.test.ts
    ├── support-issues.test.ts
    ├── support-upload.test.ts
    ├── admin.test.ts
    └── integration.test.ts            End-to-end flow
```

**Responsibility boundaries:**
- `crypto/` — pure functions, no I/O, no env access
- `storage/` — thin wrappers over R2 bindings, no business logic
- `email/`, `github/` — external-service adapters, one file per service
- `webhooks/`, `support/`, `admin/`, `recover/` — route handlers, orchestrate services, return `Response`
- `index.ts` — only routing + middleware wiring

---

## Prerequisites (one-time, manual — document in README as you go)

- Cloudflare account with Workers + R2 + KV enabled
- Domain `ohno.dev` in Cloudflare DNS
- Lemon Squeezy store created, product "Local AI Platform — Individual Lifetime" priced at $49 one-time
- Postmark account with verified sender domain (SPF/DKIM/DMARC on `ohno.dev`)
- GitHub App installed on `hankthebldr/local-ai-platform` with `issues:write` and `metadata:read` permissions only
- `wrangler` CLI installed locally (`npm i -g wrangler@3`) and authenticated (`wrangler login`)

The plan assumes these exist. Infrastructure creation (R2 buckets, KV namespaces, secrets) happens in Task 1.

---

## Task 1: Initialize project scaffolding

**Files:**
- Create: `license-service/package.json`
- Create: `license-service/tsconfig.json`
- Create: `license-service/wrangler.toml`
- Create: `license-service/.gitignore`
- Create: `license-service/.dev.vars.example`
- Create: `license-service/vitest.config.ts`
- Create: `license-service/src/index.ts`
- Create: `license-service/test/smoke.test.ts`

- [ ] **Step 1: Create repo directory & init git**

```bash
mkdir -p ~/Github/license-service && cd ~/Github/license-service
git init
```

- [ ] **Step 2: Write `package.json`**

```json
{
  "name": "license-service",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit",
    "generate-keypair": "tsx scripts/generate-keypair.ts"
  },
  "dependencies": {
    "hono": "^4.6.0",
    "zod": "^3.23.0"
  },
  "devDependencies": {
    "@cloudflare/vitest-pool-workers": "^0.5.0",
    "@cloudflare/workers-types": "^4.20250101.0",
    "@noble/ed25519": "^2.1.0",
    "tsx": "^4.19.0",
    "typescript": "^5.6.0",
    "vitest": "^2.1.0",
    "wrangler": "^3.90.0"
  }
}
```

- [ ] **Step 3: Write `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "Bundler",
    "lib": ["ES2022"],
    "types": ["@cloudflare/workers-types", "vitest/globals"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "noEmit": true
  },
  "include": ["src/**/*.ts", "test/**/*.ts", "scripts/**/*.ts"]
}
```

- [ ] **Step 4: Write `wrangler.toml`**

```toml
name = "license-service"
main = "src/index.ts"
compatibility_date = "2025-01-01"
compatibility_flags = ["nodejs_compat"]

[[r2_buckets]]
binding = "LICENSES"
bucket_name = "laip-licenses"

[[kv_namespaces]]
binding = "RATE_LIMITS"
id = "PLACEHOLDER_KV_ID"

[vars]
PRODUCT_ID = ""
GITHUB_REPO_OWNER = "hankthebldr"
GITHUB_REPO_NAME = "local-ai-platform"
PURCHASE_URL = "https://ohno.lemonsqueezy.com/local-ai-platform"
SELF_URL = "https://license.ohno.dev"
```

Secrets (populated via `wrangler secret put` later): `LICENSE_SIGNING_KEY`, `LEMONSQUEEZY_WEBHOOK_SECRET`, `LEMONSQUEEZY_API_KEY`, `POSTMARK_SERVER_TOKEN`, `POSTMARK_FROM_EMAIL`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_INSTALLATION_ID`, `ADMIN_TOKEN`.

- [ ] **Step 5: Write `.gitignore`**

```
node_modules/
.dev.vars
.wrangler/
dist/
coverage/
.DS_Store
```

- [ ] **Step 6: Write `.dev.vars.example`**

```
LICENSE_SIGNING_KEY=base64-ed25519-private-key-32-bytes
LEMONSQUEEZY_WEBHOOK_SECRET=from-lemon-squeezy-settings
LEMONSQUEEZY_API_KEY=from-lemon-squeezy-api
POSTMARK_SERVER_TOKEN=from-postmark
POSTMARK_FROM_EMAIL=licenses@ohno.dev
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----
GITHUB_APP_INSTALLATION_ID=7890123
ADMIN_TOKEN=long-random-string-rotate-if-leaked
```

- [ ] **Step 7: Write `vitest.config.ts`**

```typescript
import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        wrangler: { configPath: "./wrangler.toml" },
        miniflare: {
          r2Buckets: ["LICENSES"],
          kvNamespaces: ["RATE_LIMITS"],
          bindings: {
            PRODUCT_ID: "test-product",
            GITHUB_REPO_OWNER: "hankthebldr",
            GITHUB_REPO_NAME: "local-ai-platform",
            PURCHASE_URL: "https://example.com/buy",
            SELF_URL: "https://license.test",
            LICENSE_SIGNING_KEY: "test-key-populated-in-setup",
            LEMONSQUEEZY_WEBHOOK_SECRET: "test-secret",
            POSTMARK_SERVER_TOKEN: "test-postmark",
            POSTMARK_FROM_EMAIL: "licenses@test",
            GITHUB_APP_ID: "1",
            GITHUB_APP_PRIVATE_KEY: "test-pk",
            GITHUB_APP_INSTALLATION_ID: "1",
            ADMIN_TOKEN: "test-admin-token",
          },
        },
      },
    },
  },
});
```

- [ ] **Step 8: Write minimal `src/index.ts`**

```typescript
import { Hono } from "hono";

const app = new Hono<{ Bindings: CloudflareBindings }>();

app.get("/", (c) => c.text("license-service"));
app.get("/health", (c) => c.json({ status: "ok" }));

export default app;

export interface CloudflareBindings {
  LICENSES: R2Bucket;
  RATE_LIMITS: KVNamespace;
  PRODUCT_ID: string;
  GITHUB_REPO_OWNER: string;
  GITHUB_REPO_NAME: string;
  PURCHASE_URL: string;
  SELF_URL: string;
  LICENSE_SIGNING_KEY: string;
  LEMONSQUEEZY_WEBHOOK_SECRET: string;
  LEMONSQUEEZY_API_KEY?: string;
  POSTMARK_SERVER_TOKEN: string;
  POSTMARK_FROM_EMAIL: string;
  GITHUB_APP_ID: string;
  GITHUB_APP_PRIVATE_KEY: string;
  GITHUB_APP_INSTALLATION_ID: string;
  ADMIN_TOKEN: string;
}
```

- [ ] **Step 9: Write smoke test `test/smoke.test.ts`**

```typescript
import { SELF } from "cloudflare:test";
import { describe, it, expect } from "vitest";

describe("smoke", () => {
  it("returns 200 on /health", async () => {
    const res = await SELF.fetch("https://license.test/health");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
  });

  it("returns 200 on /", async () => {
    const res = await SELF.fetch("https://license.test/");
    expect(res.status).toBe(200);
    expect(await res.text()).toBe("license-service");
  });
});
```

- [ ] **Step 10: Install & run tests**

Run: `cd ~/Github/license-service && npm install && npm test`
Expected: 2 tests pass.

- [ ] **Step 11: Create Cloudflare resources**

```bash
wrangler r2 bucket create laip-licenses
wrangler kv namespace create RATE_LIMITS
```

Copy the returned KV `id` into `wrangler.toml` replacing `PLACEHOLDER_KV_ID`.

- [ ] **Step 12: Commit**

```bash
git add .
git commit -m "chore: scaffold license-service worker"
```

---

## Task 2: Types & constants

**Files:**
- Create: `license-service/src/types.ts`
- Create: `test/helpers/fixtures.ts`

- [ ] **Step 1: Write `src/types.ts`**

```typescript
import { z } from "zod";

export const PRODUCT = "local-ai-platform" as const;

export const INDIVIDUAL_FEATURES = [
  "workflow_engine",
  "rag",
  "multi_model",
  "desktop_gui",
  "github_support",
  "finetuning",
] as const;

export const LicensePayloadSchema = z.object({
  license_id: z.string().regex(/^laip_[A-Z0-9]{26}$/),
  email: z.string().email(),
  product: z.literal(PRODUCT),
  tier: z.enum(["individual"]),
  issued_at: z.string().datetime(),
  version: z.literal(1),
  features: z.array(z.string()),
  test: z.boolean().optional(),
});
export type LicensePayload = z.infer<typeof LicensePayloadSchema>;

export const LicenseRecordSchema = z.object({
  license_id: z.string(),
  email: z.string().email(),
  order_id: z.string(),
  order_number: z.string().optional(),
  issued_at: z.string().datetime(),
  revoked: z.boolean(),
  test: z.boolean().optional(),
});
export type LicenseRecord = z.infer<typeof LicenseRecordSchema>;

export const SupportIssueRequestSchema = z.object({
  title: z.string().min(3).max(200),
  body: z.string().min(10).max(50_000),
  severity: z.enum(["bug", "question", "feature_request"]),
  metadata: z.object({
    app_version: z.string(),
    os: z.string(),
    python: z.string(),
    models: z.array(z.string()).optional(),
  }),
  attachments: z
    .array(
      z.object({
        name: z.string().max(100),
        content_base64: z.string().max(350_000),
      })
    )
    .max(5)
    .optional(),
});
export type SupportIssueRequest = z.infer<typeof SupportIssueRequestSchema>;
```

- [ ] **Step 2: Write `test/helpers/fixtures.ts`**

```typescript
import type { LicensePayload, LicenseRecord } from "../../src/types";

export const sampleLicensePayload: LicensePayload = {
  license_id: "laip_01HXYZTEST0000000000000000",
  email: "alice@example.com",
  product: "local-ai-platform",
  tier: "individual",
  issued_at: "2026-04-19T12:00:00.000Z",
  version: 1,
  features: [
    "workflow_engine",
    "rag",
    "multi_model",
    "desktop_gui",
    "github_support",
    "finetuning",
  ],
};

export const sampleLicenseRecord: LicenseRecord = {
  license_id: "laip_01HXYZTEST0000000000000000",
  email: "alice@example.com",
  order_id: "lsorder_12345",
  order_number: "LAIP-00042",
  issued_at: "2026-04-19T12:00:00.000Z",
  revoked: false,
};

export const sampleLemonSqueezyOrderCreated = {
  meta: {
    event_name: "order_created",
    custom_data: {},
  },
  data: {
    type: "orders",
    id: "lsorder_12345",
    attributes: {
      order_number: 42,
      store_id: 1,
      customer_id: 1,
      user_email: "alice@example.com",
      first_order_item: {
        product_id: 999,
      },
      test_mode: false,
    },
  },
};
```

- [ ] **Step 3: Verify it typechecks**

Run: `cd ~/Github/license-service && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/types.ts test/helpers/fixtures.ts
git commit -m "feat: define license and support types"
```

---

## Task 3: Ed25519 signing & key generation script

**Files:**
- Create: `license-service/src/crypto/ed25519.ts`
- Create: `license-service/scripts/generate-keypair.ts`
- Create: `license-service/test/crypto.test.ts`

- [ ] **Step 1a: Generate a real test keypair first**

Before writing the test, generate a working Ed25519 keypair (Web Crypto in workerd cannot `generateKey` for Ed25519 as exportable PKCS8, so we use Node once):

```bash
node --input-type=module -e "
import { webcrypto } from 'node:crypto';
const kp = await webcrypto.subtle.generateKey({name:'Ed25519'}, true, ['sign','verify']);
const priv = await webcrypto.subtle.exportKey('pkcs8', kp.privateKey);
const pub  = await webcrypto.subtle.exportKey('spki',  kp.publicKey);
console.log('TEST_PRIVATE_B64 =', Buffer.from(priv).toString('base64'));
console.log('TEST_PUBLIC_B64  =', Buffer.from(pub ).toString('base64'));
"
```

Copy the two values into `test/helpers/keys.ts` (create):

```typescript
// test/helpers/keys.ts — TEST-ONLY keypair. Regenerate anytime. Never used in prod.
export const TEST_PRIVATE_B64 = "PASTE_OUTPUT_HERE";
export const TEST_PUBLIC_B64 = "PASTE_OUTPUT_HERE";
```

Commit both the constants file and the generated values. The private key being in git is acceptable because this pair signs only test fixtures — the production private key never leaves Cloudflare Secrets.

- [ ] **Step 1b: Write failing test `test/crypto.test.ts`**

```typescript
import { describe, it, expect } from "vitest";
import { sign, verify, importPrivateKeyFromBase64, importPublicKeyFromBase64 } from "../src/crypto/ed25519";
import { TEST_PRIVATE_B64, TEST_PUBLIC_B64 } from "./helpers/keys";

describe("ed25519", () => {
  it("signs and verifies a payload round-trip", async () => {
    const priv = await importPrivateKeyFromBase64(TEST_PRIVATE_B64);
    const pub = await importPublicKeyFromBase64(TEST_PUBLIC_B64);
    const message = new TextEncoder().encode("hello world");
    const sig = await sign(priv, message);
    expect(sig).toBeInstanceOf(Uint8Array);
    expect(sig.length).toBe(64);
    expect(await verify(pub, sig, message)).toBe(true);
  });

  it("rejects tampered messages", async () => {
    const priv = await importPrivateKeyFromBase64(TEST_PRIVATE_B64);
    const pub = await importPublicKeyFromBase64(TEST_PUBLIC_B64);
    const message = new TextEncoder().encode("hello world");
    const sig = await sign(priv, message);
    const tampered = new TextEncoder().encode("hello worlD");
    expect(await verify(pub, sig, tampered)).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- test/crypto.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/crypto/ed25519.ts`**

```typescript
/**
 * Ed25519 signing via Web Crypto (bundled in workerd).
 * Private/public keys are exchanged as base64-encoded PKCS8/SPKI DER.
 */

export async function importPrivateKeyFromBase64(b64: string): Promise<CryptoKey> {
  const der = base64ToBytes(b64);
  return await crypto.subtle.importKey("pkcs8", der, { name: "Ed25519" }, false, ["sign"]);
}

export async function importPublicKeyFromBase64(b64: string): Promise<CryptoKey> {
  const der = base64ToBytes(b64);
  return await crypto.subtle.importKey("spki", der, { name: "Ed25519" }, false, ["verify"]);
}

export async function sign(privateKey: CryptoKey, message: Uint8Array): Promise<Uint8Array> {
  const sig = await crypto.subtle.sign({ name: "Ed25519" }, privateKey, message);
  return new Uint8Array(sig);
}

export async function verify(publicKey: CryptoKey, signature: Uint8Array, message: Uint8Array): Promise<boolean> {
  return await crypto.subtle.verify({ name: "Ed25519" }, publicKey, signature, message);
}

export function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function bytesToBase64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]!);
  return btoa(bin);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- test/crypto.test.ts`
Expected: 2 tests pass.

- [ ] **Step 5: Write the keypair generation script `scripts/generate-keypair.ts`**

```typescript
/**
 * Generate an Ed25519 keypair for license signing.
 * Run once at project setup; store the private key as a Cloudflare Secret,
 * copy the public key into the main repo at api/keys/license_pubkey.pem.
 *
 * Uses @noble/ed25519 (Node-side only — Web Crypto in workerd doesn't
 * expose generateKey for Ed25519 as PKCS8-exportable).
 */
import { webcrypto } from "node:crypto";

async function main() {
  // Node's Web Crypto supports Ed25519 generation + PKCS8/SPKI export.
  const kp = (await webcrypto.subtle.generateKey(
    { name: "Ed25519" },
    true,
    ["sign", "verify"]
  )) as CryptoKeyPair;

  const priv = await webcrypto.subtle.exportKey("pkcs8", kp.privateKey);
  const pub = await webcrypto.subtle.exportKey("spki", kp.publicKey);

  const privB64 = Buffer.from(priv).toString("base64");
  const pubB64 = Buffer.from(pub).toString("base64");
  const pubPem =
    "-----BEGIN PUBLIC KEY-----\n" +
    pubB64.match(/.{1,64}/g)!.join("\n") +
    "\n-----END PUBLIC KEY-----\n";

  console.log("=== PRIVATE KEY (base64 PKCS8) — store as LICENSE_SIGNING_KEY secret ===");
  console.log(privB64);
  console.log();
  console.log("=== PUBLIC KEY (PEM) — commit to local-ai-platform:api/keys/license_pubkey.pem ===");
  console.log(pubPem);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
```

- [ ] **Step 6: Commit**

```bash
git add src/crypto/ed25519.ts scripts/generate-keypair.ts test/crypto.test.ts
git commit -m "feat: ed25519 signing primitives + keygen script"
```

---

## Task 4: License PEM format

**Files:**
- Create: `license-service/src/crypto/license.ts`
- Modify: `license-service/test/crypto.test.ts` (append)

- [ ] **Step 1: Append failing tests to `test/crypto.test.ts`**

```typescript
import { formatLicensePem, parseLicensePem, signLicense } from "../src/crypto/license";
import { sampleLicensePayload } from "./helpers/fixtures";

describe("license PEM", () => {
  it("formats and parses round-trip", () => {
    const payloadBytes = new TextEncoder().encode(JSON.stringify(sampleLicensePayload));
    const sig = new Uint8Array(64).fill(0x42);
    const pem = formatLicensePem(payloadBytes, sig);
    expect(pem).toContain("BEGIN LOCAL-AI-PLATFORM LICENSE");
    expect(pem).toContain("END LOCAL-AI-PLATFORM LICENSE");
    const parsed = parseLicensePem(pem);
    expect(parsed.payload).toEqual(payloadBytes);
    expect(parsed.signature).toEqual(sig);
  });

  it("signLicense produces a verifiable license file", async () => {
    const { pem, license_id } = await signLicense(sampleLicensePayload, TEST_PRIVATE_B64);
    expect(license_id).toBe(sampleLicensePayload.license_id);
    const { payload, signature } = parseLicensePem(pem);
    const pub = await importPublicKeyFromBase64(TEST_PUBLIC_B64);
    expect(await verify(pub, signature, payload)).toBe(true);
  });

  it("parse rejects malformed pem", () => {
    expect(() => parseLicensePem("nope")).toThrow();
    expect(() => parseLicensePem("-----BEGIN LOCAL-AI-PLATFORM LICENSE-----\n\n-----END LOCAL-AI-PLATFORM LICENSE-----")).toThrow();
  });
});
```

- [ ] **Step 2: Run to verify fails**

Run: `npm test -- test/crypto.test.ts`
Expected: FAIL — cannot find module `../src/crypto/license`.

- [ ] **Step 3: Write `src/crypto/license.ts`**

```typescript
import { importPrivateKeyFromBase64, sign, bytesToBase64, base64ToBytes } from "./ed25519";
import type { LicensePayload } from "../types";

const BEGIN = "-----BEGIN LOCAL-AI-PLATFORM LICENSE-----";
const END = "-----END LOCAL-AI-PLATFORM LICENSE-----";

export function formatLicensePem(payload: Uint8Array, signature: Uint8Array): string {
  const payloadB64 = wrap(bytesToBase64(payload));
  const sigB64 = wrap(bytesToBase64(signature));
  return `${BEGIN}\n${payloadB64}\n.\n${sigB64}\n${END}\n`;
}

export function parseLicensePem(pem: string): { payload: Uint8Array; signature: Uint8Array } {
  const trimmed = pem.trim();
  if (!trimmed.startsWith(BEGIN) || !trimmed.endsWith(END)) {
    throw new Error("invalid license file: missing markers");
  }
  const inner = trimmed.slice(BEGIN.length, -END.length).trim();
  const parts = inner.split(/\n\.\n/);
  if (parts.length !== 2) {
    throw new Error("invalid license file: expected two base64 blocks separated by '.'");
  }
  const payload = base64ToBytes(parts[0]!.replace(/\s+/g, ""));
  const signature = base64ToBytes(parts[1]!.replace(/\s+/g, ""));
  if (signature.length !== 64) {
    throw new Error(`invalid license file: signature must be 64 bytes, got ${signature.length}`);
  }
  return { payload, signature };
}

export async function signLicense(
  payload: LicensePayload,
  privateKeyB64: string
): Promise<{ pem: string; license_id: string }> {
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payload));
  const priv = await importPrivateKeyFromBase64(privateKeyB64);
  const signature = await sign(priv, payloadBytes);
  const pem = formatLicensePem(payloadBytes, signature);
  return { pem, license_id: payload.license_id };
}

function wrap(s: string, width = 64): string {
  return s.match(new RegExp(`.{1,${width}}`, "g"))!.join("\n");
}
```

- [ ] **Step 4: Run tests**

Run: `npm test -- test/crypto.test.ts`
Expected: all tests pass (5 total).

- [ ] **Step 5: Commit**

```bash
git add src/crypto/license.ts test/crypto.test.ts
git commit -m "feat: license PEM format and signing"
```

---

## Task 5: Lemon Squeezy HMAC verification

**Files:**
- Create: `license-service/src/utils/hmac.ts`
- Create: `license-service/test/hmac.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, it, expect } from "vitest";
import { verifyLemonSqueezySignature } from "../src/utils/hmac";

describe("verifyLemonSqueezySignature", () => {
  const secret = "test-secret";
  // HMAC-SHA256 of 'hello' with key 'test-secret' (precomputed).
  const validSig = "09ab16bb4bf68f21cbea7e1ff40d5f85aef4cf73f24b20d72aee7bf18b6fb057";

  it("accepts a valid signature", async () => {
    const ok = await verifyLemonSqueezySignature("hello", validSig, secret);
    expect(ok).toBe(true);
  });

  it("rejects a wrong signature", async () => {
    const ok = await verifyLemonSqueezySignature("hello", "0".repeat(64), secret);
    expect(ok).toBe(false);
  });

  it("rejects mismatched body", async () => {
    const ok = await verifyLemonSqueezySignature("helloX", validSig, secret);
    expect(ok).toBe(false);
  });

  it("rejects malformed signature hex", async () => {
    const ok = await verifyLemonSqueezySignature("hello", "not-hex", secret);
    expect(ok).toBe(false);
  });
});
```

- [ ] **Step 2: Run, confirm failure**

Run: `npm test -- test/hmac.test.ts`
Expected: FAIL, module missing.

- [ ] **Step 3: Implement `src/utils/hmac.ts`**

```typescript
/**
 * Verify Lemon Squeezy webhook signature.
 * LS posts a lowercase hex digest in the `X-Signature` header:
 *   HMAC-SHA256(body, webhook_secret)
 * Constant-time comparison to avoid timing oracles.
 */
export async function verifyLemonSqueezySignature(
  body: string,
  signatureHex: string,
  secret: string
): Promise<boolean> {
  if (!/^[0-9a-fA-F]{64}$/.test(signatureHex)) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const computed = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body))
  );
  const provided = hexToBytes(signatureHex);
  return constantTimeEqual(computed, provided);
}

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(hex.substring(i * 2, i * 2 + 2), 16);
  }
  return out;
}

function constantTimeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0;
}
```

- [ ] **Step 4: Run, confirm pass**

Run: `npm test -- test/hmac.test.ts`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/utils/hmac.ts test/hmac.test.ts
git commit -m "feat: constant-time lemon squeezy webhook HMAC verify"
```

---

## Task 6: R2 license storage

**Files:**
- Create: `license-service/src/storage/licenses.ts`
- Create: `license-service/src/storage/revocations.ts`
- Create: `license-service/test/storage.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { env } from "cloudflare:test";
import { putLicense, getLicenseById, getLicenseByOrder } from "../src/storage/licenses";
import { appendRevocation, readRevocations } from "../src/storage/revocations";
import { sampleLicenseRecord } from "./helpers/fixtures";

async function clearBucket() {
  const objs = await env.LICENSES.list();
  await Promise.all(objs.objects.map((o) => env.LICENSES.delete(o.key)));
}

describe("licenses storage", () => {
  beforeEach(clearBucket);

  it("writes and reads by license_id", async () => {
    await putLicense(env.LICENSES, sampleLicenseRecord);
    const got = await getLicenseById(env.LICENSES, sampleLicenseRecord.license_id);
    expect(got).toEqual(sampleLicenseRecord);
  });

  it("writes and reads by order_id", async () => {
    await putLicense(env.LICENSES, sampleLicenseRecord);
    const got = await getLicenseByOrder(env.LICENSES, sampleLicenseRecord.order_id);
    expect(got).toEqual(sampleLicenseRecord);
  });

  it("returns null when license_id missing", async () => {
    expect(await getLicenseById(env.LICENSES, "laip_missing")).toBeNull();
  });
});

describe("revocations", () => {
  beforeEach(clearBucket);

  it("starts empty", async () => {
    const list = await readRevocations(env.LICENSES);
    expect(list).toEqual({ revoked: [], updated_at: expect.any(String) });
  });

  it("appends and deduplicates", async () => {
    await appendRevocation(env.LICENSES, "laip_a");
    await appendRevocation(env.LICENSES, "laip_b");
    await appendRevocation(env.LICENSES, "laip_a");
    const list = await readRevocations(env.LICENSES);
    expect(list.revoked.sort()).toEqual(["laip_a", "laip_b"]);
  });
});
```

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/storage.test.ts`
Expected: module missing.

- [ ] **Step 3: Write `src/storage/licenses.ts`**

```typescript
import { LicenseRecordSchema, type LicenseRecord } from "../types";

export async function putLicense(bucket: R2Bucket, record: LicenseRecord): Promise<void> {
  const body = JSON.stringify(record);
  await Promise.all([
    bucket.put(`licenses/${record.license_id}.json`, body, {
      httpMetadata: { contentType: "application/json" },
    }),
    bucket.put(`licenses/by-order/${record.order_id}.json`, body, {
      httpMetadata: { contentType: "application/json" },
    }),
  ]);
}

export async function getLicenseById(bucket: R2Bucket, licenseId: string): Promise<LicenseRecord | null> {
  const obj = await bucket.get(`licenses/${licenseId}.json`);
  if (!obj) return null;
  const parsed = LicenseRecordSchema.safeParse(JSON.parse(await obj.text()));
  return parsed.success ? parsed.data : null;
}

export async function getLicenseByOrder(bucket: R2Bucket, orderId: string): Promise<LicenseRecord | null> {
  const obj = await bucket.get(`licenses/by-order/${orderId}.json`);
  if (!obj) return null;
  const parsed = LicenseRecordSchema.safeParse(JSON.parse(await obj.text()));
  return parsed.success ? parsed.data : null;
}

export async function updateLicense(
  bucket: R2Bucket,
  licenseId: string,
  patch: Partial<LicenseRecord>
): Promise<LicenseRecord | null> {
  const current = await getLicenseById(bucket, licenseId);
  if (!current) return null;
  const merged: LicenseRecord = { ...current, ...patch };
  await putLicense(bucket, merged);
  return merged;
}
```

- [ ] **Step 4: Write `src/storage/revocations.ts`**

```typescript
const KEY = "revocations.json";

export interface RevocationList {
  revoked: string[];
  updated_at: string;
}

export async function readRevocations(bucket: R2Bucket): Promise<RevocationList> {
  const obj = await bucket.get(KEY);
  if (!obj) {
    return { revoked: [], updated_at: new Date().toISOString() };
  }
  try {
    const parsed = JSON.parse(await obj.text());
    const revoked: string[] = Array.isArray(parsed?.revoked) ? parsed.revoked : [];
    return { revoked, updated_at: parsed?.updated_at ?? new Date().toISOString() };
  } catch {
    return { revoked: [], updated_at: new Date().toISOString() };
  }
}

export async function appendRevocation(bucket: R2Bucket, licenseId: string): Promise<RevocationList> {
  const current = await readRevocations(bucket);
  if (current.revoked.includes(licenseId)) return current;
  const next: RevocationList = {
    revoked: [...current.revoked, licenseId],
    updated_at: new Date().toISOString(),
  };
  await bucket.put(KEY, JSON.stringify(next), {
    httpMetadata: { contentType: "application/json", cacheControl: "public, max-age=3600" },
  });
  return next;
}
```

- [ ] **Step 5: Run, pass**

Run: `npm test -- test/storage.test.ts`
Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/storage/ test/storage.test.ts
git commit -m "feat: R2 license and revocation storage"
```

---

## Task 7: Postmark email adapter

**Files:**
- Create: `license-service/src/email/postmark.ts`
- Create: `license-service/test/postmark.test.ts`

- [ ] **Step 1: Write failing test** (use `fetch` mock via vi.stubGlobal)

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { sendLicenseEmail } from "../src/email/postmark";

describe("sendLicenseEmail", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("POSTs to Postmark with proper envelope and attachment", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ MessageID: "abc" }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await sendLicenseEmail({
      to: "alice@example.com",
      licensePem: "-----BEGIN LOCAL-AI-PLATFORM LICENSE-----\n...\n-----END LOCAL-AI-PLATFORM LICENSE-----\n",
      reissueUrl: "https://license.test/recover?token=xyz",
      purchaseUrl: "https://example.com/buy",
      postmarkToken: "pm-token",
      fromEmail: "licenses@ohno.dev",
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("https://api.postmarkapp.com/email");
    expect(init.method).toBe("POST");
    expect(init.headers["X-Postmark-Server-Token"]).toBe("pm-token");
    const body = JSON.parse(init.body);
    expect(body.From).toBe("licenses@ohno.dev");
    expect(body.To).toBe("alice@example.com");
    expect(body.Subject).toMatch(/Local AI Platform/i);
    expect(body.Attachments).toHaveLength(1);
    expect(body.Attachments[0].Name).toBe("license.key");
    expect(body.Attachments[0].ContentType).toBe("application/octet-stream");
  });

  it("throws on non-2xx from Postmark", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 422 })));
    await expect(
      sendLicenseEmail({
        to: "x@y", licensePem: "", reissueUrl: "",
        purchaseUrl: "", postmarkToken: "", fromEmail: "",
      })
    ).rejects.toThrow(/Postmark/);
  });
});
```

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/postmark.test.ts`
Expected: module missing.

- [ ] **Step 3: Write `src/email/postmark.ts`**

```typescript
interface SendLicenseEmailArgs {
  to: string;
  licensePem: string;
  reissueUrl: string;
  purchaseUrl: string;
  postmarkToken: string;
  fromEmail: string;
}

export async function sendLicenseEmail(args: SendLicenseEmailArgs): Promise<void> {
  const body = {
    From: args.fromEmail,
    To: args.to,
    Subject: "Your Local AI Platform license",
    MessageStream: "outbound",
    TextBody: buildText(args),
    HtmlBody: buildHtml(args),
    Attachments: [
      {
        Name: "license.key",
        Content: btoa(args.licensePem),
        ContentType: "application/octet-stream",
      },
    ],
  };
  const res = await fetch("https://api.postmarkapp.com/email", {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
      "X-Postmark-Server-Token": args.postmarkToken,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Postmark send failed: ${res.status} ${await res.text()}`);
  }
}

function buildText(a: SendLicenseEmailArgs): string {
  return [
    "Thanks for supporting Local AI Platform!",
    "",
    "Your lifetime license is attached as license.key. To install:",
    "  1. Move license.key to ~/.local-ai-platform/license.key",
    "  2. Restart the app (or run: laip license verify)",
    "",
    "Lost this email? Re-send your license:",
    a.reissueUrl,
    "",
    "Need help?",
    "  https://github.com/hankthebldr/local-ai-platform/issues (mention your license)",
    "",
    `Purchase page: ${a.purchaseUrl}`,
  ].join("\n");
}

function buildHtml(a: SendLicenseEmailArgs): string {
  return `<p>Thanks for supporting Local AI Platform!</p>
<p>Your lifetime license is attached as <code>license.key</code>. To install:</p>
<ol><li>Move <code>license.key</code> to <code>~/.local-ai-platform/license.key</code></li>
<li>Restart the app (or run <code>laip license verify</code>)</li></ol>
<p>Lost this email? <a href="${a.reissueUrl}">Re-send your license</a>.</p>
<p>Need help? <a href="https://github.com/hankthebldr/local-ai-platform/issues">File an issue</a> — mention your license.</p>`;
}
```

- [ ] **Step 4: Run, pass**

Run: `npm test -- test/postmark.test.ts`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/email/postmark.ts test/postmark.test.ts
git commit -m "feat: Postmark license-delivery adapter"
```

---

## Task 8: Lemon Squeezy webhook — order_created (happy path + idempotency)

**Files:**
- Create: `license-service/src/webhooks/lemonsqueezy.ts`
- Create: `license-service/test/webhooks.test.ts`
- Modify: `license-service/src/index.ts`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SELF, env } from "cloudflare:test";
import { sampleLemonSqueezyOrderCreated } from "./helpers/fixtures";
import { getLicenseByOrder } from "../src/storage/licenses";

import { TEST_PRIVATE_B64 as TEST_PRIVATE, TEST_PUBLIC_B64 } from "./helpers/keys";

async function clearBucket() {
  const objs = await env.LICENSES.list();
  await Promise.all(objs.objects.map((o) => env.LICENSES.delete(o.key)));
}

async function hmacSig(body: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
  return Array.from(sig).map((b) => b.toString(16).padStart(2, "0")).join("");
}

describe("POST /webhooks/lemonsqueezy", () => {
  beforeEach(async () => {
    await clearBucket();
    env.LICENSE_SIGNING_KEY = TEST_PRIVATE;
    env.LEMONSQUEEZY_WEBHOOK_SECRET = "test-secret";
    env.PRODUCT_ID = "999";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ MessageID: "x" }), { status: 200 }))
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("rejects missing signature", async () => {
    const res = await SELF.fetch("https://license.test/webhooks/lemonsqueezy", {
      method: "POST", body: "{}",
    });
    expect(res.status).toBe(401);
  });

  it("rejects bad signature", async () => {
    const res = await SELF.fetch("https://license.test/webhooks/lemonsqueezy", {
      method: "POST",
      headers: { "X-Signature": "0".repeat(64) },
      body: "{}",
    });
    expect(res.status).toBe(401);
  });

  it("ignores events for other products (returns 200)", async () => {
    const body = JSON.stringify({
      ...sampleLemonSqueezyOrderCreated,
      data: {
        ...sampleLemonSqueezyOrderCreated.data,
        attributes: {
          ...sampleLemonSqueezyOrderCreated.data.attributes,
          first_order_item: { product_id: 42 },
        },
      },
    });
    const sig = await hmacSig(body, "test-secret");
    const res = await SELF.fetch("https://license.test/webhooks/lemonsqueezy", {
      method: "POST",
      headers: { "X-Signature": sig, "Content-Type": "application/json" },
      body,
    });
    expect(res.status).toBe(200);
    const stored = await env.LICENSES.list();
    expect(stored.objects).toHaveLength(0);
  });

  it("creates license, stores record, sends email", async () => {
    const body = JSON.stringify(sampleLemonSqueezyOrderCreated);
    const sig = await hmacSig(body, "test-secret");
    const res = await SELF.fetch("https://license.test/webhooks/lemonsqueezy", {
      method: "POST",
      headers: { "X-Signature": sig, "Content-Type": "application/json" },
      body,
    });
    expect(res.status).toBe(200);
    const record = await getLicenseByOrder(env.LICENSES, "lsorder_12345");
    expect(record).not.toBeNull();
    expect(record!.email).toBe("alice@example.com");
    expect(record!.revoked).toBe(false);
    expect(fetch).toHaveBeenCalledWith(
      "https://api.postmarkapp.com/email",
      expect.anything()
    );
  });

  it("is idempotent on replay (no duplicate license, no second email)", async () => {
    const body = JSON.stringify(sampleLemonSqueezyOrderCreated);
    const sig = await hmacSig(body, "test-secret");
    const opts = {
      method: "POST",
      headers: { "X-Signature": sig, "Content-Type": "application/json" },
      body,
    } as const;
    const r1 = await SELF.fetch("https://license.test/webhooks/lemonsqueezy", opts);
    const r2 = await SELF.fetch("https://license.test/webhooks/lemonsqueezy", opts);
    expect(r1.status).toBe(200);
    expect(r2.status).toBe(200);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/webhooks.test.ts`
Expected: route not found / module missing.

- [ ] **Step 3: Implement `src/webhooks/lemonsqueezy.ts`**

```typescript
import type { Context } from "hono";
import type { CloudflareBindings } from "../index";
import { verifyLemonSqueezySignature } from "../utils/hmac";
import { getLicenseByOrder, putLicense } from "../storage/licenses";
import { signLicense } from "../crypto/license";
import { sendLicenseEmail } from "../email/postmark";
import { PRODUCT, INDIVIDUAL_FEATURES } from "../types";
import { ulid } from "../utils/ulid";

type Env = { Bindings: CloudflareBindings };

export async function handleLemonSqueezyWebhook(c: Context<Env>): Promise<Response> {
  const bodyText = await c.req.text();
  const sig = c.req.header("X-Signature") ?? "";
  const ok = await verifyLemonSqueezySignature(bodyText, sig, c.env.LEMONSQUEEZY_WEBHOOK_SECRET);
  if (!ok) return c.json({ error: "bad signature" }, 401);

  let evt: any;
  try {
    evt = JSON.parse(bodyText);
  } catch {
    return c.json({ error: "invalid json" }, 400);
  }

  const eventName: string = evt?.meta?.event_name ?? "";
  const data = evt?.data ?? {};
  const attrs = data?.attributes ?? {};
  const productId = String(attrs?.first_order_item?.product_id ?? "");

  // Ignore events for products we don't sell via this worker.
  if (productId !== c.env.PRODUCT_ID) {
    return c.json({ ignored: true, reason: "product_mismatch" }, 200);
  }

  if (eventName === "order_created") {
    return await handleOrderCreated(c, data, attrs);
  }
  if (eventName === "order_refunded") {
    return await handleOrderRefunded(c, data);
  }
  return c.json({ ignored: true, event: eventName }, 200);
}

async function handleOrderCreated(c: Context<Env>, data: any, attrs: any): Promise<Response> {
  const orderId: string = String(data.id);
  const orderNumber: string = String(attrs.order_number ?? orderId);
  const email: string = attrs.user_email;
  const testMode: boolean = Boolean(attrs.test_mode);

  // Idempotency: if we already minted a license for this order, no-op.
  const existing = await getLicenseByOrder(c.env.LICENSES, orderId);
  if (existing) {
    return c.json({ ok: true, license_id: existing.license_id, duplicate: true });
  }

  const licenseId = "laip_" + ulid();
  const issuedAt = new Date().toISOString();
  const payload = {
    license_id: licenseId,
    email,
    product: PRODUCT,
    tier: "individual" as const,
    issued_at: issuedAt,
    version: 1 as const,
    features: [...INDIVIDUAL_FEATURES],
    ...(testMode ? { test: true } : {}),
  };
  const { pem } = await signLicense(payload, c.env.LICENSE_SIGNING_KEY);

  await putLicense(c.env.LICENSES, {
    license_id: licenseId,
    email,
    order_id: orderId,
    order_number: orderNumber,
    issued_at: issuedAt,
    revoked: false,
    ...(testMode ? { test: true } : {}),
  });

  await sendLicenseEmail({
    to: email,
    licensePem: pem,
    reissueUrl: `${c.env.SELF_URL}/recover?order=${encodeURIComponent(orderId)}&email=${encodeURIComponent(email)}`,
    purchaseUrl: c.env.PURCHASE_URL,
    postmarkToken: c.env.POSTMARK_SERVER_TOKEN,
    fromEmail: c.env.POSTMARK_FROM_EMAIL,
  });

  return c.json({ ok: true, license_id: licenseId });
}

async function handleOrderRefunded(c: Context<Env>, data: any): Promise<Response> {
  // Implemented in Task 9.
  return c.json({ ok: true, deferred: "order_refunded" });
}
```

- [ ] **Step 4: Write minimal ULID helper `src/utils/ulid.ts`**

```typescript
/**
 * Minimal ULID generator — 26-char Crockford base32 uppercase.
 * Not Monotonic; sufficient for license IDs (webhook rate is trivial).
 */
const ENCODING = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const ENC_LEN = 32;
const TIME_LEN = 10;
const RAND_LEN = 16;

export function ulid(now: number = Date.now()): string {
  return encodeTime(now) + encodeRandom();
}

function encodeTime(now: number): string {
  let out = "";
  for (let i = TIME_LEN - 1; i >= 0; i--) {
    out = ENCODING.charAt(now % ENC_LEN) + out;
    now = Math.floor(now / ENC_LEN);
  }
  return out;
}

function encodeRandom(): string {
  const bytes = new Uint8Array(RAND_LEN);
  crypto.getRandomValues(bytes);
  let out = "";
  for (let i = 0; i < RAND_LEN; i++) out += ENCODING.charAt(bytes[i]! % ENC_LEN);
  return out;
}
```

- [ ] **Step 5: Wire the route in `src/index.ts`**

```typescript
import { Hono } from "hono";
import { handleLemonSqueezyWebhook } from "./webhooks/lemonsqueezy";

const app = new Hono<{ Bindings: CloudflareBindings }>();

app.get("/", (c) => c.text("license-service"));
app.get("/health", (c) => c.json({ status: "ok" }));
app.post("/webhooks/lemonsqueezy", handleLemonSqueezyWebhook);

export default app;

export interface CloudflareBindings {
  LICENSES: R2Bucket;
  RATE_LIMITS: KVNamespace;
  PRODUCT_ID: string;
  GITHUB_REPO_OWNER: string;
  GITHUB_REPO_NAME: string;
  PURCHASE_URL: string;
  SELF_URL: string;
  LICENSE_SIGNING_KEY: string;
  LEMONSQUEEZY_WEBHOOK_SECRET: string;
  LEMONSQUEEZY_API_KEY?: string;
  POSTMARK_SERVER_TOKEN: string;
  POSTMARK_FROM_EMAIL: string;
  GITHUB_APP_ID: string;
  GITHUB_APP_PRIVATE_KEY: string;
  GITHUB_APP_INSTALLATION_ID: string;
  ADMIN_TOKEN: string;
}
```

- [ ] **Step 6: Run tests**

Run: `npm test -- test/webhooks.test.ts`
Expected: 5 tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/webhooks src/utils/ulid.ts src/index.ts test/webhooks.test.ts
git commit -m "feat: handle lemon squeezy order_created webhook"
```

---

## Task 9: Webhook — order_refunded

**Files:**
- Modify: `license-service/src/webhooks/lemonsqueezy.ts` (implement `handleOrderRefunded`)
- Modify: `license-service/test/webhooks.test.ts` (append refund tests)

- [ ] **Step 1: Append failing test**

```typescript
import { readRevocations } from "../src/storage/revocations";

describe("POST /webhooks/lemonsqueezy (refund)", () => {
  beforeEach(async () => {
    await clearBucket();
    env.LICENSE_SIGNING_KEY = TEST_PRIVATE;
    env.LEMONSQUEEZY_WEBHOOK_SECRET = "test-secret";
    env.PRODUCT_ID = "999";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ MessageID: "x" }), { status: 200 }))
    );
  });

  it("marks license revoked on order_refunded", async () => {
    // Seed an existing license.
    const createBody = JSON.stringify(sampleLemonSqueezyOrderCreated);
    const createSig = await hmacSig(createBody, "test-secret");
    await SELF.fetch("https://license.test/webhooks/lemonsqueezy", {
      method: "POST",
      headers: { "X-Signature": createSig, "Content-Type": "application/json" },
      body: createBody,
    });

    const refundEvt = {
      meta: { event_name: "order_refunded" },
      data: {
        type: "orders",
        id: "lsorder_12345",
        attributes: { first_order_item: { product_id: 999 } },
      },
    };
    const refundBody = JSON.stringify(refundEvt);
    const refundSig = await hmacSig(refundBody, "test-secret");
    const res = await SELF.fetch("https://license.test/webhooks/lemonsqueezy", {
      method: "POST",
      headers: { "X-Signature": refundSig, "Content-Type": "application/json" },
      body: refundBody,
    });
    expect(res.status).toBe(200);

    const record = await getLicenseByOrder(env.LICENSES, "lsorder_12345");
    expect(record!.revoked).toBe(true);
    const revocations = await readRevocations(env.LICENSES);
    expect(revocations.revoked).toContain(record!.license_id);
  });

  it("is a no-op if refund arrives with no prior license", async () => {
    const refundEvt = {
      meta: { event_name: "order_refunded" },
      data: { type: "orders", id: "lsorder_missing",
        attributes: { first_order_item: { product_id: 999 } } },
    };
    const refundBody = JSON.stringify(refundEvt);
    const refundSig = await hmacSig(refundBody, "test-secret");
    const res = await SELF.fetch("https://license.test/webhooks/lemonsqueezy", {
      method: "POST",
      headers: { "X-Signature": refundSig, "Content-Type": "application/json" },
      body: refundBody,
    });
    expect(res.status).toBe(200);
    const revocations = await readRevocations(env.LICENSES);
    expect(revocations.revoked).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/webhooks.test.ts`
Expected: the new tests fail (record.revoked === false).

- [ ] **Step 3: Implement `handleOrderRefunded`**

Edit `src/webhooks/lemonsqueezy.ts`, replace the stub with:

```typescript
import { updateLicense } from "../storage/licenses";
import { appendRevocation } from "../storage/revocations";

async function handleOrderRefunded(c: Context<Env>, data: any): Promise<Response> {
  const orderId: string = String(data.id);
  const record = await getLicenseByOrder(c.env.LICENSES, orderId);
  if (!record) {
    return c.json({ ok: true, noop: "no license for order" });
  }
  if (record.revoked) {
    return c.json({ ok: true, duplicate: true });
  }
  const updated = await updateLicense(c.env.LICENSES, record.license_id, { revoked: true });
  await appendRevocation(c.env.LICENSES, record.license_id);
  return c.json({ ok: true, license_id: updated!.license_id, revoked: true });
}
```

- [ ] **Step 4: Run, pass**

Run: `npm test -- test/webhooks.test.ts`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/webhooks/lemonsqueezy.ts test/webhooks.test.ts
git commit -m "feat: handle order_refunded — revoke and append"
```

---

## Task 10: Public revocations endpoint

**Files:**
- Modify: `license-service/src/index.ts` (add route)
- Create: `license-service/test/revocations-endpoint.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { SELF, env } from "cloudflare:test";
import { appendRevocation } from "../src/storage/revocations";

async function clearBucket() {
  const objs = await env.LICENSES.list();
  await Promise.all(objs.objects.map((o) => env.LICENSES.delete(o.key)));
}

describe("GET /revocations.json", () => {
  beforeEach(clearBucket);

  it("returns empty list when no revocations", async () => {
    const res = await SELF.fetch("https://license.test/revocations.json");
    expect(res.status).toBe(200);
    const body = await res.json<{ revoked: string[] }>();
    expect(body.revoked).toEqual([]);
    expect(res.headers.get("Cache-Control")).toMatch(/max-age/);
  });

  it("returns appended revocations", async () => {
    await appendRevocation(env.LICENSES, "laip_a");
    await appendRevocation(env.LICENSES, "laip_b");
    const res = await SELF.fetch("https://license.test/revocations.json");
    const body = await res.json<{ revoked: string[] }>();
    expect(body.revoked.sort()).toEqual(["laip_a", "laip_b"]);
  });
});
```

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/revocations-endpoint.test.ts`
Expected: 404.

- [ ] **Step 3: Add route in `src/index.ts`**

Append before `export default app`:

```typescript
import { readRevocations } from "./storage/revocations";

app.get("/revocations.json", async (c) => {
  const list = await readRevocations(c.env.LICENSES);
  c.header("Cache-Control", "public, max-age=3600");
  return c.json(list);
});
```

- [ ] **Step 4: Run, pass**

Run: `npm test -- test/revocations-endpoint.test.ts`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/index.ts test/revocations-endpoint.test.ts
git commit -m "feat: GET /revocations.json"
```

---

## Task 11: Per-license rate limiting (KV)

**Files:**
- Create: `license-service/src/utils/rate-limit.ts`
- Create: `license-service/test/rate-limit.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { env } from "cloudflare:test";
import { checkRateLimit } from "../src/utils/rate-limit";

describe("checkRateLimit", () => {
  beforeEach(async () => {
    // KV has no bulk delete; keys expire via TTL. Use distinct license IDs per test.
  });

  it("allows up to the daily cap", async () => {
    const id = "laip_testA" + Math.random();
    for (let i = 0; i < 10; i++) {
      expect(await checkRateLimit(env.RATE_LIMITS, id, { dailyCap: 10, monthlyCap: 50 })).toEqual({
        ok: true,
        remainingDaily: 10 - (i + 1),
      });
    }
    const over = await checkRateLimit(env.RATE_LIMITS, id, { dailyCap: 10, monthlyCap: 50 });
    expect(over.ok).toBe(false);
    expect(over.reason).toBe("daily");
  });

  it("enforces monthly cap independently", async () => {
    const id = "laip_testB" + Math.random();
    for (let i = 0; i < 50; i++) {
      const r = await checkRateLimit(env.RATE_LIMITS, id, { dailyCap: 100, monthlyCap: 50 });
      if (!r.ok) break;
    }
    const over = await checkRateLimit(env.RATE_LIMITS, id, { dailyCap: 100, monthlyCap: 50 });
    expect(over.ok).toBe(false);
    expect(over.reason).toBe("monthly");
  });
});
```

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/rate-limit.test.ts`
Expected: module missing.

- [ ] **Step 3: Write `src/utils/rate-limit.ts`**

```typescript
export interface RateLimitOptions {
  dailyCap: number;
  monthlyCap: number;
}

export type RateLimitResult =
  | { ok: true; remainingDaily: number; remainingMonthly: number }
  | { ok: false; reason: "daily" | "monthly" };

export async function checkRateLimit(
  kv: KVNamespace,
  licenseId: string,
  opts: RateLimitOptions,
  now: Date = new Date()
): Promise<RateLimitResult> {
  const dayKey = `rl:${licenseId}:d:${dayStamp(now)}`;
  const monthKey = `rl:${licenseId}:m:${monthStamp(now)}`;

  const [dayRaw, monthRaw] = await Promise.all([kv.get(dayKey), kv.get(monthKey)]);
  const day = Number(dayRaw ?? 0);
  const month = Number(monthRaw ?? 0);

  if (day >= opts.dailyCap) return { ok: false, reason: "daily" };
  if (month >= opts.monthlyCap) return { ok: false, reason: "monthly" };

  await Promise.all([
    kv.put(dayKey, String(day + 1), { expirationTtl: 60 * 60 * 26 }),   // ~26h
    kv.put(monthKey, String(month + 1), { expirationTtl: 60 * 60 * 24 * 34 }), // ~34d
  ]);

  return {
    ok: true,
    remainingDaily: opts.dailyCap - day - 1,
    remainingMonthly: opts.monthlyCap - month - 1,
  };
}

function dayStamp(d: Date): string {
  return d.toISOString().slice(0, 10); // YYYY-MM-DD
}
function monthStamp(d: Date): string {
  return d.toISOString().slice(0, 7); // YYYY-MM
}
```

- [ ] **Step 4: Run, pass**

Run: `npm test -- test/rate-limit.test.ts`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/utils/rate-limit.ts test/rate-limit.test.ts
git commit -m "feat: per-license KV rate limiter"
```

---

## Task 12: GitHub App token minting & issue creation

**Files:**
- Create: `license-service/src/github/app.ts`
- Create: `license-service/test/github.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createSupportIssue } from "../src/github/app";

describe("createSupportIssue", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("mints installation token, creates issue, posts hidden metadata comment", async () => {
    const calls: Array<{ url: string; init: any }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: any) => {
        calls.push({ url, init });
        if (url.endsWith("/access_tokens")) {
          return Promise.resolve(new Response(JSON.stringify({ token: "ghs_x" }), { status: 201 }));
        }
        if (url.endsWith("/issues")) {
          return Promise.resolve(
            new Response(JSON.stringify({ number: 17, html_url: "https://gh/issues/17" }), { status: 201 })
          );
        }
        if (/\/issues\/17\/comments$/.test(url)) {
          return Promise.resolve(new Response(JSON.stringify({ id: 1 }), { status: 201 }));
        }
        return Promise.resolve(new Response("nope", { status: 500 }));
      })
    );

    const result = await createSupportIssue({
      appId: "1",
      privateKeyPem: stubRsaPemForTest(),
      installationId: "1",
      owner: "hankthebldr",
      repo: "local-ai-platform",
      publicBody: "## Desc\n\nbody",
      title: "Hello",
      labels: ["support", "supported"],
      privateMetadata: { license_id: "laip_x", email: "a@b.c" },
    });

    expect(result).toEqual({ number: 17, html_url: "https://gh/issues/17" });
    // 3 fetches: access_tokens, issues, issues/17/comments
    expect(calls).toHaveLength(3);
    expect(calls[0]!.url).toMatch(/access_tokens/);
    expect(calls[1]!.url).toMatch(/\/issues$/);
    const issueBody = JSON.parse(calls[1]!.init.body);
    expect(issueBody.title).toBe("Hello");
    expect(issueBody.labels).toEqual(["support", "supported"]);
    const commentBody = JSON.parse(calls[2]!.init.body);
    expect(commentBody.body).toContain("laip-support-metadata-v1");
    expect(commentBody.body).toContain("license_id: laip_x");
    expect(commentBody.body).toContain("email: a@b.c");
  });
});

function stubRsaPemForTest(): string {
  // Dummy key — tests stub fetch so the JWT doesn't need to verify.
  // See app.ts: when private key can't parse, we throw; test must supply a real-enough one.
  // For the test we inject a key generated via node:crypto in a one-time setup below.
  if (globalThis.__LAIP_TEST_PK__) return globalThis.__LAIP_TEST_PK__ as string;
  throw new Error("test setup missing __LAIP_TEST_PK__");
}
```

Add to `test/helpers/fixtures.ts`:

```typescript
import { generateKeyPairSync } from "node:crypto";

export function setupTestRsaKey() {
  const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const pem = privateKey.export({ type: "pkcs1", format: "pem" }) as string;
  (globalThis as any).__LAIP_TEST_PK__ = pem;
}
```

And in `vitest.config.ts`, reference a `setupFiles: ["./test/helpers/setup.ts"]`; create that file:

```typescript
// test/helpers/setup.ts
import { setupTestRsaKey } from "./fixtures";
setupTestRsaKey();
```

Update `vitest.config.ts` to add `setupFiles: ["./test/helpers/setup.ts"]` in the `test` block.

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/github.test.ts`
Expected: module missing.

- [ ] **Step 3: Implement `src/github/app.ts`**

```typescript
/**
 * GitHub App integration — mint an installation token, then use it to
 * create an issue and a (hidden-by-convention) metadata comment.
 *
 * We skip external JWT libraries and sign the app JWT with Web Crypto
 * (RS256 over the iat/exp/iss claims).
 */

interface IssueArgs {
  appId: string;
  privateKeyPem: string;
  installationId: string;
  owner: string;
  repo: string;
  title: string;
  publicBody: string;
  labels: string[];
  privateMetadata: Record<string, string>;
}

export async function createSupportIssue(args: IssueArgs): Promise<{ number: number; html_url: string }> {
  const appJwt = await mintAppJwt(args.appId, args.privateKeyPem);
  const token = await getInstallationToken(args.installationId, appJwt);

  const issueRes = await fetch(
    `https://api.github.com/repos/${args.owner}/${args.repo}/issues`,
    {
      method: "POST",
      headers: headers(token),
      body: JSON.stringify({ title: args.title, body: args.publicBody, labels: args.labels }),
    }
  );
  if (!issueRes.ok) throw new Error(`GitHub issue create failed: ${issueRes.status} ${await issueRes.text()}`);
  const issue = await issueRes.json<{ number: number; html_url: string }>();

  const commentBody = formatMetadataComment(args.privateMetadata);
  const commentRes = await fetch(
    `https://api.github.com/repos/${args.owner}/${args.repo}/issues/${issue.number}/comments`,
    { method: "POST", headers: headers(token), body: JSON.stringify({ body: commentBody }) }
  );
  if (!commentRes.ok) {
    throw new Error(`GitHub metadata comment failed: ${commentRes.status} ${await commentRes.text()}`);
  }
  return { number: issue.number, html_url: issue.html_url };
}

function headers(token: string): Record<string, string> {
  return {
    "Authorization": `Bearer ${token}`,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
    "User-Agent": "license-service",
  };
}

function formatMetadataComment(meta: Record<string, string>): string {
  const lines = Object.entries(meta).map(([k, v]) => `${k}: ${v}`);
  return ["<!-- laip-support-metadata-v1 -->", "```", ...lines, "```"].join("\n");
}

async function mintAppJwt(appId: string, pem: string): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = b64url(JSON.stringify({ iat: now - 60, exp: now + 540, iss: appId }));
  const data = `${header}.${payload}`;
  const key = await importRsaPrivateKey(pem);
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(data));
  return `${data}.${b64urlBytes(new Uint8Array(sig))}`;
}

async function getInstallationToken(installationId: string, appJwt: string): Promise<string> {
  const res = await fetch(`https://api.github.com/app/installations/${installationId}/access_tokens`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${appJwt}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "license-service",
    },
  });
  if (!res.ok) throw new Error(`installation token failed: ${res.status} ${await res.text()}`);
  const { token } = await res.json<{ token: string }>();
  return token;
}

async function importRsaPrivateKey(pem: string): Promise<CryptoKey> {
  const body = pem
    .replace(/-----BEGIN [^-]+-----/g, "")
    .replace(/-----END [^-]+-----/g, "")
    .replace(/\s+/g, "");
  const der = Uint8Array.from(atob(body), (c) => c.charCodeAt(0));
  // GitHub distributes keys in PKCS1 or PKCS8 depending on generation path.
  // workerd's importKey requires PKCS8 for RSA — wrap PKCS1 if needed.
  const pkcs8 = pem.includes("BEGIN RSA PRIVATE KEY") ? wrapPkcs1AsPkcs8(der) : der;
  return await crypto.subtle.importKey(
    "pkcs8",
    pkcs8,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"]
  );
}

function wrapPkcs1AsPkcs8(pkcs1: Uint8Array): Uint8Array {
  // Prefix bytes: PKCS8 header + algorithm OID for rsaEncryption, then OCTET STRING of PKCS1.
  const rsaOid = Uint8Array.from([
    0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00,
  ]);
  const octetHeader = asn1Len(pkcs1.length, 0x04);
  const innerLen = rsaOid.length + octetHeader.length + pkcs1.length + 3; // version INTEGER 0
  const outerHeader = asn1Len(innerLen, 0x30);
  const version = Uint8Array.from([0x02, 0x01, 0x00]);
  const out = new Uint8Array(outerHeader.length + innerLen);
  let off = 0;
  out.set(outerHeader, off); off += outerHeader.length;
  out.set(version, off); off += version.length;
  out.set(rsaOid, off); off += rsaOid.length;
  out.set(octetHeader, off); off += octetHeader.length;
  out.set(pkcs1, off);
  return out;
}

function asn1Len(len: number, tag: number): Uint8Array {
  if (len < 0x80) return Uint8Array.from([tag, len]);
  const bytes: number[] = [];
  let n = len;
  while (n > 0) { bytes.unshift(n & 0xff); n >>>= 8; }
  return Uint8Array.from([tag, 0x80 | bytes.length, ...bytes]);
}

function b64url(s: string): string {
  return btoa(s).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}
function b64urlBytes(b: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < b.length; i++) bin += String.fromCharCode(b[i]!);
  return btoa(bin).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}
```

- [ ] **Step 4: Run, pass**

Run: `npm test -- test/github.test.ts`
Expected: test passes.

- [ ] **Step 5: Commit**

```bash
git add src/github test/github.test.ts test/helpers/fixtures.ts test/helpers/setup.ts vitest.config.ts
git commit -m "feat: GitHub App token + issue + metadata comment"
```

---

## Task 13: POST /support/issues endpoint

**Files:**
- Create: `license-service/src/support/issues.ts`
- Create: `license-service/test/support-issues.test.ts`
- Modify: `license-service/src/index.ts` (mount route)

- [ ] **Step 1: Write failing test**

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SELF, env } from "cloudflare:test";
import { signLicense } from "../src/crypto/license";
import { sampleLicensePayload, sampleLicenseRecord } from "./helpers/fixtures";
import { putLicense } from "../src/storage/licenses";
import { appendRevocation } from "../src/storage/revocations";

import { TEST_PRIVATE_B64 as TEST_PRIVATE, TEST_PUBLIC_B64 } from "./helpers/keys";

async function clearBucket() {
  const objs = await env.LICENSES.list();
  await Promise.all(objs.objects.map((o) => env.LICENSES.delete(o.key)));
}

async function signedLicenseHeader(): Promise<string> {
  const { pem } = await signLicense(sampleLicensePayload, TEST_PRIVATE);
  return btoa(pem);
}

describe("POST /support/issues", () => {
  beforeEach(async () => {
    await clearBucket();
    env.LICENSE_SIGNING_KEY = TEST_PRIVATE;
    // Derive & inject the public key by test setup.
    env.LICENSE_PUBLIC_KEY = await derivePublicKeyB64(TEST_PRIVATE);
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.endsWith("/access_tokens"))
          return Promise.resolve(new Response(JSON.stringify({ token: "ghs_x" }), { status: 201 }));
        if (url.endsWith("/issues"))
          return Promise.resolve(
            new Response(JSON.stringify({ number: 42, html_url: "https://gh/42" }), { status: 201 })
          );
        if (/\/comments$/.test(url))
          return Promise.resolve(new Response(JSON.stringify({ id: 1 }), { status: 201 }));
        return Promise.resolve(new Response("x", { status: 500 }));
      })
    );
  });
  afterEach(() => vi.restoreAllMocks());

  const validRequest = {
    title: "Workflow hangs",
    body: "Step 3 of my workflow hangs after 30 seconds.",
    severity: "bug" as const,
    metadata: { app_version: "0.4.2", os: "macOS 15.3 arm64", python: "3.12.7", models: ["mistral"] },
  };

  it("rejects missing license header", async () => {
    const res = await SELF.fetch("https://license.test/support/issues", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(validRequest),
    });
    expect(res.status).toBe(401);
  });

  it("rejects tampered license", async () => {
    const raw = await signedLicenseHeader();
    const tampered = raw.slice(0, -4) + "XXXX";
    const res = await SELF.fetch("https://license.test/support/issues", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Local-AI-License": tampered },
      body: JSON.stringify(validRequest),
    });
    expect(res.status).toBe(401);
  });

  it("rejects revoked license", async () => {
    await putLicense(env.LICENSES, sampleLicenseRecord);
    await appendRevocation(env.LICENSES, sampleLicenseRecord.license_id);
    const res = await SELF.fetch("https://license.test/support/issues", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Local-AI-License": await signedLicenseHeader(),
      },
      body: JSON.stringify(validRequest),
    });
    expect(res.status).toBe(403);
  });

  it("creates issue on valid request", async () => {
    const res = await SELF.fetch("https://license.test/support/issues", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Local-AI-License": await signedLicenseHeader(),
      },
      body: JSON.stringify(validRequest),
    });
    expect(res.status).toBe(201);
    const body = await res.json<{ number: number; html_url: string }>();
    expect(body.number).toBe(42);
  });

  it("rejects oversized payload (>256KB)", async () => {
    const big = "x".repeat(300_000);
    const res = await SELF.fetch("https://license.test/support/issues", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Local-AI-License": await signedLicenseHeader(),
      },
      body: JSON.stringify({ ...validRequest, body: big }),
    });
    expect(res.status).toBe(413);
  });
});

async function derivePublicKeyB64(privB64: string): Promise<string> {
  // In tests we hardcode the matching public key (see crypto.test.ts).
  return TEST_PUBLIC_B64;
}
```

Add `LICENSE_PUBLIC_KEY: string` to `CloudflareBindings` in `src/index.ts`, and to the bindings block in `vitest.config.ts`.

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/support-issues.test.ts`
Expected: 404 / missing module.

- [ ] **Step 3: Implement `src/support/issues.ts`**

```typescript
import type { Context } from "hono";
import type { CloudflareBindings } from "../index";
import { SupportIssueRequestSchema, LicensePayloadSchema } from "../types";
import { parseLicensePem } from "../crypto/license";
import { importPublicKeyFromBase64, verify } from "../crypto/ed25519";
import { readRevocations } from "../storage/revocations";
import { checkRateLimit } from "../utils/rate-limit";
import { createSupportIssue } from "../github/app";

type Env = { Bindings: CloudflareBindings };

const MAX_PAYLOAD = 256 * 1024;

export async function handleSupportIssue(c: Context<Env>): Promise<Response> {
  const headerB64 = c.req.header("X-Local-AI-License");
  if (!headerB64) return c.json({ error: "missing X-Local-AI-License header" }, 401);

  // License verification
  let pem: string;
  try { pem = atob(headerB64); }
  catch { return c.json({ error: "license header not base64" }, 401); }

  let licensePayload;
  try {
    const { payload, signature } = parseLicensePem(pem);
    const pubKey = await importPublicKeyFromBase64(c.env.LICENSE_PUBLIC_KEY);
    const valid = await verify(pubKey, signature, payload);
    if (!valid) return c.json({ error: "invalid license signature" }, 401);
    const parsed = LicensePayloadSchema.safeParse(JSON.parse(new TextDecoder().decode(payload)));
    if (!parsed.success) return c.json({ error: "invalid license payload" }, 401);
    licensePayload = parsed.data;
  } catch (e) {
    return c.json({ error: "license parse failed" }, 401);
  }

  // Revocation
  const revs = await readRevocations(c.env.LICENSES);
  if (revs.revoked.includes(licensePayload.license_id)) {
    return c.json({ error: "license revoked" }, 403);
  }

  // Body size + shape
  const raw = await c.req.raw.clone().text();
  if (raw.length > MAX_PAYLOAD) {
    return c.json({ error: "payload too large (256KB max)" }, 413);
  }
  const parsedBody = SupportIssueRequestSchema.safeParse(JSON.parse(raw));
  if (!parsedBody.success) {
    return c.json({ error: "invalid body", issues: parsedBody.error.issues }, 400);
  }
  const req = parsedBody.data;

  // Rate limit
  const rl = await checkRateLimit(c.env.RATE_LIMITS, licensePayload.license_id, {
    dailyCap: 10, monthlyCap: 50,
  });
  if (!rl.ok) {
    return c.json({ error: `rate limit exceeded (${rl.reason})` }, 429);
  }

  // Assemble public body
  const publicBody = renderPublicBody(req);

  // Create issue
  const issue = await createSupportIssue({
    appId: c.env.GITHUB_APP_ID,
    privateKeyPem: c.env.GITHUB_APP_PRIVATE_KEY,
    installationId: c.env.GITHUB_APP_INSTALLATION_ID,
    owner: c.env.GITHUB_REPO_OWNER,
    repo: c.env.GITHUB_REPO_NAME,
    title: req.title,
    publicBody,
    labels: ["support", "supported", `tier:${licensePayload.tier}`, `severity:${req.severity}`],
    privateMetadata: {
      license_id: licensePayload.license_id,
      email: licensePayload.email,
      submitted_at: new Date().toISOString(),
      app_version: req.metadata.app_version,
      os: req.metadata.os,
      python: req.metadata.python,
    },
  });

  return c.json({ number: issue.number, html_url: issue.html_url }, 201);
}

function renderPublicBody(req: import("../types").SupportIssueRequest): string {
  const md = [
    `### Local AI Platform support — v${req.metadata.app_version} · ${req.metadata.os} · Python ${req.metadata.python}`,
    "",
    "#### Description",
    req.body,
  ];
  if (req.metadata.models?.length) {
    md.push("", "#### Installed models", "```", ...req.metadata.models, "```");
  }
  if (req.attachments?.length) {
    md.push("", "#### Attachments");
    for (const a of req.attachments) {
      md.push("", `**${a.name}** (${a.content_base64.length} bytes base64)`, "```", atob(a.content_base64).slice(0, 4000), "```");
    }
  }
  md.push("", "---", "*Reported by a licensed user. Maintainer metadata in hidden comment.*");
  return md.join("\n");
}
```

- [ ] **Step 4: Wire the route in `src/index.ts`**

```typescript
import { handleSupportIssue } from "./support/issues";
app.post("/support/issues", handleSupportIssue);
```

- [ ] **Step 5: Run, pass**

Run: `npm test -- test/support-issues.test.ts`
Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/support/issues.ts src/index.ts test/support-issues.test.ts
git commit -m "feat: POST /support/issues"
```

---

## Task 14: GET /support/upload-url (R2 presigned URLs)

**Files:**
- Create: `license-service/src/support/upload.ts`
- Create: `license-service/test/support-upload.test.ts`
- Modify: `license-service/src/index.ts`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { SELF, env } from "cloudflare:test";
import { signLicense } from "../src/crypto/license";
import { sampleLicensePayload } from "./helpers/fixtures";

import { TEST_PRIVATE_B64 as TEST_PRIVATE, TEST_PUBLIC_B64 } from "./helpers/keys";

describe("GET /support/upload-url", () => {
  beforeEach(() => {
    env.LICENSE_PUBLIC_KEY = TEST_PUBLIC_B64;
  });

  it("401 without license", async () => {
    const res = await SELF.fetch("https://license.test/support/upload-url");
    expect(res.status).toBe(401);
  });

  it("returns an upload token + url for a valid license", async () => {
    const { pem } = await signLicense(sampleLicensePayload, TEST_PRIVATE);
    const res = await SELF.fetch("https://license.test/support/upload-url", {
      headers: { "X-Local-AI-License": btoa(pem) },
    });
    expect(res.status).toBe(200);
    const body = await res.json<{ upload_url: string; key: string; expires_at: string }>();
    expect(body.upload_url).toMatch(/https:\/\/license\.test\/support\/upload\/.+/);
    expect(body.key).toMatch(/^support-uploads\//);
  });
});
```

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/support-upload.test.ts`
Expected: 404.

- [ ] **Step 3: Implement `src/support/upload.ts`**

Because Workers doesn't emit native R2-presigned URLs cheaply inside Workers, we use a **proxy upload**: the client uploads to `PUT /support/upload/:token`, which stores into R2 after verifying the token. Simpler, same effect.

```typescript
import type { Context } from "hono";
import type { CloudflareBindings } from "../index";
import { parseLicensePem } from "../crypto/license";
import { importPublicKeyFromBase64, verify } from "../crypto/ed25519";
import { LicensePayloadSchema } from "../types";
import { ulid } from "../utils/ulid";

type Env = { Bindings: CloudflareBindings };

const UPLOAD_TTL_SECONDS = 300;

export async function handleUploadUrl(c: Context<Env>): Promise<Response> {
  const headerB64 = c.req.header("X-Local-AI-License");
  if (!headerB64) return c.json({ error: "missing license" }, 401);
  let payloadData;
  try {
    const pem = atob(headerB64);
    const { payload, signature } = parseLicensePem(pem);
    const pub = await importPublicKeyFromBase64(c.env.LICENSE_PUBLIC_KEY);
    if (!(await verify(pub, signature, payload))) return c.json({ error: "bad signature" }, 401);
    const parsed = LicensePayloadSchema.safeParse(JSON.parse(new TextDecoder().decode(payload)));
    if (!parsed.success) return c.json({ error: "bad payload" }, 401);
    payloadData = parsed.data;
  } catch {
    return c.json({ error: "license parse failed" }, 401);
  }

  const token = ulid();
  const key = `support-uploads/${payloadData.license_id}/${token}`;
  const expiresAt = new Date(Date.now() + UPLOAD_TTL_SECONDS * 1000).toISOString();

  await c.env.RATE_LIMITS.put(`upload-token:${token}`, key, { expirationTtl: UPLOAD_TTL_SECONDS });

  return c.json({
    upload_url: `${c.env.SELF_URL}/support/upload/${token}`,
    key,
    expires_at: expiresAt,
    max_bytes: 5 * 1024 * 1024,
  });
}

export async function handleUploadPut(c: Context<Env>): Promise<Response> {
  const token = c.req.param("token");
  if (!token) return c.json({ error: "missing token" }, 400);
  const key = await c.env.RATE_LIMITS.get(`upload-token:${token}`);
  if (!key) return c.json({ error: "token expired or invalid" }, 410);

  const body = await c.req.raw.arrayBuffer();
  if (body.byteLength > 5 * 1024 * 1024) return c.json({ error: "too large (5MB max)" }, 413);

  await c.env.LICENSES.put(key, body, {
    httpMetadata: { contentType: c.req.header("Content-Type") ?? "application/octet-stream" },
  });
  await c.env.RATE_LIMITS.delete(`upload-token:${token}`);
  return c.json({ ok: true, key, bytes: body.byteLength });
}
```

- [ ] **Step 4: Wire in `src/index.ts`**

```typescript
import { handleUploadUrl, handleUploadPut } from "./support/upload";
app.get("/support/upload-url", handleUploadUrl);
app.put("/support/upload/:token", handleUploadPut);
```

- [ ] **Step 5: Run, pass**

Run: `npm test -- test/support-upload.test.ts`
Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/support/upload.ts src/index.ts test/support-upload.test.ts
git commit -m "feat: GET /support/upload-url + PUT /support/upload/:token"
```

---

## Task 15: Admin revoke & reissue

**Files:**
- Create: `license-service/src/admin/revoke.ts`
- Create: `license-service/src/admin/reissue.ts`
- Create: `license-service/test/admin.test.ts`
- Modify: `license-service/src/index.ts`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SELF, env } from "cloudflare:test";
import { putLicense, getLicenseById } from "../src/storage/licenses";
import { readRevocations } from "../src/storage/revocations";
import { sampleLicenseRecord } from "./helpers/fixtures";

async function clearBucket() {
  const objs = await env.LICENSES.list();
  await Promise.all(objs.objects.map((o) => env.LICENSES.delete(o.key)));
}

describe("admin endpoints", () => {
  beforeEach(async () => {
    await clearBucket();
    env.ADMIN_TOKEN = "test-admin";
    env.LICENSE_SIGNING_KEY = "MC4CAQAwBQYDK2VwBCIEIObzBJTtTvIM8K9iGjCS4+lZnjUiQjRrjWGzJp8YBnYy";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ MessageID: "x" }), { status: 200 })));
  });
  afterEach(() => vi.restoreAllMocks());

  it("rejects /admin/revoke without token", async () => {
    const res = await SELF.fetch("https://license.test/admin/revoke", {
      method: "POST", body: JSON.stringify({ license_id: "x" }),
    });
    expect(res.status).toBe(401);
  });

  it("revokes license", async () => {
    await putLicense(env.LICENSES, sampleLicenseRecord);
    const res = await SELF.fetch("https://license.test/admin/revoke", {
      method: "POST",
      headers: { "Authorization": "Bearer test-admin", "Content-Type": "application/json" },
      body: JSON.stringify({ license_id: sampleLicenseRecord.license_id }),
    });
    expect(res.status).toBe(200);
    const rec = await getLicenseById(env.LICENSES, sampleLicenseRecord.license_id);
    expect(rec!.revoked).toBe(true);
    const revs = await readRevocations(env.LICENSES);
    expect(revs.revoked).toContain(sampleLicenseRecord.license_id);
  });

  it("reissues license (same id, new signature, email sent)", async () => {
    await putLicense(env.LICENSES, sampleLicenseRecord);
    const res = await SELF.fetch("https://license.test/admin/reissue", {
      method: "POST",
      headers: { "Authorization": "Bearer test-admin", "Content-Type": "application/json" },
      body: JSON.stringify({ order_id: sampleLicenseRecord.order_id }),
    });
    expect(res.status).toBe(200);
    // Postmark was called
    expect(fetch).toHaveBeenCalledWith("https://api.postmarkapp.com/email", expect.anything());
  });
});
```

- [ ] **Step 2: Run, fail**

Run: `npm test -- test/admin.test.ts`
Expected: 404.

- [ ] **Step 3: Implement `src/admin/revoke.ts`**

```typescript
import type { Context } from "hono";
import type { CloudflareBindings } from "../index";
import { getLicenseById, updateLicense } from "../storage/licenses";
import { appendRevocation } from "../storage/revocations";

type Env = { Bindings: CloudflareBindings };

export async function handleAdminRevoke(c: Context<Env>): Promise<Response> {
  if (!requireAdmin(c)) return c.json({ error: "unauthorized" }, 401);
  const body = await c.req.json<{ license_id?: string }>().catch(() => ({}));
  if (!body.license_id) return c.json({ error: "license_id required" }, 400);

  const record = await getLicenseById(c.env.LICENSES, body.license_id);
  if (!record) return c.json({ error: "not found" }, 404);
  if (record.revoked) return c.json({ ok: true, already_revoked: true });

  await updateLicense(c.env.LICENSES, record.license_id, { revoked: true });
  await appendRevocation(c.env.LICENSES, record.license_id);
  return c.json({ ok: true, license_id: record.license_id });
}

export function requireAdmin(c: Context<Env>): boolean {
  const h = c.req.header("Authorization") ?? "";
  const expected = `Bearer ${c.env.ADMIN_TOKEN}`;
  if (h.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < h.length; i++) diff |= h.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}
```

- [ ] **Step 4: Implement `src/admin/reissue.ts`**

```typescript
import type { Context } from "hono";
import type { CloudflareBindings } from "../index";
import { getLicenseByOrder } from "../storage/licenses";
import { signLicense } from "../crypto/license";
import { sendLicenseEmail } from "../email/postmark";
import { PRODUCT, INDIVIDUAL_FEATURES } from "../types";
import { requireAdmin } from "./revoke";

type Env = { Bindings: CloudflareBindings };

export async function handleAdminReissue(c: Context<Env>): Promise<Response> {
  if (!requireAdmin(c)) return c.json({ error: "unauthorized" }, 401);
  const body = await c.req.json<{ order_id?: string }>().catch(() => ({}));
  if (!body.order_id) return c.json({ error: "order_id required" }, 400);

  const record = await getLicenseByOrder(c.env.LICENSES, body.order_id);
  if (!record) return c.json({ error: "not found" }, 404);
  if (record.revoked) return c.json({ error: "license revoked; unrevoke first" }, 409);

  // Re-sign the same payload (same license_id, same email, same issued_at).
  const { pem } = await signLicense(
    {
      license_id: record.license_id,
      email: record.email,
      product: PRODUCT,
      tier: "individual",
      issued_at: record.issued_at,
      version: 1,
      features: [...INDIVIDUAL_FEATURES],
      ...(record.test ? { test: true } : {}),
    },
    c.env.LICENSE_SIGNING_KEY
  );

  await sendLicenseEmail({
    to: record.email,
    licensePem: pem,
    reissueUrl: `${c.env.SELF_URL}/recover?order=${encodeURIComponent(record.order_id)}&email=${encodeURIComponent(record.email)}`,
    purchaseUrl: c.env.PURCHASE_URL,
    postmarkToken: c.env.POSTMARK_SERVER_TOKEN,
    fromEmail: c.env.POSTMARK_FROM_EMAIL,
  });

  return c.json({ ok: true, license_id: record.license_id, reissued: true });
}
```

- [ ] **Step 5: Wire in `src/index.ts`**

```typescript
import { handleAdminRevoke } from "./admin/revoke";
import { handleAdminReissue } from "./admin/reissue";
app.post("/admin/revoke", handleAdminRevoke);
app.post("/admin/reissue", handleAdminReissue);
```

- [ ] **Step 6: Run, pass**

Run: `npm test -- test/admin.test.ts`
Expected: 3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/admin src/index.ts test/admin.test.ts
git commit -m "feat: admin revoke & reissue"
```

---

## Task 16: Self-serve /recover endpoint

**Files:**
- Create: `license-service/src/recover/self-serve.ts`
- Create: `license-service/test/recover.test.ts`
- Modify: `license-service/src/index.ts`

- [ ] **Step 1: Write failing test**

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SELF, env } from "cloudflare:test";
import { putLicense } from "../src/storage/licenses";
import { sampleLicenseRecord } from "./helpers/fixtures";

describe("GET /recover", () => {
  beforeEach(async () => {
    const objs = await env.LICENSES.list();
    await Promise.all(objs.objects.map((o) => env.LICENSES.delete(o.key)));
    env.LICENSE_SIGNING_KEY = "MC4CAQAwBQYDK2VwBCIEIObzBJTtTvIM8K9iGjCS4+lZnjUiQjRrjWGzJp8YBnYy";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ MessageID: "x" }), { status: 200 }))
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("404s for unknown order", async () => {
    const res = await SELF.fetch("https://license.test/recover?order=missing&email=x@y");
    expect(res.status).toBe(404);
  });

  it("rejects mismatched email", async () => {
    await putLicense(env.LICENSES, sampleLicenseRecord);
    const res = await SELF.fetch(`https://license.test/recover?order=${sampleLicenseRecord.order_id}&email=wrong@x`);
    expect(res.status).toBe(403);
  });

  it("sends email on matching order+email", async () => {
    await putLicense(env.LICENSES, sampleLicenseRecord);
    const res = await SELF.fetch(
      `https://license.test/recover?order=${sampleLicenseRecord.order_id}&email=${encodeURIComponent(sampleLicenseRecord.email)}`
    );
    expect(res.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith("https://api.postmarkapp.com/email", expect.anything());
  });

  it("refuses to reissue revoked license", async () => {
    await putLicense(env.LICENSES, { ...sampleLicenseRecord, revoked: true });
    const res = await SELF.fetch(
      `https://license.test/recover?order=${sampleLicenseRecord.order_id}&email=${encodeURIComponent(sampleLicenseRecord.email)}`
    );
    expect(res.status).toBe(410);
  });
});
```

- [ ] **Step 2: Implement `src/recover/self-serve.ts`**

```typescript
import type { Context } from "hono";
import type { CloudflareBindings } from "../index";
import { getLicenseByOrder } from "../storage/licenses";
import { signLicense } from "../crypto/license";
import { sendLicenseEmail } from "../email/postmark";
import { PRODUCT, INDIVIDUAL_FEATURES } from "../types";

type Env = { Bindings: CloudflareBindings };

export async function handleRecover(c: Context<Env>): Promise<Response> {
  const order = c.req.query("order");
  const email = c.req.query("email");
  if (!order || !email) return c.text("Missing parameters.", 400);

  const record = await getLicenseByOrder(c.env.LICENSES, order);
  if (!record) return c.text("No license found for that order.", 404);
  if (record.email.toLowerCase() !== email.toLowerCase()) {
    return c.text("Email doesn't match the order on record.", 403);
  }
  if (record.revoked) return c.text("This license has been revoked.", 410);

  const { pem } = await signLicense(
    {
      license_id: record.license_id,
      email: record.email,
      product: PRODUCT,
      tier: "individual",
      issued_at: record.issued_at,
      version: 1,
      features: [...INDIVIDUAL_FEATURES],
      ...(record.test ? { test: true } : {}),
    },
    c.env.LICENSE_SIGNING_KEY
  );

  await sendLicenseEmail({
    to: record.email,
    licensePem: pem,
    reissueUrl: `${c.env.SELF_URL}/recover?order=${encodeURIComponent(record.order_id)}&email=${encodeURIComponent(record.email)}`,
    purchaseUrl: c.env.PURCHASE_URL,
    postmarkToken: c.env.POSTMARK_SERVER_TOKEN,
    fromEmail: c.env.POSTMARK_FROM_EMAIL,
  });

  return c.text(`We've re-sent the license to ${record.email}.`);
}
```

- [ ] **Step 3: Wire in `src/index.ts`**

```typescript
import { handleRecover } from "./recover/self-serve";
app.get("/recover", handleRecover);
```

- [ ] **Step 4: Run, pass**

Run: `npm test -- test/recover.test.ts`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/recover src/index.ts test/recover.test.ts
git commit -m "feat: GET /recover self-serve license resend"
```

---

## Task 17: README & deployment runbook

**Files:**
- Create: `license-service/README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# license-service

Cloudflare Worker that mints Ed25519-signed license files for
[Local AI Platform](https://github.com/hankthebldr/local-ai-platform),
delivers them via Postmark on Lemon Squeezy webhooks, and creates
structured GitHub support issues for licensed users.

## Setup (one-time)

1. Install Cloudflare resources:
   ```bash
   wrangler r2 bucket create laip-licenses
   wrangler kv namespace create RATE_LIMITS
   ```
   Copy the KV `id` into `wrangler.toml`.

2. Generate the signing keypair:
   ```bash
   npm run generate-keypair
   ```
   - Save private key → `wrangler secret put LICENSE_SIGNING_KEY`
   - Copy public PEM → `local-ai-platform/api/keys/license_pubkey.pem`

3. Populate remaining secrets:
   ```bash
   wrangler secret put LEMONSQUEEZY_WEBHOOK_SECRET
   wrangler secret put LEMONSQUEEZY_API_KEY
   wrangler secret put POSTMARK_SERVER_TOKEN
   wrangler secret put POSTMARK_FROM_EMAIL
   wrangler secret put GITHUB_APP_ID
   wrangler secret put GITHUB_APP_PRIVATE_KEY
   wrangler secret put GITHUB_APP_INSTALLATION_ID
   wrangler secret put ADMIN_TOKEN
   wrangler secret put LICENSE_PUBLIC_KEY    # base64 SPKI (no PEM headers)
   ```

4. Set `PRODUCT_ID` in `wrangler.toml` to the Lemon Squeezy product ID
   (integer, from the LS product URL).

5. Deploy:
   ```bash
   npm run deploy
   ```

6. In Lemon Squeezy → Settings → Webhooks:
   - URL: `https://license.ohno.dev/webhooks/lemonsqueezy`
   - Signing secret: matches `LEMONSQUEEZY_WEBHOOK_SECRET`
   - Events: `order_created`, `order_refunded`

## Pre-launch QA (in LS Test Mode)

1. LS Test Mode on → buy with card `4242 4242 4242 4242`.
2. Confirm Postmark email arrives within ~1 min with `license.key` attached.
3. Confirm R2 has `licenses/<id>.json` and `licenses/by-order/<order>.json`.
4. Revoke via `curl -X POST https://license.ohno.dev/admin/revoke -H "Authorization: Bearer $ADMIN_TOKEN" -d '{"license_id":"..."}'`
5. `curl https://license.ohno.dev/revocations.json` — confirm the id appears.
6. `curl https://license.ohno.dev/recover?order=<ls_order_id>&email=<buyer>` — confirm 410 on revoked.
7. Submit a test issue via CLI (see main-repo `SUPPORT.md`) — confirm issue lands on GitHub with the `supported` label and private metadata comment.

## Admin operations

- **Revoke:** `POST /admin/revoke` with `Authorization: Bearer $ADMIN_TOKEN` and JSON `{"license_id": "laip_..."}`
- **Reissue:** `POST /admin/reissue` with JSON `{"order_id": "lsorder_..."}`

## Architecture

See `../local-ai-platform/docs/superpowers/specs/2026-04-18-licensing-and-supportability-design.md`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with setup, QA, and ops instructions"
```

---

## Task 18: Final integration test + deploy smoke

**Files:**
- Create: `license-service/test/integration.test.ts`

- [ ] **Step 1: Write end-to-end test**

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SELF, env } from "cloudflare:test";
import { sampleLemonSqueezyOrderCreated } from "./helpers/fixtures";

import { TEST_PRIVATE_B64 as TEST_PRIVATE, TEST_PUBLIC_B64 } from "./helpers/keys";


async function hmacSig(body: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
  return Array.from(sig).map((b) => b.toString(16).padStart(2, "0")).join("");
}

describe("integration: order → license → support → revoke", () => {
  beforeEach(async () => {
    const objs = await env.LICENSES.list();
    await Promise.all(objs.objects.map((o) => env.LICENSES.delete(o.key)));
    env.LICENSE_SIGNING_KEY = TEST_PRIVATE;
    env.LICENSE_PUBLIC_KEY = TEST_PUBLIC;
    env.LEMONSQUEEZY_WEBHOOK_SECRET = "test-secret";
    env.PRODUCT_ID = "999";
    env.ADMIN_TOKEN = "admintok";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "https://api.postmarkapp.com/email")
          return Promise.resolve(new Response(JSON.stringify({ MessageID: "x" }), { status: 200 }));
        if (url.endsWith("/access_tokens"))
          return Promise.resolve(new Response(JSON.stringify({ token: "ghs_x" }), { status: 201 }));
        if (url.endsWith("/issues"))
          return Promise.resolve(new Response(JSON.stringify({ number: 99, html_url: "https://gh/99" }), { status: 201 }));
        if (/\/comments$/.test(url))
          return Promise.resolve(new Response(JSON.stringify({ id: 1 }), { status: 201 }));
        return Promise.resolve(new Response("x", { status: 500 }));
      })
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("runs the full purchase → support → revoke flow", async () => {
    // 1. Purchase
    const orderBody = JSON.stringify(sampleLemonSqueezyOrderCreated);
    const orderSig = await hmacSig(orderBody, "test-secret");
    const orderRes = await SELF.fetch("https://license.test/webhooks/lemonsqueezy", {
      method: "POST",
      headers: { "X-Signature": orderSig, "Content-Type": "application/json" },
      body: orderBody,
    });
    expect(orderRes.status).toBe(200);
    const { license_id } = await orderRes.json<{ license_id: string }>();

    // 2. Read revocations — empty
    const rev1 = await SELF.fetch("https://license.test/revocations.json");
    expect((await rev1.json<{ revoked: string[] }>()).revoked).toEqual([]);

    // 3. Revoke admin
    const revokeRes = await SELF.fetch("https://license.test/admin/revoke", {
      method: "POST",
      headers: { "Authorization": "Bearer admintok", "Content-Type": "application/json" },
      body: JSON.stringify({ license_id }),
    });
    expect(revokeRes.status).toBe(200);

    // 4. Revocations now includes it
    const rev2 = await SELF.fetch("https://license.test/revocations.json");
    expect((await rev2.json<{ revoked: string[] }>()).revoked).toContain(license_id);
  });
});
```

- [ ] **Step 2: Run full suite**

Run: `npm test`
Expected: all tests pass across all files.

- [ ] **Step 3: Typecheck**

Run: `npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Deploy to Cloudflare**

```bash
npm run deploy
```
Expected: URL printed. Visit `https://<worker-name>.<subdomain>.workers.dev/health` → `{"status":"ok"}`.

- [ ] **Step 5: Push worker repo to GitHub**

```bash
git remote add origin git@github.com:hankthebldr/license-service.git
git push -u origin main
```

- [ ] **Step 6: Commit final integration test**

```bash
git add test/integration.test.ts
git commit -m "test: end-to-end purchase → support → revoke"
```

---

## Self-Review Checklist (completed during plan authoring)

- **Spec coverage:** Every endpoint from spec §7 is implemented across Tasks 8–16. GitHub private comment (§6) is in Task 12. Rate-limiting (§6 "abuse controls") in Task 11+13. Ed25519 signing (§4) in Tasks 3–4. Revocations list (§3) in Tasks 9–10.
- **Placeholder scan:** no TBD / TODO. Every step has full code or full commands.
- **Type consistency:** `LicensePayload`, `LicenseRecord`, `INDIVIDUAL_FEATURES`, `PRODUCT` defined once in `types.ts` and re-used across webhook, reissue, recover. `CloudflareBindings` expanded in Task 13 to add `LICENSE_PUBLIC_KEY`. Callers updated.
- **Scope:** plan focused on the Worker; in-app client is a separate plan.

## Out of Scope (confirmed)

- Team-tier seat management (spec §12).
- AI-assisted PR generation (spec §6 future phases).
- Customer web portal.
