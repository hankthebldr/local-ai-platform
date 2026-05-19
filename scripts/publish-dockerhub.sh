#!/usr/bin/env bash
# Build + tag + push the Enclave API image to Docker Hub.
#
# Usage:
#   scripts/publish-dockerhub.sh                # builds, tags as :latest + :<version>, pushes both
#   scripts/publish-dockerhub.sh --no-push      # build + tag only
#   VERSION=1.2.0 scripts/publish-dockerhub.sh  # override version tag
#
# Prereqs:
#   - `docker login` against docker.io (one-time; check with
#     `cat ~/.docker/config.json | jq '.auths."https://index.docker.io/v1/"'`).
#   - You are on the branch you want to ship. The script reads version
#     from MODELS.md / .env.example / CLAUDE.md fallbacks — overrideable
#     via the VERSION env var.
#
# Note the registry name: the repo on Docker Hub is
#   `hankthebldrr/local-ai-platfrom`  ←  with the typo "platfrom"
# That's the canonical name the operator created. Do not "fix" it
# here unless the repo is renamed first.

set -euo pipefail

REGISTRY="${REGISTRY:-docker.io}"
NAMESPACE="${NAMESPACE:-hankthebldrr}"
IMAGE_NAME="${IMAGE_NAME:-local-ai-platfrom}"   # NOTE: typo is intentional, matches the Docker Hub repo
VERSION="${VERSION:-1.1.1}"
PUSH=1

for arg in "$@"; do
  case "$arg" in
    --no-push) PUSH=0 ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
  esac
done

IMAGE_FULL="${REGISTRY}/${NAMESPACE}/${IMAGE_NAME}"

echo "▸ Building ${IMAGE_FULL}:${VERSION} (and :latest)"
docker build \
  -t "${IMAGE_FULL}:${VERSION}" \
  -t "${IMAGE_FULL}:latest" \
  .

echo
echo "▸ Built tags:"
docker images "${IMAGE_FULL}" --format "  {{.Repository}}:{{.Tag}}  {{.Size}}  {{.CreatedAt}}"

if [ "${PUSH}" -eq 0 ]; then
  echo
  echo "▸ --no-push specified; skipping docker push."
  exit 0
fi

# Sanity-check the operator is logged in. `docker info` reads
# ~/.docker/config.json; the "Username" field is populated after
# `docker login` for the default index.
if ! grep -q "https://index.docker.io" "${HOME}/.docker/config.json" 2>/dev/null; then
  echo "✗ Not logged in to Docker Hub. Run: docker login"
  exit 2
fi

echo
echo "▸ Pushing ${IMAGE_FULL}:${VERSION} (5+ GB — this takes a while)"
docker push "${IMAGE_FULL}:${VERSION}"
echo
echo "▸ Pushing ${IMAGE_FULL}:latest"
docker push "${IMAGE_FULL}:latest"

echo
echo "▸ Published. Pull anywhere with:"
echo "    docker pull ${IMAGE_FULL}:${VERSION}"
echo "    docker pull ${IMAGE_FULL}:latest"
echo
echo "▸ Web: https://hub.docker.com/r/${NAMESPACE}/${IMAGE_NAME}"
