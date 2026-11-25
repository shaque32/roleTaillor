#!/usr/bin/env bash
# Deploy RoleTailor to Fly.io.
#   deploy/fly/deploy.sh <staging|prod> [api|web|redis|all]
# "all" (default) deploys api then web. Redis is only deployed when named explicitly.
# Auth: flyctl reads FLY_API_TOKEN from the environment (CI) or your `fly auth login`.
# Optional: IMAGE_LABEL overrides the image label (default: git short SHA when available).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

usage() { echo "usage: $0 <staging|prod> [api|web|redis|all]" >&2; exit 2; }
[[ $# -ge 1 && $# -le 2 ]] || usage
ENVIRONMENT="$1"
TARGET="${2:-all}"
case "$ENVIRONMENT" in staging) SUFFIX="-staging" ;; prod) SUFFIX="" ;; *) usage ;; esac
case "$TARGET" in api|web|redis|all) ;; *) usage ;; esac

if grep -q 'roletailor\.example' "$ROOT/deploy/fly/env/$ENVIRONMENT".*.env; then
  echo "deploy/fly/env/$ENVIRONMENT.*.env still has placeholder roletailor.example domains; set real ones first" >&2
  exit 1
fi

command -v flyctl >/dev/null 2>&1 || { echo "flyctl not found on PATH" >&2; exit 1; }

LABEL="${IMAGE_LABEL:-}"
if [[ -z "$LABEL" ]] && SHA="$(git rev-parse --short=12 HEAD 2>/dev/null)"; then
  LABEL="$SHA"
fi

# Echo "--env KEY=VALUE" arguments (one token per line) from an env file.
env_args() {
  local file="$1" line
  [[ -f "$file" ]] || { echo "missing env file: $file" >&2; exit 1; }
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line//[[:space:]]/}" || "$line" =~ ^[[:space:]]*# ]] && continue
    printf '%s\n%s\n' "--env" "$line"
  done <"$file"
}

deploy() {
  local name="$1" config="$2" envfile="$3" workdir="$4" dockerfile="$5"
  local -a args=(deploy "$workdir" --config "$ROOT/deploy/fly/$config" --app "${name}${SUFFIX}"
    --remote-only --wait-timeout 600)
  [[ -n "$dockerfile" ]] && args+=(--dockerfile "$dockerfile")
  [[ -n "$LABEL" && "$name" != "roletailor-redis" ]] && args+=(--image-label "rt-$LABEL")
  if [[ -n "$envfile" ]]; then
    while IFS= read -r a; do args+=("$a"); done < <(env_args "$ROOT/deploy/fly/env/$envfile")
  fi
  echo "==> flyctl deploy: ${name}${SUFFIX} ($ENVIRONMENT)"
  flyctl "${args[@]}"
}

case "$TARGET" in
  redis) deploy roletailor-redis redis.toml "" "$ROOT" "" ;;
  api)   deploy roletailor-api api.toml "$ENVIRONMENT.api.env" "$ROOT" "$ROOT/backend/Dockerfile" ;;
  web)   deploy roletailor-web web.toml "$ENVIRONMENT.web.env" "$ROOT/frontend" "$ROOT/frontend/Dockerfile" ;;
  all)
    # api first: its release_command runs migrations before new machines start.
    deploy roletailor-api api.toml "$ENVIRONMENT.api.env" "$ROOT" "$ROOT/backend/Dockerfile"
    deploy roletailor-web web.toml "$ENVIRONMENT.web.env" "$ROOT/frontend" "$ROOT/frontend/Dockerfile"
    ;;
esac
echo "==> done"
