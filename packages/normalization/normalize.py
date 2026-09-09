from packages.domain.identity import place_identity
ALLOWED={"place_identity","place_id","google_maps_url","requested_category","observed_category","source_city","source_state","place_name","total_score","reviews_count","address","whatsapp","website","emails","instagram","facebook","linkedin","legal_name","cnpj","qualification_status","qualification_stage","contact_ready","needs_enrichment","enrichment_complete"}
CATEGORY_REJECTS={"clinica","clínica","consultorio","consultório","hospital","centro médico","centro medico"}

def normalize_place(raw: dict, request: dict) -> dict:
    observed=str(raw.get("category") or raw.get("categories") or "").strip()
    mismatch=request["requested_category"].strip().lower() in {"lanchonete","restaurante"} and any(x in observed.lower() for x in CATEGORY_REJECTS)
    row={"place_identity":place_identity(raw),"place_id":raw.get("place_id") or raw.get("data_id"),"google_maps_url":raw.get("google_maps_url") or raw.get("url"),"requested_category":request["requested_category"],"observed_category":observed or None,"source_city":request["city"],"source_state":request["state"],"place_name":raw.get("place_name") or raw.get("title"),"total_score":raw.get("total_score") or raw.get("rating"),"reviews_count":raw.get("reviews_count"),"address":raw.get("address"),"whatsapp":raw.get("whatsapp") or raw.get("phone"),"website":raw.get("website"),"emails":raw.get("emails") or [],"instagram":raw.get("instagram") or [],"facebook":raw.get("facebook") or [],"linkedin":raw.get("linkedin") or [],"legal_name":raw.get("legal_name"),"cnpj":raw.get("cnpj"),"qualification_status":"rejected" if mismatch else "qualified","qualification_stage":"category_gate","contact_ready":bool(raw.get("whatsapp") or raw.get("phone")),"needs_enrichment":True,"enrichment_complete":False}
    if mismatch: row["reject_reason"]="category_mismatch"
    return {k:v for k,v in row.items() if k in ALLOWED or k=="reject_reason"}
