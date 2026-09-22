"""Bounded live smoke audit. No application DB, accounts, cache or jobs are used.
Run with --live --index-dir <copied indexes> --output /tmp/report.json.
Results are observations, not an independent proof of interchangeability.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.sources.registry import SourceRegistry, CANDIDATES

CASES = {
 'sbparts': [('brake_pads','58101H5A25'),('brake_hoses','587312E000')],
 'brembo': [('brake_pads','58101H5A25'),('brake_discs','1K0615301AA'),('brake_hoses','1K0611701K')],
 'trialli': [('brake_pads','58101H5A25'),('shock_absorbers','553101G210')],
 'nibkru': [('brake_pads','58101H5A25')], 'brixo':[('radiators','8200735038')],
 'luzar':[('radiators','8200735038')], 'nissens':[('radiators','8200735038')],
 'kyb':[('shock_absorbers','4851080378')], 'hola':[('brake_pads','58101H5A25')],
 'brannor':[('brake_pads','8K0698451D')], 'hel':[('brake_hoses','1K0611701')],
 'metaco':[('brake_pads','58101H5A25'),('brake_discs','1K0615301AA'),('shock_absorbers','553101G210'),('radiators','8200735038'),('brake_hoses','13399770')],
 'marshall':[('brake_pads','58101H5A25')],
 'lynxauto':[('brake_pads','58101H5A25'),('shock_absorbers','553101G210'),('brake_hoses','1K0611701K')],
 'masterkit':[('brake_pads','58101H5A25')], 'fap':[('brake_pads','58101H5A25'),('brake_discs','1K0615301AA')],
 'ganz':[('brake_pads','581011RA00'),('brake_discs','51712G4000'),
         ('shock_absorbers','8450033433'),('radiators','21903130000811')],
 'zimmermann':[('brake_pads','58101H5A25'),('brake_discs','1K0615301AA')],
 'monaer':[('brake_pads','050090800'),('brake_discs','128424899')],
 'ate':[('brake_pads','58101H5A25'),('brake_discs','1K0615301AA'),('brake_hoses','1K0611701K')],
 'febest':[('shock_absorbers','553101G210')], 'torr':[('shock_absorbers','553101G210')],
}
async def main(args):
 rules={c.key:{'groups':list(c.groups),'tenants':['audit'],'default':True} for c in CANDIDATES}
 settings=Settings(_env_file=None, database_url='sqlite+aiosqlite:///:memory:', users='', api_keys='',
  proxy_url='', proxy_sources='', browser_fallback=False, source_timeout=20,
  pilot_rules=json.dumps(rules), metaco_index_path=str(args.index_dir/'metaco-w4.sqlite3'),
  marshall_index_path=str(args.index_dir/'marshall-w1.sqlite3'), monaer_index_path=str(args.index_dir/'monaer-w1.sqlite3'))
 registry=SourceRegistry(settings); results=[]; semaphore=asyncio.Semaphore(3)
 async def check_source(key,cases):
  async with semaphore:
   for group,oe in [*cases,(cases[0][0],'ZZCPAUDITNONEXISTENT999999')]:
    src=registry.get(key,group=group,tenant='audit'); start=time.monotonic()
    try:
     res=await asyncio.wait_for(src.lookup(oe),timeout=45)
     row=dict(source=key,group=group,oe=oe,status=res.status.value,products=res.products,
      rows=len(res.crosses),message=res.message,
      sample=[{'brand':c.brand,'number':c.number,'kind':c.kind} for c in res.crosses[:5]])
    except Exception as exc: row=dict(source=key,group=group,oe=oe,status='exception',message=str(exc))
    row['seconds']=round(time.monotonic()-start,3)
    row['expectation']='not_found' if oe.startswith('ZZCP') else 'ok'
    row['passed']=(row['status']==row['expectation'] and
                   (row['expectation']=='not_found' or bool(row.get('products'))))
    results.append(row)
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print(key,group,oe,row['status'],row.get('products'),row['seconds'],flush=True)
    await asyncio.sleep(3)
 try: await asyncio.gather(*(check_source(k,v) for k,v in CASES.items()))
 finally: await registry.close()
 return all(row['passed'] for row in results)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--index-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 args=p.parse_args()
 if not args.live:p.error('Live requests require --live')
 raise SystemExit(0 if asyncio.run(main(args)) else 1)
