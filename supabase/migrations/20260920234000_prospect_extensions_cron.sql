-- Migration: 20260920234000_prospect_extensions_cron.sql
-- Description: Enable pg_cron, pg_net extensions and register prospect cron jobs (GRU-89)

CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
        -- 1. prospect-leads-google-dispatcher
        IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'prospect-leads-google-dispatcher') THEN
            PERFORM cron.schedule(
                'prospect-leads-google-dispatcher',
                '* * * * *',
                'SELECT public.dispatch_prospect_lead();'
            );
        END IF;

        -- 2. followup-dispatcher-every-minute
        IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'followup-dispatcher-every-minute') THEN
            PERFORM cron.schedule(
                'followup-dispatcher-every-minute',
                '* * * * *',
                'SELECT public.processar_proximo_lead_prospeccao();'
            );
        END IF;

        -- 3. prospeccao-novos-leads
        IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'prospeccao-novos-leads') THEN
            PERFORM cron.schedule(
                'prospeccao-novos-leads',
                '* * * * *',
                'SELECT public.processar_proximo_lead_prospeccao();'
            );
        END IF;
    END IF;
END $$;
