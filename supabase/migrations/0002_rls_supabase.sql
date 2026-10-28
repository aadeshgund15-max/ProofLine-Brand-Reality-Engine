-- Row Level Security for Supabase (requires the auth schema; do NOT run on plain Postgres).
-- Design: the browser may read workspace data directly with the user's JWT only where
-- the user is a member. All writes go through the FastAPI backend (service connection),
-- which enforces roles. No INSERT/UPDATE/DELETE policy is granted to `authenticated`,
-- so direct client writes are denied by default.

create or replace function public.is_workspace_member(ws uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from workspace_members m where m.workspace_id = ws and m.user_id = auth.uid());
$$;

do $$
declare t text;
begin
  foreach t in array array[
    'workspaces','brand_profiles','source_records','brand_facts','brand_fact_versions',
    'brand_rules','brand_rule_versions','submissions','submission_versions','review_runs',
    'findings','finding_evidence','finding_dependencies','review_decisions','impact_records','audit_events'
  ] loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;

alter table app_users enable row level security;
alter table workspace_members enable row level security;
alter table local_credentials enable row level security;  -- no policy: never readable by clients
alter table review_run_fact_versions enable row level security;
alter table review_run_rule_versions enable row level security;

create policy app_users_self on app_users for select to authenticated using (id = auth.uid());
create policy members_select on workspace_members for select to authenticated
  using (user_id = auth.uid() or public.is_workspace_member(workspace_id));
create policy workspaces_select on workspaces for select to authenticated
  using (public.is_workspace_member(id));

do $$
declare t text;
begin
  foreach t in array array[
    'brand_profiles','source_records','brand_facts','brand_fact_versions','brand_rules',
    'brand_rule_versions','submissions','submission_versions','review_runs','findings',
    'finding_evidence','finding_dependencies','review_decisions','impact_records','audit_events'
  ] loop
    execute format(
      'create policy %I on %I for select to authenticated using (public.is_workspace_member(workspace_id))',
      t || '_member_select', t);
  end loop;
end $$;

create policy rrfv_select on review_run_fact_versions for select to authenticated
  using (exists (select 1 from review_runs r where r.id = review_run_id and public.is_workspace_member(r.workspace_id)));
create policy rrrv_select on review_run_rule_versions for select to authenticated
  using (exists (select 1 from review_runs r where r.id = review_run_id and public.is_workspace_member(r.workspace_id)));

-- Private bucket for original uploads. No public access; the API issues short-lived signed URLs
-- after checking workspace membership. Object keys are '<workspace_id>/<submission_id>/<file>'.
insert into storage.buckets (id, name, public) values ('submissions', 'submissions', false)
  on conflict (id) do update set public = false;
