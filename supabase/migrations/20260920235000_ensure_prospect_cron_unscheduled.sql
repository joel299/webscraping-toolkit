-- Migration: 20260920235000_ensure_prospect_cron_unscheduled.sql
-- Description: Explicitly ensure all operational prospect cron jobs are unscheduled (GRU-89)
-- CRON_ACTIVATION_ALLOWED=false
-- CRON_JOBS_ACTIVE=0

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
        IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'prospect-leads-google-dispatcher') THEN
            PERFORM cron.unschedule('prospect-leads-google-dispatcher');
        END IF;

        IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'followup-dispatcher-every-minute') THEN
            PERFORM cron.unschedule('followup-dispatcher-every-minute');
        END IF;

        IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'prospeccao-novos-leads') THEN
            PERFORM cron.unschedule('prospeccao-novos-leads');
        END IF;
    END IF;
END $$;
