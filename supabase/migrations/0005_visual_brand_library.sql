-- Workspace-scoped reference assets and versioned approved palettes.
create table brand_assets (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  family_id uuid not null default gen_random_uuid(),
  version_no int not null check (version_no > 0),
  name text not null,
  asset_type text not null check (asset_type in ('logo','reference_image')),
  category text not null default 'general',
  original_filename text not null,
  storage_path text not null,
  mime_type text not null check (mime_type in ('image/png','image/jpeg')),
  size_bytes bigint not null check (size_bytes > 0),
  content_hash text not null,
  approved boolean not null default false,
  approved_by uuid references app_users(id),
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now(),
  unique (family_id, version_no)
);
create index brand_assets_profile_idx on brand_assets(brand_profile_id, created_at desc);
create index brand_assets_workspace_idx on brand_assets(workspace_id);

create table brand_palette_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  version_no int not null check (version_no > 0),
  colors jsonb not null check (jsonb_typeof(colors) = 'array' and jsonb_array_length(colors) between 1 and 20),
  approved_by uuid not null references app_users(id),
  created_at timestamptz not null default now(),
  unique (brand_profile_id, version_no)
);
create index brand_palette_profile_idx on brand_palette_versions(brand_profile_id, version_no desc);

create table visual_analyses (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  submission_version_id uuid not null references submission_versions(id) on delete cascade,
  review_run_id uuid not null unique references review_runs(id) on delete cascade,
  status text not null check (status in ('completed','partial','unavailable','failed')),
  results jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index visual_analyses_workspace_idx on visual_analyses(workspace_id, created_at desc);

create trigger brand_assets_immutable before update or delete on brand_assets
  for each row execute function proofline_block_mutation();
create trigger brand_palette_versions_immutable before update or delete on brand_palette_versions
  for each row execute function proofline_block_mutation();
create trigger visual_analyses_immutable before update or delete on visual_analyses
  for each row execute function proofline_block_mutation();

do $$
begin
  if to_regrole('authenticated') is not null
     and to_regprocedure('public.is_workspace_member(uuid)') is not null then
    alter table brand_assets enable row level security;
    alter table brand_palette_versions enable row level security;
    alter table visual_analyses enable row level security;
    create policy brand_assets_member_select on brand_assets for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy brand_palette_member_select on brand_palette_versions for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy visual_analyses_member_select on visual_analyses for select to authenticated
      using (public.is_workspace_member(workspace_id));
  end if;
end $$;
