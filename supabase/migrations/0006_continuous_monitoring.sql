create table monitored_sources (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  url text not null,
  label text not null,
  interval_minutes int not null default 60 check (interval_minutes between 15 and 10080),
  status text not null default 'active' check (status in ('active','paused','error','removed')),
  last_checked_at timestamptz,
  next_check_at timestamptz not null default now(),
  lease_until timestamptz,
  failure_count int not null default 0,
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now()
);
create index monitored_sources_due_idx on monitored_sources(next_check_at) where status='active';
create index monitored_sources_workspace_idx on monitored_sources(workspace_id, created_at desc);

create table monitoring_snapshots (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  monitored_source_id uuid not null references monitored_sources(id) on delete cascade,
  version_no int not null check (version_no > 0),
  final_url text not null,
  fetched_at timestamptz not null default now(),
  content_hash text not null,
  extracted_text text not null,
  metadata jsonb not null default '{}',
  unique (monitored_source_id, version_no)
);
create index monitoring_snapshots_source_idx on monitoring_snapshots(monitored_source_id, version_no desc);
create index monitoring_snapshots_hash_idx on monitoring_snapshots(monitored_source_id, content_hash);

create table monitoring_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  monitored_source_id uuid not null references monitored_sources(id) on delete cascade,
  status text not null check (status in ('completed','unchanged','failed')),
  snapshot_id uuid references monitoring_snapshots(id),
  error_code text,
  started_at timestamptz not null,
  completed_at timestamptz not null default now()
);
create index monitoring_runs_source_idx on monitoring_runs(monitored_source_id, completed_at desc);

create table monitoring_changes (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  monitored_source_id uuid not null references monitored_sources(id) on delete cascade,
  previous_snapshot_id uuid not null references monitoring_snapshots(id),
  current_snapshot_id uuid not null references monitoring_snapshots(id),
  change_summary text not null,
  change_excerpt text not null default '',
  status text not null default 'open' check (status in ('open','reviewed','dismissed')),
  created_at timestamptz not null default now()
);
create index monitoring_changes_queue_idx on monitoring_changes(workspace_id, status, created_at desc);

create table monitoring_change_reviews (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  change_id uuid not null unique references monitoring_changes(id) on delete cascade,
  status text not null check (status in ('completed','completed_with_warnings','failed')),
  outcome text not null check (outcome in ('approved','rejected','on_hold')),
  risk_score smallint not null check (risk_score between 0 and 100),
  policy_version text not null,
  report jsonb not null,
  created_at timestamptz not null default now()
);
create index monitoring_change_reviews_workspace_idx on monitoring_change_reviews(workspace_id, created_at desc);
create trigger monitoring_change_reviews_immutable before update or delete on monitoring_change_reviews
  for each row execute function proofline_block_mutation();

create trigger monitoring_snapshots_immutable before update or delete on monitoring_snapshots
  for each row execute function proofline_block_mutation();
create trigger monitoring_runs_immutable before update or delete on monitoring_runs
  for each row execute function proofline_block_mutation();
do $$
begin
  if to_regrole('authenticated') is not null
     and to_regprocedure('public.is_workspace_member(uuid)') is not null then
    alter table monitored_sources enable row level security;
    alter table monitoring_snapshots enable row level security;
    alter table monitoring_runs enable row level security;
    alter table monitoring_changes enable row level security;
    alter table monitoring_change_reviews enable row level security;
    create policy monitored_sources_member_select on monitored_sources for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy monitoring_snapshots_member_select on monitoring_snapshots for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy monitoring_runs_member_select on monitoring_runs for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy monitoring_changes_member_select on monitoring_changes for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy monitoring_change_reviews_member_select on monitoring_change_reviews for select to authenticated
      using (public.is_workspace_member(workspace_id));
  end if;
end $$;
