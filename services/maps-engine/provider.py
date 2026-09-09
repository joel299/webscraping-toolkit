import csv,io,json,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor
class GosomMapsProvider:
 def __init__(self,base_url): self.base_url=base_url.rstrip('/')
 def _request(self,path,method='GET',payload=None):
  req=urllib.request.Request(self.base_url+path,method=method,headers={'Content-Type':'application/json'},data=json.dumps(payload).encode() if payload is not None else None)
  with urllib.request.urlopen(req,timeout=40) as r: return json.loads(r.read() or b'null')
 def health(self):
  with urllib.request.urlopen(self.base_url+'/api/docs',timeout=10) as r: return r.status==200
 def create_job(self,request): return self._request('/api/v1/jobs','POST',request)['id']
 def get_job(self,provider_job_id): return self._request('/api/v1/jobs/'+provider_job_id)
 def cancel_job(self,provider_job_id):
  req=urllib.request.Request(self.base_url+'/api/v1/jobs/'+provider_job_id,method='DELETE')
  with urllib.request.urlopen(req,timeout=20) as r: return r.status in (200,204)
 def read_results(self,provider_job_id):
  with urllib.request.urlopen(self.base_url+'/api/v1/jobs/'+provider_job_id+'/download',timeout=60) as r: return list(csv.DictReader(io.StringIO(r.read().decode(errors='replace'))))
 def run(self,request):
  job_id=self.create_job(request)
  for _ in range(120):
   job=self.get_job(job_id)
   if job.get('Status') in ('ok','failed','error'): break
  return {'provider_job_id':job_id,'job':job,'results':self.read_results(job_id)}

def run_shards(provider,requests):
 with ThreadPoolExecutor(max_workers=len(requests)) as pool:
  results=list(pool.map(provider.run,requests))
 return results
