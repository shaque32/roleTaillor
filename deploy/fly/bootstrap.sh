#!/usr/bin/env bash
# One-time (re-runnable) Fly.io setup for one environment. Run by the operator after `fly auth login`.
#   deploy/fly/bootstrap.sh <staging|prod> [region]
# Secrets are never printed. Blank answers to prompts skip that secret.
set -euo pipefail

usage() { echo "usage: $0 <staging|prod> [region]" >&2; exit 2; }
[[ $# -ge 1 && $# -le 2 ]] || usage
ENVIRONMENT="$1"
REGION="${2:-iad}"
case "$ENVIRONMENT" in staging) SUFFIX="-staging" ;; prod) SUFFIX="" ;; *) usage ;; esac
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
API="roletailor-api$SUFFIX"; WEB="roletailor-web$SUFFIX"; REDIS="roletailor-redis$SUFFIX"
BUCKET="$(sed -n 's/^RT_S3_BUCKET=//p' "$ROOT/deploy/fly/env/$ENVIRONMENT.api.env")"
[[ -n "$BUCKET" ]] || { echo "RT_S3_BUCKET missing in env/$ENVIRONMENT.api.env" >&2; exit 1; }

command -v flyctl >/dev/null 2>&1 || { echo "flyctl not found" >&2; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "openssl not found" >&2; exit 1; }

step() { printf '\n==> %s\n' "$*"; }

app_exists() { flyctl status --app "$1" >/dev/null 2>&1; }

step "1/7 Create apps"
for app in "$API" "$WEB" "$REDIS"; do
  if app_exists "$app"; then echo "exists: $app"; else flyctl apps create "$app"; fi
done

step "2/7 Redis volume (redis_data, 1 GB, $REGION)"
if flyctl volumes list --app "$REDIS" 2>/dev/null | grep -q redis_data; then
  echo "volume redis_data already exists"
else
  flyctl volumes create redis_data --size 1 --region "$REGION" --app "$REDIS" --yes
fi

step "3/7 Redis password -> redis app (REDIS_PASSWORD) and api app (RT_REDIS_URL)"
if flyctl secrets list --app "$API" 2>/dev/null | grep -q 'RT_REDIS_URL'; then
  echo "RT_REDIS_URL already set on $API; leaving the existing Redis password in place"
else
  # hex avoids URL-escaping problems in the redis:// URL
  REDIS_PASSWORD="$(openssl rand -hex 24)"
  # --stage stores the secret without triggering a deploy
  printf 'REDIS_PASSWORD=%s\n' "$REDIS_PASSWORD" | flyctl secrets import --stage --app "$REDIS"
  printf 'RT_REDIS_URL=redis://default:%s@%s.internal:6379/0\n' "$REDIS_PASSWORD" "$REDIS" \
    | flyctl secrets import --stage --app "$API"
  unset REDIS_PASSWORD
fi

step "4/7 Tigris bucket '$BUCKET' attached to $API"
# Sets AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL_S3, BUCKET_NAME (and AWS_REGION) as secrets on the app.
# Bucket name must equal RT_S3_BUCKET in env/$ENVIRONMENT.api.env.
if flyctl secrets list --app "$API" 2>/dev/null | grep -q 'BUCKET_NAME'; then
  echo "Tigris already attached to $API"
else
  flyctl storage create --name "$BUCKET" --app "$API" --yes
fi
echo "NOTE: RT_S3_BUCKET in env/$ENVIRONMENT.api.env must equal '$BUCKET' (it is passed on deploy)."
echo "NOTE: Tigris buckets have no versioning; the app tolerates a missing VersionId."

step "5/7 PostgreSQL (Fly Managed Postgres) - manual"
cat <<MSG
Create the cluster (adjust plan/region/size):
  flyctl mpg create --name roletailor-db$SUFFIX --region $REGION --plan Basic --pg-major-version 16 --volume-size 10
Attach it / fetch the admin connection string:
  flyctl mpg attach roletailor-db$SUFFIX --app $API   # verify the exact subcommand with 'flyctl mpg --help'
Then, as the cluster admin, create the roles and extension:
  psql "\$ADMIN_URL" -v owner_password=... -v app_password=... -f $ROOT/db/bootstrap/managed_roles.sql
Finally set (use "flyctl secrets set --stage --app $API ..."):
  RT_DATABASE_URL            postgresql+psycopg://rt_app:<pw>@<POOLED host>/<db>      (pooled, rt_app)
  RT_MIGRATION_DATABASE_URL  postgresql://rt_owner:<pw>@<DIRECT host>/<db>            (direct, rt_owner; NOT a transaction-mode pooler)
MSG

step "6/7 RT_SECRET_KEY"
if flyctl secrets list --app "$API" 2>/dev/null | grep -q 'RT_SECRET_KEY'; then
  echo "RT_SECRET_KEY already set"
else
  printf 'RT_SECRET_KEY=%s\n' "$(openssl rand -hex 32)" | flyctl secrets import --stage --app "$API"
fi

# Lets the API believe the browser address the web app relays (per-visitor rate limits).
# Both apps must hold the same value, so a half-set pair is regenerated on both.
has_api_proxy=0; has_web_proxy=0
flyctl secrets list --app "$API" 2>/dev/null | grep -q 'RT_PROXY_SHARED_SECRET' && has_api_proxy=1
flyctl secrets list --app "$WEB" 2>/dev/null | grep -q 'API_PROXY_SECRET' && has_web_proxy=1
if [[ $has_api_proxy -eq 1 && $has_web_proxy -eq 1 ]]; then
  echo "RT_PROXY_SHARED_SECRET and API_PROXY_SECRET already set (to rotate: set both to one new value)"
else
  if [[ $has_api_proxy -ne $has_web_proxy ]]; then
    echo "proxy secret is set on only one of $API and $WEB; staging a new value on both"
  fi
  PROXY_SECRET="$(openssl rand -hex 32)"
  printf 'RT_PROXY_SHARED_SECRET=%s\n' "$PROXY_SECRET" | flyctl secrets import --stage --app "$API"
  if ! printf 'API_PROXY_SECRET=%s\n' "$PROXY_SECRET" | flyctl secrets import --stage --app "$WEB"; then
    PROXY_SECRET=""
    # Never leave the two apps holding different values: a later run could not tell.
    flyctl secrets unset --stage --app "$API" RT_PROXY_SHARED_SECRET || true
    flyctl secrets unset --stage --app "$WEB" API_PROXY_SECRET || true
    echo "ERROR: could not set API_PROXY_SECRET on $WEB, so removing the proxy secret from both apps was attempted." >&2
    echo "Fix access to $WEB and run this script again. If the removal above also failed, first run:" >&2
    echo "  flyctl secrets unset --stage --app $API RT_PROXY_SHARED_SECRET" >&2
    echo "  flyctl secrets unset --stage --app $WEB API_PROXY_SECRET" >&2
    exit 1
  fi
  PROXY_SECRET=""
fi

step "7/7 Provider and billing secrets (blank = skip; input hidden)"
for name in ANTHROPIC_API_KEY DEEPSEEK_API_KEY RESEND_API_KEY RT_STRIPE_SECRET_KEY RT_STRIPE_WEBHOOK_SECRET RT_STRIPE_SUBSCRIPTION_PRICE_ID; do
  read -r -s -p "$name: " value || value=""
  echo
  if [[ -n "$value" ]]; then
    printf '%s=%s\n' "$name" "$value" | flyctl secrets import --stage --app "$API"
  else
    echo "skipped $name"
  fi
  value=""
done

cat <<MSG

Done. Secrets are staged (applied at the next deploy). Next:
  1. Complete the Postgres step above (RT_DATABASE_URL / RT_MIGRATION_DATABASE_URL).
  2. deploy/fly/deploy.sh $ENVIRONMENT redis     # first deploy of Redis
  3. deploy/fly/deploy.sh $ENVIRONMENT all       # api (runs migrations) then web
  4. Point DNS at the apps (flyctl certs add <host> --app <app>) and update env/*.env placeholder domains.
  5. Stripe webhook endpoint: https://<api host>/v1/billing/webhook
MSG
