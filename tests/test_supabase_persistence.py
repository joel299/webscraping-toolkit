import json
import urllib.request

from src import supabase_persistence


def test_supabase_is_noop_without_configuration(monkeypatch):
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    assert supabase_persistence.persist_leads([{'place_name': 'A'}]) == {
        'enabled': False, 'persisted': 0, 'verified': False,
    }


def test_schema_row_omits_empty_and_commercial_fields():
    row = supabase_persistence._row_for_schema({
        'place_name': 'A', 'whatsapp': '5511999999999', 'website': '',
        'facebook': [], 'lead_status': 'enviar', 'followup_count': 4,
    }, category='clinica', city='Campo Grande', state='MS')
    assert row['place_name'] == 'A'
    assert row['whatsapp'] == '5511999999999'
    assert row['categories'] == 'clinica'
    assert row['source_city'] == 'Campo Grande'
    assert 'lead_status' not in row
    assert 'followup_count' not in row
    assert 'website' not in row


def test_incremental_insert_readback(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://project.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-role-test-key')
    calls = []

    def fake_request(url, api_key, method='GET', payload=None, timeout=30):
        calls.append((url, method, payload))
        if method == 'GET':
            return 200, []
        return 201, [{'id': payload['id'], 'whatsapp': payload['whatsapp']}]

    monkeypatch.setattr(supabase_persistence, '_request', fake_request)
    result = supabase_persistence.persist_leads(
        [{'place_name': 'A', 'whatsapp': '5511999999999'}],
        category='clinica', city='Campo Grande', state='MS',
    )
    assert result['verified'] is True
    assert result['actions'] == ['inserted']
    assert calls[-1][1] == 'POST'


def test_incremental_existing_updates_without_commercial_fields(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://project.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-role-test-key')
    calls = []

    def fake_request(url, api_key, method='GET', payload=None, timeout=30):
        calls.append((url, method, payload))
        if method == 'GET':
            return 200, [{'id': 'existing-id'}]
        return 200, [{'id': 'existing-id'}]

    monkeypatch.setattr(supabase_persistence, '_request', fake_request)
    result = supabase_persistence.persist_leads(
        [{'place_name': 'A', 'whatsapp': '5511999999999', 'website': ''}],
        category='clinica', city='Campo Grande', state='MS',
    )
    assert result['verified'] is True
    assert result['actions'] == ['updated']
    patch = calls[-1]
    assert patch[1] == 'PATCH'
    assert patch[2]['id'] == 'google:wa:5511999999999'
    assert 'lead_status' not in patch[2]


def test_failure_is_reported_without_raising(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://project.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'key')
    monkeypatch.setattr(supabase_persistence, '_request', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('offline')))
    result = supabase_persistence.persist_leads([{'place_name': 'A'}])
    assert result['enabled'] is True
    assert result['verified'] is False
    assert 'offline' in result['error']
