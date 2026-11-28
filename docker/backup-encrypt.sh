#!/usr/bin/env bash
# Chiffre chaque sauvegarde datee en clair (dump Postgres + miroir MinIO) avec age,
# puis supprime le clair. Cle publique seulement ; la cle privee reste hors du VPS.
# KEEP_PLAINTEXT=1 : chiffre sans supprimer (verification avant bascule).
#
# Usage: ./backup-encrypt.sh <backup_root_dir>
set -euo pipefail
ROOT="${1:?usage: backup-encrypt.sh <backup_root_dir>}"
RECIP="$(cat "${AGE_PUBKEY_FILE:-$HOME/studio-backup.age.pub}")"
for d in "$ROOT"/[0-9]*T*Z; do
  [ -f "$d/postgres/studio.dump" ] || continue
  age -r "$RECIP" -o "$d/postgres/studio.dump.age" "$d/postgres/studio.dump"
  tar -C "$d" -cf - minio | age -r "$RECIP" -o "$d/minio.tar.age"
  test -s "$d/postgres/studio.dump.age"
  test -s "$d/minio.tar.age"
  if [ "${KEEP_PLAINTEXT:-0}" != 1 ]; then rm -rf "$d/postgres/studio.dump" "$d/minio"; fi
  echo "encrypted: $d"
done
