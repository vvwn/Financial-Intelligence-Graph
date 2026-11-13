#!/usr/bin/env bash
# Backup/restore drill: proves a dump can actually be restored.
#
# Strategy: dump the live database, restore it into a scratch database, compare
# row counts for the core tables, then drop the scratch database. The live
# database is never touched.

set -euo pipefail

CONTAINER="${PG_CONTAINER:-fig-postgres}"
DB="${POSTGRES_DB:-fig}"
DB_USER="${POSTGRES_USER:-fig}"
SCRATCH="fig_restore_verify_$(date +%s)"
OUT_DIR="${TMPDIR:-/tmp}/fig_backup_verify"
DUMP="${OUT_DIR}/fig_verify.dump"

CORE_TABLES=(entity evidence claim relationship relationship_history app_setting)

mkdir -p "${OUT_DIR}"
trap 'docker exec "${CONTAINER}" psql -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${SCRATCH}" >/dev/null 2>&1 || true; rm -rf "${OUT_DIR}"' EXIT

echo "[1/4] dump"
docker exec "${CONTAINER}" pg_dump -U "${DB_USER}" -d "${DB}" -Fc -f /tmp/fig_verify.dump
docker cp "${CONTAINER}:/tmp/fig_verify.dump" "${DUMP}"
docker exec "${CONTAINER}" rm -f /tmp/fig_verify.dump

echo "[2/4] restore into ${SCRATCH}"
docker exec "${CONTAINER}" psql -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${SCRATCH}" >/dev/null
docker cp "${DUMP}" "${CONTAINER}:/tmp/fig_verify.dump"
docker exec "${CONTAINER}" pg_restore -U "${DB_USER}" -d "${SCRATCH}" --no-owner /tmp/fig_verify.dump >/dev/null
docker exec "${CONTAINER}" rm -f /tmp/fig_verify.dump

echo "[3/4] compare row counts"
FAILED=0
for table in "${CORE_TABLES[@]}"; do
  src="$(docker exec "${CONTAINER}" psql -U "${DB_USER}" -d "${DB}" -tAc "SELECT count(*) FROM ${table}")"
  dst="$(docker exec "${CONTAINER}" psql -U "${DB_USER}" -d "${SCRATCH}" -tAc "SELECT count(*) FROM ${table}")"
  if [[ "${src}" == "${dst}" ]]; then
    echo "  ok   ${table}: ${src}"
  else
    echo "  FAIL ${table}: source=${src} restored=${dst}"
    FAILED=1
  fi
done

echo "[4/4] drop scratch database"
docker exec "${CONTAINER}" psql -U "${DB_USER}" -d postgres -c "DROP DATABASE ${SCRATCH}" >/dev/null

if [[ "${FAILED}" -ne 0 ]]; then
  echo "backup/restore drill FAILED"
  exit 1
fi

echo "backup/restore drill PASSED"
