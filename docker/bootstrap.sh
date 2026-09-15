#!/usr/bin/env bash
# Bootstrap a fresh Studio OS VPS deployment:
#   1. start Postgres and MinIO
#   2. run Alembic migrations
#   3. create the first admin user (interactive)
#   4. create the first admin machine (optional)
#
# Usage: ./bootstrap.sh [--create-machine NAME]
set -euo pipefail
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# shellcheck disable=SC1091
set -a; source ./.env; set +a

CREATE_MACHINE_NAME=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --create-machine)
      CREATE_MACHINE_NAME="${2:?--create-machine requires a value}"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

echo "[bootstrap] starting infrastructure services..."
docker compose up -d postgres minio minio-init

echo "[bootstrap] waiting for postgres..."
until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
  sleep 1
done

echo "[bootstrap] running alembic upgrade head..."
docker compose run --rm api alembic upgrade head

echo ""
echo "[bootstrap] create the first admin user:"
read -rp "Display name: " ADMIN_NAME
read -rp "Email: " ADMIN_EMAIL

read -rsp "Dashboard password (empty = no dashboard auth yet): " ADMIN_PASSWORD
echo ""

echo "[bootstrap] creating admin user..."
if [[ -n "$ADMIN_PASSWORD" ]]; then
  docker compose run --rm api python -m studio_api.admin_cli bootstrap-admin \
    --display-name "$ADMIN_NAME" --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD"
else
  docker compose run --rm api python -m studio_api.admin_cli bootstrap-admin \
    --display-name "$ADMIN_NAME" --email "$ADMIN_EMAIL"
fi

if [[ -n "$CREATE_MACHINE_NAME" ]]; then
  echo "[bootstrap] creating first admin machine..."
  docker compose run --rm api python -m studio_api.admin_cli machine create \
    --owner-email "$ADMIN_EMAIL" --display-name "$CREATE_MACHINE_NAME"
fi

echo "[bootstrap] done. You can now start the API/MCP/dashboard with: docker compose up -d"
