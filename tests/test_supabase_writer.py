import json
import urllib.error
import urllib.parse

import src.supabase_writer as sw


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def close(self):
        return None
    def read(self):
        return json.dumps(self.payload).encode()


def make_urlopen(existing=None, conflict_once=False):
    state = {'existing': list(existing or []), 'posts': [], 'conflicts': 0}

    def fake(request, timeout=20):
        parsed = urllib.parse.urlparse(request.full_url)
        qs = urllib.parse.parse_qs(parsed.query)
        if request.method == 'GET':
            phones = []
            raw = qs.get('whatsapp', [''])[0]
            if raw.startswith('in.('):
                phones = raw[4:-1].split(',')
            elif raw.startswith('eq.'):
                phones = [raw[3:]]
            rows = [row for row in state['existing'] if not phones or row.get('whatsapp') in phones]
            return Response(rows)
        if request.method == 'POST':
            rows = json.loads(request.data.decode())
            state['posts'].append(rows)
            if conflict_once and state['conflicts'] == 0:
                state['conflicts'] += 1
                raise urllib.error.HTTPError(request.full_url, 409, 'Conflict', {}, Response({'code': '23505', 'message': 'duplicate key value violates unique constraint prospect_leads_google_whatsapp_unique'}))
            returned = []
            all_new = True
            for row in rows:
                found = next((x for x in state['existing'] if x.get('id') == row['id']), None)
                if found:
                    all_new = False
                    found.update(row)
                    returned.append(found.copy())
                else:
                    state['existing'].append(row.copy())
                    returned.append(row.copy())
            return Response(returned, 201 if all_new else 200)
        raise AssertionError(request.method)

    return fake, state


def sample(phone='5511111111111', website=''):
    return {'place_name': 'Empresa Teste', 'phone_raw': phone, 'whatsapp': phone, 'website': website, 'google_maps_url': 'https://maps.google.com/maps/place/teste', 'category': 'clínica'}


def test_new_lead_is_inserted_and_metrics_are_explicit(monkeypatch):
    fake, state = make_urlopen()
    monkeypatch.setattr(sw.urllib.request, 'urlopen', fake)
    writer = sw.SupabaseBatchWriter('https://example.supabase.co', 'key')
    writer.enqueue(sample())
    result = writer.flush()
    assert result['ok'] is True
    assert writer.metrics['supabase_inserted'] == 1
    assert writer.metrics['supabase_failed'] == 0
    assert writer.metrics['supabase_updated'] == 0


def test_existing_lead_updates_and_commercial_fields_are_not_sent(monkeypatch):
    existing = {'id': 'ABC', 'whatsapp': '55679992339611', 'place_name': 'Empresa', 'website': 'https://old.example', 'instagram': ['https://instagram.com/existing'], 'lead_status': 'enviar', 'followup_count': 0, 'pipeline_stage': 'new'}
    fake, state = make_urlopen([existing])
    monkeypatch.setattr(sw.urllib.request, 'urlopen', fake)
    writer = sw.SupabaseBatchWriter('https://example.supabase.co', 'key')
    writer.enqueue(sample('55679992339611', 'https://new.example'))
    result = writer.flush()
    assert result['ok'] is True
    assert writer.metrics['supabase_updated'] == 1
    posted = state['posts'][-1][0]
    assert posted['id'] == 'ABC'
    assert posted['website'] == 'https://new.example'
    assert 'lead_status' not in posted and 'followup_count' not in posted and 'pipeline_stage' not in posted
    assert state['existing'][0]['lead_status'] == 'enviar'
    assert state['existing'][0]['followup_count'] == 0


def test_empty_discovery_fields_preserve_existing(monkeypatch):
    existing = {'id': 'ABC', 'whatsapp': '5511111111111', 'website': 'https://empresa.com', 'instagram': ['https://instagram.com/empresa'], 'cnpj': '00.000.000/0001-00', 'lead_status': 'enviar', 'followup_count': 0}
    fake, state = make_urlopen([existing])
    monkeypatch.setattr(sw.urllib.request, 'urlopen', fake)
    writer = sw.SupabaseBatchWriter('https://example.supabase.co', 'key')
    writer.enqueue(sample())
    writer.flush()
    posted = state['posts'][-1][0]
    assert posted['website'] == 'https://empresa.com'
    assert posted['instagram'] == ['https://instagram.com/empresa']
    assert posted['cnpj'] == '00.000.000/0001-00'


def test_duplicate_inside_batch_is_resolved_before_http(monkeypatch):
    fake, state = make_urlopen()
    monkeypatch.setattr(sw.urllib.request, 'urlopen', fake)
    writer = sw.SupabaseBatchWriter('https://example.supabase.co', 'key', batch_size=99)
    writer.enqueue(sample('5511111111111'))
    writer.enqueue({**sample('5511111111111'), 'website': 'https://new.example'})
    writer.flush()
    assert writer.metrics['supabase_duplicates_resolved'] == 1
    assert len(state['posts']) == 1
    assert len(state['posts'][0]) == 1


def test_duplicate_409_is_recovered_as_update(monkeypatch):
    existing = {'id': 'ABC', 'whatsapp': '5511111111111', 'website': 'https://old.example', 'lead_status': 'enviar', 'followup_count': 0}
    fake, state = make_urlopen([existing], conflict_once=True)
    monkeypatch.setattr(sw.urllib.request, 'urlopen', fake)
    writer = sw.SupabaseBatchWriter('https://example.supabase.co', 'key')
    writer.enqueue(sample('5511111111111', 'https://new.example'))
    result = writer.flush()
    assert result['ok'] is True
    assert writer.metrics['supabase_conflicts_recovered'] == 1
    assert writer.metrics['supabase_failed'] == 0
    assert state['existing'][0]['id'] == 'ABC'
    assert state['existing'][0]['lead_status'] == 'enviar'


def test_non_duplicate_409_remains_failure(monkeypatch):
    fake, state = make_urlopen()
    def conflict(request, timeout=20):
        if request.method == 'POST':
            raise urllib.error.HTTPError(request.full_url, 409, 'Conflict', {}, Response({'code': 'PGRST123', 'message': 'other conflict'}))
        return fake(request, timeout)
    monkeypatch.setattr(sw.urllib.request, 'urlopen', conflict)
    writer = sw.SupabaseBatchWriter('https://example.supabase.co', 'key')
    writer.enqueue(sample())
    result = writer.flush()
    assert result['ok'] is False
    assert writer.metrics['supabase_conflicts_recovered'] == 0
    assert writer.metrics['supabase_failed'] == 1
