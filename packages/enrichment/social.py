from urllib.parse import urlsplit

def promote_social_website(place: dict) -> dict:
    """Promote only explicit public social URLs; never invent URLs."""
    urls=[]
    website=str(place.get('website') or '').strip()
    if website: urls.append(website)
    for key in ('social_links','links'):
        value=place.get(key) or []
        urls.extend(value if isinstance(value,list) else [value])
    out={k:list(place.get(k) or []) for k in ('instagram','facebook','linkedin')}
    for value in urls:
        u=str(value).strip(); host=urlsplit(u).netloc.lower().removeprefix('www.')
        if host in ('instagram.com','facebook.com','fb.com','linkedin.com'):
            key='instagram' if host=='instagram.com' else ('linkedin' if host=='linkedin.com' else 'facebook')
            if u not in out[key]: out[key].append(u)
    return out
