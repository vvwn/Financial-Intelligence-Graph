#!/usr/bin/env bash
# Backup PostgreSQL to a custom-format dump.
#
# Neo4j is NOT backed up on purpose: it is a derived projection (ADR-0001).
# Rebuilding it from PostgreSQL is cheaper and safer than restoring a dump of
# something that can drift. See docs/deployment.md.
#
# Usage: scripts/backup.sh [output_dir]

set -euo pipefail

CONTAINER="${PG_CONTAINER:-fig-postgres}"
DB="${POSTGRES_DB:-fig}"
DB_USER="${POSTGRES_USER:-fig}"
OUT_DIR="${1:-backups}"
TS="$(date +%Y%m%d_%H%M%S)"
FILE="${OUT_DIR}/fig_${TS}.dump"

mkdir -p "${OUT_DIR}"

echo "dumping ${DB} from ${CONTAINER} ..."
docker exec "${CONTAINER}" pg_dump -U "${DB_USER}" -d "${DB}" -Fc -f /tmp/fig_backup.dump
docker cp "${CONTAINER}:/tmp/fig_backup.dump" "${FILE}"
docker exec "${CONTAINER}" rm -f /tmp/fig_backup.dump

SIZE="$(du -h "${FILE}" | cut -f1)"
echo "ok: ${FILE} (${SIZE})"
