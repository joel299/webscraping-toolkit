alter table public.prospect_leads_google
  add column if not exists observed_category text,
  add column if not exists v2_last_job_id uuid references public.scraper_jobs(id) on delete set null,
  add column if not exists v2_worker_label text,
  add column if not exists persistence_verified boolean not null default false,
  add column if not exists persistence_verified_at timestamptz;

create index if not exists prospect_leads_google_v2_job_idx on public.prospect_leads_google(v2_last_job_id);
create index if not exists prospect_leads_google_source_identity_idx on public.prospect_leads_google(id);

alter table public.prospect_leads_google enable row level security;
