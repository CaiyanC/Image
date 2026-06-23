# Windows PostgreSQL backup

## Scope

This project runs PostgreSQL locally on Windows in the current deployment. The Linux scripts in `deploy/scripts/*.sh` remain available for Linux servers, but the current Windows host uses the PowerShell scripts below.

## Backup

Script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\scripts\backup_postgres.ps1
```

Defaults:

- Reads database connection from `backend\.env` `DATABASE_URL`.
- Writes custom-format PostgreSQL dumps to `backups\postgres`.
- Retains the latest 14 days by deleting older `*.dump` files.
- Does not write database passwords to logs.

## Scheduled task

Task name: `CaiYanPostgresBackup`

Action:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\CaiYan\Image-Generation-feature-v5\deploy\scripts\backup_postgres.ps1
```

Schedule: daily at 03:00.

Validation performed on 2026-06-20:

- Manual task trigger succeeded.
- `LastTaskResult`: `0`.
- Latest task-created backup: `D:\CaiYan\Image-Generation-feature-v5\backups\postgres\product_knowledge_20260620_182400.dump`.
- Next scheduled run: `2026-06-21 03:00:00`.
- The task is registered under the Windows `SYSTEM` account, so it does not depend on the current user staying logged in.

## Restore drill performed on 2026-06-20

Source database: `product_knowledge`.

Backup file:

```text
D:\CaiYan\Image-Generation-feature-v5\backups\postgres\product_knowledge_20260620_181840.dump
```

Result:

- Backup size: 10,499,327 bytes.
- `pg_restore --list` recognized the archive as PostgreSQL custom format with 242 TOC entries.
- Restored into test database `product_knowledge_restore_check_20260620`.
- Verified 42 public tables.
- Row counts in restored database matched the source database table by table.
- The PowerShell backup script was also verified with `product_knowledge_20260620_182059.dump`, restored into `product_knowledge_restore_script_check_20260620`, with 42 table row counts matching.
- Retention was verified by creating an expired test dump with `LastWriteTime` 30 days old. Running the backup script deleted it as expected.

Validation outputs:

- `reports\backup_prod_counts_20260620.csv`
- `reports\backup_restore_counts_20260620.csv`

## Restore command

Create the target database first, then restore:

```powershell
createdb --host localhost --port 5432 --username postgres product_knowledge_restore_check
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\scripts\restore_postgres.ps1 -BackupFile .\backups\postgres\product_knowledge_YYYYMMDD_HHMMSS.dump -TargetDatabase product_knowledge_restore_check
```

For production recovery, stop the application first, restore to a new database or a confirmed empty target, then point `DATABASE_URL` to the restored database after validation.
