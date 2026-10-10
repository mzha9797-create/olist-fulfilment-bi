"""Rebuild the MBI807 SQLite mart from packaged Olist raw data.
No MySQL server is touched. Candidate database is checked before atomic promotion.
Python 3.11+ and pandas/numpy required. Run from TechnicalPortfolio: python 02_ETL_Code/audit_run.py
"""
from pathlib import Path
import contextlib, hashlib, io, json, logging, os, re, runpy, sqlite3, time
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'04_Data_Examples'
DBDIR=ROOT/'01_Database'
AUDIT=ROOT/'04_Data_Examples/verification'
AUDIT.mkdir(exist_ok=True)
logging.basicConfig(filename=AUDIT/'etl.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
NAMES=['customers','sellers','products','orders','order_items']
KEYS={'customers':['customer_id'],'sellers':['seller_id'],'products':['product_id'],'orders':['order_id'],'order_items':['order_id','order_item_id']}
FKS={'orders':[('customer_id','customers','customer_id')],'order_items':[('order_id','orders','order_id'),('seller_id','sellers','seller_id'),('product_id','products','product_id')]}

def frames():
    # Preserve the declared minute precision; the raw timestamps retain seconds.
    os.environ['MBI807_CLEAN_OUTPUT']=str(DATA/'clean')
    with open(AUDIT/'cleaning_execution.txt','w',encoding='utf-8') as out, contextlib.redirect_stdout(out):
        runpy.run_path(str(ROOT/'02_ETL_Code/reused_cleaning.py'),run_name='__main__')
    return {n:pd.read_csv(DATA/'clean'/f'{n}_clean.csv',dtype={k:'string' for k in ['customer_id','customer_unique_id','seller_id','product_id','order_id','customer_zip_code_prefix','seller_zip_code_prefix']}) for n in NAMES}

def validate(d):
    checks=[]
    for n,f in d.items():
        for label,bad in [('null_key',int(f[KEYS[n]].isna().any(axis=1).sum())),('duplicate_key',int(f.duplicated(KEYS[n]).sum()))]:
            checks.append({'check':n+'_'+label,'failures':bad});assert bad==0,(n,label,bad)
    for child,rels in FKS.items():
        for fk,parent,pk in rels:
            bad=int((~d[child][fk].isin(d[parent][pk])).sum())
            checks.append({'check':child+'_'+fk+'_orphan','failures':bad});assert bad==0,(child,fk,bad)
    for col in ['price','freight_value']:
        bad=int((d['order_items'][col].isna() | (d['order_items'][col]<0)).sum())
        checks.append({'check':col+'_invalid','failures':bad});assert bad==0
    return checks

def sqltype(s,col):
    if pd.api.types.is_bool_dtype(s) or col.startswith(('flag_','eligible_')) or col=='on_time_delivery':return 'INTEGER'
    if pd.api.types.is_integer_dtype(s):return 'INTEGER'
    if pd.api.types.is_numeric_dtype(s):return 'REAL'
    return 'TEXT'

def load(d,path):
    con=sqlite3.connect(path);con.execute('PRAGMA foreign_keys=ON')
    schema=[]
    try:
        with con:
            for n,f in d.items():
                cols=[f'"{col}" {sqltype(f[col],col)}'+(' NOT NULL' if col in KEYS[n] else '') for col in f]
                cols+=['PRIMARY KEY ('+','.join('"'+k+'"' for k in KEYS[n])+')']
                cols += [f'FOREIGN KEY ("{fk}") REFERENCES {parent}("{pk}")' for fk,parent,pk in FKS.get(n,[])]
                if n=='order_items':cols+=['CHECK(price >= 0)','CHECK(freight_value >= 0)']
                q=f'CREATE TABLE {n} ('+',\n'.join(cols)+');';schema.append(q);con.execute(q)
                f=f.copy()
                for col in f:
                    if sqltype(f[col],col)=='INTEGER' and (pd.api.types.is_bool_dtype(f[col]) or col=='on_time_delivery'):
                        f[col]=f[col].map(lambda v: None if pd.isna(v) else int(v in [True,1,'True','true']))
                rows=f.astype(object).where(pd.notna(f),None).values.tolist()
                con.executemany(f'INSERT INTO {n} VALUES ('+','.join('?' for _ in f.columns)+')',rows)
            for q in ['CREATE INDEX idx_orders_customer ON orders(customer_id)','CREATE INDEX idx_orders_purchase ON orders(order_purchase_timestamp)','CREATE INDEX idx_items_seller_order ON order_items(seller_id,order_id)','CREATE INDEX idx_items_product_order ON order_items(product_id,order_id)']:
                schema.append(q+';');con.execute(q)
            # Load the three versioned analytical view definitions.
            old=(DBDIR/'analytical_views.sql').read_text(encoding='utf-8-sig')
            # Read the final analytical view definitions from analytical_views.sql.
            for name,body in dict(re.findall(r'CREATE VIEW\s+(\w+)\s+AS\s+(.*?);',old,re.S|re.I)).items():
                q='CREATE VIEW '+name+' AS '+body+';';con.execute(q);schema.append(q)
            mart='''CREATE VIEW order_fulfilment AS
            SELECT o.*,c.customer_state,c.customer_city,c.customer_unique_id,
            COALESCE(i.item_count,0) item_count,COALESCE(i.seller_count,0) seller_count,
            i.item_value,i.freight_value FROM orders o JOIN customers c USING(customer_id)
            LEFT JOIN (SELECT order_id,COUNT(*) item_count,COUNT(DISTINCT seller_id) seller_count,
            ROUND(SUM(price),2) item_value,ROUND(SUM(freight_value),2) freight_value
            FROM order_items GROUP BY order_id) i USING(order_id);'''
            con.execute(mart);schema.append(mart)
        assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        assert con.execute('SELECT count(*) FROM order_fulfilment').fetchone()[0]==len(d['orders'])
        (DBDIR/'schema.sql').write_text('PRAGMA foreign_keys=ON;\n'+'\n\n'.join(schema),encoding='utf-8')
        (DBDIR/'restore.sql').write_text('\n'.join(con.iterdump()),encoding='utf-8')
        for view in ['vw_state_delivery_performance','vw_seller_performance','vw_category_performance','order_fulfilment']:
            pd.read_sql_query('SELECT * FROM '+view,con).to_csv(DATA/'clean'/f'{view}.csv',index=False)
    finally:con.close()

def analyse(path):
    with contextlib.closing(sqlite3.connect(path)) as con:
        f=pd.read_sql_query('SELECT * FROM order_fulfilment',con)
        eligible=f[f.eligible_on_time==1]
        cohorts=[]
        for group,g in f.groupby('customer_state'):
            e=g[g.eligible_on_time==1]
            cohorts.append({'state':group,'orders':len(g),'eligible':len(e),'late':int((e.on_time_delivery==0).sum()),'late_pct':100*(e.on_time_delivery==0).mean(),'mean_days':g.loc[g.eligible_delivery_days==1,'delivery_days'].mean()})
        rates=pd.DataFrame(cohorts).sort_values('late',ascending=False);rates.to_csv(AUDIT/'state_results.csv',index=False)
        m={ 'orders':len(f),'columns':len(f.columns),'delivered':int((f.order_status=='delivered').sum()),'eligible':len(eligible),'late':int((eligible.on_time_delivery==0).sum()),'on_time_pct':100*eligible.on_time_delivery.mean(),
            'mean_delivery_days':f.loc[f.eligible_delivery_days==1,'delivery_days'].mean(),'median_delivery_days':f.loc[f.eligible_delivery_days==1,'delivery_days'].median(),
            'p90_delivery_days':f.loc[f.eligible_delivery_days==1,'delivery_days'].quantile(.9),'processing_n':int(f.eligible_processing_time.sum()),'transit_n':int(f.eligible_transit_time.sum()),
            'mean_processing_days':f.loc[f.eligible_processing_time==1,'processing_days'].mean(),'mean_transit_days':f.loc[f.eligible_transit_time==1,'transit_days'].mean(),
            'temporal_flags':int(f.flag_temporal_error.sum()),'extreme_flags':int(f.flag_extreme_delivery.sum()),'delivered_missing_date':int(f.flag_missing_delivery_date.sum()),'no_items':int((f.item_count==0).sum()),
            'order_start':f.order_purchase_timestamp.min(),'order_end':f.order_purchase_timestamp.max(),
            'item_rows':con.execute('select count(*) from order_items').fetchone()[0],
            'seller_order_pairs':con.execute('select count(*) from (select distinct seller_id,order_id from order_items)').fetchone()[0]}
        # Compare the same late-order definition at incorrect item grain.
        m['naive_item_late_pct']=con.execute('select 100.0*sum(1-o.on_time_delivery)/count(*) from order_items i join orders o using(order_id) where eligible_on_time=1').fetchone()[0]
        m['true_order_late_pct']=100-m['on_time_pct']
        m['top_states']=rates.head(8).to_dict('records')
        # Stage components on a common valid cohort are additive; separate means are not.
        common=f[(f.eligible_processing_time==1)&(f.eligible_transit_time==1)&(f.eligible_delivery_days==1)]
        m['common_stage_n']=len(common);m['common_processing_mean']=common.processing_days.mean();m['common_transit_mean']=common.transit_days.mean()
        m['source_fingerprint']=hashlib.sha256(''.join(hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((DATA/'03_Raw_Dataset').glob('*.csv'))).encode()).hexdigest()
        (AUDIT/'results.json').write_text(json.dumps(m,indent=2),encoding='utf-8')
        return m

def main():
    start=time.perf_counter();candidate=DBDIR/'candidate.sqlite';final=DBDIR/'fulfilment.sqlite'
    logging.info('START rebuild')
    try:
        d=frames();checks=validate(d)
        # A prior interrupted candidate is disposable; final DB is never modified in place.
        if candidate.exists():candidate.unlink()
        load(d,candidate)
        # Re-execute the SQL dump in a separate memory database to test portability.
        with sqlite3.connect(':memory:') as restored:
            restored.executescript((DBDIR/'restore.sql').read_text(encoding='utf-8'))
            assert restored.execute('SELECT count(*) FROM orders').fetchone()[0]==len(d['orders'])
            assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        m=analyse(candidate)
        checks += [{'check':'sqlite_integrity_and_foreign_keys','failures':0},{'check':'restore_sql_recreated_orders','failures':0},{'check':'order_mart_row_preservation','failures':0}]
        pd.DataFrame(checks).to_csv(AUDIT/'checks.csv',index=False)
        os.replace(candidate,final)
        logging.info('SUCCESS orders=%s elapsed=%.2fs',len(d['orders']),time.perf_counter()-start)
        print(json.dumps(m,indent=2))
    except Exception:
        logging.exception('FAILED rebuild; prior final database retained until promotion');raise

if __name__=='__main__':main()
