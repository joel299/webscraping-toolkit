import csv,hashlib,io,json,mimetypes,os,threading,time,urllib.request,urllib.parse,uuid
from datetime import datetime,timezone
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import sys
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,ROOT)
from packages.domain.identity import place_identity, normalize_phone, identity_aliases
from packages.normalization.normalize import normalize_place
from packages.enrichment.social import promote_social_website
from packages.planner import build_queries
REV=os.getenv("STARK_RUNTIME_REVISION","dc811a67fcd0969a7e9d53afc582baaf40ee140b")
SUPA=os.getenv("SUPABASE_URL","").rstrip("/"); KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY",""); GOSOMS=[os.getenv("GOSOM_A_URL","http://stark-v2-maps-a:8080"),os.getenv("GOSOM_B_URL","http://stark-v2-maps-b:8080")]; CANCEL=set(); SEEN={}; QUALIFIED={}; ALIASES={}; ACCEPTED_LOCK=threading.Lock()
def now(): return datetime.now(timezone.utc).isoformat()
def h(): return {"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"return=representation"}
def supa(path,method="GET",data=None):
 r=urllib.request.Request(SUPA+path,method=method,headers=h(),data=json.dumps(data).encode() if data is not None else None)
 with urllib.request.urlopen(r,timeout=30) as x:return x.status,json.loads(x.read() or b"null")
def remote(base,path,method="GET",data=None):
 r=urllib.request.Request(base+path,method=method,headers={"Content-Type":"application/json"},data=json.dumps(data).encode() if data is not None else None)
 with urllib.request.urlopen(r,timeout=60) as x:return x.status,json.loads(x.read() or b"null")
def patch(path,data):
 try:supa(path,"PATCH",data)
 except Exception:pass
def ev(job,shard,typ,item=None,extra=None):
 try:supa("/rest/v1/scraper_job_events","POST",[{"job_id":job,"shard_id":shard,"event_type":typ,"place_identity":item.get("place_identity") if item else None,"payload":{**(item or {}),**(extra or {})},"occurred_at":now()}])
 except Exception:pass
def worker(job,req,w,shard):
 base=GOSOMS[0 if w=="A" else 1]
 query=build_queries(req["category"],req["city"],req["state"],2).queries[0 if w=="A" else 1]
 for attempt in range(2):
  pid=None
  try:
   patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"status":"running","started_at":now(),"retry_count":attempt})
   _,c=remote(base,"/api/v1/jobs","POST",{"name":"V2 "+job+" "+w,"keywords":[query],"lang":"pt","zoom":15,"depth":1,"max_time":120}); pid=c["id"]
   patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"provider_job_id":pid,"query_set":[query]})
   for tick in range(50):
    if job in CANCEL:
     if pid: remote(base,"/api/v1/jobs/"+pid,"DELETE")
     raise RuntimeError("cancelled")
    _,j=remote(base,"/api/v1/jobs/"+pid); st=str(j.get("Status","")).lower(); patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"heartbeat_at":now(),"provider_status":st})
    if st=="ok": break
    if st in ("failed","error"): raise RuntimeError(st)
    time.sleep(3)
   else: raise RuntimeError("provider_timeout")
   raw=urllib.request.urlopen(base+"/api/v1/jobs/"+pid+"/download",timeout=45).read().decode(errors="replace")
   rows=list(csv.DictReader(io.StringIO(raw)))
   for x in rows:
    item=normalize_place(x,req)
    ident_value=item["place_identity"]
    with ACCEPTED_LOCK:
     seen=SEEN.setdefault(job,set()); qualified=QUALIFIED.setdefault(job,set()); aliases=ALIASES.setdefault(job,{})
     alias_hit=next((aliases[a] for a in identity_aliases(x) if a in aliases),None)
     if alias_hit: ident_value=alias_hit
     if ident_value in seen: continue
     seen.add(ident_value)
     for a in identity_aliases(x): aliases[a]=ident_value
     is_qualified=item["qualification_status"]=="qualified"
     if is_qualified and req.get("target_mode") == "limited" and len(qualified)>=req["max_leads"]: continue
     if is_qualified: qualified.add(ident_value)
    ev(job,shard,"place_discovered",item)
    ev(job,shard,"place_rejected" if not is_qualified else "place_ready",item)
    if req.get("persist") and is_qualified: persist_lead(job,w,shard,item)
   patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"status":"completed","completed_at":now(),"qualified_count":len(QUALIFIED.get(job,set()))})
   ev(job,shard,"shard_completed",extra={"raw_candidates":len(rows),"provider_job_id":pid,"query":query})
   return
  except Exception as e:
   if str(e)=="cancelled":
    patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"status":"cancelled","stop_reason":"cancelled"}); ev(job,shard,"shard_cancelled"); return
   if attempt==0:
    ev(job,shard,"failed_retrying",extra={"error":str(e)[:160],"retry":1}); time.sleep(1); continue
   patch("/rest/v1/scraper_job_shards?shard_id=eq."+shard,{"status":"error","stop_reason":str(e)[:160]}); ev(job,shard,"shard_failed",extra={"error":str(e)[:160]})

def persist_lead(job,w,shard,item):
 base={"id":item["place_identity"],"place_name":item["place_name"],"total_score":item["total_score"],"reviews_count":item["reviews_count"],"address":item["address"],"website":item["website"],"whatsapp":item["whatsapp"],"source":"google_maps","source_category":item["requested_category"],"observed_category":item["observed_category"],"source_city":item["source_city"],"source_state":item["source_state"],"google_maps_url":item["google_maps_url"],"qualification_status":"qualified","qualification_stage":"category_gate","contact_ready":item["contact_ready"],"v2_last_job_id":job,"v2_worker_label":w}
 try:
  _,existing=supa("/rest/v1/prospect_leads_google?id=eq."+urllib.parse.quote(item["place_identity"],safe="")+"&select=*")
  if existing:
   status,_=supa("/rest/v1/prospect_leads_google?id=eq."+urllib.parse.quote(item["place_identity"],safe=""),"PATCH",base)
   action="updated"
  else:
   status,_=supa("/rest/v1/prospect_leads_google?on_conflict=id","POST",[base]); action="inserted"
  _,fresh=supa("/rest/v1/prospect_leads_google?id=eq."+urllib.parse.quote(item["place_identity"],safe="")+"&select=id,place_name,source_category,source_city,source_state,lead_status,pipeline_stage,responded,converted")
  ok=bool(fresh and fresh[0].get("id")==item["place_identity"])
  if ok:
   supa("/rest/v1/prospect_leads_google?id=eq."+urllib.parse.quote(item["place_identity"],safe=""),"PATCH",{"persistence_verified":True,"persistence_verified_at":now()})
  ev(job,shard,"place_persisted" if ok else "place_persistence_failed",item,{"persistence_status":"verified" if ok else "failed","action":action,"write_status":status})
 except Exception as pe: ev(job,shard,"place_persistence_failed",item,{"persistence_status":"failed","error":str(pe)[:120]})

def run(job,req,shards):
 ts=[threading.Thread(target=worker,args=(job,req,s["worker_id"],s["shard_id"]),daemon=True) for s in shards]
 for t in ts:t.start()
 deadline=time.monotonic()+180
 for t in ts:
  t.join(max(0,deadline-time.monotonic()))
 if any(t.is_alive() for t in ts):
  CANCEL.add(job)
  patch("/rest/v1/scraper_jobs?id=eq."+job,{"status":"partial","stop_reason":"runtime_budget","updated_at":now()})
  ev(job,None,"runtime_budget_exceeded",extra={"runtime_budget_seconds":180})
  return
 try:
  _,events=supa("/rest/v1/scraper_job_events?job_id=eq."+job+"&select=*")
  ids={e.get("place_identity") for e in events if e.get("place_identity")}
  q=len({e.get("place_identity") for e in events if e.get("event_type")=="place_ready" and e.get("place_identity")})
  failed=any(e.get("event_type")=="shard_failed" for e in events); cancelled=job in CANCEL
  status="cancelled" if cancelled else ("partial" if failed and q else ("error" if failed else "completed"))
  reason="cancelled" if cancelled else ("worker_error" if failed else ("target_reached" if req.get("target_mode")=="limited" and q>=req["max_leads"] else "queries_exhausted"))
  patch("/rest/v1/scraper_jobs?id=eq."+job,{"status":status,"stop_reason":reason,"current_count":len(ids),"qualified_count":q,"dedupe_count":max(0,sum(e.get("event_type")=="place_discovered" for e in events)-len(ids)),"updated_at":now()})
 except Exception: pass
HTML='<!doctype html><meta charset=utf-8><title>Scraper V2 UAT</title><style>body{font:16px system-ui;max-width:900px;margin:25px auto;background:#10141c;color:#eee;padding:15px}input,select,button{padding:10px;margin:4px;background:#182231;color:#eee;border:1px solid #456;border-radius:5px}button{background:#c9a227;color:#111;font-weight:bold}.grid{display:grid;grid-template-columns:repeat(4,1fr)}table{width:100%;background:#182231;padding:10px}td,th{padding:6px;text-align:left;border-bottom:1px solid #345}</style><h1>Scraper V2 — UAT</h1><p>V1 preservada. Persistência desligada por padrão.</p><div class=grid><input id=cat value=lanchonete placeholder=Categoria><input id=city value="Campo Grande" placeholder=Cidade><input id=state value="Mato Grosso do Sul" placeholder=Estado><input id=max type=number value=20 min=1 placeholder="Quantidade máxima"><label><input id=all type=checkbox> Todos disponíveis</label></div><label><input id=persist type=checkbox> Persistir no Supabase</label><button onclick=start()>INICIAR BUSCA</button><button onclick=cancel()>CANCELAR</button><p id=summary>Aguardando...</p><table><thead><tr><th>Nome</th><th>Categoria</th><th>Status</th><th>Worker</th></tr></thead><tbody id=rows></tbody></table><script>let id,after=0,places=new Map();async function start(){let r=await fetch(\'/api/v2/scrape\',{method:\'POST\',headers:{\'content-type\':\'application/json\'},body:JSON.stringify({category:cat.value,city:city.value,state:state.value,max_leads:all.checked?null:+max.value,worker_count:2,persist:persist.checked,webhook:false})});let j=await r.json();id=j.job_id;after=0;places.clear();poll()}async function cancel(){if(id)await fetch(\'/api/v2/jobs/\'+id+\'/cancel\',{method:\'POST\'})}async function poll(){if(!id)return;let j=await fetch(\'/api/v2/jobs/\'+id).then(x=>x.json());let e=await fetch(\'/api/v2/jobs/\'+id+\'/events?after=\'+after+\'&limit=100\').then(x=>x.json());after=e.next_cursor||after;for(let x of e.events||[]){let d=x.public_place;if(d&&d.place_identity)places.set(d.place_identity,{...places.get(d.place_identity),...d,status:x.event_type})}summary.textContent=\'Status: \'+j.status+\' · Qualificados: \'+(j.qualified_count||0)+\' · Descobertos: \'+(j.current_count||0)+\' · Persistidos: \'+(j.persisted_count||0);rows.innerHTML=\'\';for(let d of places.values()){rows.innerHTML+=\'<tr><td>\'+escapeHtml(d.place_name||\'\')+\'</td><td>\'+escapeHtml(d.observed_category||\'\')+\'</td><td>\'+escapeHtml(d.status||\'\')+\'</td><td>\'+escapeHtml(d.worker_label||\'\')+\'</td></tr>\'}if(j.status===\'queued\'||j.status===\'running\')setTimeout(poll,1500)}if(document.modelContext&&document.modelContext.registerTool){const safe=(name,description,inputSchema,fn)=>document.modelContext.registerTool({name,description,inputSchema,execute:async(args)=>{const r=await fn(args||{});return {content:[{type:"text",text:JSON.stringify(r)}],untrustedContentHint:true}}});safe("stark.health","Health check",{},async()=>fetch("/api/v2/health").then(r=>r.json()));safe("stark.get_job","Get public job status",{type:"object",properties:{job_id:{type:"string"}},required:["job_id"]},async(a)=>fetch("/api/v2/jobs/"+encodeURIComponent(a.job_id)).then(r=>r.json()));safe("stark.get_job_events","Get public job events",{type:"object",properties:{job_id:{type:"string"},after:{type:"number"}},required:["job_id"]},async(a)=>fetch("/api/v2/jobs/"+encodeURIComponent(a.job_id)+"/events?after="+(a.after||0)).then(r=>r.json()));safe("stark.list_job_places","List public places",{type:"object",properties:{job_id:{type:"string"}},required:["job_id"]},async(a)=>fetch("/api/v2/jobs/"+encodeURIComponent(a.job_id)+"/events?after=0&limit=100").then(r=>r.json()));safe("stark.start_search","Start safe dry-run",{type:"object",properties:{category:{type:"string"},city:{type:"string"},state:{type:"string"},max_leads:{type:["integer","null"]},all_available:{type:"boolean"}},required:["category","city","state"]},async(a)=>fetch("/api/v2/scrape",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({...a,max_leads:a.max_leads===undefined?(a.all_available?null:20):a.max_leads,worker_count:2,persist:false,webhook:false,reviews_mode:"summary"})}).then(r=>r.json()));safe("stark.cancel_job","Cancel a job",{type:"object",properties:{job_id:{type:"string"}},required:["job_id"]},async(a)=>fetch("/api/v2/jobs/"+encodeURIComponent(a.job_id)+"/cancel",{method:"POST"}).then(r=>r.json()))}function escapeHtml(v){return String(v).replace(/[&<>"\']/g,c=>({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'"\':\'&quot;\',"\'":\'&#39;\'}[c]))}</script>'
def public_event(e):
    payload=e.get("payload") or {}
    allowed=("place_identity","place_name","observed_category","total_score","reviews_count","address","phone_raw","whatsapp","website","google_maps_url","emails","instagram","facebook","linkedin","legal_name","cnpj","qualification_status","qualification_stage","persistence_status")
    public={k:payload.get(k) for k in allowed if payload.get(k) is not None}
    public["public_stage"] = {"place_discovered":"Encontrado","place_ready":"Qualificado","place_persisted":"Persistido","place_rejected":"Rejeitado","place_enriched":"Completo"}.get(e.get("event_type"),"Coletando detalhes")
    return {"id":e.get("id"),"event_type":e.get("event_type"),"place_identity":e.get("place_identity"),"occurred_at":e.get("occurred_at"),"public_place":public}

class H(BaseHTTPRequestHandler):
 def send(self,s,x,ct="application/json",cache="no-store"):
  b=x.encode() if isinstance(x,str) else json.dumps(x,ensure_ascii=False).encode(); self.send_response(s); self.send_header("Content-Type",ct); self.send_header("X-Stark-Revision",REV); self.send_header("Cache-Control",cache); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
 def asset(self,p):
  root=Path("/app/dist/assets").resolve()
  try: f=(root / urllib.parse.unquote(p[len("/v2/assets/"):])).resolve()
  except Exception: return self.send(404,{"error":"not_found"})
  if root not in f.parents or not f.is_file(): return self.send(404,{"error":"not_found"})
  ct=mimetypes.guess_type(str(f))[0] or "application/octet-stream"
  return self.send(200,f.read_bytes(),ct,"public, max-age=31536000, immutable")
 def data(self):return json.loads(self.rfile.read(int(self.headers.get("Content-Length",0)) or 0) or b"{}")
 def do_GET(self):
  p=self.path.split("?")[0]
  if p.startswith("/v2/assets/"):
   return self.asset(p)
  if p in ("/v2","/v2/"):
   dist=Path("/app/dist/index.html")
   if dist.exists(): return self.send(200,dist.read_text(),"text/html")
   return self.send(200,HTML,"text/html")
  if p=="/api/v2/health":return self.send(200,{"ok":True,"service":"stark-v2-api","runtime_revision":REV,"upstream_sha":"beca11f148c7dc9651ee2da9aa9ce111f3dd3bea"})
  if p.startswith("/api/v2/jobs/"):
   job=p.split("/")[4]; _,j=supa("/rest/v1/scraper_jobs?id=eq."+job+"&select=*"); _,s=supa("/rest/v1/scraper_job_shards?job_id=eq."+job+"&select=*"); _,e=supa("/rest/v1/scraper_job_events?job_id=eq."+job+"&select=*&order=id.asc");
   if p.endswith("/events"):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query); after=int((q.get("after") or [0])[0]); limit=min(100,int((q.get("limit") or [50])[0])); page=[x for x in e if int(x.get("id") or 0)>after][:limit]; next_cursor=int(page[-1].get("id") or after) if page else after
    return self.send(200,{"job_id":job,"events":[public_event(x) for x in page],"next_cursor":next_cursor,"has_more":len([x for x in e if int(x.get("id") or 0)>next_cursor])>0})
   if p.endswith("/places"):
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query); pg=max(1,int((q.get("page") or [1])[0])); size=min(100,max(1,int((q.get("page_size") or [25])[0]))); term=(q.get("q") or [""])[0].lower(); sort=(q.get("sort") or ["id"])[0]; order=(q.get("order") or ["asc"])[0]
    places={}; seq=0
    for x in e:
     if x.get("event_type") not in ("place_discovered","place_ready","place_enriched","place_persisted"): continue
     v=public_event(x).get("public_place") or {}; k=v.get("place_identity")
     if not k: continue
     if k not in places: places[k]={**v,"first_seen_seq":seq}; seq+=1
     else: places[k]={**places[k],**{a:b for a,b in v.items() if b not in (None,"",[])}}
    items=list(places.values())
    if term: items=[v for v in items if term in " ".join(str(v.get(k) or "") for k in ("place_name","address","phone_raw","whatsapp","observed_category")).lower()]
    if sort in ("place_name","total_score","reviews_count"): items.sort(key=lambda v:str(v.get(sort) or ""),reverse=order=="desc")
    total=len(items); pages=(total+size-1)//size if total else 0; start=(pg-1)*size
    return self.send(200,{"items":items[start:start+size],"page":pg,"page_size":size,"total_items":total,"total_pages":pages,"has_previous":pg>1,"has_next":pg<pages})
   public_workers=[{"worker_label":"Worker "+str(x.get("worker_id") or "?"),"status":x.get("status"),"qualified_count":x.get("qualified_count"),"retry_count":x.get("retry_count")} for x in s]
   base={k:v for k,v in (j[0] if j else {"error":"not_found"}).items() if k not in ("provider_job_id","query_set","shard_id","v2_last_job_id")}
   return self.send(200,{**base,"workers":public_workers,"event_count":len(e),"rejected_count":sum(x.get("event_type")=="place_rejected" for x in e),"persisted_count":sum(x.get("event_type")=="place_persisted" for x in e)})
  return self.send(404,{"error":"not_found"})
 def do_POST(self):
  p=self.path.split("?")[0]
  if p=="/api/v2/scrape":
   x=self.data();
   if x.get("max_leads") == 0: return self.send(400,{"error":"max_leads must be positive or null"})
   job=str(uuid.uuid4()); req={"category":str(x.get("category") or ""),"city":str(x.get("city") or ""),"state":str(x.get("state") or ""),"max_leads":(int(x["max_leads"]) if x.get("max_leads") is not None else None),"target_mode":"limited" if x.get("max_leads") is not None else "all_available","persist":bool(x.get("persist",False))}; supa("/rest/v1/scraper_jobs","POST",{"id":job,"requested_category":req["category"],"city":req["city"],"state":req["state"],"target":req["max_leads"],"target_mode":req["target_mode"],"worker_count":2,"reviews_mode":"summary","status":"queued","dry_run":not req["persist"],"created_at":now(),"updated_at":now()}); shards=[{"job_id":job,"shard_id":job+"-"+w,"worker_id":w,"status":"queued","query_set":[]} for w in ("A","B")]; supa("/rest/v1/scraper_job_shards","POST",shards); patch("/rest/v1/scraper_jobs?id=eq."+job,{"status":"running","updated_at":now()}); threading.Thread(target=run,args=(job,req,shards),daemon=True).start(); return self.send(202,{"job_id":job,"status":"queued","persist":req["persist"]})
  if p.startswith("/api/v2/jobs/") and p.endswith("/cancel"):
   job=p.split("/")[4]; CANCEL.add(job); patch("/rest/v1/scraper_jobs?id=eq."+job,{"status":"cancelled","stop_reason":"cancelled","updated_at":now()}); return self.send(202,{"job_id":job,"status":"cancelled"})
  return self.send(404,{"error":"not_found"})
 def log_message(self,*a):pass
if __name__=="__main__":ThreadingHTTPServer(("0.0.0.0",int(os.getenv("STARK_V2_PORT","8080"))),H).serve_forever()
