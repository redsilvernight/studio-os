#!/usr/bin/env bash
# Backup Postgres (pg_dump, custom format) and MinIO (mc mirror) for the
# docker-compose stack in this directory. Run from a VPS cron job; not an
# in-process scheduler (same rationale as roadmap step 4.3, DEC-0020).
#
# Usage: ./backup.sh <backup_root_dir> [retention_count]
set -euo pipefail
export MSYS_NO_PATHCONV=1  # no-op outside Git Bash/MSYS; prevents path mangling of /backup, /bin/sh there

BACKUP_ROOT="${1:?usage: backup.sh <backup_root_dir> [retention_count]}"
RETENTION="${2:-7}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# shellcheck disable=SC1091
set -a; source ./.env; set +a

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_ROOT}/${TIMESTAMP}"
mkdir -p "${DEST}/postgres" "${DEST}/minio"

docker compose exec -T postgres pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --format=custom \
  > "${DEST}/postgres/studio.dump"

docker compose run --rm --no-deps -T \
  -v "${DEST}/minio:/backup" \
  --entrypoint /bin/sh \
  minio -c "
    mc alias set local http://minio:9000 '${MINIO_ROOT_USER}' '${MINIO_ROOT_PASSWORD}' >/dev/null &&
    mc mirror --overwrite local/${MINIO_BUCKET} /backup
  "

echo "backup complete: ${DEST}"

find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d | sort -r | tail -n "+$((RETENTION + 1))" | while IFS= read -r old; do
  rm -rf "${old}"
  echo "pruned old backup: ${old}"
done
