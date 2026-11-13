#!/usr/bin/env bash
# Restore a PostgreSQL custom-format dump.
#
# Usage: scripts/restore.sh <dump_file> [target_db]
#
# Restoring into a scratch database is the safe way to verify a backup:
#   scripts/restore.sh backups/fig_20261113_090000.dump fig_restore_test

set -euo pipefail

FILE="${1:?usage: restore.sh <dump_file> [target_db]}"
CONTAINER="${PG_CONTAINER:-fig-postgres}"
TARGET_DB="${2:-${POSTGRES_DB:-fig}}"
DB_USER="${POSTGRES_USER:-fig}"

if [[ ! -f "${FILE}" ]]; then
  echo "no such dump: ${FILE}" >&2
  exit 1
fi

echo "restoring ${FILE} into ${TARGET_DB} ..."

docker cp "${FILE}" "${CONTAINER}:/tmp/fig_restore.dump"

if [[ "${TARGET_DB}" != "${POSTGRES_DB:-fig}" ]]; then
  docker exec "${CONTAINER}" psql -U "${DB_USER}" -d postgres \
    -c "DROP DATABASE IF EXISTS ${TARGET_DB}" \
    -c "CREATE DATABASE ${TARGET_DB}"
fi

docker exec "${CONTAINER}" pg_restore -U "${DB_USER}" -d "${TARGET_DB}" \
  --clean --if-exists --no-owner /tmp/fig_restore.dump

docker exec "${CONTAINER}" rm -f /tmp/fig_restore.dump
echo "ok: restored into ${TARGET_DB}"
