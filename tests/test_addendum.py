from src.gmaps_playwright_scraper import (
    adaptive_query_limit,
    candidate_identity,
    classify_business_niche,
    discovery_limits,
    discovery_should_stop,
    generate_query_variations,
    low_yield_should_stop,
    preserve_google_instagram,
    normalize_place_name,
    place_name_from_maps_url,
    resolve_place_name,
    extract_basic_place_detail,
    extract_optional_google_web_results,
    route_fast_resources,
    summarize_samples,
    _prequalify_card,
    parse_google_web_result_payload,
    parse_rating,
    parse_reviews,
)
from src.gmaps_web_ui import make_payload


def test_niche_classifier_rejects_negative_terms():
    assert classify_business_niche({'title': 'Clínica de Estética Facial'}) is True
    assert classify_business_niche({'title': 'Estética Animal Pet Shop'}) is False
    assert classify_business_niche({'title': 'Barbearia Estética Masculina'}) is False


def test_card_value_parsers():
    assert parse_rating('Clínica · 4,8 · 183 avaliações') == 4.8
    assert parse_reviews('Clínica · 4,8 · 1,2 mil avaliações') == 1200


def test_google_web_results_keep_metadata_and_sources():
    result = parse_google_web_result_payload({
        'text': 'CNPJ: 00.000.000/0001-00',
        'links': [
            {
                'url': 'https://www.instagram.com/empresa',
                'title': 'Empresa no Instagram',
                'snippet': 'Agende sua avaliação pelo WhatsApp',
            },
            {
                'url': 'https://doctoralia.com.br/empresa',
                'title': 'Empresa | Doctoralia',
                'snippet': 'Consulta e agendamento',
            },
        ],
    })
    assert result['instagram'] == ['https://www.instagram.com/empresa']
    assert result['cnpj'] == '00.000.000/0001-00'
    assert result['web_results'][0]['type'] == 'instagram'
    assert result['web_results'][0]['domain'] == 'instagram.com'
    assert result['web_results'][0]['snippet'] == 'Agende sua avaliação pelo WhatsApp'
    assert result['web_results'][1]['type'] == 'directory'


def test_payload_preserves_legacy_and_addendum_fields():
    payload = make_payload({'category': 'estética', 'city': 'Campo Grande', 'state': 'MS', 'leads': [{
        'place_name': 'Clínica Exemplo',
        'total_score': '4.8',
        'reviews_count': '183',
        'whatsapp': '5567999999999',
        'web_results': [{'type': 'instagram', 'url': 'https://instagram.com/exemplo'}],
        'google_sponsored': True,
        'instagram_source': 'google_web_results',
        'cnpj_source': 'google_web_results',
        'qualification_status': 'qualified',
    }]})
    lead = payload['leads'][0]
    assert lead['nome'] == 'Clínica Exemplo'
    assert lead['nota'] == '4.8'
    assert lead['whatsapp'] == '5567999999999'
    assert lead['google_sponsored'] is True
    assert lead['web_results'][0]['type'] == 'instagram'
    assert lead['qualification_status'] == 'qualified'


def test_incremental_discovery_defaults_and_adaptive_limit(monkeypatch):
    for key in ('SCRAPER_OVERSAMPLING_FACTOR', 'SCRAPER_QUERY_CANDIDATE_LIMIT', 'SCRAPER_MAX_SCROLLS_PER_QUERY', 'SCRAPER_SCROLL_WAIT_MS', 'SCRAPER_MAX_NO_NEW_SCROLLS', 'SCRAPER_LOW_YIELD_QUERY_THRESHOLD', 'SCRAPER_MAX_LOW_YIELD_QUERIES', 'SCRAPER_REUSE_DETAIL_PAGE'):
        monkeypatch.delenv(key, raising=False)
    limits = discovery_limits(100)
    assert limits['max_pool'] == 150
    assert limits['query_limit'] == 50
    assert limits['max_scrolls'] == 18
    assert limits['scroll_wait_ms'] == 1500
    assert limits['max_no_new_scrolls'] == 3
    assert adaptive_query_limit(10, 50) == 20
    assert adaptive_query_limit(70, 50) == 50


def test_incremental_discovery_stop_and_low_yield_rules():
    assert discovery_should_stop(10, 10) is True
    assert discovery_should_stop(9, 10) is False
    assert low_yield_should_stop(1, 5, 2) is False
    assert low_yield_should_stop(2, 5, 2) is True


def test_prequalification_happens_before_details_and_identity_is_stable():
    rejected = {'title': 'Clínica de Estética', 'card_text': '4,2 · 8 avaliações', 'rating': 4.2, 'reviews_count': 8}
    assert _prequalify_card(rejected, 'estética') == 'rating'
    accepted = {'title': 'Clínica de Estética', 'card_text': '4,8 · 80 avaliações', 'rating': 4.8, 'reviews_count': 80}
    assert _prequalify_card(accepted, 'estética') == ''
    item = {'href': 'https://www.google.com/maps/place/X/?q=1', 'title': 'X'}
    assert candidate_identity(item) == candidate_identity({'href': item['href'], 'title': 'X diferente'})


def test_aesthetic_query_order_prioritizes_high_intent():
    queries = generate_query_variations('estética', 'Campo Grande', 'Mato Grosso do Sul')
    assert queries[0].startswith('clínica de estética Campo Grande')
    assert any('harmonização facial' in query for query in queries[:4])


def test_fast_preserves_instagram_found_by_google_results():
    assert preserve_google_instagram([
        'https://www.instagram.com/empresa/',
        'https://www.instagram.com/empresa/',
    ]) == ['https://www.instagram.com/empresa/']


def test_place_name_resolution_ignores_generic_maps_title():
    url = 'https://www.google.com.br/maps/place/Flowers+Clinic+-+Cl%C3%ADnica+de+Est%C3%A9tica+Avan%C3%A7ada+por+Dra.+Flora+Martinez/'
    assert normalize_place_name('Google Maps') == ''
    assert place_name_from_maps_url(url) == 'Flowers Clinic - Clínica de Estética Avançada por Dra. Flora Martinez'
    assert resolve_place_name({'place_name': 'Google Maps'}, {}, url) == 'Flowers Clinic - Clínica de Estética Avançada por Dra. Flora Martinez'


def test_place_name_resolution_prefers_card_title_over_url():
    url = 'https://www.google.com.br/maps/place/Clinica+de+Estetica+Claudia+Massolim+%7C+Campo+Grande+MS/'
    assert resolve_place_name({'place_name': 'Google Maps'}, {'title': 'Clínica de Estética Cláudia Massolim | Campo Grande MS'}, url) == 'Clínica de Estética Cláudia Massolim | Campo Grande MS'


def test_fast_optional_web_results_uses_quick_limits(monkeypatch):
    calls = []

    def fake_extract(page, max_scrolls=None, scroll_delay_ms=None):
        calls.append((max_scrolls, scroll_delay_ms))
        return {'website': '', 'instagram': [], 'cnpj': '', 'web_results': []}

    monkeypatch.setattr('src.gmaps_playwright_scraper.extract_google_web_results', fake_extract)
    extract_optional_google_web_results(object(), fast=True)
    assert calls == [(1, 200)]


def test_basic_detail_does_not_call_optional_results(monkeypatch):
    calls = []

    def fake_extract(*args, **kwargs):
        calls.append(kwargs.get('include_optional'))
        return {'place_name': 'Clínica', 'instagram': [], 'web_results': []}

    monkeypatch.setattr('src.gmaps_playwright_scraper._extract_place_detail', fake_extract)
    extract_basic_place_detail(object(), fast=True)
    assert calls == [False]


def test_resource_blocker_only_aborts_heavy_types():
    actions = []

    class Route:
        def abort(self):
            actions.append('abort')

        def continue_(self):
            actions.append('continue')

    class Request:
        def __init__(self, resource_type):
            self.resource_type = resource_type

    for resource_type in ('image', 'media', 'font', 'document', 'script', 'xhr', 'fetch'):
        route_fast_resources(Route(), Request(resource_type))
    assert actions == ['abort', 'abort', 'abort', 'continue', 'continue', 'continue', 'continue']


def test_detail_sample_summary_is_aggregated():
    summary = summarize_samples([100, 200, 400, None])
    assert summary['count'] == 3
    assert summary['min_ms'] == 100
    assert summary['max_ms'] == 400
