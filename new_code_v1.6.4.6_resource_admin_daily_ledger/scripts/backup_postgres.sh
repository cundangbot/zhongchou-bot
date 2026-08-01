#!/bin/sh
set -eu
mkdir -p backups
STAMP=$(date +%Y%m%d_%H%M%S)
FILE="backups/crowdfund_${STAMP}.sql.gz"
URL="${DATABASE_URL_SYNC:-${DATABASE_URL:-}}"
if [ -z "$URL" ]; then
  echo "DATABASE_URL is not configured" >&2
  exit 1
fi
URL=$(printf '%s' "$URL" | sed 's#postgresql+asyncpg://#postgresql://#; s#postgresql+psycopg://#postgresql://#')
pg_dump "$URL" | gzip > "$FILE"
echo "$(date -Iseconds) $FILE" > backups/last_backup.txt
find backups -type f -name 'crowdfund_*.sql.gz' -mtime +30 -delete
printf 'backup: %s\n' "$FILE"
