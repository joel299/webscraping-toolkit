#!/usr/bin/env python3
"""Benchmark the scraper API without persisting lead records."""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request


def request_json(url, method="GET", body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=data, method=method)
    if data:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def run_once(base_url, args):
    payload = {
        "category": args.category,
        "city": args.city,
        "state": args.state,
        "max_leads": args.max_leads,
        "mode": args.mode,
        "auto_enrich": args.mode == "full",
    }
    if args.webhook:
        payload["webhook"] = args.webhook
    started = time.perf_counter()
    created = request_json(base_url.rstrip("/") + "/api/scrape", "POST", payload)
    job_id = created["job_id"]
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        job = request_json(base_url.rstrip("/") + "/api/job/" + job_id)
        if job.get("status") in {"completed", "enriched", "error"}:
            elapsed_ms = (time.perf_counter() - started) * 1000
            metrics = {
                "mode": args.mode,
                "target_leads": args.max_leads,
                "job_id": job_id,
                "elapsed_ms": round(elapsed_ms, 2),
                "candidates_found": job.get("candidates_found", 0),
                "leads_found": len(job.get("leads") or []),
                "time_to_first_lead_ms": job.get("time_to_first_lead_ms", ""),
                "candidate_search_ms": job.get("candidate_search_ms", ""),
                "details_ms": job.get("details_ms", ""),
                "scrape_total_ms": job.get("scrape_total_ms", ""),
                "enrichment_ms": job.get("enrichment_ms", 0),
                "webhook_ms": job.get("webhook_ms", 0),
                "total_pipeline_ms": job.get("total_pipeline_ms", elapsed_ms),
                "with_phone": job.get("leads_with_phone", 0),
                "with_whatsapp": job.get("leads_with_whatsapp", 0),
                "with_website": job.get("leads_with_website", 0),
                "duplicates_removed": job.get("duplicates_removed", 0),
                "webhook_http_status": (job.get("n8n_response") or {}).get("status", 0),
                "webhook_success": bool((job.get("n8n_response") or {}).get("ok")),
                "queries_started": job.get("queries_started", 0),
                "queries_completed": job.get("queries_completed", 0),
                "candidate_cards_seen": job.get("candidate_cards_seen", 0),
                "candidates_prequalified": job.get("candidates_prequalified", 0),
                "details_opened": job.get("details_opened", 0),
                "rejected_before_web_results": job.get("rejected_before_web_results", 0),
                "web_results_attempted": job.get("web_results_attempted", 0),
                "web_results_skipped": job.get("web_results_skipped", 0),
                "web_results_instagram_found": job.get("web_results_instagram_found", 0),
                "time_to_first_qualified_lead_ms": job.get("time_to_first_qualified_lead_ms", ""),
                "average_detail_ms": job.get("average_detail_ms", ""),
                "p50_detail_ms": job.get("p50_detail_ms", ""),
                "p95_detail_ms": job.get("p95_detail_ms", ""),
                "max_detail_ms": job.get("max_detail_ms", ""),
                "performance": job.get("performance", {}),
                "status": job.get("status"),
            }
            return metrics
        time.sleep(args.poll_interval)
    raise TimeoutError(f"job {job_id} did not finish within {args.timeout}s")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8990")
    parser.add_argument("--category", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--max-leads", type=int, default=50)
    parser.add_argument("--mode", choices=("full", "fast"), required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--webhook", default="", help="Only use an authorized test webhook")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--poll-interval", type=float, default=1.5)
    args = parser.parse_args()

    runs = [run_once(args.base_url, args) for _ in range(args.runs)]
    total_ms = [run["total_pipeline_ms"] for run in runs if isinstance(run["total_pipeline_ms"], (int, float))]
    leads_per_min = [run["leads_found"] / (run["total_pipeline_ms"] / 60000) for run in runs if run["total_pipeline_ms"]]
    summary = {
        "mode": args.mode.upper(),
        "runs": runs,
        "median_total_pipeline_ms": round(statistics.median(total_ms), 2) if total_ms else None,
        "median_leads_per_minute": round(statistics.median(leads_per_min), 2) if leads_per_min else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
