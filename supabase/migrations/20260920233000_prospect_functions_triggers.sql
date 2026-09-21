-- Migration: 20260920233000_prospect_functions_triggers.sql
-- Description: Replicate legacy prospect functions and triggers (GRU-89)

-- 1. normalize_prospect_whatsapp
CREATE OR REPLACE FUNCTION public.normalize_prospect_whatsapp(input_phone text)
 RETURNS text
 LANGUAGE plpgsql
 IMMUTABLE
AS $function$
DECLARE
    phone text;
BEGIN
    phone := regexp_replace(
        COALESCE(input_phone, ''),
        '[^0-9]',
        '',
        'g'
    );

    IF phone = '' THEN
        RETURN NULL;
    END IF;

    IF left(phone, 2) = '00' THEN
        phone := substring(phone FROM 3);
    END IF;

    IF left(phone, 1) = '0' AND length(phone) IN (11, 12) THEN
        phone := substring(phone FROM 2);
    END IF;

    IF left(phone, 2) <> '55' AND length(phone) IN (10, 11) THEN
        phone := '55' || phone;
    END IF;

    IF left(phone, 2) = '55' AND length(phone) IN (12, 13) THEN
        RETURN phone;
    END IF;

    RETURN NULL;
END;
$function$;

-- 2. create_google_lead_followup
CREATE OR REPLACE FUNCTION public.create_google_lead_followup()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
    base_date timestamptz;
    v_lead_id text;
begin
    base_date := coalesce(new.created_at, now());
    v_lead_id := coalesce(new.id, new.place_id);

    if v_lead_id is null or v_lead_id = '' then
        return new;
    end if;

    insert into public.prospect_followup_google (
        lead_id,
        status,
        current_followup,
        followup_1_at,
        followup_2_at,
        followup_3_at,
        followup_4_at,
        followup_5_at,
        followup_6_at,
        followup_7_at,
        next_followup_at
    )
    values (
        v_lead_id,
        'pending',
        1,
        base_date + interval '1 day',
        base_date + interval '2 days',
        base_date + interval '3 days',
        base_date + interval '4 days',
        base_date + interval '5 days',
        base_date + interval '6 days',
        base_date + interval '7 days',
        base_date + interval '1 day'
    )
    on conflict (lead_id) do nothing;

    update public.prospect_leads_google
    set
        id = coalesce(id, v_lead_id),
        status = 'followup_pending',
        followup_enabled = true,
        followup_current = 1,
        next_followup_at = base_date + interval '1 day',
        updated_at = now()
    where id = v_lead_id or place_id = v_lead_id;

    return new;
end;
$function$;

-- 3. advance_google_lead_followup
CREATE OR REPLACE FUNCTION public.advance_google_lead_followup(p_lead_id text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
    current_step integer;
    next_date timestamptz;
begin
    select current_followup
    into current_step
    from public.prospect_followup_google
    where lead_id = p_lead_id
    for update;

    if current_step is null then
        return;
    end if;

    case current_step
        when 1 then update public.prospect_followup_google set followup_1_status = 'sent' where lead_id = p_lead_id;
        when 2 then update public.prospect_followup_google set followup_2_status = 'sent' where lead_id = p_lead_id;
        when 3 then update public.prospect_followup_google set followup_3_status = 'sent' where lead_id = p_lead_id;
        when 4 then update public.prospect_followup_google set followup_4_status = 'sent' where lead_id = p_lead_id;
        when 5 then update public.prospect_followup_google set followup_5_status = 'sent' where lead_id = p_lead_id;
        when 6 then update public.prospect_followup_google set followup_6_status = 'sent' where lead_id = p_lead_id;
        when 7 then update public.prospect_followup_google set followup_7_status = 'sent' where lead_id = p_lead_id;
    end case;

    if current_step >= 7 then
        update public.prospect_followup_google
        set
            status = 'completed',
            last_followup_at = now(),
            next_followup_at = null,
            completed_at = now(),
            updated_at = now()
        where lead_id = p_lead_id;

        update public.prospect_leads_google
        set
            status = 'followup_completed',
            followup_current = 7,
            followup_completed = true,
            followup_completed_at = now(),
            last_followup_at = now(),
            next_followup_at = null,
            updated_at = now()
        where id = p_lead_id;

        return;
    end if;

    select
        case current_step + 1
            when 2 then followup_2_at
            when 3 then followup_3_at
            when 4 then followup_4_at
            when 5 then followup_5_at
            when 6 then followup_6_at
            when 7 then followup_7_at
        end
    into next_date
    from public.prospect_followup_google
    where lead_id = p_lead_id;

    update public.prospect_followup_google
    set
        current_followup = current_step + 1,
        last_followup_at = now(),
        next_followup_at = next_date,
        status = 'pending',
        updated_at = now()
    where lead_id = p_lead_id;

    update public.prospect_leads_google
    set
        followup_current = current_step + 1,
        last_followup_at = now(),
        next_followup_at = next_date,
        status = 'followup_pending',
        updated_at = now()
    where id = p_lead_id;
end;
$function$;

-- 4. stop_google_lead_followup
CREATE OR REPLACE FUNCTION public.stop_google_lead_followup(p_lead_id text, p_status text DEFAULT 'stopped'::text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
    update public.prospect_followup_google
    set
        status = p_status,
        next_followup_at = null,
        updated_at = now()
    where lead_id = p_lead_id;

    update public.prospect_leads_google
    set
        status = p_status,
        followup_enabled = false,
        next_followup_at = null,
        updated_at = now()
    where id = p_lead_id;
end;
$function$;

-- 5. dispatch_prospect_lead
CREATE OR REPLACE FUNCTION public.dispatch_prospect_lead()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'net', 'pg_temp'
AS $function$
DECLARE
    v_agora_local timestamp;
    v_lead public.prospect_leads_google%ROWTYPE;
    v_phone text;
    v_request_id bigint;
BEGIN
    v_agora_local := timezone('America/Campo_Grande', now());

    IF EXTRACT(ISODOW FROM v_agora_local) NOT BETWEEN 1 AND 5 THEN
        RETURN jsonb_build_object(
            'success', false,
            'reason', 'fora_dia_comercial',
            'datetime', v_agora_local
        );
    END IF;

    IF v_agora_local::time < TIME '08:00' OR v_agora_local::time >= TIME '19:00' THEN
        RETURN jsonb_build_object(
            'success', false,
            'reason', 'fora_horario_comercial',
            'datetime', v_agora_local
        );
    END IF;

    SELECT * INTO v_lead
    FROM public.prospect_leads_google
    WHERE processing_status = 'pending'
      AND contact_ready = true
      AND whatsapp IS NOT NULL
      AND whatsapp <> ''
      AND (processing_locked_at IS NULL OR processing_locked_at < now() - INTERVAL '10 minutes')
    ORDER BY created_at ASC NULLS LAST
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF v_lead.id IS NULL THEN
        RETURN jsonb_build_object(
            'success', true,
            'lead_found', false,
            'reason', 'fila_vazia'
        );
    END IF;

    UPDATE public.prospect_leads_google
    SET processing_status = 'processing',
        processing_locked_at = now(),
        processing_attempts = COALESCE(processing_attempts, 0) + 1,
        updated_at = now()
    WHERE id = v_lead.id;

    v_phone := public.normalize_prospect_whatsapp(v_lead.whatsapp);

    IF v_phone IS NULL THEN
        UPDATE public.prospect_leads_google
        SET processing_status = 'invalid_phone',
            processing_locked_at = NULL,
            processing_error = 'WhatsApp invalido apos normalizacao',
            updated_at = now()
        WHERE id = v_lead.id;

        RETURN jsonb_build_object(
            'success', false,
            'lead_found', true,
            'id', v_lead.id,
            'reason', 'invalid_phone'
        );
    END IF;

    UPDATE public.prospect_leads_google
    SET whatsapp = v_phone,
        updated_at = now()
    WHERE id = v_lead.id;

    SELECT net.http_post(
        url := 'https://webhookbuilder.iainfinito.com.br/webhook/ryze',
        headers := jsonb_build_object('Content-Type', 'application/json'),
        body := jsonb_build_object(
            'whatsapp', v_phone,
            'id', v_lead.id,
            'place_name', v_lead.place_name,
            'direction', 'incoming'
        ),
        timeout_milliseconds := 10000
    ) INTO v_request_id;

    UPDATE public.prospect_leads_google
    SET processing_status = 'waiting_delivery',
        processing_locked_at = NULL,
        updated_at = now()
    WHERE id = v_lead.id;

    RETURN jsonb_build_object(
        'success', true,
        'lead_found', true,
        'id', v_lead.id,
        'place_name', v_lead.place_name,
        'whatsapp', v_phone,
        'lead_status', 'enviar',
        'request_id', v_request_id
    );

EXCEPTION WHEN OTHERS THEN
    IF v_lead.id IS NOT NULL THEN
        UPDATE public.prospect_leads_google
        SET processing_status = 'error',
            processing_locked_at = NULL,
            processing_error = SQLERRM,
            updated_at = now()
        WHERE id = v_lead.id;
    END IF;
    RAISE;
END;
$function$;

-- 6. processar_proximo_lead_prospeccao
CREATE OR REPLACE FUNCTION public.processar_proximo_lead_prospeccao()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'net', 'pg_temp'
AS $function$
DECLARE
    v_agora_local timestamp;
    v_id public.prospect_leads_google.id%TYPE;
    v_whatsapp public.prospect_leads_google.whatsapp%TYPE;
    v_place_name public.prospect_leads_google.place_name%TYPE;
    v_request_id bigint;
BEGIN
    v_agora_local := timezone('America/Campo_Grande', now());

    IF EXTRACT(ISODOW FROM v_agora_local) NOT BETWEEN 1 AND 5 THEN
        RETURN jsonb_build_object(
            'success', false,
            'reason', 'fora_dia_comercial',
            'datetime', v_agora_local
        );
    END IF;

    IF v_agora_local::time < TIME '08:00' OR v_agora_local::time >= TIME '19:00' THEN
        RETURN jsonb_build_object(
            'success', false,
            'reason', 'fora_horario_comercial',
            'datetime', v_agora_local
        );
    END IF;

    SELECT id, whatsapp, place_name
    INTO v_id, v_whatsapp, v_place_name
    FROM public.prospect_leads_google
    WHERE LOWER(TRIM(lead_status)) IN ('enviar', 'new')
    ORDER BY created_at ASC NULLS LAST, id ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF v_id IS NULL THEN
        RETURN jsonb_build_object(
            'success', true,
            'reason', 'fila_vazia',
            'datetime', v_agora_local
        );
    END IF;

    UPDATE public.prospect_leads_google
    SET lead_status = 'processando'
    WHERE id = v_id;

    BEGIN
        SELECT net.http_post(
            url := 'https://webhookbuilder.iainfinito.com.br/webhook/ryze',
            headers := jsonb_build_object('Content-Type', 'application/json'),
            body := jsonb_build_object(
                'whatsapp', v_whatsapp,
                'id', v_id,
                'place_name', v_place_name,
                'direction', 'incoming'
            )
        ) INTO v_request_id;

        IF v_request_id IS NULL THEN
            RAISE EXCEPTION 'pg_net não retornou request_id';
        END IF;

        UPDATE public.prospect_leads_google
        SET lead_status = 'template_enviado'
        WHERE id = v_id;

        RETURN jsonb_build_object(
            'success', true,
            'lead_id', v_id,
            'whatsapp', v_whatsapp,
            'request_id', v_request_id,
            'status', 'template_enviado',
            'datetime', v_agora_local
        );
    EXCEPTION WHEN OTHERS THEN
        UPDATE public.prospect_leads_google
        SET lead_status = 'enviar'
        WHERE id = v_id;

        RETURN jsonb_build_object(
            'success', false,
            'lead_id', v_id,
            'status', 'enviar',
            'error', SQLERRM,
            'datetime', v_agora_local
        );
    END;
END;
$function$;

-- Trigger
DROP TRIGGER IF EXISTS trigger_create_google_lead_followup ON public.prospect_leads_google;
CREATE TRIGGER trigger_create_google_lead_followup
    AFTER INSERT ON public.prospect_leads_google
    FOR EACH ROW
    EXECUTE FUNCTION public.create_google_lead_followup();
