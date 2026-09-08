"""Incremental persistence for public.prospect_leads_google.

Uses Supabase REST without adding runtime dependencies. Writes only discovery
columns and never sends commercial/follow-up state fields.
"""
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

TABLE_DEFAULT = "prospect_leads_google"
DISCOVERY_FIELDS = (
    "place_name", "total_score", "reviews_count", "address", "website", "whatsapp",
    "categories", "owner_name", "administrator_name", "legal_name", "cnpj",
    "emails", "instagram", "facebook", "linkedin", "source", "source_category",
    "source_city", "source_state", "google_maps_url", "qualification_status",
)
ARRAY_FIELDS = {"emails", "instagram", "facebook", "linkedin"}


def _config():
    base_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    api_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or ""
    table = (os.environ.get("SUPABASE_LEADS_TABLE", TABLE_DEFAULT).strip() or TABLE_DEFAULT)
    conflict_column = (os.environ.get("SUPABASE_CONFLICT_COLUMN", "whatsapp") or "whatsapp").strip()
    return base_url, api_key, table, conflict_column


def supabase_enabled():
    base_url, api_key, _, _ = _config()
    return bool(base_url and api_key)


def _headers(api_key, prefer="return=representation"):
    return {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": prefer,
    }


def _request(url, api_key, method="GET", payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_headers(api_key), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            value = json.loads(body) if body else []
            return response.status, value if isinstance(value, list) else [value]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
        except ValueError:
            detail = {"message": body}
        raise RuntimeError(f"supabase_http_{exc.code}: {detail}") from exc


def _stable_id(lead):
    whatsapp = str(lead.get("whatsapp") or "").strip()
    if whatsapp:
        return f"google:wa:{whatsapp}"
    source = str(lead.get("google_maps_url") or lead.get("place_name") or "unknown")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    return f"google:src:{digest}"


def _row_for_schema(lead, *, category="", city="", state=""):
    row = {}
    for field in DISCOVERY_FIELDS:
        value = lead.get(field)
        if field == "categories":
            value = value or lead.get("category") or category
        elif field == "source_category":
            value = value or category
        elif field == "source_city":
            value = value or city
        elif field == "source_state":
            value = value or state
        elif field == "source":
            value = value or "google_maps"
        elif field == "qualification_status":
            value = value or "qualified"
        if field in ARRAY_FIELDS:
            value = list(dict.fromkeys(value or []))
            if not value:
                continue
        elif value is None or value == "":
            continue
        row[field] = value
    if "whatsapp" in row:
        row["id"] = _stable_id(lead)
    else:
        row["id"] = _stable_id(lead)
    return row


def _table_url(base_url, table):
    return f"{base_url}/rest/v1/{urllib.parse.quote(table, safe='')}"


def _find_existing(base_url, api_key, table, whatsapp, timeout):
    if not whatsapp:
        return None
    query = urllib.parse.urlencode({"whatsapp": f"eq.{whatsapp}", "select": "id", "limit": "1"})
    status, rows = _request(f"{_table_url(base_url, table)}?{query}", api_key, timeout=timeout)
    return rows[0].get("id") if rows and rows[0].get("id") else None


def _write_one(base_url, api_key, table, row, timeout):
    whatsapp = str(row.get("whatsapp") or "").strip()
    existing_id = _find_existing(base_url, api_key, table, whatsapp, timeout)
    if existing_id:
        query = urllib.parse.urlencode({"id": f"eq.{existing_id}"})
        _, rows = _request(f"{_table_url(base_url, table)}?{query}", api_key, method="PATCH", payload=row, timeout=timeout)
        return "updated", rows
    try:
        _, rows = _request(_table_url(base_url, table), api_key, method="POST", payload=row, timeout=timeout)
        return "inserted", rows
    except RuntimeError as exc:
        # Partial unique index conflicts are recovered by requery + PATCH.
        if whatsapp and ("409" in str(exc) or "23505" in str(exc)):
            existing_id = _find_existing(base_url, api_key, table, whatsapp, timeout)
            if existing_id:
                query = urllib.parse.urlencode({"id": f"eq.{existing_id}"})
                _, rows = _request(f"{_table_url(base_url, table)}?{query}", api_key, method="PATCH", payload=row, timeout=timeout)
                return "updated_after_conflict", rows
        raise


def persist_leads(leads, *, job_id="", category="", city="", state="", timeout=30):
    """Insert/update discovery data incrementally and return verified metadata."""
    del job_id  # retained in the call contract; no job_id column exists in target schema
    base_url, api_key, table, _ = _config()
    if not base_url or not api_key:
        return {"enabled": False, "persisted": 0, "verified": False}
    rows = [_row_for_schema(lead, category=category, city=city, state=state) for lead in (leads or [])]
    if not rows:
        return {"enabled": True, "persisted": 0, "verified": True, "actions": []}
    actions = []
    try:
        for row in rows:
            action, returned = _write_one(base_url, api_key, table, row, timeout)
            actions.append(action)
            if not returned:
                raise RuntimeError("supabase_readback_empty")
        return {
            "enabled": True,
            "persisted": len(rows),
            "requested": len(rows),
            "verified": True,
            "actions": actions,
        }
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, RuntimeError) as exc:
        return {
            "enabled": True,
            "persisted": len(actions),
            "requested": len(rows),
            "verified": False,
            "actions": actions,
            "error": str(exc),
        }
