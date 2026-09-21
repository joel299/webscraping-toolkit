-- Migration: 20260920234000_prospect_extensions_cron.sql
-- Description: Enable pg_cron and pg_net extensions, safely unschedule operational cron jobs (GRU-89)
-- CRON_ACTIVATION_ALLOWED=false
-- EXTERNAL_SIDE_EFFECTS_DISABLED=PASS

DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS pg_cron;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'pg_cron extension not available in environment: %', SQLERRM;
    END;
    BEGIN
        CREATE EXTENSION IF NOT EXISTS pg_net;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'pg_net extension not available in environment: %', SQLERRM;
    END;

    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
        -- Unschedule prospect-leads-google-dispatcher if present
        IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'prospect-leads-google-dispatcher') THEN
            PERFORM cron.unschedule('prospect-leads-google-dispatcher');
        END IF;

        -- Unschedule followup-dispatcher-every-minute if present
        IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'followup-dispatcher-every-minute') THEN
            PERFORM cron.unschedule('followup-dispatcher-every-minute');
        END IF;

        -- Unschedule prospeccao-novos-leads if present
        IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'prospeccao-novos-leads') THEN
            PERFORM cron.unschedule('prospeccao-novos-leads');
        END IF;
    END IF;
END $$;

/*
  INVENTORY FOR FUTURE REFERENCE (DISABLED IN THIS GATE):

  1. prospect-leads-google-dispatcher
     Schedule: '* * * * *'
     Command: 'SELECT public.dispatch_prospect_lead();'

  2. followup-dispatcher-every-minute
     Schedule: '* * * * *'
     Command: 'SELECT public.processar_proximo_lead_prospeccao();'

  3. prospeccao-novos-leads
     Schedule: '* * * * *'
     Command: 'SELECT public.processar_proximo_lead_prospeccao();'
*/
