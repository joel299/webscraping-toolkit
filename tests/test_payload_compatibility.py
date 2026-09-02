from src.gmaps_web_ui import make_payload


EXPECTED_N8N_LEAD_KEYS = {
    "nome", "categoria", "nota", "avaliacoes", "endereco", "rua", "cidade",
    "estado", "pais", "telefone", "whatsapp", "site", "google_maps",
    "instagram", "facebook", "linkedin", "emails", "razao_social", "cnpj",
    "representante_legal", "administrador", "situacao_cadastral", "data_abertura",
    "atividade_principal", "natureza_juridica", "quadro_societario",
 "google_sponsored",
 "web_results",
 "instagram_source",
 "cnpj_source",
 "qualification_status",
 "qualification",
 }


def test_payload_compatibility_preserves_n8n_keys_in_fast_shape():
    payload = make_payload({
        "category": "estética",
        "city": "Campo Grande",
        "state": "Mato Grosso do Sul",
        "leads": [{
            "place_name": "Clínica Exemplo",
            "category": "Clínica de estética",
            "total_score": "4.8",
            "reviews_count": "183",
            "address": "Rua Exemplo, 123",
            "street": "Rua Exemplo, 123",
            "city": "Campo Grande",
            "state": "Mato Grosso do Sul",
            "country_code": "BR",
            "phone_raw": "(67) 99999-9999",
            "whatsapp": "5567999999999",
            "website": "https://example.com",
            "google_maps_url": "https://maps.google.com/example",
        }],
    })

    assert set(payload["leads"][0]) == EXPECTED_N8N_LEAD_KEYS
    assert payload["leads"][0]["instagram"] == []
    assert payload["leads"][0]["cnpj"] == ""
    assert payload["leads"][0]["quadro_societario"] == []


def test_webhook_delivery_is_idempotent_for_a_job(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "src.gmaps_web_ui.send_to_n8n",
        lambda payload, url: calls.append((payload, url)) or {"ok": True, "status": 200},
    )
    job = {"job_id": "job-1"}
    payload = {"leads": [{"nome": "Empresa"}]}

    first = __import__("src.gmaps_web_ui", fromlist=["_send_webhook_once"])._send_webhook_once(
        job, payload, "https://n8n.example/webhook"
    )
    second = __import__("src.gmaps_web_ui", fromlist=["_send_webhook_once"])._send_webhook_once(
        job, payload, "https://n8n.example/webhook"
    )

    assert first["status"] == 200
    assert second["status"] == 200
    assert len(calls) == 1
