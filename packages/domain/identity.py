import hashlib, re, urllib.parse

def _norm(value): return re.sub(r"\s+", " ", str(value or "").strip().lower())

def canonical_url(value):
    if not value: return ""
    p=urllib.parse.urlsplit(str(value).strip())
    query=urllib.parse.parse_qs(p.query, keep_blank_values=False)
    kept={k:v for k,v in query.items() if k in {"cid","data_id","place_id"}}
    return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip("/"),urllib.parse.urlencode(kept,doseq=True),""))

def place_identity(place: dict) -> str:
    for key in ("place_id","cid","data_id"):
        if _norm(place.get(key)): return f"google:{_norm(place[key])}"
    url=canonical_url(place.get("google_maps_url") or place.get("url"))
    if url: return "url:"+hashlib.sha256(url.encode()).hexdigest()[:32]
    seed=f"{_norm(place.get('place_name'))}|{_norm(place.get('address'))}"
    return "place:"+hashlib.sha256(seed.encode()).hexdigest()[:32]
