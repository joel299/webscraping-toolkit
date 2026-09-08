import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import src.gmaps_web_ui as web_ui


def http_json(url, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class FakeProcess:
    def __init__(self, target, args, daemon=True):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        return None


def run_server(monkeypatch):
    jobs = {}
    monkeypatch.setattr(web_ui, "get_jobs_dict", lambda: jobs)
    monkeypatch.setattr(web_ui.multiprocessing, "Process", FakeProcess)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_ui.CustomHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, jobs, f"http://127.0.0.1:{server.server_address[1]}"


def test_health_is_process_only_and_public(monkeypatch):
    server, _, base = run_server(monkeypatch)
    try:
        status, body = http_json(f"{base}/api/health")
        assert status == 200
        assert body == {"ok": True, "service": "webscraping-toolkit"}
    finally:
        server.shutdown()
        server.server_close()


def test_scrape_and_job_poll_stay_available_over_http(monkeypatch):
    server, jobs, base = run_server(monkeypatch)
    try:
        status, started = http_json(
            f"{base}/api/scrape",
            method="POST",
            payload={
                "category": "clínica",
                "city": "Campo Grande",
                "state": "Mato Grosso do Sul",
                "max_leads": 1,
                "mode": "fast",
                "auto_enrich": False,
            },
        )
        assert status == 200
        assert started["status"] == "started"
        job_id = started["job_id"]
        assert job_id in jobs

        status, job = http_json(f"{base}/api/job/{job_id}")
        assert status == 200
        assert job["job_id"] == job_id
        assert job["status"] == "pending"

        health_status, health = http_json(f"{base}/api/health")
        assert health_status == 200
        assert health["ok"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_unknown_job_is_404_not_connection_failure(monkeypatch):
    server, _, base = run_server(monkeypatch)
    try:
        status, body = http_json(f"{base}/api/job/teste")
        assert status == 404
        assert body == {"error": "job not found"}
    finally:
        server.shutdown()
        server.server_close()
