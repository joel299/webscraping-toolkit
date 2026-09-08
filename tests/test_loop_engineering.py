from multiprocessing import Manager

from src.gmaps_playwright_scraper import _promote_social_website, _set_job_phase, classify_business_niche
from src.gmaps_web_ui import JobProxy


def test_jobproxy_update_and_pop_sync_manager_dict():
    with Manager() as manager:
        shared = manager.dict({'job': {'count': 0, 'stale': True}})
        proxy = JobProxy('job', shared, dict(shared['job']))
        proxy.update({'count': 1, 'leads': [{'place_name': 'A'}]})
        assert shared['job']['count'] == 1
        assert shared['job']['leads'][0]['place_name'] == 'A'
        proxy.pop('stale')
        assert 'stale' not in shared['job']


def test_bootstrap_phase_updates_heartbeat_and_log():
    data = {}
    _set_job_phase(data, 'chromium_launching', 'Iniciando Chromium...')
    assert data['last_phase'] == 'chromium_launching'
    assert data['worker_heartbeat_at'] == data['last_activity']
    assert data['log'] == 'Iniciando Chromium...'


def test_social_website_is_promoted_without_losing_discovery():
    detail = {'website': 'https://instagram.com/example', 'instagram': []}
    _promote_social_website(detail)
    assert detail['website'] == ''
    assert detail['instagram'] == ['https://instagram.com/example']


def test_generic_clinica_query_is_eligible_but_veterinary_is_not():
    assert classify_business_niche({'place_name': 'Clínica Médica', 'category': 'Clínica'})
    assert not classify_business_niche({'place_name': 'Clínica Veterinária', 'category': 'Veterinária'})
