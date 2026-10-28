-- Proofline schema. Plain PostgreSQL (works on Supabase and on a local Postgres).
-- Supabase-specific Row Level Security lives in 0002_rls_supabase.sql.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- users
-- Mirror of the authenticated identity. In Supabase mode the id equals auth.users.id
-- and the row is upserted by the API on first authenticated request.
create table app_users (
  id uuid primary key,
  email text not null unique,
  display_name text,
  created_at timestamptz not null default now()
);

-- Only used when AUTH_MODE=local (no Supabase available).
create table local_credentials (
  user_id uuid primary key references app_users(id) on delete cascade,
  password_hash text not null
);

-- ----------------------------------------------------------- workspaces
create table workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(trim(name)) between 1 and 120),
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now()
);

create table workspace_members (
  workspace_id uuid not null references workspaces(id) on delete cascade,
  user_id uuid not null references app_users(id) on delete cascade,
  role text not null check (role in ('owner','editor','reviewer')),
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);
create index workspace_members_user_idx on workspace_members(user_id);

create table brand_profiles (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  name text not null check (length(trim(name)) between 1 and 120),
  description text,
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now()
);
create index brand_profiles_ws_idx on brand_profiles(workspace_id);

-- -------------------------------------------------------------- sources
create table source_records (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  kind text not null check (kind in ('reference','external_retrieval')),
  title text not null,
  url text,
  publisher text,
  retrieved_at timestamptz,
  published_at timestamptz,
  content_hash text,
  access_status text not null default 'ok' check (access_status in ('ok','unreachable','blocked','unknown')),
  excerpt text,
  created_by uuid references app_users(id),
  created_at timestamptz not null default now()
);
create index source_records_ws_idx on source_records(workspace_id);

-- ------------------------------------------------------- facts (versioned)
create table brand_facts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  key text not null check (length(trim(key)) between 1 and 120),
  current_version_id uuid,
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now(),
  unique (brand_profile_id, key)
);
create index brand_facts_ws_idx on brand_facts(workspace_id);

create table brand_fact_versions (
  id uuid primary key default gen_random_uuid(),
  fact_id uuid not null references brand_facts(id) on delete cascade,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  version_no int not null check (version_no >= 1),
  name text not null,
  approved_value text not null check (length(trim(approved_value)) > 0),
  value_type text not null check (value_type in ('text','number','money','date')),
  -- phrases that identify where this fact is discussed in content
  subject_terms text[] not null default '{}',
  status text not null check (status in ('draft','approved','inactive')),
  source_record_id uuid references source_records(id),
  effective_date date,
  change_note text,
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now(),
  unique (fact_id, version_no)
);
create index brand_fact_versions_fact_idx on brand_fact_versions(fact_id);
alter table brand_facts
  add constraint brand_facts_current_fk foreign key (current_version_id)
  references brand_fact_versions(id) deferrable initially deferred;

-- ------------------------------------------------------- rules (versioned)
create table brand_rules (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  key text not null check (length(trim(key)) between 1 and 120),
  current_version_id uuid,
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now(),
  unique (brand_profile_id, key)
);
create index brand_rules_ws_idx on brand_rules(workspace_id);

create table brand_rule_versions (
  id uuid primary key default gen_random_uuid(),
  rule_id uuid not null references brand_rules(id) on delete cascade,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  version_no int not null check (version_no >= 1),
  rule_type text not null check (rule_type in
    ('prohibited_phrase','required_term','approved_name','claim_requires_evidence')),
  description text not null,
  patterns text[] not null default '{}',
  severity text not null check (severity in ('low','medium','high')),
  -- content types the rule applies to; empty array = all
  applies_to text[] not null default '{}',
  status text not null check (status in ('draft','approved','inactive')),
  source_record_id uuid references source_records(id),
  change_note text,
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now(),
  unique (rule_id, version_no)
);
create index brand_rule_versions_rule_idx on brand_rule_versions(rule_id);
alter table brand_rules
  add constraint brand_rules_current_fk foreign key (current_version_id)
  references brand_rule_versions(id) deferrable initially deferred;

-- ---------------------------------------------------------- submissions
create table submissions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id),
  title text not null check (length(trim(title)) between 1 and 200),
  current_version_id uuid,
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now()
);
create index submissions_ws_idx on submissions(workspace_id);

create table submission_versions (
  id uuid primary key default gen_random_uuid(),
  submission_id uuid not null references submissions(id) on delete cascade,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  version_no int not null check (version_no >= 1),
  source_type text not null check (source_type in ('text','docx','pdf','image','pptx','url')),
  original_filename text,
  original_url text,
  storage_path text,              -- private object storage key of the original upload
  mime_type text,
  size_bytes bigint,
  retrieved_at timestamptz,
  extracted_text text not null default '',
  content_hash text not null,
  extraction_status text not null check (extraction_status in ('complete','partial','empty','unsupported','failed')),
  extraction_warnings jsonb not null default '[]',
  extraction_quality jsonb not null default '{}',
  -- [{start,end,label,kind}] maps character ranges to page / slide / paragraph / url
  segments jsonb not null default '[]',
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now(),
  unique (submission_id, version_no)
);
create index submission_versions_sub_idx on submission_versions(submission_id);
alter table submissions
  add constraint submissions_current_fk foreign key (current_version_id)
  references submission_versions(id) deferrable initially deferred;

-- ----------------------------------------------------------- review runs
create table review_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  submission_version_id uuid not null references submission_versions(id) on delete cascade,
  status text not null check (status in ('running','completed','completed_with_warnings','failed')),
  -- per stage: {"deterministic":{"status":"completed","message":..},"semantic":{...},"verification":{...}}
  stages jsonb not null default '{}',
  engine_version text not null,
  requested_by uuid not null references app_users(id),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  error text
);
create index review_runs_sv_idx on review_runs(submission_version_id);
create index review_runs_ws_idx on review_runs(workspace_id);

-- exact versions used by a run
create table review_run_fact_versions (
  review_run_id uuid not null references review_runs(id) on delete cascade,
  fact_version_id uuid not null references brand_fact_versions(id),
  primary key (review_run_id, fact_version_id)
);
create table review_run_rule_versions (
  review_run_id uuid not null references review_runs(id) on delete cascade,
  rule_version_id uuid not null references brand_rule_versions(id),
  primary key (review_run_id, rule_version_id)
);

-- --------------------------------------------------------------- findings
create table findings (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  review_run_id uuid not null references review_runs(id) on delete cascade,
  submission_version_id uuid not null references submission_versions(id) on delete cascade,
  origin text not null check (origin in ('deterministic','semantic','verification','extraction')),
  category text not null check (category in
    ('rule_violation','possible_inconsistency','verified_contradiction','claim_verification','extraction_limitation')),
  title text not null,
  explanation text not null,
  severity text not null check (severity in ('low','medium','high')),
  excerpt text,
  span_start int,
  span_end int,
  location jsonb,                 -- {"label":"Slide 3","kind":"slide"} etc.
  fact_version_id uuid references brand_fact_versions(id),
  rule_version_id uuid references brand_rule_versions(id),
  verification_status text not null default 'not_applicable' check (verification_status in
    ('not_applicable','supported','contradicted','conflicting','insufficient_evidence','unavailable','needs_human_review')),
  status text not null default 'open' check (status in ('open','accepted','resolved','dismissed','needs_investigation')),
  status_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (status <> 'dismissed' or length(trim(coalesce(status_reason,''))) > 0)
);
create index findings_run_idx on findings(review_run_id);
create index findings_sv_idx on findings(submission_version_id);

create table finding_evidence (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  finding_id uuid not null references findings(id) on delete cascade,
  kind text not null check (kind in ('brand_fact','brand_rule','external_source')),
  fact_version_id uuid references brand_fact_versions(id),
  rule_version_id uuid references brand_rule_versions(id),
  source_record_id uuid references source_records(id),
  excerpt text,
  stance text not null check (stance in ('supports','contradicts','unclassified','reference')),
  created_at timestamptz not null default now(),
  check (
    (kind = 'brand_fact' and fact_version_id is not null) or
    (kind = 'brand_rule' and rule_version_id is not null) or
    (kind = 'external_source' and source_record_id is not null)
  )
);
create index finding_evidence_finding_idx on finding_evidence(finding_id);

-- Dependency links used by the Brand Time Machine. One row per fact/rule version that a
-- review run actually evaluated against the content (matched, applicable or violated).
create table finding_dependencies (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  review_run_id uuid not null references review_runs(id) on delete cascade,
  submission_version_id uuid not null references submission_versions(id) on delete cascade,
  finding_id uuid references findings(id) on delete cascade,
  fact_id uuid references brand_facts(id),
  fact_version_id uuid references brand_fact_versions(id),
  rule_id uuid references brand_rules(id),
  rule_version_id uuid references brand_rule_versions(id),
  dependency_kind text not null check (dependency_kind in ('violation','matched','applicable')),
  created_at timestamptz not null default now(),
  check ((fact_id is not null and fact_version_id is not null and rule_id is null and rule_version_id is null)
      or (rule_id is not null and rule_version_id is not null and fact_id is null and fact_version_id is null))
);
create index finding_dependencies_fact_idx on finding_dependencies(fact_id);
create index finding_dependencies_rule_idx on finding_dependencies(rule_id);
create index finding_dependencies_sv_idx on finding_dependencies(submission_version_id);

-- ----------------------------------------------------------- decisions
create table review_decisions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  submission_version_id uuid not null references submission_versions(id) on delete cascade,
  review_run_id uuid references review_runs(id),
  decision text not null check (decision in ('approved','changes_requested','rejected')),
  comment text,
  decided_by uuid not null references app_users(id),
  decided_at timestamptz not null default now()
);
create index review_decisions_sv_idx on review_decisions(submission_version_id);

-- ------------------------------------------------------ impact (time machine)
create table impact_records (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  submission_id uuid not null references submissions(id) on delete cascade,
  submission_version_id uuid not null references submission_versions(id) on delete cascade,
  change_kind text not null check (change_kind in ('fact','rule')),
  fact_id uuid references brand_facts(id),
  rule_id uuid references brand_rules(id),
  old_version_id uuid not null,   -- brand_fact_versions.id or brand_rule_versions.id depending on change_kind
  new_version_id uuid not null,
  status text not null default 'review_required' check (status in ('review_required','resolved')),
  created_by uuid references app_users(id),
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  resolved_by uuid references app_users(id),
  resolution_decision_id uuid references review_decisions(id),
  resolution_review_run_id uuid references review_runs(id),
  check ((change_kind = 'fact' and fact_id is not null and rule_id is null)
      or (change_kind = 'rule' and rule_id is not null and fact_id is null))
);
create index impact_records_ws_status_idx on impact_records(workspace_id, status);
create index impact_records_sub_idx on impact_records(submission_id);
-- a given content version is flagged at most once per fact/rule change
create unique index impact_records_unique_fact on impact_records(submission_version_id, new_version_id) where change_kind = 'fact';
create unique index impact_records_unique_rule on impact_records(submission_version_id, new_version_id) where change_kind = 'rule';

-- ----------------------------------------------------------------- audit
create table audit_events (
  id bigserial primary key,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  actor_id uuid references app_users(id),
  event_type text not null,
  entity_type text not null,
  entity_id uuid,
  summary text not null,
  payload jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index audit_events_ws_idx on audit_events(workspace_id, created_at desc);

-- ------------------------------------------------------------ immutability
create function proofline_block_mutation() returns trigger language plpgsql as $$
begin
  raise exception '% rows are immutable (attempted %)', tg_table_name, tg_op;
end $$;

create trigger brand_fact_versions_immutable before update or delete on brand_fact_versions
  for each row execute function proofline_block_mutation();
create trigger brand_rule_versions_immutable before update or delete on brand_rule_versions
  for each row execute function proofline_block_mutation();
create trigger submission_versions_immutable before update or delete on submission_versions
  for each row execute function proofline_block_mutation();
create trigger review_decisions_immutable before update or delete on review_decisions
  for each row execute function proofline_block_mutation();
create trigger finding_evidence_immutable before update or delete on finding_evidence
  for each row execute function proofline_block_mutation();
create trigger audit_events_immutable before update or delete on audit_events
  for each row execute function proofline_block_mutation();
