#!/usr/bin/env bash
# A27: backup → restore into a separate DB → verify counts and invariants match the live DB.
set -euo pipefail
dump=$(scripts/backup.sh "${1:-backups}")
scripts/restore.sh "$dump" pocketops_restore
q="SELECT 'units', count(*) FROM organization_unit UNION ALL SELECT 'users', count(*) FROM accounts_user
 UNION ALL SELECT 'records', count(*) FROM records_workrecord UNION ALL SELECT 'done', count(*) FROM records_workrecord WHERE status='DONE'
 UNION ALL SELECT 'results', count(*) FROM records_resultreference UNION ALL SELECT 'audit', count(*) FROM audit_auditevent
 UNION ALL SELECT 'notifications', count(*) FROM notifications_notification ORDER BY 1"
live=$(docker compose exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -AtF= -c \"$q\"")
restored=$(docker compose exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d pocketops_restore -AtF= -c \"$q\"")
echo "live:     $(echo $live)"; echo "restored: $(echo $restored)"
[ "$live" = "$restored" ] || { echo "RESTORE DRILL FAIL: counts differ"; exit 1; }
# Restored DB must still enforce append-only audit.
if docker compose exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d pocketops_restore -v ON_ERROR_STOP=1 -c 'DELETE FROM audit_auditevent'" >/dev/null 2>&1; then
  echo "RESTORE DRILL FAIL: audit trigger missing after restore"; exit 1
fi
echo "RESTORE DRILL PASS ($dump)"
