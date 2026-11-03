# Disposable development backup and restore check

This procedure is for a verified disposable development project only. The configured Supabase project reference `dbheroiyahorzwxexlaw` was confirmed by the user as disposable, and the running local backend reports database readiness. No database or private Storage backup has been verified. The ledger reports only 0001–0002, while all checked tables, indexes, triggers, and policies from 0003 exist; its columns and constraints still need verification before reconciling the ledger. Do not migrate or run database-backed tests until the database and Storage backup paths are available. Keep credentials in the local environment or a protected PostgreSQL password file; do not paste them into commands, tickets, or chat.

## PostgreSQL

1. Install PostgreSQL client tools (`pg_dump`, `pg_restore`, and `psql`) on Windows:

   - In Supabase Dashboard, open the intended project's **Connect** panel and note its PostgreSQL server major version from the project settings. Do not infer the target from the existing local environment.
   - Open the [official PostgreSQL Windows downloads page](https://www.postgresql.org/download/windows/) and choose the EDB installer for that server major version (or a newer client major version). In the component selection, include **Command Line Tools**. The installer is hosted by EDB, as described on the PostgreSQL downloads page.
   - In a new PowerShell window, add the installed `bin` directory to this window's PATH and verify all three tools. Replace `<major>` with the version installed:

     ```powershell
     $pgBin = "C:\Program Files\PostgreSQL\<major>\bin"
     $env:Path = "$pgBin;$env:Path"
     Get-Command pg_dump,pg_restore,psql
     pg_dump --version
     pg_restore --version
     psql --version
     ```

   - Keep the database password out of the command line and shell history. Create the default password-file directory and open the file:

     ```powershell
     New-Item -ItemType Directory -Force "$env:APPDATA\postgresql" | Out-Null
     notepad "$env:APPDATA\postgresql\pgpass.conf"
     ```

     In Notepad, add one line in this format, filling it from the dashboard connection details (never paste the real line into chat):

     ```text
     hostname:port:database:username:password
     ```

     Keep the file in your Windows user profile and do not sync it to source control. Alternatively, set `PGPASSFILE` to another protected file. Keep the connection URL in a process-local environment variable and omit its password so libpq can obtain the password from this file. PostgreSQL documents this Windows filename and field order in its [password-file documentation](https://www.postgresql.org/docs/current/libpq-pgpass.html).
   - Verify the environment still points to the approved disposable development project before running any dump or restore command. Never run restore against the source project.

   For Supabase-specific logical backups, install the Supabase CLI separately only if needed. The official CLI guide supports the npm route on Windows (Node.js 20 or later); run `npm install --save-dev supabase` only after choosing to update the project dependencies, then run `npx supabase --version`. Docker Desktop is required to start the local Supabase stack, not for ordinary `pg_dump` commands. Do not run `supabase link`, `db push`, or migration commands until the project identity and backup gates below are satisfied.
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

1. In Supabase Dashboard, open **Storage > Configuration > S3**, enable the S3 protocol, and generate an access key pair. Use those credentials only in a local S3 client configuration; never paste them into chat or a command. Alternatively, download individual files from **Storage > Files**. For bulk export, use an S3-compatible client such as AWS CLI, rclone, or Cyberduck with the endpoint and credentials displayed by the dashboard. Supabase's documentation notes that Storage object metadata is stored separately in the database, so both the database and objects must be included in a complete backup.
2. Download every object while preserving its full bucket-relative path. Keep a manifest of object path, size, content type, and checksum; do not include signed URLs or keys.
3. Store the export encrypted with the database archive and restrict access similarly.
4. Restore objects only to the separate disposable restore project/bucket. Compare object counts, paths, sizes, and checksums with the manifest, then verify a sample download through the authenticated application route.

The execution environment previously reported no `pg_dump`, `pg_restore`, Supabase CLI, or Storage export utility. No backup or restore has been verified. The configured database is now reachable from the user's local backend, but the backup prerequisite and 0003 schema reconciliation remain outstanding; do not begin migrations or database-backed tests until both are resolved.
