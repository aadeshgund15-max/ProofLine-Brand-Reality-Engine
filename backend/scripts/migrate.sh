#!/usr/bin/env bash
# Applies SQL migrations in order, once each (tracked in schema_migrations).
# Usage: DATABASE_URL=postgresql://... ./scripts/migrate.sh [--supabase]
# --supabase also applies 0002_rls_supabase.sql (needs the Supabase `auth` and `storage` schemas).
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
DIR="$(cd "$(dirname "$0")/../../supabase/migrations" && pwd)"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -c "create table if not exists schema_migrations (name text primary key, applied_at timestamptz not null default now())"
for f in "$DIR"/*.sql; do
  name="$(basename "$f")"
  if [[ "$name" == 0002_rls_supabase.sql && "${1:-}" != "--supabase" ]]; then echo "skip $name (plain Postgres)"; continue; fi
  if [[ "$(psql "$DATABASE_URL" -Atq -c "select 1 from schema_migrations where name='$name'")" == "1" ]]; then echo "already applied $name"; continue; fi
  echo "applying $name"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q --single-transaction -f "$f" -c "insert into schema_migrations(name) values ('$name')"
done
