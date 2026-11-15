#!/usr/bin/env bash
# Usage: scripts/restore.sh <dump> [target_db]
# Restores into target_db (default: pocketops_restore) so the live DB is never overwritten by accident.
# To replace the live DB: stop web/scheduler, restore into POSTGRES_DB explicitly, start again.
set -euo pipefail
dump=${1:?dump file required}
target=${2:-pocketops_restore}
docker compose exec -T db sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists --force '$target' && createdb -U \"\$POSTGRES_USER\" '$target'"
docker compose exec -T db sh -c "pg_restore -U \"\$POSTGRES_USER\" -d '$target' --no-owner --exit-on-error" < "$dump"
echo "restored into $target"
