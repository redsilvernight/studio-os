#!/usr/bin/env bash
# Install a cron job that runs docker/backup.sh periodically.
#
# Usage: ./install-backup-cron.sh <backup_root_dir> [hour_of_day] [retention_count]
# Default: daily at 02:00, keep 7 backups.
set -euo pipefail
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

[[ $# -ge 1 && $# -le 3 ]] || fail 'usage: install-backup-cron.sh <backup_root_dir> [hour_of_day] [retention_count]'
BACKUP_ROOT="$1"
HOUR="${2:-2}"
RETENTION="${3:-7}"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup.sh"

[[ "$HOUR" =~ ^([01]?[0-9]|2[0-3])$ ]] || fail 'hour_of_day must be between 0 and 23'
[[ "$RETENTION" =~ ^[1-9][0-9]{0,17}$ ]] || fail 'retention_count must be a positive decimal integer of at most 18 digits'
HOUR="$((10#$HOUR))"

validate_path() {
  [[ -n "$1" && "$1" != *$'\n'* && "$1" != *$'\r'* && "$1" != *%* ]] ||
    fail 'cron paths must be nonempty and cannot contain %, CR or LF'
}

shell_quote() {
  local value="$1"
  value="${value//\'/\'\\\'\'}"
  printf "'%s'" "$value"
}

validate_path "$BACKUP_ROOT"
validate_path "$BACKUP_SCRIPT"
validate_path "$BASH"

if ! CURRENT_CRONTAB="$(LC_ALL=C crontab -l 2>&1)"; then
  [[ "$CURRENT_CRONTAB" == 'no crontab for '* ]] || fail "cannot read crontab: $CURRENT_CRONTAB"
  CURRENT_CRONTAB=''
fi

mkdir -p -- "$BACKUP_ROOT"
BACKUP_ROOT="$(cd -- "$BACKUP_ROOT" && pwd -P)"
validate_path "$BACKUP_ROOT"
MARKER="# studio-os-backup: $BACKUP_SCRIPT"
CRON_LINE="0 ${HOUR} * * * $(shell_quote "$BASH") -- $(shell_quote "$BACKUP_SCRIPT") $(shell_quote "$BACKUP_ROOT") $(shell_quote "$RETENTION") >> $(shell_quote "$BACKUP_ROOT/backup.log") 2>&1 $MARKER"

write_crontab() {
  local line legacy_command
  local legacy_schedule='^[[:space:]]*0[[:space:]]+[0-9]+[[:space:]]+\*[[:space:]]+\*[[:space:]]+\*[[:space:]]+'
  if [[ -n "$CURRENT_CRONTAB" ]]; then
    while IFS= read -r line; do
      if [[ ! "$line" =~ ^[[:space:]]*# ]]; then
        [[ "$line" != *" $MARKER" ]] || continue
        if [[ "$line" =~ $legacy_schedule ]]; then
          legacy_command="${line:${#BASH_REMATCH[0]}}"
          [[ "$legacy_command" != "$BACKUP_SCRIPT "* ]] || continue
        fi
      fi
      printf '%s\n' "$line"
    done <<< "$CURRENT_CRONTAB"
  fi
  printf '%s\n' "$CRON_LINE"
}

write_crontab | crontab -

echo "installed cron backup: ${CRON_LINE}"
