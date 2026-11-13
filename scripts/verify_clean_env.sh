#!/usr/bin/env bash
# Clean-environment drill: stand up a brand-new PostgreSQL + Neo4j with empty
# volumes, build the schema from migrations only, and run the full verification
# against it. The working environment on ports 5432/7687 is never touched —
# a separate compose project name and separate ports are used.
#
# This is the closest local equivalent of "deploy on a clean machine". It does
# NOT cover the OS/runtime layer (see the review report, section 7).
#
# Usage: scripts/verify_clean_env.sh

set -euo pipefail

export MSYS_NO_PATHCONV=1

PROJECT="figcleanverify"
COMPOSE_FILE="deploy/docker-compose.yml"
COMPOSE_OVERRIDE="deploy/docker-compose.clean.yml"
PG_PORT=55432
NEO_PORT=57687
NEO_HTTP_PORT=57474
PASSWORD="fig_clean_env_pwd"
ENV_FILE=".env.cleanverify"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

cleanup() {
  echo
  echo "[cleanup] tearing down ${PROJECT} and removing its volumes"
  docker compose -p "${PROJECT}" -f "${COMPOSE_FILE}" -f "${COMPOSE_OVERRIDE}" --env-file "${ENV_FILE}" down -v >/dev/null 2>&1 || true
  rm -f "${ENV_FILE}"
}
trap cleanup EXIT

cat > "${ENV_FILE}" <<EOF
POSTGRES_DB=fig
POSTGRES_USER=fig
POSTGRES_PASSWORD=${PASSWORD}
POSTGRES_PORT=${PG_PORT}
NEO4J_PASSWORD=${PASSWORD}
NEO4J_HTTP_PORT=${NEO_HTTP_PORT}
NEO4J_BOLT_PORT=${NEO_PORT}
EOF

echo "[1/6] start a brand-new environment (project=${PROJECT}, pg=${PG_PORT}, neo4j=${NEO_PORT})"
docker compose -p "${PROJECT}" -f "${COMPOSE_FILE}" -f "${COMPOSE_OVERRIDE}" --env-file "${ENV_FILE}" up -d postgres neo4j >/dev/null

echo "[2/6] wait for both to report healthy"
for _ in $(seq 1 40); do
  pg=$(docker inspect -f '{{.State.Health.Status}}' figclean-postgres 2>/dev/null || echo unknown)
  neo=$(docker inspect -f '{{.State.Health.Status}}' figclean-neo4j 2>/dev/null || echo unknown)
  if [[ "${pg}" == "healthy" && "${neo}" == "healthy" ]]; then
    echo "      postgres=${pg} neo4j=${neo}"
    break
  fi
  sleep 3
done

# Point the application at the clean environment for every command below.
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT="${PG_PORT}"
export POSTGRES_DB=fig
export POSTGRES_USER=fig
export POSTGRES_PASSWORD="${PASSWORD}"
export DATABASE_URL="postgresql+asyncpg://fig:${PASSWORD}@127.0.0.1:${PG_PORT}/fig"
export NEO4J_URI="bolt://127.0.0.1:${NEO_PORT}"
export NEO4J_USER=neo4j
export NEO4J_PASSWORD="${PASSWORD}"

PY="backend/.venv/Scripts/python.exe"
[[ -x "${PY}" ]] || PY="backend/.venv/bin/python"

echo "[3/6] build the schema from migrations only (empty database)"
(cd backend && "../${PY}" -m alembic upgrade head)
(cd backend && "../${PY}" -m alembic check)

echo "[4/6] apply Neo4j constraints and indexes"
"${PY}" scripts/apply_neo4j_schema.py | tail -1

echo "[5/6] full test suite against the clean environment"
"${PY}" -m pytest -q

echo "[6/6] invariant checks against the clean environment"
"${PY}" scripts/verify_invariants.py | tail -3

echo
echo "clean-environment drill PASSED"
