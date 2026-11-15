#!/usr/bin/env bash
# Usage: scripts/backup.sh [out_dir]  → custom-format pg_dump of the compose DB.
set -euo pipefail
out_dir=${1:-backups}
mkdir -p "$out_dir"
file="$out_dir/pocketops-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$file"
chmod 600 "$file"
echo "$file"
