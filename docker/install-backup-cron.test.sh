#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMP_BASE="$(cd "${TMPDIR:-/tmp}" && pwd -P)"
TEST_DIR="$(mktemp -d "$TEMP_BASE/studio-backup-cron.XXXXXX")"
cleanup() {
  [[ "$TEST_DIR" == "$TEMP_BASE"/studio-backup-cron.* ]] && rm -rf -- "$TEST_DIR"
}
trap cleanup EXIT

INSTALL_DIR="$TEST_DIR/Studio's checkout"
mkdir -p "$TEST_DIR/bin" "$INSTALL_DIR"
cp "${INSTALLER_UNDER_TEST:-$SCRIPT_DIR/install-backup-cron.sh}" "$INSTALL_DIR/install-backup-cron.sh"
export MOCK_CRON="$TEST_DIR/crontab" MOCK_CALLS="$TEST_DIR/calls" MOCK_ARGS="$TEST_DIR/args"
export PATH="$TEST_DIR/bin:$PATH"

cat > "$TEST_DIR/bin/crontab" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$1" >> "$MOCK_CALLS"
case "$1" in
  -l)
    if [[ "${MOCK_LIST_FAILURE:-0}" == 1 ]]; then
      printf 'crontab: permission denied\n' >&2
      exit 1
    fi
    if [[ ! -f "$MOCK_CRON" ]]; then
      printf 'no crontab for test-user\n' >&2
      exit 1
    fi
    cat "$MOCK_CRON"
    ;;
  -)
    if [[ "${MOCK_WRITE_FAILURE:-0}" == 1 ]]; then
      cat > /dev/null
      printf 'crontab: installation refused\n' >&2
      exit 1
    fi
    cat > "$MOCK_CRON.new"
    mv -- "$MOCK_CRON.new" "$MOCK_CRON"
    ;;
  *) exit 2 ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/crontab"

cat > "$INSTALL_DIR/backup.sh" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$MOCK_ARGS"
printf 'backup stub ran\n'
MOCK
chmod 644 "$INSTALL_DIR/backup.sh"

passed=0
pass() {
  passed=$((passed + 1))
  printf 'PASS: %s\n' "$1"
}
fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}
reset_crontab() {
  printf '15 4 * * * /usr/bin/true\n' > "$MOCK_CRON"
  : > "$MOCK_CALLS"
}
assert_unchanged() {
  [[ "$(cat "$MOCK_CRON")" == '15 4 * * * /usr/bin/true' ]] || fail 'unrelated crontab changed'
  [[ ! -s "$MOCK_CALLS" ]] || fail 'invalid input accessed crontab'
}
expect_rejected() {
  reset_crontab
  if bash "$INSTALL_DIR/install-backup-cron.sh" "$@" > "$TEST_DIR/result" 2>&1; then
    fail "accepted invalid arguments: $*"
  fi
  assert_unchanged
  pass 'invalid arguments rejected before crontab access'
}

BACKUP_ROOT="$TEST_DIR/backups' ; touch SENTINEL ; #"
cd "$TEST_DIR"
bash "$INSTALL_DIR/install-backup-cron.sh" "$BACKUP_ROOT" > "$TEST_DIR/result"
[[ "$(cat "$MOCK_CALLS")" == $'-l\n-' ]] || fail 'installation must read once and write once'
[[ "$(cat "$MOCK_CRON")" == '0 2 * * * '* ]] || fail 'default schedule differs'
command_line="$(sed 's/^0 2 \* \* \* //' "$MOCK_CRON")"
/bin/sh -c "$command_line"
[[ "$(cat "$MOCK_ARGS")" == "$BACKUP_ROOT"$'\n7' ]] || fail 'backup arguments were not preserved'
[[ ! -e SENTINEL ]] || fail 'path contents executed as shell code'
[[ "$(cat "$BACKUP_ROOT/backup.log")" == 'backup stub ran' ]] || fail 'backup output was not redirected'
pass 'scheduled command executes a nonexecutable backup script with quoted paths'

legacy="0 2 * * * $INSTALL_DIR/backup.sh /old/backups 7 >> /old/backups/backup.log 2>&1"
unrelated="20 5 * * * echo '$INSTALL_DIR/backup.sh'"
reference="# documentation: $INSTALL_DIR/backup.sh"
printf '%s\n' 'MAILTO=ops@example.test' '15 4 * * * /usr/bin/true' "$legacy" "$unrelated" "$reference" > "$MOCK_CRON"
: > "$MOCK_CALLS"
bash "$INSTALL_DIR/install-backup-cron.sh" "$BACKUP_ROOT" 03 12 > "$TEST_DIR/result"
bash "$INSTALL_DIR/install-backup-cron.sh" "$BACKUP_ROOT" 4 9 > "$TEST_DIR/result"
[[ "$(cat "$MOCK_CALLS")" == $'-l\n-\n-l\n-' ]] || fail 'reinstallation performs extra crontab writes'
[[ "$(grep -cF '# studio-os-backup: ' "$MOCK_CRON")" == 1 ]] || fail 'duplicate managed cron job'
grep -qxF 'MAILTO=ops@example.test' "$MOCK_CRON"
grep -qxF '15 4 * * * /usr/bin/true' "$MOCK_CRON"
grep -qxF "$unrelated" "$MOCK_CRON"
grep -qxF "$reference" "$MOCK_CRON"
if grep -qxF "$legacy" "$MOCK_CRON"; then fail 'legacy job was not replaced'; fi
command_line="$(sed -n 's/^0 4 \* \* \* //p' "$MOCK_CRON")"
/bin/sh -c "$command_line"
[[ "$(cat "$MOCK_ARGS")" == "$BACKUP_ROOT"$'\n9' ]] || fail 'updated retention was not scheduled'
pass 'reinstallation migrates legacy jobs and preserves unrelated entries'

for hour in 0 00 09 23; do
  reset_crontab
  bash "$INSTALL_DIR/install-backup-cron.sh" "$BACKUP_ROOT" "$hour" > "$TEST_DIR/result"
  grep -q "^0 $((10#$hour)) \* \* \* " "$MOCK_CRON"
done
pass 'hour boundaries and leading zero are accepted'

for hour in 24 -1 abc '2; touch SENTINEL' $'2\n* * * * * bad'; do
  expect_rejected "$BACKUP_ROOT" "$hour"
done
for retention in 0 -1 abc 01 9999999999999999999 '7; touch SENTINEL'; do
  expect_rejected "$BACKUP_ROOT" 2 "$retention"
done
expect_rejected
expect_rejected ''
expect_rejected "$BACKUP_ROOT" 2 7 extra
expect_rejected "$TEST_DIR/backup%path"
expect_rejected "$TEST_DIR/backup"$'\nline'
expect_rejected "$TEST_DIR/backup"$'\rline'

reset_crontab
export MOCK_LIST_FAILURE=1
if bash "$INSTALL_DIR/install-backup-cron.sh" "$BACKUP_ROOT" > "$TEST_DIR/result" 2>&1; then
  fail 'crontab read error was ignored'
fi
unset MOCK_LIST_FAILURE
[[ "$(cat "$MOCK_CALLS")" == '-l' ]] || fail 'read error caused a write'
[[ "$(cat "$MOCK_CRON")" == '15 4 * * * /usr/bin/true' ]] || fail 'read error replaced crontab'
pass 'read error leaves crontab intact'

reset_crontab
export MOCK_WRITE_FAILURE=1
if bash "$INSTALL_DIR/install-backup-cron.sh" "$BACKUP_ROOT" > "$TEST_DIR/result" 2>&1; then
  fail 'crontab write error was ignored'
fi
unset MOCK_WRITE_FAILURE
[[ "$(cat "$MOCK_CALLS")" == $'-l\n-' ]] || fail 'write error retried installation'
[[ "$(cat "$MOCK_CRON")" == '15 4 * * * /usr/bin/true' ]] || fail 'failed install first removed existing jobs'
pass 'installation failure does not clear existing jobs'

printf 'PASS: %s backup cron scenarios\n' "$passed"
