# Private overlay — keep methodology off the public repo

## Why

The Enclave engine is open source; the *methodology* that goes through
it doesn't have to be. The 6-step XSIAM detection engineering pipeline,
the 50-rule XQL validator's prompt library, the curated agent personas
— these are the consultant's IP and shouldn't ship on GitHub. The
private-overlay pattern keeps that content local without forking the
engine.

## How the loader works

The workflow engine, agent service, and plugin loader each scan **two
directories**: a public one (committed to git) and an optional private
overlay (gitignored). When a file with the same `id` exists in both,
the private version wins.

| Resource | Public path | Private path (gitignored) | Env override |
|---|---|---|---|
| Workflows | `workflows/*.yaml` | `workflows-private/*.yaml` | `WORKFLOWS_PRIVATE_DIR` |
| Agents | `agents/*.yaml` | `agents-private/*.yaml` | `AGENTS_PRIVATE_DIR` (planned) |
| Plugins | `plugins/<id>/` | `plugins-private/<id>/` | `PLUGINS_PRIVATE_DIR` (planned) |
| Corpus | `docs/seed/xql/` | `docs/seed-private/xql/` | n/a (file-system only) |

The `.gitignore` excludes every `*-private/` dir at the repo root and
`docs/seed-private/`.

## Where it surfaces

- `GET /api/workflows` returns each workflow with a `source` field
  (`"public"` or `"private"`) so the SPA can render an "internal only"
  chip on the cards that came from the overlay.
- `GET /api/workflows/{id}` resolves via `WorkflowEngine.resolve_workflow_path`,
  which checks the private overlay first.
- The async runner (`POST /api/workflows/run-async`) and the YAML
  executor (`POST /api/workflows/run`) both use the resolver — no
  separate code path for private content.

## Adding a private workflow

```bash
# 1. Drop the YAML in the overlay
mkdir -p workflows-private
cp my-internal.yaml workflows-private/

# 2. Restart the api so the engine picks it up
docker compose restart api

# 3. Confirm it shows as private
curl -s http://localhost:8000/api/workflows \
  -H "Authorization: Bearer $(cat data/config/first-run-key.txt)" \
  | jq '.[] | select(.id == "my-internal") | {id, source}'
# Expected: { "id": "my-internal", "source": "private" }
```

The file never appears in `git status`, never gets pushed to GitHub,
never shows up in the public docs. Engine treats it identically to a
public workflow at runtime.

## Promoting / demoting

- **Public → Private:** `git mv workflows/foo.yaml workflows-private/`
  + commit. The file disappears from the public repo and lives only on
  the local box going forward.
- **Private → Public:** `mv workflows-private/foo.yaml workflows/` +
  `git add workflows/foo.yaml`.

## What still leaks (the limitations)

- **Git history of *prior* commits.** Anything already pushed to a
  public branch lives in that branch's history forever (short of a
  history rewrite). The overlay only protects *future* additions.
- **Run artifacts.** A private workflow's `data/workflows/<run_id>/`
  output is on the local disk — fine for a single operator's box, not
  fine if you sync `data/` to a shared volume that ends up in a
  public bucket. The default compose volumes are local-only.
- **The workflow id appears in `/api/workflows`** even for private
  entries (the SPA wouldn't be able to list them otherwise). If the
  *id alone* is sensitive, mount the overlay only in trusted environments.

## What's in the overlay today

`workflows-private/xsiam-detection-engineering.yaml` — the 6-step
detection-engineering pipeline authored during the test-harness work.
Methodology-heavy: combines a fast classifier, IOC extraction, XQL
enrichment-query designer, XQL detection drafter, static validator,
and an operator runbook generator. Kept private because the system
prompts are the value, not the wiring.
