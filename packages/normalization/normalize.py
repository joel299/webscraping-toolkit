from packages.domain.identity import place_identity, normalize_phone
ALLOWED={"place_identity","place_id","cid","data_id","google_maps_url","requested_category","observed_category","source_city","source_state","place_name","total_score","reviews_count","address","phone_raw","whatsapp","website","emails","instagram","facebook","linkedin","legal_name","cnpj","qualification_status","qualification_stage","reject_reason","contact_ready","needs_enrichment","enrichment_complete"}
FOOD={"lanchonete","hamburgueria","restaurante","cafe","cafeteria","pizzaria"}
HEALTH={"clinica","clínica","consultorio","consultório","hospital","odontologia"}

def _first(raw,*keys):
    for k in keys:
        v=raw.get(k)
        if v not in (None, "", []): return v
    return None

def normalize_place(raw: dict, request: dict) -> dict:
    observed=str(_first(raw,"category","categories") or "").strip()
    want=str(request.get("requested_category") or request.get("category") or "").strip()
    wl=want.lower(); ol=observed.lower()
    mismatch=(wl in FOOD and any(x in ol for x in HEALTH)) or (wl in HEALTH and any(x in ol for x in FOOD))
    phone_raw=_first(raw,"phone","phone_raw","whatsapp")
    row={"place_identity":place_identity(raw),"place_id":raw.get("place_id"),"cid":raw.get("cid"),"data_id":raw.get("data_id"),"google_maps_url":_first(raw,"link","google_maps_url","url"),"requested_category":want,"observed_category":observed or None,"source_city":request.get("city"),"source_state":request.get("state"),"place_name":_first(raw,"title","place_name"),"total_score":_first(raw,"review_rating","total_score","rating"),"reviews_count":_first(raw,"review_count","reviews_count"),"address":_first(raw,"complete_address","address"),"phone_raw":phone_raw,"whatsapp":normalize_phone(phone_raw),"website":raw.get("website"),"emails":raw.get("emails") or [],"instagram":raw.get("instagram") or [],"facebook":raw.get("facebook") or [],"linkedin":raw.get("linkedin") or [],"legal_name":raw.get("legal_name"),"cnpj":raw.get("cnpj"),"qualification_status":"rejected" if mismatch else "qualified","qualification_stage":"category_gate","contact_ready":bool(phone_raw),"needs_enrichment":True,"enrichment_complete":False}
    if mismatch: row["reject_reason"]="category_mismatch"
    return {k:v for k,v in row.items() if k in ALLOWED}
