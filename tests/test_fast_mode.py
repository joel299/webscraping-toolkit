import src.gmaps_web_ui as web_ui


SAMPLE_LEAD = {
    "place_name": "Clínica Exemplo",
    "category": "Clínica de estética",
    "total_score": "4.8",
    "reviews_count": "183",
    "address": "Rua Exemplo, 123 - Campo Grande - MS",
    "street": "Rua Exemplo, 123",
    "city": "Campo Grande",
    "state": "Mato Grosso do Sul",
    "country_code": "BR",
    "phone_raw": "(67) 99999-9999",
    "whatsapp": "5567999999999",
    "website": "https://example.com",
    "google_maps_url": "https://maps.google.com/example",
}


def run_worker(monkeypatch, mode):
    jobs = {}
    jobs["job-1"] = {
        "job_id": "job-1",
        "status": "pending",
        "phase": "scrape",
        "mode": mode,
        "auto_enrich": mode == "full",
        "category": "estética",
        "city": "Campo Grande",
        "state": "Mato Grosso do Sul",
        "max_leads": 1,
        "webhook": "https://n8n.example/webhook",
        "leads": [],
    }
    monkeypatch.setattr(web_ui, "get_jobs_dict", lambda: jobs)
    monkeypatch.setattr(
        web_ui.gmaps_playwright_scraper,
        "scrape_gmaps",
        lambda *args, **kwargs: [dict(SAMPLE_LEAD)],
    )
    return jobs


def test_fast_mode_skips_enrichment_and_sends_once(monkeypatch):
    jobs = run_worker(monkeypatch, "fast")
    enrich_calls = []
    webhook_calls = []

    monkeypatch.setattr(
        web_ui,
        "run_enrich_inline",
        lambda *args, **kwargs: enrich_calls.append(True),
    )
    monkeypatch.setattr(
        web_ui,
        "send_to_n8n",
        lambda payload, url: webhook_calls.append((payload, url)) or {"ok": True, "status": 200},
    )

    web_ui.worker_scrape_process(
        "job-1", "estética", "Campo Grande", "Mato Grosso do Sul", 1,
        "https://n8n.example/webhook", jobs, "fast"
    )

    job = jobs["job-1"]
    assert job["status"] == "completed"
    assert job["mode"] == "fast"
    assert job["auto_enrich"] is False
    assert enrich_calls == []
    assert len(webhook_calls) == 1
    assert job["webhook_sent"] is True
    assert job["n8n_response"]["status"] == 200
    assert job["payload"]["leads"][0]["instagram"] == []
    assert job["payload"]["leads"][0]["emails"] == []


def test_full_mode_keeps_enrichment_path(monkeypatch):
    jobs = run_worker(monkeypatch, "full")
    enrich_calls = []
    monkeypatch.setattr(
        web_ui,
        "run_enrich_inline",
        lambda *args, **kwargs: enrich_calls.append(True),
    )

    web_ui.worker_scrape_process(
        "job-1", "estética", "Campo Grande", "Mato Grosso do Sul", 1,
        "", jobs, "full"
    )

    assert enrich_calls == [True]


def test_fast_mode_never_opens_website_for_socials(monkeypatch):
    jobs = run_worker(monkeypatch, "fast")
    social_calls = []
    monkeypatch.setattr(
        web_ui.gmaps_playwright_scraper,
        "extract_socials_from_website",
        lambda *args, **kwargs: social_calls.append(True),
        raising=False,
    )
    monkeypatch.setattr(web_ui, "send_to_n8n", lambda payload, url: {"ok": True, "status": 200})

    web_ui.worker_scrape_process(
        "job-1", "estética", "Campo Grande", "Mato Grosso do Sul", 1,
        "https://n8n.example/webhook", jobs, "fast"
    )

    assert social_calls == []
