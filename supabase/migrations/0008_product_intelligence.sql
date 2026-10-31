-- Versioned product identity and auditable background research records.
create table products (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  product_name text not null,
  brand text,
  manufacturer text,
  model_number text,
  product_category text,
  market text,
  official_website text,
  identity_status text not null default 'ambiguous' check (identity_status in ('confirmed','ambiguous')),
  identity_confirmed_by uuid references app_users(id),
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index products_workspace_idx on products(workspace_id, updated_at desc);

create table product_research_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  status text not null check (status in ('queued','running','completed','partial','failed')),
  lease_until timestamptz,
  query_count int not null default 0,
  result_count int not null default 0,
  unique_source_count int not null default 0,
  inspected_source_count int not null default 0,
  inaccessible_source_count int not null default 0,
  profile jsonb not null default '{}',
  coverage jsonb not null default '{}',
  error_summary text,
  requested_by uuid not null references app_users(id),
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);
create index product_research_runs_product_idx on product_research_runs(product_id, created_at desc);
create index product_research_runs_queue_idx on product_research_runs(status, created_at) where status='queued';

create table product_research_queries (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  research_run_id uuid not null references product_research_runs(id) on delete cascade,
  category text not null,
  query_text text not null,
  status text not null check (status in ('completed','failed')),
  result_count int not null default 0,
  error_code text,
  executed_at timestamptz not null default now()
);
create index product_research_queries_run_idx on product_research_queries(research_run_id, executed_at);

create table product_research_sources (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  research_run_id uuid not null references product_research_runs(id) on delete cascade,
  title text not null,
  url text not null,
  domain text not null,
  source_category text not null,
  publisher text,
  published_at timestamptz,
  retrieved_at timestamptz not null default now(),
  access_status text not null check (access_status in ('ok','unreachable','blocked')),
  extraction_status text not null,
  extracted_text text not null default '',
  content_hash text not null,
  duplicate_of uuid references product_research_sources(id),
  cached_from uuid references product_research_sources(id),
  product_match_status text not null default 'unassessed' check (product_match_status in ('unassessed','matched_by_identifier','ambiguous')),
  created_at timestamptz not null default now(),
  unique (research_run_id, url)
);
create index product_research_sources_product_idx on product_research_sources(product_id, retrieved_at desc);
create index product_research_sources_run_idx on product_research_sources(research_run_id, source_category);
alter table source_records add column product_research_source_id uuid references product_research_sources(id);
create index source_records_product_source_idx on source_records(product_research_source_id) where product_research_source_id is not null;

create table product_research_query_sources (
  workspace_id uuid not null references workspaces(id) on delete cascade,
  research_run_id uuid not null references product_research_runs(id) on delete cascade,
  query_id uuid not null references product_research_queries(id) on delete cascade,
  source_id uuid not null references product_research_sources(id) on delete cascade,
  primary key (query_id, source_id)
);
create index product_research_query_sources_source_idx on product_research_query_sources(source_id);

create table product_profiles (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  research_run_id uuid not null unique references product_research_runs(id) on delete cascade,
  version_no int not null check (version_no > 0),
  profile jsonb not null,
  coverage jsonb not null,
  created_at timestamptz not null default now(),
  unique (product_id, version_no)
);
create index product_profiles_product_idx on product_profiles(product_id, version_no desc);

alter table monitored_sources add column product_id uuid references products(id) on delete set null;
create index monitored_sources_product_idx on monitored_sources(product_id) where product_id is not null;

create table submission_product_links (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  submission_version_id uuid not null unique references submission_versions(id) on delete cascade,
  product_id uuid not null references products(id) on delete restrict,
  linked_by uuid not null references app_users(id),
  created_at timestamptz not null default now()
);
create index submission_product_links_product_idx on submission_product_links(product_id, created_at desc);
create trigger submission_product_links_immutable before update or delete on submission_product_links
  for each row execute function proofline_block_mutation();

create trigger product_research_queries_immutable before update or delete on product_research_queries
  for each row execute function proofline_block_mutation();
create trigger product_research_sources_immutable before update or delete on product_research_sources
  for each row execute function proofline_block_mutation();
create trigger product_research_query_sources_immutable before update or delete on product_research_query_sources
  for each row execute function proofline_block_mutation();
create trigger product_profiles_immutable before update or delete on product_profiles
  for each row execute function proofline_block_mutation();
alter table products enable row level security;
alter table product_research_runs enable row level security;
alter table product_research_queries enable row level security;
alter table product_research_sources enable row level security;
alter table product_research_query_sources enable row level security;
alter table product_profiles enable row level security;
alter table submission_product_links enable row level security;

do $$
begin
  if to_regrole('authenticated') is not null and to_regprocedure('public.is_workspace_member(uuid)') is not null then
    create policy products_member_select on products for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy product_research_runs_member_select on product_research_runs for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy product_research_queries_member_select on product_research_queries for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy product_research_sources_member_select on product_research_sources for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy product_research_query_sources_member_select on product_research_query_sources for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy product_profiles_member_select on product_profiles for select to authenticated
      using (public.is_workspace_member(workspace_id));
    create policy submission_product_links_member_select on submission_product_links for select to authenticated
      using (public.is_workspace_member(workspace_id));
  end if;
end $$;
