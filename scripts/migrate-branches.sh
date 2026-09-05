#!/usr/bin/env bash
#
# One-shot migration to the dev/main branch model (docs/BRANCHING.md).
#
# Run this from a machine whose GitHub credentials can push tags, delete
# branches, and change repo settings. The Claude Code session that prepared
# the consolidation PR could push branches but was denied ref deletion and tag
# pushes (HTTP 403), so these steps were left to be run by hand.
#
#   ./scripts/migrate-branches.sh            # dry run: prints, changes nothing
#   ./scripts/migrate-branches.sh --apply    # actually do it
#
# Requires: git, gh (authenticated with repo admin).
#
# RUN THIS AFTER the branch-consolidation PR has merged into the current
# default branch. The order matters: the PR carries the dev/main-aware
# workflows, so renaming first would leave `main` briefly wired to a branch
# name that no longer exists.
#
# Safe by construction: the first push to `main` afterwards triggers
# release.yml, which reads __version__ (1.1.1), finds tag v1.1.1 already
# published, and no-ops instead of re-releasing.
#
# Idempotent: re-running after a partial run converges. Safe to re-run.

set -euo pipefail

REPO="hankthebldr/local-ai-platform"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

if [[ $APPLY -eq 0 ]]; then
    echo "DRY RUN — nothing will change. Re-run with --apply to execute."
    echo
fi

run() {
    if [[ $APPLY -eq 1 ]]; then
        echo "  + $*"
        "$@"
    else
        echo "  would run: $*"
    fi
}

step() { echo; echo "── $* ─────────────────────────────────────────"; }

command -v gh >/dev/null || { echo "gh CLI required"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh is not authenticated"; exit 1; }

git fetch origin --prune --tags


# ── 1. Archive tags ───────────────────────────────────────────────────────
# Created BEFORE any branch is deleted. Only the OpenClaw branch holds content
# that exists nowhere else; the rest are tagged for provenance so the audit is
# reproducible. Annotated tags, so the reasoning travels with the ref.

step "1. Archive tags"

tag_branch() {  # <branch> <tag> <message>
    local br="$1" tag="$2" msg="$3"
    if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null 2>&1; then
        echo "  ok: ${tag} already exists locally"
    elif ! git rev-parse -q --verify "refs/remotes/origin/${br}" >/dev/null 2>&1; then
        echo "  skip: origin/${br} is already gone"
        return
    else
        run git tag -a "${tag}" "origin/${br}" -m "${msg}"
    fi
    run git push origin "refs/tags/${tag}"
}

tag_branch claude/enterprise-deployment-gaps-012rz4arKrZhivZVASpFTfdd \
    archive/2026-04-08-openclaw-skill-system \
"Archive of claude/enterprise-deployment-gaps-012rz4arKrZhivZVASpFTfdd (2026-04-08).

An OpenClaw/ClawHub skill registry and Claude-API-backed agent executor plus a
webui/skills.html surface. NOT merged: it depends on hosted Claude inference,
contrary to Enclave's local-only principle; it targets the retired webui/ tree;
and its api/routers/skills.py was superseded by the local-first skills
marketplace on the trunk. The only branch in the 2026-09 consolidation whose
content exists nowhere else."

tag_branch claude/angry-dubinsky archive/2026-04-20-api-key-tight-wins \
"Archive of claude/angry-dubinsky (2026-04-20).

Scope enforcement and the api_key_service YAML mtime cache reached the trunk
independently and in richer form. The usage-tracking middleware wiring did not,
and was ported during the 2026-09 consolidation. Provenance only."

tag_branch feat/onnx-embedding-substrate archive/2026-06-02-onnx-embedding-substrate \
"Archive of feat/onnx-embedding-substrate (2026-06-02).

Fully absorbed into the trunk; the trunk is a strict superset (it adds an
onnxruntime import guard and RAG auto-reindex). Pre-rebase history."

tag_branch feat/run-event-substrate archive/2026-06-29-run-event-substrate \
"Archive of feat/run-event-substrate (2026-06-29).

Fully absorbed into the trunk, which carried the UI work further through the
ES-module split. Pre-rebase history."

tag_branch worktree-design+ohno-brand-refresh archive/2026-05-29-teal-palette-design \
"Archive of worktree-design+ohno-brand-refresh (2026-05-29).

Carried one design spec for the teal rebrand, recovered onto the trunk during
the 2026-09 consolidation. The rebrand itself had already shipped with tuned
token values."


# ── 2. Rename master -> main ──────────────────────────────────────────────
# GitHub's rename retargets open PRs and sets up redirects for the old ref.

step "2. Rename master -> main"

if git rev-parse -q --verify refs/remotes/origin/main >/dev/null 2>&1; then
    echo "  ok: origin/main already exists"
else
    run gh api -X POST "repos/${REPO}/branches/master/rename" -f new_name=main
fi


# ── 3. Create dev off main, make it the default ───────────────────────────

step "3. Create dev and make it the default branch"

if git rev-parse -q --verify refs/remotes/origin/dev >/dev/null 2>&1; then
    echo "  ok: origin/dev already exists"
else
    run git fetch origin main
    run git branch -f dev origin/main
    run git push -u origin dev
fi

run gh api -X PATCH "repos/${REPO}" -f default_branch=dev


# ── 4. Repo merge settings ────────────────────────────────────────────────
# Squash-only with the PR title as the message is what makes the branch model's
# version-bump derivation work. Auto-delete keeps merged refs from lingering.

step "4. Merge settings"

run gh api -X PATCH "repos/${REPO}" \
    -F allow_squash_merge=true \
    -F allow_merge_commit=true \
    -F allow_rebase_merge=false \
    -F delete_branch_on_merge=true \
    -f squash_merge_commit_title=PR_TITLE \
    -f squash_merge_commit_message=PR_BODY

# NOTE: allow_merge_commit stays TRUE on purpose. Merge-forward syncs
# (main -> dev after a hotfix) must be plain merges, not squashes -- squashing
# a sync hides the hotfix commit from dev and re-conflicts at the next release.


# ── 5. Delete the consolidated branches ───────────────────────────────────
# Every branch below was audited against the trunk in the 2026-09
# consolidation. Deletion is safe only once step 1 has actually pushed the
# archive tags -- the guard enforces that rather than trusting it.

step "5. Delete consolidated branches"

STALE=(
    fix/chat-singletons                    # 0 unique commits; fully merged
    docs/changelog-code-exec-sandbox       # content-equivalent upstream
    feat/onnx-embedding-substrate          # absorbed; trunk is a superset
    feat/run-event-substrate               # absorbed; trunk is a superset
    worktree-design+ohno-brand-refresh     # spec recovered onto the trunk
    claude/angry-dubinsky                  # usage tracking ported to the trunk
    claude/enterprise-deployment-gaps-012rz4arKrZhivZVASpFTfdd  # rejected; archived
)

for br in "${STALE[@]}"; do
    if ! git rev-parse -q --verify "refs/remotes/origin/${br}" >/dev/null 2>&1; then
        echo "  ok: origin/${br} already gone"
        continue
    fi
    if [[ $APPLY -eq 1 ]] && ! git ls-remote --exit-code --heads origin "${br}" >/dev/null 2>&1; then
        echo "  ok: origin/${br} already gone"
        continue
    fi
    # The one branch with irreplaceable content must be archived on the remote
    # before it can be deleted.
    if [[ "${br}" == claude/enterprise-deployment-gaps-* ]]; then
        if ! git ls-remote --exit-code --tags origin \
                refs/tags/archive/2026-04-08-openclaw-skill-system >/dev/null 2>&1; then
            echo "  REFUSING to delete ${br}: archive tag is not on the remote."
            echo "  Re-run step 1 first -- this branch's content exists nowhere else."
            continue
        fi
    fi
    run git push origin --delete "${br}"
done


# ── 6. Rulesets ───────────────────────────────────────────────────────────

step "6. Branch protection"
cat <<'EOF'
  Not scripted -- apply in the GitHub UI or via `gh api repos/OWNER/REPO/rulesets`,
  because the right strictness depends on whether anyone else is contributing:

    main   require a PR · require the `ci` + `Release readiness` checks ·
           block force-push · block deletion · linear history
    dev    require the `ci` check · block force-push · block deletion
           (leave PR-required off for a solo operator; turn it on when a
           second contributor appears)

  Do NOT require a PR on main without also allowing the release PR to merge --
  the release path IS a PR, so this is compatible.
EOF


# ── 7. Dependabot PRs ─────────────────────────────────────────────────────

step "7. Dependabot (manual triage)"
cat <<'EOF'
  Seven open dependabot PRs were left untouched -- they are live PRs, not stale
  branches, and several close real CVE gaps. Rebase them onto dev after the
  rename (comment `@dependabot rebase` on each), then merge in this order:

    #185 aiohttp   3.9.1  -> 3.14.3   <- largest security gap; do this first
    #186 pypdf     4.3.1  -> 6.15.0
    #183 pillow   10.1.0  -> 12.3.0
    #182 torch     2.1.2  -> 2.13.0   <- major; check ML extras still resolve
    #179 transformers 4.36.2 -> 5.5.0 <- major; API breaks are likely
    #170 python-multipart 0.0.6 -> 0.0.31
    #104 pytest    7.4.3  -> 9.0.3    <- oldest; 78 commits behind, expect conflicts

  There is no .github/dependabot.yml in the repo -- these PRs come from the
  repo's Dependabot security/version settings, which follow the default
  branch, so they will retarget dev automatically once step 3 lands.
EOF

step "Done"
if [[ $APPLY -eq 0 ]]; then
    echo "That was a dry run. Re-run with --apply to execute."
else
    echo "Migration applied. Verify:"
    echo "  gh api repos/${REPO} --jq .default_branch     # -> dev"
    echo "  git ls-remote --heads origin"
    echo "  git ls-remote --tags origin | grep archive"
fi
