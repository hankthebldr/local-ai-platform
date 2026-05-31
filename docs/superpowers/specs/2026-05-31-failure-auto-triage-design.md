# Failure Auto-Triage & Operator-Owned Error Telemetry — Design Document

**Status:** Draft v1 · **Author:** Henry Reed · **Date:** 2026-05-31 · **Target release:** 1.3.x (CI) → 1.4.x (runtime telemetry)
**Paired implementation plan:** [2026-05-31-failure-auto-triage-implementation.md](2026-05-31-failure-auto-triage-implementation.md) *(to be written)*

---

## Executive summary

Enclave surfaces failures in two places — **test failures in CI** and **errors in the running app** — and today both are dead ends. CI failures show as `--tb=short` text in an Actions log nobody re-reads; runtime exceptions return a bare 500 and (for unhandled cases) aren't even logged. This design adds an auto-triage system that turns both into actionable, deduplicated GitHub output: inline `::error::` annotations on the PR diff, a markdown triage table in the run summary, and auto-filed GitHub Issues grouped by a stable fingerprint so the same bug never spams the tracker.

The system is built as **two collectors → one triage core → many emitters**. The core (normalize → fingerprint → classify → enrich → emit) is a self-contained `triage/` package with **zero FastAPI dependency**, so CI can run it standalone via `python -m triage` and the live app can call the same code from a catch-all exception handler. Classification is **deterministic rules** (severity + category), with **best-effort local Ollama enrichment** (`qwen2.5:14b`, reusing the n8n release-workflow model) that adds a human-readable likely-cause — and that silently degrades to rules-only wherever Ollama is unreachable, which is *always* the case in GitHub-hosted CI.

This work also marks a **deliberate, scoped revision to Enclave's telemetry stance**. The product promise moves from absolute "no telemetry" to **operator-owned error reporting, opt-in and off by default**, where each deployed box reports to a sink *its own operator controls* (their GitHub repo, a homelab collector, a webhook). A vendor phone-home path exists but is **optional, explicit, and disabled by default**, behind a one-time in-product disclosure. Redaction of prompts, secrets, and home-directory paths is **mandatory and non-disableable** for anything that leaves the process. The net effect: aggressive automatic failure visibility for the operator's own fleet, with the "sovereign appliance" promise intact for everyone who doesn't opt in.

Critically, that **opt-in selection is itself the scaling mechanism for bug reporting** — not merely a privacy gate. Enabling it (`ENABLE_ERROR_REPORTING=true`, `ERROR_SINK=github`) converts raw CI *and* field failures into a single **deduplicated, severity-labelled GitHub Issue backlog, generated automatically**: each distinct product bug becomes a tracked, triaged issue the moment it occurs — one issue per fingerprint, recurrences counted not duplicated — turning "we have logs somewhere" into a managed bug pipeline that scales without spam. See [Opt-in product-bug issue generation](#opt-in-product-bug-issue-generation--the-manageable-scaling-mechanism).

Delivery is phased along the CI-first line: **Phase 1** (CI triage) ships with no application changes, only one tiny security-hardening dependency (`defusedxml`, for XXE/billion-laughs-safe JUnit parsing), and no network egress. **Phase 2** (runtime capture + operator-owned telemetry) adds the catch-all handler, redaction, opt-in gate, and operator sinks. **Phase 3** (optional vendor phone-home) is deferred and gated.

---

## Goals & non-goals

**Goals**
- Turn CI test failures into inline annotations + a run-summary table + deduplicated auto-filed Issues.
- Capture unhandled runtime exceptions in the live app, classify them, and (opt-in) report them to an operator-controlled sink.
- One triage core, written once, shared by both sources.
- Deterministic, dependency-light CI path; richer local-Ollama enrichment where available.
- Never let triage break or delay a user-facing request, and never let it spam the issue tracker.
- Preserve the privacy posture for any operator who does not opt in.

**Non-goals**
- Replacing a full APM/observability stack (Prometheus/Grafana/Sentry server). We *emit to* a Sentry-compatible sink; we don't build one.
- Cloud-hosted telemetry as a default. Vendor phone-home is opt-in, Phase 3, and out of scope for the initial build.
- Flaky-test *quarantine/retry* automation. We *classify* flaky-candidates; auto-retry is a later concern.
- Changing the OpenAI-compatible error envelope returned to API clients. `APIError` responses are byte-for-byte unchanged.

---

## Architecture: two collectors → one core → many emitters

```
┌─────────────────────┐         ┌──────────────────────────────────────┐
│ COLLECTORS          │         │ TRIAGE CORE  (triage/, no FastAPI dep) │
│                     │         │                                        │
│  junit.py   (CI)    │──┐      │  normalize → FailureEvent              │
│  runtime.py (live)  │──┼────► │  fingerprint()   (stable dedup hash)   │
└─────────────────────┘  │      │  classify()      (rules → severity/cat)│
                         │      │  enrich()        (local Ollama, best-  │
                         │      │                   effort, may no-op)   │
                         │      └───────────────┬────────────────────────┘
                         │                      │ [TriageVerdict]
                         │                      ▼
                         │      ┌──────────────────────────────────────┐
                         │      │ EMITTERS                              │
                         │      │  annotations.py   ::error:: (CI)      │
                         │      │  step_summary.py  $GITHUB_STEP_SUMMARY│
                         │      │  github_issues.py deduped issues (gh) │
                         │      │  webhook.py       operator sink (live)│
                         │      └──────────────────────────────────────┘
```

Each unit has one purpose and a narrow interface: a collector returns `list[FailureEvent]`; the core is pure functions over those; an emitter consumes `list[TriageVerdict]` and has a single `emit()` method. A reviewer can understand `junit.py` without reading `github_issues.py`, and the runtime path can be tested without touching CI code.

**Why a standalone package, not `api/services/`:** CI must parse a JUnit file without installing or importing the FastAPI app (the CI config already refuses heavy deps — "RAG suite needs sentence-transformers which are heavy to install on every CI run"). A top-level `triage/` package with zero app imports keeps the CI job fast and lets `python -m triage` run anywhere. The runtime handler imports the same core.

**Why not off-the-shelf Actions** (`dorny/test-reporter` etc.): for a security-positioned product, every third-party marketplace Action is supply-chain surface in the release pipeline, and they split triage logic (Action for CI, custom for runtime) instead of sharing one core. We own all the code and control the fingerprint/dedup behavior.

---

## Core data model (`triage/models.py`, Pydantic v2)

```python
class Severity(str, Enum):
    critical = "critical"   # app won't boot · mass test failure · security-relevant
    high     = "high"       # feature broken · infra dependency down
    medium   = "medium"     # single logic/assertion regression
    low      = "low"        # flaky-candidate · warning-level

class Category(str, Enum):
    assertion = "assertion"      # logic regression
    import_error = "import_error"
    timeout = "timeout"
    connection = "connection"    # Ollama / infra unreachable
    flaky = "flaky"
    config = "config"
    unhandled = "unhandled"      # runtime: uncaught exception
    unknown = "unknown"

class FailureEvent(BaseModel):
    source: Literal["ci", "runtime"]
    fingerprint: str = ""          # filled by fingerprint()
    exception_type: str
    message: str                   # one-line; redacted for runtime
    traceback: str | None = None   # full text; redacted for runtime
    test_id: str | None = None     # CI:  "tests/unit/test_foo.py::TestBar::test_baz"
    route: str | None = None       # runtime: "POST /v1/chat/completions"
    file: str | None = None
    line: int | None = None
    func: str | None = None
    env: dict[str, str] = {}       # python_version, os, enclave_version, arch
    occurred_at: str | None = None # ISO 8601; runtime sets it
    request_id: str | None = None  # runtime correlation id

class TriageVerdict(BaseModel):
    event: FailureEvent
    severity: Severity
    category: Category
    rule_summary: str              # deterministic one-liner
    likely_cause: str | None = None  # Ollama enrichment, optional
    first_check: str | None = None   # Ollama enrichment, optional
    enriched: bool = False           # did Ollama actually run?
    seen_count: int = 1              # dedup: occurrences of this fingerprint
```

---

## Fingerprint & dedup (`triage/fingerprint.py`) — the load-bearing decision

The fingerprint is the dedup key for GitHub Issues. It must survive cosmetic edits but distinguish genuinely different failures.

```
CI:      sha256( test_id | exception_type | last_app_frame "file:func" )[:16]
runtime: sha256( route   | exception_type | top_3_app_frames "file:func" )[:16]
```

**Normalized out (deliberately):** line numbers, absolute paths (→ repo-relative), memory addresses, UUIDs, timestamps, and object `repr()` ids. "app frame" = a stack frame inside the repo, skipping pytest/library internals.

**Rationale & accepted trade-off.** Keeping line numbers means any edit *above* a failing line forges a "new" fingerprint and spams the tracker (fragmentation). Dropping them dedupes correctly but risks *collision* — two distinct bugs in the same function with the same exception type merging into one issue. For a single-operator appliance, fragmentation is the worse failure mode; the full traceback in the issue body lets a human distinguish a collision by eye. This mirrors Sentry's "grouping" heuristic with a pragmatic subset. **Confirmed default: drop line numbers.** Granularity is a documented tunable if collisions prove annoying in practice.

---

## Classification (`triage/classify.py` + `triage/enrich.py`)

### Rules (always run · deterministic · no dependencies)

`classify(event) -> (Severity, Category, rule_summary)` — an ordered rule list, first match wins, fallback `(medium, unknown)`. Indicative rules:

| Signal | Severity | Category |
|---|---|---|
| `*ConnectionError`, "Connection refused", `OllamaConnectionError` | high | connection |
| `ImportError`/`ModuleNotFoundError` of a **core** module | critical | import_error |
| `ImportError`/`ModuleNotFoundError` (non-core) | high | import_error |
| `TimeoutError`, or `slow`-marked test exceeding budget | low | timeout/flaky |
| `AssertionError` | medium | assertion |
| runtime source, uncaught, 5xx | high | unhandled |
| **> 50% of suite failing** (collection-time break smell) | critical | import_error |

> **Learning-mode contribution point.** The rule *ordering* and the **mass-failure escalation threshold** are genuine operator judgment calls — Henry is the one who will triage these. During implementation, `classify()` is scaffolded with signature, comments, and a `TODO`, and Henry writes the ~8-line rule body. This is business logic with multiple valid approaches, not boilerplate.

### Ollama enrichment (best-effort · optional · degrades silently)

`enrich(verdict, *, model, url, timeout) -> verdict` posts the failure (type, message, traceback tail) to **local** Ollama and asks for a 2-sentence *likely cause + first thing to check* at low temperature. Defaults reuse the n8n release workflow: `qwen2.5:14b-instruct-q5_K_M` at `http://localhost:11434`.

**Hard contract:** the call is wrapped so *any* failure — connection refused, model missing, timeout — returns the verdict unchanged with `enriched=False` and raises nothing. **GitHub-hosted CI has no Ollama, so the CI path is always rules-only by design.** `enrich.py` uses a minimal standalone `requests` call (matching the existing [api/services/ollama_service.py](../../../api/services/ollama_service.py) convention, **not** importing it) to preserve the zero-app-dependency rule; the small duplication is justified and can later be factored into a shared minimal client.

---

## Phase 1 — CI path (ships first; no app changes, one tiny security dep, no egress)

### Flow

```
pytest tests/ ... --junitxml=reports/junit.xml      # --junitxml is built into pytest
   └─ pytest exit code saved; job pass/fail still reflects real test result
        └─ python -m triage ci --junit reports/junit.xml \
                 --emit annotations,summary,issues
             ├─ parse JUnit → [FailureEvent]
             ├─ fingerprint + classify (rules only)
             └─ emit:
                  • annotations  → ::error file=…,line=…,title=…:: (inline on PR diff)
                  • step summary → markdown table to $GITHUB_STEP_SUMMARY
                  • github issues→ gh, deduped by <!-- fp:… --> marker
```

### Emitters

- **`annotations.py`** — prints `::error file={file},line={line},title={severity}: {category}::{message}` (and `::warning::` for `low`). GitHub renders these inline on the PR diff and in the log. Stdout only, zero deps.
- **`step_summary.py`** *(default-on, per operator decision 2026-05-31)* — appends a markdown table (severity · category · test · summary · issue link) to `$GITHUB_STEP_SUMMARY` for an at-a-glance run overview.
- **`github_issues.py`** — dedup-aware via `gh`, **engineered to stay under GitHub API rate limits** (operator guardrail, 2026-05-31):
  - **One** `gh issue list --label triage:auto --state open` call per run (core REST), building an in-memory `{fingerprint → issue#}` map from `<!-- fp:… -->` markers. **Never** a per-failure `--search` (the search API caps at 30 req/min).
  - **Dedupe verdicts by fingerprint before any API call**; **cap issues/run** (default 10, `--max-issues`, suppressed count logged via `::warning::`); **throttle** between writes; **hard-stop on the first API error** (no retry storm).
  - **Recurrence** (fp already in map) → add a comment ("Recurred in {run_url}, now seen ×N") and bump `seen_count`; no duplicate opened.
  - **New** → create issue: title `[{severity}] {category}: {short message}`, labels `bug, triage:auto, severity:{x}, category:{y}`, body in the [bug_report.yml](../../../.github/ISSUE_TEMPLATE/bug_report.yml) shape (description / repro hint / version / os / logs=traceback) + fp marker + run link + enrichment if present.
  - A small idempotent label-bootstrap (`gh label create …`) ensures `severity:*`, `category:*`, `triage:auto` exist.

### CI wiring & two safety nuances

1. **Job pass/fail integrity.** pytest runs, its exit code is saved to a file; the triage step runs with `if: always()`; a final step re-exits with the saved code so the job's red/green still reflects the actual tests. Triage is observational, never the arbiter of build status.
2. **`permissions: issues: write`.** `GITHUB_TOKEN` cannot open issues by default — the `test` job gets an explicit `permissions` block.
3. **Fork-PR boundary.** PRs from forks receive a **read-only** `GITHUB_TOKEN`, so issue creation silently no-ops there. This is *correct* — otherwise any fork could spam the tracker. For fork PRs the emitter auto-downgrades to annotations + summary only. Documented as a deliberate supply-chain boundary, not a defect.

**Phase 1 acceptance criteria / Gate:** a seeded failing test produces (a) an inline annotation, (b) a row in the run summary, (c) exactly one new issue; a second run with the same failure adds a comment and opens **no** second issue; a passing run produces no output; fork-PR runs never create issues. No new runtime dependency; CI wall-clock increase < ~5s.

---

## Phase 2 — runtime path (opt-in, operator-owned)

### Catch-all exception handler (`api/exceptions.py`, registered in `api/main.py`)

Today only `APIError` is handled, and that handler doesn't log. Phase 2 adds:

- Logging to the existing `api_error_handler` (fixes the current silent gap; behavior otherwise unchanged).
- A new handler registered for `Exception`. Because FastAPI dispatches the **most-specific** handler first, `APIError` responses remain byte-for-byte identical; the catch-all only sees genuinely unhandled exceptions.

The catch-all:
1. **Always** logs a structured error record.
2. **If `ENABLE_ERROR_REPORTING=true` and a sink is configured:** build a **redacted** `FailureEvent` → classify → enrich (best-effort) → emit to the operator sink, **fire-and-forget** (background task / detached), wrapped so triage **never raises into or delays the request path**. A triage hiccup logs a warning and is swallowed.
3. Returns the standard OpenAI-compatible 500 envelope (same shape as `api_error_handler`) with a generic message + a `request_id` for correlation. No internals leak to the caller.

**Known limitation (documented, not over-engineered):** exceptions raised *inside middleware* (auth, rate-limit) may bypass the route-level handler per Starlette's `ServerErrorMiddleware` ordering. Phase 2 covers route/handler/service exceptions; middleware-raised errors are a noted gap.

### Redaction (`triage/redact.py`) — mandatory, non-disableable

Before *anything* leaves the process:
- **Drop request bodies / prompt text** entirely (the product processes private prompts — they never ship). Operator may opt into length-only/hashed metadata.
- **Scrub** auth headers (`Authorization`, `X-API-Key`) and secret patterns (`sk-…`, bearer tokens, AWS keys, `password=…`).
- **Rewrite** `$HOME`-anchored absolute paths to `~`/repo-relative.
- **Configurable** extra patterns via `TRIAGE_REDACT_EXTRA`; PII patterns (emails, IPs) scrubbed by default.

This mirrors the operator's global OPSEC egress rules (the pre-tool-use hook already blocks `~/.ssh`, `~/.aws`, `*.env` in outbound bodies). `TRIAGE_REDACT=true` is the floor; the prompt/secret classes cannot be disabled.

### Operator sinks (`triage/emitters/webhook.py`)

POST the redacted `TriageVerdict` JSON to `ERROR_SINK_URL`. Two envelope shapes: a Sentry-compatible event and a generic JSON payload. `ERROR_SINK=github` reuses the Phase-1 issue emitter so a deployed box can file into its own repo. This is the **operator-owned default**.

**Phase 2 acceptance criteria / Gate:** with reporting off (default), a route exception yields the 500 envelope, logs locally, and emits **nothing**; with reporting on + a mock sink, the same exception delivers a **redacted** payload (asserted: no prompt text, no secrets, no home paths) without delaying the response; an unreachable Ollama still produces a rules-only verdict; an unreachable sink degrades to local-log without raising.

---

## Opt-in product-bug issue generation — the manageable scaling mechanism

The single capability that makes this system *scale* bug reporting rather than merely *collect* errors is **operator opt-in to automatic, deduplicated GitHub Issue generation**, applied uniformly to both sources through one pipeline:

- **CI test failures** generate issues in the repo (Phase 1, always-on in CI).
- **Runtime/product bugs** from a deployed box generate issues in the operator's *own* repo once they opt in and select `ERROR_SINK=github` (Phase 2).

Both run the *same* `fingerprint → classify → dedup → emit` core, so the operator gets **one tracker with one grouping scheme** spanning "broke in CI" and "broke in the field." There is no second bug system to reconcile.

**Why this scales manageably (and is not issue spam):**

| Scaling risk | Mitigation |
|---|---|
| Same bug recurs → N issues | One issue per fingerprint; recurrences add a comment + `seen ×N`, never a duplicate |
| Backlog becomes unreadable | Every issue carries `severity:*` + `category:*` labels → filterable, triageable at a glance |
| Volume escapes operator control | Opt-in gate + operator-owned sink: the operator chooses *whether*, *where*, and (via severity / `--fail-on`) *how loud* |
| Sensitive payloads land in a tracker | Mandatory redaction — prompts/secrets/paths never reach the issue body |

The opt-in *selection* is therefore the **control plane**: enabling it converts raw failures into a curated, deduplicated, severity-labelled bug backlog automatically — the difference between "we have logs somewhere" and "every distinct product bug is a triaged, tracked issue the moment it occurs." This is the operator-facing value of the whole system, and the reason the telemetry-stance revision was worth making.

---

## Phase 3 — vendor phone-home (deferred, gated)

The same `webhook.py` emitter pointed at a vendor URL, behind `ERROR_REPORTING_VENDOR=true` (default false) and a **one-time in-product disclosure** on first enable. Requires a published privacy policy and disclosure copy before it ships. Out of scope for the initial build; the seam exists so the decision can be made later without rework.

---

## Configuration (`triage/config.py`) — mirrors existing `api/` conventions

| Env var | Default | Controls |
|---|---|---|
| `ENABLE_ERROR_REPORTING` | `false` | Master switch for runtime reporting (opt-in, like `ENABLE_API_AUTH`) |
| `ERROR_SINK` | `none` | `none` \| `github` \| `webhook` \| `sentry` |
| `ERROR_SINK_URL` | — | Operator sink endpoint |
| `ERROR_SINK_TOKEN` | — | Sink auth (env reference, never inline) |
| `ERROR_REPORTING_VENDOR` | `false` | Phase-3 vendor phone-home opt-in |
| `ERROR_VENDOR_URL` | — | Vendor endpoint (Phase 3) |
| `TRIAGE_ENRICH` | `true` | Attempt local-Ollama enrichment (auto-skips if unreachable) |
| `TRIAGE_OLLAMA_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `TRIAGE_OLLAMA_MODEL` | `qwen2.5:14b-instruct-q5_K_M` | Enrichment model (reuses n8n default) |
| `TRIAGE_REDACT` | `true` | Redaction floor (prompt/secret classes non-disableable) |
| `TRIAGE_REDACT_EXTRA` | — | Additional redaction regexes |

CI-side knobs are CLI args: `--emit annotations,summary,issues`, `--repo`, `--dry-run`, `--fail-on {none,critical}`.

---

## Telemetry stance & privacy posture (explicit, because this changes a product promise)

**Previous stance** (CLAUDE.md `## Conventions`, n8n README rationale): *"No telemetry. No cloud. All data local."*

**Revised stance (operator decision, 2026-05-31):**
- **Operator-owned error reporting is opt-in and off by default.** Each box reports to a sink its operator controls; the vendor never sees it.
- **The opt-in selection is the scaling mechanism for bug reporting.** Selecting `ERROR_SINK=github` turns runtime/product failures into the *same* deduplicated, severity-labelled GitHub Issues as CI — one tracker, one grouping scheme, one issue per fingerprint plus a recurrence counter. This is the capability that lets bug reporting scale manageably instead of becoming log noise.
- **Vendor phone-home is optional, explicit, disabled by default,** behind a disclosure (Phase 3).
- **Redaction is mandatory** for everything that leaves the process; prompts and secrets are never transmitted.
- **For any operator who does not opt in, behavior is identical to today** — fully local, zero egress.

**Downstream doc work this triggers** (tracked, not done in this spec): update the CLAUDE.md `## Conventions` line from absolute "No telemetry" to the nuanced statement above; refresh marketing/landing and README privacy copy; add the Phase-3 privacy policy before any vendor path ships.

---

## Testing strategy (`tests/triage/`, all deterministic — no network, Ollama mocked)

- **Fingerprint:** same logical failure across line shifts → identical fp; different exception/test → different fp; documented collision case asserted.
- **JUnit parser:** against `tests/fixtures/junit/*.xml` (pass, single failure, error, mass-failure fixtures).
- **Classifier:** table-driven `event → (severity, category)` including the >50% escalation.
- **Redaction:** leak-assertions — feed a payload containing a fake `sk-` key, a prompt, and a `/Users/henry/...` path; assert none survive.
- **Emitters:** annotations format; step-summary markdown; `github_issues` mocks the `gh` subprocess and asserts **one `list` call precedes any create (no per-fingerprint `--search`)**, fingerprint dedup collapses duplicates, the per-run cap holds with a logged suppression, and an API error stops without a retry storm; `webhook` mocks the HTTP client and asserts the payload is redacted.
- **Enrichment:** Ollama unreachable → `enriched=False`, no raise.
- **Runtime handler:** a `TestClient` test raising in a route asserts the 500 envelope shape, that reporting is skipped when the flag is off, and (flag on, mock sink) that a redacted payload is delivered without blocking the response.

All built **test-first** (TDD), fitting the existing `tests/` layout and markers.

---

## Package layout

```
triage/
  __init__.py
  __main__.py        # python -m triage ci --junit <path> --emit <list>
  models.py          # FailureEvent, TriageVerdict, Severity, Category
  fingerprint.py
  classify.py        # ← operator-authored rule body (learning-mode)
  enrich.py          # local-Ollama, best-effort
  redact.py
  config.py
  collectors/
    junit.py         # CI
    runtime.py       # live exception → FailureEvent
  emitters/
    base.py          # Emitter protocol: emit(list[TriageVerdict]) -> None
    annotations.py
    step_summary.py
    github_issues.py
    webhook.py
tests/triage/        # mirrors above, test-first
tests/fixtures/junit/*.xml
```

---

## Open questions / tunables

1. **Fingerprint granularity** — line numbers dropped (confirmed default). Revisit only if collisions become noisy.
2. **Issue auto-close** — should an issue auto-close when its fingerprint stops recurring for N runs? Deferred; risks closing real-but-intermittent bugs.
3. **Flaky handling** — Phase-1 only *classifies* flaky-candidates. Retry/quarantine is a later concern.
4. **Severity routing** — future: `critical` could page (PagerDuty/ntfy) on operator boxes. Out of scope; the verdict carries enough to add it later.

---

## Phasing summary

| Phase | Scope | App changes | New deps | Egress |
|---|---|---|---|---|
| **1 — CI** | JUnit → annotations + summary + deduped issues | none | `defusedxml` (tiny, security) | none |
| **2 — Runtime** | catch-all handler + redaction + opt-in operator sink + Ollama enrichment | `api/exceptions.py`, `api/main.py` | none (`requests`, already a core dep) | only if opted in, redacted, operator-owned |
| **3 — Vendor** | optional phone-home behind flag + disclosure | config + disclosure UI | none | only if explicitly enabled |

Each phase is independently shippable and gated on its acceptance criteria above.
