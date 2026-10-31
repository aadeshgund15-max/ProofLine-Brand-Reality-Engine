alter table source_records add column search_query text not null default '';
alter table source_records add column extraction_status text not null default 'unknown';
create index source_records_url_hash_idx on source_records(workspace_id, url, content_hash);
