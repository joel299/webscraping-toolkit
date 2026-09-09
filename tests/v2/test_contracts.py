import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from packages.domain.identity import place_identity
from packages.normalization.normalize import normalize_place

def test_identity_prefers_place_id():
    assert place_identity({"place_id":"ChIJabc"}) == "google:chijabc"

def test_same_url_same_identity():
    a={"google_maps_url":"https://maps.google.com/?cid=123"}; b={"url":"https://maps.google.com/?cid=123"}
    assert place_identity(a)==place_identity(b)

def test_category_gate_rejects_health_for_lanchonete():
    row=normalize_place({"place_name":"M.CO","category":"Clínica especializada"},{"requested_category":"lanchonete","city":"Campo Grande","state":"MS"})
    assert row["qualification_status"]=="rejected"
    assert row["reject_reason"]=="category_mismatch"

def test_normalized_payload_has_no_raw_fields():
    row=normalize_place({"place_name":"X","raw_html":"bad"},{"requested_category":"clinica","city":"CG","state":"MS"})
    assert "raw_html" not in row
