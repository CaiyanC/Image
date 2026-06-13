#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=product_knowledge}"
: "${PGUSER:=postgres}"
: "${BACKUP_DIR:=/var/backups/caiyan}"
: "${RETENTION_DAYS:=14}"

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
target="$BACKUP_DIR/${PGDATABASE}_${timestamp}.dump"

pg_dump \
  --host "$PGHOST" \
  --port "$PGPORT" \
  --username "$PGUSER" \
  --format custom \
  --file "$target" \
  "$PGDATABASE"

find "$BACKUP_DIR" -type f -name "${PGDATABASE}_*.dump" -mtime +"$RETENTION_DAYS" -delete

echo "$target"
