import os

import src.gmaps_playwright_scraper as scraper
import src.gmaps_web_ui as web_ui


def test_deterministic_shards_are_disjoint_and_cover_queries():
    queries = [f'q{i}' for i in range(9)]
    a = scraper.deterministic_query_shard(queries, 0, 2)
    b = scraper.deterministic_query_shard(queries, 1, 2)
    assert set(a).isdisjoint(b)
    assert set(a) | set(b) == set(queries)


def test_global_merge_is_idempotent_and_bounded():
    leads = [
        {'google_maps_url': 'https://maps.google.test/place/a', 'place_name': 'A'},
        {'google_maps_url': 'https://maps.google.test/place/a', 'place_name': 'A duplicate'},
        {'google_maps_url': 'https://maps.google.test/place/b', 'place_name': 'B'},
    ]
    merged = web_ui._dedupe_leads_global(leads, 2)
    assert [x['google_maps_url'] for x in merged] == [
        'https://maps.google.test/place/a', 'https://maps.google.test/place/b'
    ]
    assert web_ui._dedupe_leads_global(merged + merged, 100) == merged


def test_multi_worker_aggregates_failure_without_blocking_sibling(monkeypatch):
    class FakeProcess:
        calls = []
        def __init__(self, target, args, daemon=True):
            self.target, self.args = target, args
        def start(self):
            FakeProcess.calls.append(self.args)
            worker_id = self.args[-1]
            jobs = self.args[6]
            index = self.args[8]
            if index == 0:
                jobs[worker_id] = dict(jobs[worker_id], status='error', leads=[], worker_index=index)
            else:
                jobs[worker_id] = dict(jobs[worker_id], status='completed', worker_index=index,
                                       leads=[{'google_maps_url': 'https://maps.google.test/place/a', 'place_name': 'A'}])
        def join(self):
            return None

    monkeypatch.setattr(web_ui.multiprocessing, 'Process', FakeProcess)
    jobs = {'job': {'job_id': 'job', 'category': 'c', 'city': 'x', 'state': 'y'}}
    monkeypatch.setenv('SCRAPER_WORKER_RETRIES', '0')
    web_ui.multi_worker_scrape_process('job', 'c', 'x', 'y', 10, '', jobs, 'fast', 2)
    assert jobs['job']['status'] == 'partial'
    assert jobs['job']['stop_reason'] == 'worker_error'
    assert jobs['job']['current_count'] == 1
    assert jobs['job']['worker_failures'] == 1
    assert jobs['job']['worker_progress'][1]['current_count'] == 1
