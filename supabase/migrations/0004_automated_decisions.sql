-- Append-only result of the deterministic baseline governance policy.
create table automated_decisions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  submission_version_id uuid not null references submission_versions(id) on delete cascade,
  review_run_id uuid not null unique references review_runs(id) on delete cascade,
  outcome text not null check (outcome in ('approved','rejected','on_hold')),
  risk_score smallint not null check (risk_score between 0 and 100),
  rationale text not null,
  factors jsonb not null default '[]',
  policy_version text not null,
  created_at timestamptz not null default now()
);
create index automated_decisions_workspace_created_idx
  on automated_decisions(workspace_id, created_at desc);
create index automated_decisions_submission_version_idx
  on automated_decisions(submission_version_id, created_at desc);

create trigger automated_decisions_immutable before update or delete on automated_decisions
  for each row execute function proofline_block_mutation();

alter table automated_decisions enable row level security;
-- Plain Postgres does not have Supabase's `authenticated` role or membership helper.
-- On Supabase, keep the report visible only to members of its workspace.
do $$
begin
  if to_regrole('authenticated') is not null
     and to_regprocedure('public.is_workspace_member(uuid)') is not null then
    create policy automated_decisions_member_select on automated_decisions
      for select to authenticated using (public.is_workspace_member(workspace_id));
  end if;
end $$;
