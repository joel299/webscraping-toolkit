import os,sys,json,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import importlib.util
_spec=importlib.util.spec_from_file_location("gosom_provider", str(Path(__file__).resolve().parents[1]/"maps-engine"/"provider.py"))
_mod=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_mod)
GosomMapsProvider,run_shards=_mod.GosomMapsProvider,_mod.run_shards
from packages.normalization.normalize import normalize_place

def main():
 p=GosomMapsProvider(os.environ.get('GOSOM_URL','http://127.0.0.1:18081'))
 assert p.health(), 'Gosom API unavailable'
 base={'lang':'pt','zoom':15,'depth':1,'max_time':180}
 requests=[dict(base,name='V2 shard A',keywords=['lanchonete Campo Grande Mato Grosso do Sul']),dict(base,name='V2 shard B',keywords=['hamburgueria Campo Grande Mato Grosso do Sul'])]
 results=run_shards(p,requests)
 normalized=[]
 for shard in results:
  for raw in shard['results']:
   normalized.append(normalize_place({'place_name':raw.get('title'),'category':raw.get('category'),'address':raw.get('address'),'google_maps_url':raw.get('link'),'place_id':raw.get('place_id'),'phone':raw.get('phone'),'website':raw.get('website'),'reviews_count':raw.get('review_count'),'total_score':raw.get('review_rating')},{'requested_category':'lanchonete','city':'Campo Grande','state':'Mato Grosso do Sul'}))
 dedup={x['place_identity']:x for x in normalized}
 qualified=[x for x in dedup.values() if x['qualification_status']=='qualified']
 print(json.dumps({'health':True,'shards':[{'provider_job_id':x['provider_job_id'],'status':x['job'].get('Status'),'raw_count':len(x['results'])} for x in results],'shard_count':len(results),'provider_ids_distinct':len({x['provider_job_id'] for x in results})==2,'raw_count':len(normalized),'dedupe_count':len(normalized)-len(dedup),'qualified_count':len(qualified),'rejected_count':len(dedup)-len(qualified),'sample':qualified[:3]},ensure_ascii=False))
if __name__=='__main__': main()
