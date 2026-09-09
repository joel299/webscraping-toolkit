import json, os, uuid, urllib.request, urllib.error
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from packages.domain.models import ScrapeRequest

SUPA=os.environ.get("SUPABASE_URL","").rstrip("/")
KEY=os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY","")

def now(): return datetime.now(timezone.utc).isoformat()
def headers(): return {"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json","Prefer":"return=representation"}
def supa(path, method="GET", payload=None):
    if not SUPA or not KEY: raise RuntimeError("Supabase V2 configuration missing")
    req=urllib.request.Request(SUPA+path,method=method,headers=headers(),data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req,timeout=20) as r: return r.status,json.loads(r.read() or b"null")

class Handler(BaseHTTPRequestHandler):
    def send_json(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path=="/health": return self.send_json(200,{"ok":True,"service":"stark-v2-api","supabase_configured":bool(SUPA and KEY)})
        if self.path.startswith("/api/v2/jobs/"):
            job_id=self.path.rsplit("/",1)[-1]
            try: _,data=supa(f"/rest/v1/scraper_jobs?id=eq.{job_id}&select=*"); return self.send_json(200,data[0] if data else {"error":"not_found"})
            except Exception as e: return self.send_json(503,{"error":str(e)})
        return self.send_json(404,{"error":"not_found"})
    def do_POST(self):
        if self.path!="/api/v2/jobs": return self.send_json(404,{"error":"not_found"})
        try:
            n=int(self.headers.get("Content-Length","0")); body=json.loads(self.rfile.read(n) or b"{}")
            req=ScrapeRequest(str(body["requested_category"]),str(body["city"]),str(body["state"]),int(body.get("max_leads",5)),int(body.get("worker_count",1)),str(body.get("reviews_mode","summary")),bool(body.get("dry_run",True)))
            if req.max_leads<1 or req.worker_count not in (1,2): raise ValueError("max_leads>=1 and worker_count must be 1 or 2")
            job_id=str(uuid.uuid4()); row={"id":job_id,"requested_category":req.requested_category,"city":req.city,"state":req.state,"target":req.max_leads,"worker_count":req.worker_count,"reviews_mode":req.reviews_mode,"status":"queued","stop_reason":None,"dry_run":req.dry_run,"created_at":now(),"updated_at":now()}
            _,data=supa("/rest/v1/scraper_jobs","POST",row)
            shards=[{"job_id":job_id,"shard_id":f"{job_id}-A" if i==0 else f"{job_id}-B","worker_id":chr(65+i),"status":"queued","query_set":[]} for i in range(req.worker_count)]
            supa("/rest/v1/scraper_job_shards","POST",shards)
            return self.send_json(202,{"job_id":job_id,"status":"queued","shards":shards,"persisted":bool(data)})
        except Exception as e: return self.send_json(503,{"error":str(e)})
    def log_message(self,*args): pass

if __name__=="__main__": ThreadingHTTPServer((os.environ.get("STARK_V2_BIND","127.0.0.1"),int(os.environ.get("STARK_V2_PORT","18080"))),Handler).serve_forever()
