"""Validate the packaged SQLite solution without external project dependencies."""
from pathlib import Path
import json,sqlite3,hashlib
from datetime import datetime,timezone
from contextlib import closing
import pandas as pd
import run_etl
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'04_Data_Examples/verification'
def main():
 report={'checked_utc':datetime.now(timezone.utc).isoformat(),'scope':'Local database and extract checks; no Power BI refresh or independent-machine acceptance is implied.'}
 with closing(sqlite3.connect(ROOT/'01_Database/fulfilment.sqlite')) as c:
  report['integrity']=c.execute('pragma integrity_check').fetchone()[0]
  assert report['integrity']=='ok'
  report['foreign_key_failures']=len(c.execute('pragma foreign_key_check').fetchall());assert report['foreign_key_failures']==0
  d={n:pd.read_sql_query('select * from '+n,c) for n in run_etl.NAMES}
  run_etl.validate(d)
  report['table_counts']={n:len(f) for n,f in d.items()}
  assert report['table_counts']=={'customers':99441,'sellers':3095,'products':32951,'orders':99441,'order_items':112650}
  eligible=int(d['orders'].eligible_on_time.sum())
  late=int(((d['orders'].eligible_on_time==1)&(d['orders'].on_time_delivery==0)).sum())
  assert eligible==96470 and late==6534
  report['eligible']=eligible;report['late']=late;report['on_time_pct']=100*(eligible-late)/eligible
  report['order_view_rows']=c.execute('select count(*) from order_fulfilment').fetchone()[0]
  assert report['order_view_rows']==99441
  with closing(sqlite3.connect(':memory:')) as recovery:
   recovery.executescript((ROOT/'01_Database/restore.sql').read_text(encoding='utf-8'))
   for n in run_etl.NAMES:
    cols=run_etl.KEYS[n]
    a=d[n].sort_values(cols).reset_index(drop=True)
    b=pd.read_sql_query('select * from '+n,recovery).sort_values(cols).reset_index(drop=True)
    pd.testing.assert_frame_equal(a,b,check_exact=True)
  report['full_value_restore_comparison']=True
  c.execute('pragma foreign_keys=on');before=c.execute('select count(*) from sellers').fetchone()[0]
  try:
   with c:
    c.execute("insert into sellers values ('test_rollback','00000','test','ZZ')")
    c.execute("insert into sellers values ('test_rollback','00000','test','ZZ')")
  except sqlite3.IntegrityError:pass
  else:raise AssertionError('Duplicate key was accepted')
  assert c.execute('select count(*) from sellers').fetchone()[0]==before
  report['transaction_rollback']=True
  report['invalid_input_rejected']=[]
  for case in ['duplicate_order','orphan_seller','negative_price']:
   bad={n:f.copy() for n,f in d.items()}
   if case=='duplicate_order':bad['orders']=pd.concat([bad['orders'],bad['orders'].iloc[:1]],ignore_index=True)
   if case=='orphan_seller':bad['order_items'].loc[0,'seller_id']='missing_seller'
   if case=='negative_price':bad['order_items'].loc[0,'price']=-1
   try:run_etl.validate(bad)
   except AssertionError:report['invalid_input_rejected'].append(case)
   else:raise AssertionError('Invalid input accepted: '+case)
  e=pd.read_csv(ROOT/'04_Data_Examples/clean/order_explorer.csv')
  sel=e[(e.purchase_month=='2018-01')&(e.customer_state=='RJ')]
  assert (len(sel),int(sel.eligible_on_time.sum()),int(sel.late_flag.sum()))==(893,850,111)
  report['explorer_filter']={'orders':893,'eligible':850,'late':111}
 report['source_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'04_Data_Examples/03_Raw_Dataset').glob('*.csv')}
 (OUT/'submission_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps(report,indent=2))
if __name__=='__main__':main()
