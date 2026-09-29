# RESEARCH

Append-only trail of research passes, repo summaries, and investigations.
Each entry: date + commit SHA + one line.

## 2026-06-28 @ `1708b7c` — `/repo-summary` regenerated

Full-depth repo snapshot written to vault `Github-Projects/local-ai-platform (github)/SUMMARY.md`
(operator chose the existing governing-anchor folder over a byte-identical new one). Flagged: vault
folder in `__temp__` mid-sync state (anchor dropped from `_MOC Dev Projects`), version string `1.1.1`
lags ~40 PRs of merged `1.3.0` work, stale `ENTERPRISE_DEPLOYMENT_GAPS.md`, missing `LICENSE`.

## 2026-09-29 @ `d9efdfe` — revisit audit

Full-repo revisit after a three-month gap: structural survey, suite run (2,506 passed / 80% cov), four read-only
audits (backend, frontend, planned-vs-shipped, hardening). Written to `docs/roadmap/2026-09-29-revisit-audit.md`.
Headline: publishing frozen since 2026-09-11 (`migrate-branches.sh` never applied — release/docker/pages fire on
`dev`/`main` only), 126 commits unreleased behind `1.1.1`, `POST /api/setup/install-ollama` pipes a remote script
into `sh` behind base auth, `LICENSE` still missing, streaming path blocks the event loop.
