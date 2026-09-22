import argparse,asyncio,json,sqlite3,time,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.sources.registry import SourceRegistry,CANDIDATES
async def main(args):
 base=args.index_dir;report={}
 rules={c.key:{'groups':list(c.groups),'tenants':['audit'],'default':True} for c in CANDIDATES}
 s=Settings(_env_file=None,pilot_rules=json.dumps(rules),metaco_index_path=str(base/'metaco-w4.sqlite3'),marshall_index_path=str(base/'marshall-w1.sqlite3'),monaer_index_path=str(base/'monaer-w1.sqlite3'),browser_fallback=False)
 registry=SourceRegistry(s)
 cases=[('metaco','brake_pads','58101H5A25'),('metaco','brake_discs','1K0615301AA'),('metaco','shock_absorbers','553101G210'),('metaco','radiators','8200735038'),('metaco','brake_hoses','13399770'),('marshall','brake_pads','58101H5A25'),('monaer','brake_pads','050090800'),('monaer','brake_discs','128424899')]
 for key,group,oe in cases:
  source=registry.get(key,group=group,tenant='audit');times=[]
  for i in range(120):
   start=time.perf_counter();result=await source.lookup(oe);times.append((time.perf_counter()-start)*1000)
   assert result.products,(key,oe)
  report[key+':'+group]={'samples':120,'p50_ms':round(sorted(times)[59],3),'p95_ms':round(sorted(times)[113],3),'products':result.products,'rows':len(result.crosses)}
 for path in base.glob('*.sqlite3'):
  c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
  report[path.name]={'integrity_check':c.execute('pragma integrity_check').fetchone()[0],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()};c.close()
 await registry.close()
 args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
if __name__ == '__main__':
 parser=argparse.ArgumentParser()
 parser.add_argument('--index-dir',type=Path,required=True)
 parser.add_argument('--output',type=Path,required=True)
 asyncio.run(main(parser.parse_args()))
