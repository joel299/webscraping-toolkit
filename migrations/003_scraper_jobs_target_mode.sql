-- GRU-30: target mode is additive and preserves existing jobs.
ALTER TABLE public.scraper_jobs
  ADD COLUMN IF NOT EXISTS target_mode text NOT NULL DEFAULT 'limited';
ALTER TABLE public.scraper_jobs
  ALTER COLUMN target DROP NOT NULL;
ALTER TABLE public.scraper_jobs
  DROP CONSTRAINT IF EXISTS scraper_jobs_target_check;
ALTER TABLE public.scraper_jobs
  ADD CONSTRAINT scraper_jobs_target_mode_check CHECK (
    (target_mode = 'limited' AND target IS NOT NULL AND target > 0)
    OR (target_mode = 'all_available' AND target IS NULL)
  );
UPDATE public.scraper_jobs SET target_mode='limited' WHERE target_mode IS NULL;
CREATE INDEX IF NOT EXISTS scraper_jobs_target_mode_idx ON public.scraper_jobs(target_mode);
