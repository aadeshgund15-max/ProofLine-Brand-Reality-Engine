-- Persist conservative, explainable source signals for each product research source.
alter table product_research_sources
  add column source_assessment jsonb not null default
  '{"policy_version":"source-signals-1","overall_status":"unassessed","signals":{},"limitations":["No assessment was available before migration 0009."]}'::jsonb;
