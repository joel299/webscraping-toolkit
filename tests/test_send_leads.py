import csv
from pathlib import Path

from src.send_leads_to_mcp import lead_payload, split_phone


def test_split_phone_mobile():
    telefone, celular = split_phone({"telefone_whatsapp": "5541999999999"})
    assert telefone == ""
    assert celular == "5541999999999"


def test_lead_payload_maps_common_columns():
    payload = lead_payload({
        "nome": "Empresa Exemplo",
        "website": "https://example.com",
        "address": "Curitiba - PR",
        "phone": "554133333333",
    })
    assert payload["nome_barbearia"] == "Empresa Exemplo"
    assert payload["site"] == "https://example.com"
    assert payload["endereco"] == "Curitiba - PR"
    assert payload["telefone"] == "554133333333"
