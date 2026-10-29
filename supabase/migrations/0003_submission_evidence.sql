-- Evidence files are immutable, private, and tied to the exact claim version they support.
create table submission_evidence (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  submission_version_id uuid not null references submission_versions(id) on delete cascade,
  original_filename text not null,
  storage_path text not null,
  mime_type text not null,
  size_bytes bigint not null,
  content_hash text not null,
  description text,
  extracted_text text not null default '',
  extraction_status text not null check (extraction_status in ('complete','partial','empty','unsupported','failed')),
  extraction_warnings jsonb not null default '[]',
  segments jsonb not null default '[]',
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now()
);
create index submission_evidence_version_idx on submission_evidence(submission_version_id);
create index submission_evidence_workspace_idx on submission_evidence(workspace_id);

create table evidence_assessments (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  submission_version_id uuid not null references submission_versions(id) on delete cascade,
  evidence_id uuid not null references submission_evidence(id) on delete cascade,
  review_run_id uuid not null references review_runs(id) on delete cascade,
  assessment text not null check (assessment in ('supported','contradicted','partially_supported','insufficient_evidence','unable_to_determine')),
  explanation text not null,
  excerpt text,
  location jsonb,
  created_at timestamptz not null default now()
);
create index evidence_assessments_run_idx on evidence_assessments(review_run_id);
create index evidence_assessments_version_idx on evidence_assessments(submission_version_id);

alter table submission_evidence enable row level security;
alter table evidence_assessments enable row level security;

create policy submission_evidence_member_select on submission_evidence
  for select to authenticated using (public.is_workspace_member(workspace_id));
create policy evidence_assessments_member_select on evidence_assessments
  for select to authenticated using (public.is_workspace_member(workspace_id));

create trigger submission_evidence_immutable before update or delete on submission_evidence
  for each row execute function proofline_block_mutation();
create trigger evidence_assessments_immutable before update or delete on evidence_assessments
  for each row execute function proofline_block_mutation();
