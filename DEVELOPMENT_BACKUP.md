# Disposable development backup and restore check

This procedure is for a verified disposable development project only. Do not point restore commands at production or at the currently configured project until its identity has been confirmed. Keep credentials in the local environment or a protected PostgreSQL password file; do not paste them into commands, tickets, or chat.

## PostgreSQL

1. Install PostgreSQL client tools (`pg_dump`, `pg_restore`, and `psql`) from the official PostgreSQL distribution for your platform.
2. Verify the Supabase project reference in the dashboard and choose a new, empty disposable restore database/project. Never use the source database as the restore target.
3. Configure `DATABASE_URL` for the verified development database in the local process environment. Provide its password through `%APPDATA%\postgresql\pgpass.conf` or another protected `PGPASSFILE`, not in shell history.
4. Create a custom-format archive and validate that the archive is readable:

   ```powershell
   pg_dump --format=custom --no-owner --file=proofline-development.dump --dbname=$env:DATABASE_URL
   pg_restore --list proofline-development.dump | Out-Null
   if ($LASTEXITCODE -ne 0) { throw 'Backup archive validation failed' }
   ```

5. Restore only to a newly created empty disposable restore target, configured locally as `PROOFLINE_RESTORE_URL`:

   ```powershell
   pg_restore --no-owner --exit-on-error --dbname=$env:PROOFLINE_RESTORE_URL proofline-development.dump
   if ($LASTEXITCODE -ne 0) { throw 'Restore check failed' }
   psql --dbname=$env:PROOFLINE_RESTORE_URL --set=ON_ERROR_STOP=1 --command="SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
   ```

6. Confirm expected tables and row counts with the project owner, then delete the disposable restore target using its provider dashboard after preserving any needed validation evidence.

Treat the archive as sensitive because it may contain user submissions and audit records. Store it encrypted with restricted access and a defined retention period. Record the project reference, archive timestamp, tool versions, and restore-check result without recording credentials.

## Supabase Storage objects

Database archives do not include objects in the private `submissions` bucket. Before a migration or other development change that may affect evidence storage:

1. Use the Supabase dashboard or an approved authenticated Storage export tool to enumerate the private bucket.
2. Download every object while preserving its full bucket-relative path. Keep a manifest of object path, size, content type, and checksum; do not include signed URLs or keys.
3. Store the export encrypted with the database archive and restrict access similarly.
4. Restore objects only to the separate disposable restore project/bucket. Compare object counts, paths, sizes, and checksums with the manifest, then verify a sample download through the authenticated application route.

The project environment does not currently include `pg_dump`, `pg_restore`, Supabase CLI, or a Storage export utility. No backup or restore was performed as part of implementation.
