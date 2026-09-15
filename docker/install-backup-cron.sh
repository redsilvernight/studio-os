#!/usr/bin/env bash
# Install a cron job that runs docker/backup.sh periodically.
#
# Usage: ./install-backup-cron.sh <backup_root_dir> [hour_of_day] [retention_count]
# Default: daily at 02:00, keep 7 backups.
set -euo pipefail
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT="${1:?usage: install-backup-cron.sh <backup_root_dir> [hour_of_day] [retention_count]}"
HOUR="${2:-2}"
RETENTION="${3:-7}"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup.sh"
CRON_LINE="0 ${HOUR} * * * ${BACKUP_SCRIPT} ${BACKUP_ROOT} ${RETENTION} >> ${BACKUP_ROOT}/backup.log 2>&1"

mkdir -p "$BACKUP_ROOT"

# Remove any pre-existing line for this backup script.
( crontab -l 2>/dev/null || true ) | grep -vF "$BACKUP_SCRIPT" | crontab -

# Append the new line.
( crontab -l 2>/dev/null || true ; echo "$CRON_LINE" ) | crontab -

echo "installed cron backup: ${CRON_LINE}"
