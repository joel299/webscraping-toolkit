import csv,hashlib,io,json,os,threading,time,urllib.request,uuid
from datetime import datetime,timezone
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
SUPA=os.getenv("SUPABASE_URL","").rstrip("/"); KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY",""); GOSOMS=[os.getenv("GOSOM_A_URL","http://stark-v2-maps-a:8080"),os.getenv("GOSOM_B_URL","http://stark-v2-maps-b:8080")]; CANCEL=set(); ACCEPTED={}; ACCEPTED_LOCK=threading.Lock()
def now(): return datetime.now(timezone.utc).isoformat()
def h(): return {"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"return=representation"}
def supa(path,method="GET",data=None):
 r=urllib.request.Request(SUPA+path,method=method,headers=h(),data=json.dumps(data).encode() if data is not None else None)
 with urllib.request.urlopen(r,timeout=30) as x:return x.status,json.loads(x.read() or b"null")
def remote(base,path,method="GET",data=None):
 r=urllib.request.Request(base+path,method=method,headers={"Content-Type":"application/json"},data=json.dumps(data).encode() if data is not None else None)
 with urllib.request.urlopen(r,timeout=60) as x:return x.status,json.loads(x.read() or b"null")
def ident(x): return hashlib.sha256((x.get("place_id") or x.get("link") or x.get("title","")+x.get("address","")).lower().encode()).hexdigest()[:40]
def norm(x,req,w):
 cat=(x.get("category") or "").lower(); want=req["category"].lower(); food=("lanchonete","hamburgueria","restaurante","cafe"); health=("clinica","clínica","consultorio","consultório","hospital","odontologia"); bad=(want in food and any(z in cat for z in health)) or (want in health and any(z in cat for z in food))
 return {"place_identity":ident(x),"place_id":x.get("place_id"),"google_maps_url":x.get("link"),"requested_category":req["category"],"observed_category":x.get("category"),"source_city":req["city"],"source_state":req["state"],"place_name":x.get("title"),"total_score":x.get("review_rating"),"reviews_count":x.get("review_count"),"address":x.get("address"),"whatsapp":x.get("phone"),"website":x.get("website"),"qualification_status":"rejected" if bad else "qualified","qualification_stage":"category_gate","reject_reason":"category_mismatch" if bad else None,"contact_ready":bool(x.get("phone")),"worker_id":w}
def patch(path,data):
 try:supa(path,"PATCH",data)
 except Exception:pass
def ev(job,shard,typ,item=None,extra=None):
 try:supa("/rest/v1/scraper_job_events","POST",[{"job_id":job,"shard_id":shard,"event_type":typ,"place_identity":item.get("place_identity") if item else None,"payload":{**(item or {}),**(extra or {})},"occurred_at":now()}])
 except Exception:pass
def worker(job,req,w,shard):
 base=GOSOMS[0 if w=="A" else 1]
 try:
  patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"status":"running","started_at":now()}); kw=f"{req['category']} {req['city']} {req['state']}" if w=="A" else f"{req['category']} {req['city']} {req['state']} hamburgueria"; _,c=remote(base,"/api/v1/jobs","POST",{"name":"V2 "+job+" "+w,"keywords":[kw],"lang":"pt","zoom":15,"depth":1,"max_time":300}); pid=c["id"]; patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"provider_job_id":pid,"query_set":[kw]})
  for _ in range(120):
   if job in CANCEL: remote(base,"/api/v1/jobs/"+pid,"DELETE"); raise RuntimeError("cancelled")
   _,j=remote(base,"/api/v1/jobs/"+pid); st=str(j.get("Status","")).lower()
   if st=="ok":break
   if st in ("failed","error"):raise RuntimeError(st)
   time.sleep(3)
  raw=urllib.request.urlopen(base+"/api/v1/jobs/"+pid+"/download",timeout=90).read().decode(errors="replace"); rows=list(csv.DictReader(io.StringIO(raw))); patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"status":"completed","completed_at":now(),"qualified_count":len(rows)})
  for x in rows:
   item=norm(x,req,w)
   with ACCEPTED_LOCK:
    seen=ACCEPTED.setdefault(job,set())
    if item["place_identity"] in seen or len(seen)>=req["max_leads"]:
     continue
    seen.add(item["place_identity"])
   ev(job,shard,"place_discovered",item); ev(job,shard,"place_rejected" if item["qualification_status"]=="rejected" else "place_ready",item)
   if req.get("persist") and item["qualification_status"]=="qualified":
    try:
     payload={"id":item["place_identity"],"place_name":item["place_name"],"total_score":item["total_score"],"reviews_count":item["reviews_count"],"address":item["address"],"website":item["website"],"whatsapp":item["whatsapp"],"source":"google_maps","source_category":item["requested_category"],"observed_category":item["observed_category"],"source_city":item["source_city"],"source_state":item["source_state"],"google_maps_url":item["google_maps_url"],"qualification_status":"qualified","qualification_stage":"category_gate","contact_ready":item["contact_ready"],"v2_last_job_id":job,"v2_worker_label":w,"persistence_verified":True,"persistence_verified_at":now(),"lead_status":"new","pipeline_stage":"new","responded":False,"converted":False}
     status,rep=supa("/rest/v1/prospect_leads_google?on_conflict=id","POST",[payload]); ev(job,shard,"place_persisted",item,{"persistence_status":"written","write_status":status,"representation_count":len(rep) if isinstance(rep,list) else 0})
    except Exception as pe: ev(job,shard,"place_persistence_failed",item,{"persistence_status":"failed","error":str(pe)[:120]})
  ev(job,shard,"shard_completed",extra={"raw_candidates":len(rows),"provider_job_id":pid})
 except Exception as e: patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"status":"error","stop_reason":str(e)[:160]}); ev(job,shard,"shard_failed",extra={"error":str(e)[:160]})
def run(job,req,shards):
 ts=[threading.Thread(target=worker,args=(job,req,s["worker_id"],s["shard_id"]),daemon=True) for s in shards]
 for t in ts:t.start()
 for t in ts:t.join()
 try:
  _,events=supa("/rest/v1/scraper_job_events?job_id=eq."+job+"&select=*"); ids={e.get("place_identity") for e in events if e.get("place_identity")}; q=len({e.get("place_identity") for e in events if e.get("event_type")=="place_ready" and e.get("place_identity")}); failed=any(e.get("event_type")=="shard_failed" for e in events); patch("/rest/v1/scraper_jobs?id=eq."+job,{"status":"error" if failed else "completed","stop_reason":"worker_error" if failed else ("target_reached" if q>=req["max_leads"] else "source_exhausted"),"current_count":len(ids),"qualified_count":q,"dedupe_count":max(0,sum(e.get("event_type")=="place_discovered" for e in events)-len(ids),),"updated_at":now()})
 except Exception:pass
HTML="""<!doctype html><meta charset=utf-8><title>Scraper V2 UAT</title><style>body{font:16px system-ui;max-width:900px;margin:25px auto;background:#10141c;color:#eee;padding:15px}input,select,button{padding:10px;margin:4px;background:#182231;color:#eee;border:1px solid #456;border-radius:5px}button{background:#c9a227;color:#111;font-weight:bold}.grid{display:grid;grid-template-columns:repeat(4,1fr)}pre,table{width:100%;background:#182231;padding:10px}td,th{padding:6px;text-align:left;border-bottom:1px solid #345}</style><h1>Scraper V2 — UAT</h1><p>V1 preservada. Persistência desligada por padrão.</p><div class=grid><input id=cat value=lanchonete placeholder=Categoria><input id=city value="Campo Grande" placeholder=Cidade><input id=state value="Mato Grosso do Sul" placeholder=Estado><select id=max><option>5</option><option selected>20</option><option>50</option><option>100</option></select></div><label><input id=persist type=checkbox> Persistir no Supabase</label><button onclick=start()>INICIAR BUSCA</button><button onclick=cancel()>CANCELAR</button><pre id=out>Aguardando...</pre><table><thead><tr><th>Nome</th><th>Categoria</th><th>Status</th><th>Shard</th></tr></thead><tbody id=rows></tbody></table><script>let id,last=0;async function start(){let r=await fetch('/api/v2/scrape',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({category:cat.value,city:city.value,state:state.value,max_leads:+max.value,worker_count:2,persist:persist.checked})});id=(await r.json()).job_id; poll()}async function cancel(){if(id)fetch('/api/v2/jobs/'+id+'/cancel',{method:'POST'})}async function poll(){if(!id)return;let j=await fetch('/api/v2/jobs/'+id).then(x=>x.json());let e=await fetch('/api/v2/jobs/'+id+'/events').then(x=>x.json());out.textContent=JSON.stringify({job_id:id,status:j.status,stop_reason:j.stop_reason,workers:j.workers,discovered:j.current_count,qualified:j.qualified_count,rejected:j.rejected_count,persisted:j.persisted_count,dedupe:j.dedupe_count},null,2);rows.innerHTML='';for(let x of e.events||[]){if(x.event_type==='place_discovered'||x.event_type==='place_ready'||x.event_type==='place_rejected'){let d=x.payload||{};rows.innerHTML+='<tr><td>'+((d.place_name)||x.place_identity)+'</td><td>'+((d.observed_category)||'')+'</td><td>'+x.event_type+'</td><td>'+x.shard_id+'</td></tr>'}}if(j.status==='queued'||j.status==='running')setTimeout(poll,2000)} </script>"""
class H(BaseHTTPRequestHandler):
 def send(self,s,x,ct="application/json"):
  b=x.encode() if isinstance(x,str) else json.dumps(x,ensure_ascii=False).encode(); self.send_response(s); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
 def data(self):return json.loads(self.rfile.read(int(self.headers.get("Content-Length",0)) or 0) or b"{}")
 def do_GET(self):
  p=self.path.split("?")[0]
  if p in ("/v2","/v2/"):return self.send(200,HTML,"text/html")
  if p=="/api/v2/health":return self.send(200,{"ok":True,"service":"stark-v2-api","supabase_configured":bool(SUPA and KEY),"upstream_sha":"beca11f148c7dc9651ee2da9aa9ce111f3dd3bea"})
  if p.startswith("/api/v2/jobs/"):
   job=p.split("/")[4]; _,j=supa("/rest/v1/scraper_jobs?id=eq."+job+"&select=*"); _,s=supa("/rest/v1/scraper_job_shards?job_id=eq."+job+"&select=*"); _,e=supa("/rest/v1/scraper_job_events?job_id=eq."+job+"&select=*&order=id.asc");
   if p.endswith("/events"):return self.send(200,{"events":e,"event_count":len(e)})
   return self.send(200,{**(j[0] if j else {"error":"not_found"}),"workers":s,"event_count":len(e),"rejected_count":sum(x.get("event_type")=="place_rejected" for x in e),"persisted_count":sum(x.get("event_type")=="place_persisted" for x in e)})
  return self.send(404,{"error":"not_found"})
 def do_POST(self):
  p=self.path.split("?")[0]
  if p=="/api/v2/scrape":
   x=self.data(); job=str(uuid.uuid4()); req={"category":str(x.get("category") or ""),"city":str(x.get("city") or ""),"state":str(x.get("state") or ""),"max_leads":int(x.get("max_leads",20)),"persist":bool(x.get("persist",False))}; supa("/rest/v1/scraper_jobs","POST",{"id":job,"requested_category":req["category"],"city":req["city"],"state":req["state"],"target":req["max_leads"],"worker_count":2,"reviews_mode":"summary","status":"queued","dry_run":not req["persist"],"created_at":now(),"updated_at":now()}); shards=[{"job_id":job,"shard_id":job+"-"+w,"worker_id":w,"status":"queued","query_set":[]} for w in ("A","B")]; supa("/rest/v1/scraper_job_shards","POST",shards); patch("/rest/v1/scraper_jobs?id=eq."+job,{"status":"running","updated_at":now()}); threading.Thread(target=run,args=(job,req,shards),daemon=True).start(); return self.send(202,{"job_id":job,"status":"queued","persist":req["persist"]})
  if p.startswith("/api/v2/jobs/") and p.endswith("/cancel"):
   job=p.split("/")[4]; CANCEL.add(job); patch("/rest/v1/scraper_jobs?id=eq."+job,{"status":"cancelled","stop_reason":"cancelled","updated_at":now()}); return self.send(202,{"job_id":job,"status":"cancelled"})
  return self.send(404,{"error":"not_found"})
 def log_message(self,*a):pass
if __name__=="__main__":ThreadingHTTPServer(("0.0.0.0",int(os.getenv("STARK_V2_PORT","8080"))),H).serve_forever()
