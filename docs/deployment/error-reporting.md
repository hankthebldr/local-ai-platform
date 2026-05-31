# Error reporting & auto-triage

Enclave can automatically triage failures and report them to a sink **you control**.
It is **opt-in and off by default** — out of the box, nothing leaves the machine.

## What gets reported

Unhandled runtime exceptions, normalized into a deduplicated, severity-labelled event.
Test failures in CI are triaged separately by `python -m triage ci` (see the CI workflow).

## Turning it on

Set in `.env`:

    ENABLE_ERROR_REPORTING=true
    ERROR_SINK=github            # or webhook | sentry
    ERROR_SINK_URL=youruser/yourrepo   # owner/repo for github; URL for webhook/sentry

## Privacy guarantees

- **Redaction is mandatory.** Prompt text and request bodies are dropped; secrets,
  API keys, and `$HOME` paths are scrubbed before anything is sent. This cannot be disabled.
- **Operator-owned by default.** Reports go to *your* GitHub repo / collector / webhook.
- **Vendor phone-home is separate, off by default,** and requires `ERROR_REPORTING_VENDOR=true`
  plus an explicit disclosure (a deferred, gated capability).

## How it scales bug reporting

The same fingerprint / dedup / severity machinery powers CI and runtime, so distinct bugs
become one tracked issue each — recurrences add a comment, never a duplicate. The reporting
path is fire-and-forget and never delays or breaks a user-facing request; if the local
Ollama enrichment model or the sink is unreachable, it degrades to a local log line.

## Configuration reference

| Env var | Default | Controls |
|---|---|---|
| `ENABLE_ERROR_REPORTING` | `false` | Master switch (opt-in) |
| `ERROR_SINK` | `none` | `none` \| `github` \| `webhook` \| `sentry` |
| `ERROR_SINK_URL` | — | `owner/repo` (github) or endpoint URL |
| `ERROR_SINK_TOKEN` | — | Sink auth (env reference) |
| `ERROR_REPORTING_VENDOR` | `false` | Phase-3 vendor phone-home opt-in |
| `TRIAGE_ENRICH` | `true` | Best-effort local-Ollama enrichment |
| `TRIAGE_OLLAMA_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `TRIAGE_OLLAMA_MODEL` | `qwen2.5:14b-instruct-q5_K_M` | Enrichment model |
| `TRIAGE_REDACT` | `true` | Redaction floor (cannot be fully disabled) |
