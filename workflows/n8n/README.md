# n8n release-update workflow

An importable n8n workflow that drives Enclave release prep through your **local** Ollama instance. No cloud LLM calls — designed for the BD790i / MS-01 homelab.

## What it does

```
Manual trigger
   │
   ▼
Resolve config (env-overridable)
   │
   ▼
git fetch + checkout + pull + collect commit log since last tag
   │
   ├──►  Ollama: draft CHANGELOG entry (Keep-a-Changelog format)
   │
   └──►  Ollama: draft 4-sentence release announcement
            │
            ▼
   Consolidate drafts → write to .release-prep/<version>-draft.md
            │
            ▼
   If ENCLAVE_CREATE_RELEASE=true:
        ├──►  git tag + push (triggers release.yml CI on GitHub)
        └──►  Summary
   Else:
        └──►  Summary (you commit + push manually after review)
```

## Prerequisites

- n8n running somewhere with network access to your local Ollama (default `http://localhost:11434`)
- Ollama with a 14B-class instruct model pulled (`qwen2.5:14b-instruct-q5_K_M` by default)
- The Enclave repo cloned on the same machine running n8n's `Execute Command` nodes
- `git`, `gh` CLI (optional, only if `ENCLAVE_CREATE_RELEASE=true`)

## Configuration

All knobs are environment variables on the n8n process. Defaults shown:

| Env var | Default | What it controls |
|---|---|---|
| `ENCLAVE_REPO_PATH` | `/home/henry/Github/Github_desktop/local-ai-platform` | Absolute path to the repo checkout |
| `ENCLAVE_OLLAMA_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `ENCLAVE_OLLAMA_MODEL` | `qwen2.5:14b-instruct-q5_K_M` | Model used for drafting |
| `ENCLAVE_RELEASE_VERSION` | `v1.3.0` | The tag this run targets |
| `ENCLAVE_BRANCH` | `master` | Branch to pull before drafting |
| `ENCLAVE_CREATE_RELEASE` | `false` | If `true`, tags + pushes; otherwise stops at draft |

## How to import

1. Open n8n → **Workflows** → top-right menu → **Import from File**.
2. Pick `workflows/n8n/enclave-release-update.json`.
3. (Optional) Open the **Resolve config** node and override defaults in-line if you don't want to use env vars.
4. Hit **Execute Workflow** to run a draft pass. The draft lands at `.release-prep/v1.3.0-draft.md` inside your repo checkout.

## Recommended flow

1. **Draft pass.** Run with `ENCLAVE_CREATE_RELEASE=false` (the default). Inspect the draft Markdown file.
2. **Edit.** Open `CHANGELOG.md`, paste the generated section, fix anything the LLM got wrong.
3. **Commit + push.** Manually:
   ```bash
   git add CHANGELOG.md
   git commit -m "docs(changelog): finalize 1.3.0 release notes"
   git push
   ```
4. **Release pass.** Re-run the workflow with `ENCLAVE_CREATE_RELEASE=true`. It tags + pushes; the GitHub Actions [release.yml](../../.github/workflows/release.yml) workflow takes over and publishes the DMG + wheel + sdist + tarball.

## Why local Ollama

This is a release pipeline for a **self-hosted, zero-telemetry** product. Routing release notes through a cloud LLM would undermine the product story — and would be a needless data leak (every commit message and PR title piped to a third party). Local inference is slower but ideologically consistent.

## Quality knobs

- The CHANGELOG node runs at `temperature=0.3` for factual output
- The announcement node runs at `temperature=0.4` for slightly more prose latitude
- Both nodes have `timeout: 600000` (10 minutes) — adequate for a 14B model on CPU
- Swap to a larger model (`dolphin-mixtral:8x7b`, `qwen2.5:32b`) for higher quality at slower speed

## Limits

- The workflow assumes `git describe --tags --abbrev=0 HEAD~1` finds the previous tag. On a fresh repo with no tags it walks back to the root commit, which can produce a huge log.
- Tagging is done locally via `git tag -a`; if your repo requires signed tags, run the tag step manually with `git tag -s` instead.
- The `executeCommand` nodes run shell commands on whatever host n8n is running on — pointing this at a multi-user n8n instance without sandboxing is a bad idea. Homelab use only.
