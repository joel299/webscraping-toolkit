from src.gmaps_playwright_scraper import (
    classify_business_niche,
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
