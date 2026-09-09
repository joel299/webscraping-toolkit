"""Safe batch persistence for Google Maps discovery leads in Supabase REST."""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

try:
    from .gmaps_playwright_scraper import format_whatsapp, parse_rating, parse_reviews, stable_source_key
except ImportError:
    from gmaps_playwright_scraper import format_whatsapp, parse_rating, parse_reviews, stable_source_key

TABLE = "prospect_leads_google"
DISCOVERY_COLUMNS = {
    "id", "place_name", "total_score", "reviews_count", "address", "website",
    "whatsapp", "categories", "legal_name", "cnpj", "emails", "instagram",
    "facebook", "linkedin", "source", "source_category", "source_city",
    "source_state", "google_maps_url", "qualification_status", "qualification_stage",
    "needs_enrichment", "enrichment_complete", "contact_ready",
}
IDENTITY_COLUMNS = ("whatsapp", "google_maps_url", "id")


def _int_or_none(value):
    parsed = parse_reviews(value)
    return parsed if parsed is not None else None


def _non_empty(value):
    return value not in (None, "", [], {}, False)


def _valid_field_count(row):
    return sum(_non_empty(value) for key, value in row.items() if key not in {"id", "source"})


def _merge_non_empty(existing, incoming):
    merged = dict(existing or {})
    for key, value in incoming.items():
        if _non_empty(value):
            merged[key] = value
    return merged


def lead_row(lead: dict, category: str = "", city: str = "", state: str = "") -> dict:
    """Map only discovery fields; commercial fields are deliberately excluded."""
    row = {
        "id": stable_source_key(lead),
        "place_name": str(lead.get("place_name") or "").strip(),
        "total_score": parse_rating(lead.get("total_score")),
        "reviews_count": _int_or_none(lead.get("reviews_count")),
        "address": str(lead.get("address") or "").strip() or None,
        "website": str(lead.get("website") or "").strip() or None,
        "whatsapp": format_whatsapp(lead.get("whatsapp") or lead.get("phone_raw")) or None,
        "categories": str(lead.get("category") or "").strip() or None,
        "legal_name": str(lead.get("legal_name") or "").strip() or None,
        "cnpj": str(lead.get("cnpj") or "").strip() or None,
        "emails": list(dict.fromkeys(lead.get("emails") or [])),
        "instagram": list(dict.fromkeys(lead.get("instagram") or [])),
        "facebook": list(dict.fromkeys(lead.get("facebook") or [])),
        "linkedin": list(dict.fromkeys(lead.get("linkedin") or [])),
        "source": "google_maps",
        "source_category": category or None,
        "source_city": city or None,
        "source_state": state or None,
        "google_maps_url": str(lead.get("google_maps_url") or "").strip() or None,
        "qualification_status": str(lead.get("qualification_status") or "qualified"),
        "qualification_stage": "google_maps_discovery",
        "needs_enrichment": True,
        "enrichment_complete": False,
        "contact_ready": bool(format_whatsapp(lead.get("whatsapp") or lead.get("phone_raw"))),
    }
    return {key: value for key, value in row.items() if key in DISCOVERY_COLUMNS}


class SupabaseBatchWriter:
    def __init__(self, url=None, key=None, batch_size=None, flush_interval_ms=None):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.batch_size = max(1, int(batch_size or os.environ.get("SUPABASE_BATCH_SIZE", "10")))
        self.flush_interval_ms = max(0, int(flush_interval_ms or os.environ.get("SUPABASE_FLUSH_INTERVAL_MS", "1000")))
        self._buffer = []
        self._lock = threading.Lock()
        self.metrics = {
            "supabase_inserted": 0,
            "supabase_updated": 0,
            "supabase_unchanged": 0,
            "supabase_duplicates_resolved": 0,
            "supabase_conflicts_recovered": 0,
            "supabase_failed": 0,
            "supabase_batches": 0,
        }

    @property
    def enabled(self):
        return bool(self.url and self.key)

    def enqueue(self, lead, category="", city="", state=""):
        with self._lock:
            self._buffer.append(lead_row(lead, category, city, state))
            should_flush = len(self._buffer) >= self.batch_size
        if should_flush:
            return self.flush()
        return {"ok": True, "queued": True}

    def _headers(self):
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def _request_json(self, method, url, body=None, headers=None):
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
            method=method,
            headers=headers or self._headers(),
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8") or "[]")

    def _lookup_existing(self, rows):
        phones = sorted({row["whatsapp"] for row in rows if row.get("whatsapp")})
        if not phones:
            return {}
        value = "in.({})".format(",".join(phones))
        columns = ",".join(sorted(DISCOVERY_COLUMNS | {"lead_status", "followup_count", "pipeline_stage"}))
        query = urllib.parse.urlencode({"whatsapp": value, "select": columns})
        existing = self._request_json("GET", f"{self.url}/rest/v1/{TABLE}?{query}")
        return {str(row.get("whatsapp")): row for row in existing if row.get("whatsapp")}

    def _dedupe_rows(self, rows):
        by_identity = {}
        duplicates = 0
        for row in rows:
            identity = row.get("whatsapp") or row.get("google_maps_url") or row.get("id")
            if identity not in by_identity:
                by_identity[identity] = row
                continue
            duplicates += 1
            current = by_identity[identity]
            if _valid_field_count(row) > _valid_field_count(current):
                by_identity[identity] = _merge_non_empty(current, row)
            else:
                by_identity[identity] = _merge_non_empty(row, current)
        return list(by_identity.values()), duplicates

    @staticmethod
    def _is_duplicate_error(detail):
        text = str(detail or "").lower()
        return any(token in text for token in ("23505", "duplicate key", "unique constraint", "unique violation"))

    @staticmethod
    def _error_detail(exc):
        try:
            return exc.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            return str(exc)

    def _upsert(self, rows):
        body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
        query = urllib.parse.urlencode({"on_conflict": "id"})
        headers = {**self._headers(), "Prefer": "resolution=merge-duplicates,return=representation"}
        request = urllib.request.Request(
            f"{self.url}/rest/v1/{TABLE}?{query}",
            data=body,
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "[]")

    def flush(self):
        with self._lock:
            rows = self._buffer
            self._buffer = []
        if not rows:
            return {"ok": True, "count": 0}
        if not self.enabled:
            self.metrics["supabase_failed"] += len(rows)
            return {"ok": False, "count": len(rows), "error": "Supabase não configurado"}

        rows, deduped = self._dedupe_rows(rows)
        self.metrics["supabase_duplicates_resolved"] += deduped
        try:
            existing_by_phone = self._lookup_existing(rows)
            prepared = []
            existed = {}
            changed_ids = set()
            for row in rows:
                existing = existing_by_phone.get(row.get("whatsapp")) if row.get("whatsapp") else None
                if existing:
                    if any(_non_empty(value) and value != existing.get(key) for key, value in row.items() if key in DISCOVERY_COLUMNS and key != "id"):
                        changed_ids.add(existing["id"])
                    row = _merge_non_empty(existing, row)
                    row = {key: value for key, value in row.items() if key in DISCOVERY_COLUMNS}
                    row["id"] = existing["id"]
                    existed[row["id"]] = existing
                prepared.append(row)
            try:
                upsert_status, returned = self._upsert(prepared)
            except urllib.error.HTTPError as exc:
                detail = self._error_detail(exc)
                if exc.code not in (409, 400) or not self._is_duplicate_error(detail):
                    raise
                # A concurrent writer won between lookup and insert. Re-read
                # the identity map and retry by the winner's id.
                self.metrics["supabase_conflicts_recovered"] += 1
                existing_by_phone = self._lookup_existing(prepared)
                retry_rows = []
                for row in prepared:
                    existing = existing_by_phone.get(row.get("whatsapp")) if row.get("whatsapp") else None
                    if existing:
                        row = _merge_non_empty(existing, row)
                        row = {key: value for key, value in row.items() if key in DISCOVERY_COLUMNS}
                        row["id"] = existing["id"]
                        existed[row["id"]] = existing
                    retry_rows.append(row)
                upsert_status, returned = self._upsert(retry_rows)

            self.metrics["supabase_batches"] += 1
            for row in prepared:
                if row["id"] in existed:
                    self.metrics["supabase_updated" if row["id"] in changed_ids else "supabase_unchanged"] += 1
                elif upsert_status == 201:
                    self.metrics["supabase_inserted"] += 1
                else:
                    self.metrics["supabase_unchanged"] += 1
            return {"ok": True, "count": len(returned), "rows": returned, "deduped": deduped}
        except urllib.error.HTTPError as exc:
            detail = self._error_detail(exc)
            self.metrics["supabase_failed"] += len(rows)
            return {"ok": False, "count": len(rows), "error": f"HTTP {exc.code}: {detail or exc.reason}"}
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            self.metrics["supabase_failed"] += len(rows)
            return {"ok": False, "count": len(rows), "error": str(exc)}


def persist_leads_batch(leads: Iterable[dict], category="", city="", state=""):
    writer = SupabaseBatchWriter()
    results = []
    for lead in leads:
        results.append(writer.enqueue(lead, category, city, state))
    results.append(writer.flush())
    return {"enabled": writer.enabled, **writer.metrics, "results": results}
