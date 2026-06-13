#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 /path/to/backup.dump" >&2
  exit 2
fi

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=product_knowledge}"
: "${PGUSER:=postgres}"

backup_file="$1"

pg_restore \
  --host "$PGHOST" \
  --port "$PGPORT" \
  --username "$PGUSER" \
  --dbname "$PGDATABASE" \
  --clean \
  --if-exists \
  "$backup_file"
