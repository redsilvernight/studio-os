#!/usr/bin/env bash
# Disaster-recovery restore for the docker-compose stack in this directory.
# Restores a backup produced by backup.sh into a FRESH, EMPTY postgres/minio
# pair (no schema migration step needed: the pg_dump already carries the
# full schema, including alembic_version, as of backup time).
#
# Usage: ./restore.sh <backup_dir>
# Expects: docker compose up -d postgres minio minio-init already ran once
# against a brand-new (empty) ./.data/{postgres,minio}, and services api/mcp
# are NOT yet started.
set -euo pipefail
export MSYS_NO_PATHCONV=1  # no-op outside Git Bash/MSYS; prevents path mangling of /backup, /bin/sh there

BACKUP_DIR="${1:?usage: restore.sh <backup_dir>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# shellcheck disable=SC1091
set -a; source ./.env; set +a

[ -f "${BACKUP_DIR}/postgres/studio.dump" ] || { echo "missing ${BACKUP_DIR}/postgres/studio.dump" >&2; exit 1; }

docker compose exec -T postgres pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --clean --if-exists --no-owner \
  < "${BACKUP_DIR}/postgres/studio.dump"

docker compose run --rm --no-deps -T \
  -v "${BACKUP_DIR}/minio:/backup" \
  --entrypoint /bin/sh \
  minio -c "
    mc alias set local http://minio:9000 '${MINIO_ROOT_USER}' '${MINIO_ROOT_PASSWORD}' >/dev/null &&
    mc mb --ignore-existing local/${MINIO_BUCKET} &&
    mc mirror --overwrite /backup local/${MINIO_BUCKET}
  "

echo "restore complete from: ${BACKUP_DIR}"
