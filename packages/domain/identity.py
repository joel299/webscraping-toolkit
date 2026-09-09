import hashlib, re, urllib.parse

def _norm(value): return re.sub(r"\s+", " ", str(value or "").strip().lower())
def normalize_phone(value):
    digits=re.sub(r"\D", "", str(value or ""))
    if digits.startswith("00"): digits=digits[2:]
    if digits.startswith("55") and len(digits)>=12: return digits
    if len(digits) in (10,11): return "55"+digits
    return digits or None

def canonical_url(value):
    if not value: return ""
    p=urllib.parse.urlsplit(str(value).strip()); q=urllib.parse.parse_qs(p.query,keep_blank_values=False)
    kept={k:v for k,v in q.items() if k in {"cid","data_id","place_id"}}
    return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip("/"),urllib.parse.urlencode(kept,doseq=True),""))

def place_identity(place: dict) -> str:
    for key in ("place_id","cid","data_id"):
        if _norm(place.get(key)): return f"google:{_norm(place[key])}"
    url=canonical_url(place.get("link") or place.get("google_maps_url") or place.get("url"))
    if url: return "url:"+hashlib.sha256(url.encode()).hexdigest()[:32]
    phone=normalize_phone(place.get("phone") or place.get("phone_raw") or place.get("whatsapp"))
    if phone: return "phone:"+phone
    seed=f"{_norm(place.get('place_name') or place.get('title'))}|{_norm(place.get('address') or place.get('complete_address'))}"
    return "place:"+hashlib.sha256(seed.encode()).hexdigest()[:32]

def identity_aliases(place: dict):
    out=[]
    for key in ("place_id","cid","data_id"):
        if _norm(place.get(key)): out.append("google:"+_norm(place[key]))
    url=canonical_url(place.get("link") or place.get("google_maps_url") or place.get("url"))
    if url: out.append("url:"+hashlib.sha256(url.encode()).hexdigest()[:32])
    phone=normalize_phone(place.get("phone") or place.get("phone_raw") or place.get("whatsapp"))
    if phone: out.append("phone:"+phone)
    return list(dict.fromkeys(out))
