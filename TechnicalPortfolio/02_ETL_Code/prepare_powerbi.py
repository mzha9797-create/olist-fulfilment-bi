"""Prepare an independent Power BI project with CSV sources and additive statistics.
Requires Power BI Desktop to refresh and save as PBIX; structural QA is not GUI QA.
"""
from pathlib import Path
import shutil,re,json,sqlite3,uuid
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'03_Dashboards/MBI807_Fulfilment_Project'
if not DEST.exists():
    raise FileNotFoundError('Keep the supplied editable Power BI project inside 03_Dashboards.')
report=DEST/'MBI807_Fulfilment.Report';model=DEST/'MBI807_Fulfilment.SemanticModel'
for p in [report/'definition.pbir',model/'definition/model.tmdl']:
    t=p.read_text(encoding='utf-8-sig').replace('MBI806_Late_Delivery','MBI807_Fulfilment')
    t=re.sub(r"ref table 'ML [^']+'\s*",'',t)
    t=t.replace(',"ML Predictions","ML Comparison"','')
    p.write_text(t,encoding='utf-8')
meta=report/'definition/pages/pages.json';j=json.loads(meta.read_text());j['pageOrder']=[p for p in j['pageOrder'] if p!='b806latedeliveryml01'];j['activePageName']=j['pageOrder'][0];meta.write_text(json.dumps(j,indent=2))
(DEST/'MBI807_Fulfilment.pbip').write_text(json.dumps({'version':'1.0','artifacts':[{'report':{'path':'MBI807_Fulfilment.Report'}}],'settings':{'enableAutoRecovery':True}},indent=2))
with sqlite3.connect(ROOT/'01_Database/fulfilment.sqlite') as con:
    orders=pd.read_sql('select * from order_fulfilment',con)
    items=pd.read_sql('select i.*,p.category_display,p.product_weight_g from order_items i join products p using(product_id)',con)
    frames={'State Performance':orders,'Seller Performance':items[['seller_id','order_id']].drop_duplicates().merge(orders,on='order_id',validate='many_to_one'),'Category Performance':items[['category_display','order_id']].drop_duplicates().merge(orders,on='order_id',validate='many_to_one')}
    mapping={'State Performance':('customer_state','vw_state_delivery_performance'),'Seller Performance':('seller_id','vw_seller_performance'),'Category Performance':('category_display','vw_category_performance')}
    validation=[]
    for table,(key,view) in mapping.items():
        f=frames[table].copy();extras=[]
        for short,eligible,value in [('delivery','eligible_delivery_days','delivery_days'),('processing','eligible_processing_time','processing_days'),('transit','eligible_transit_time','transit_days')]:
            f[short+'_sum']=f[value].where(f[eligible]==1,0).fillna(0)
            f[short+'_n']=(f[eligible]==1).astype(int);extras.extend([short+'_sum',short+'_n'])
        agg=f.groupby(key)[extras].sum().reset_index()
        base=pd.read_sql('select * from '+view,con)
        # The inherited category view names its join key category_display.
        out=base.merge(agg,on=key,how='left',validate='one_to_one')
        if table=='Category Performance':
            w=items.assign(weight_sum=items.product_weight_g.fillna(0),weight_n=items.product_weight_g.notna().astype(int)).groupby(key)[['weight_sum','weight_n']].sum().reset_index()
            out=out.merge(w,on=key,validate='one_to_one');extras+=['weight_sum','weight_n']
        outpath=ROOT/'04_Data_Examples/clean'/f'{view}_powerbi.csv';out.to_csv(outpath,index=False)
        p=model/'definition/tables'/f'{table}.tmdl';t=p.read_text(encoding='utf-8-sig')
        # Correct group-average totals using exact sums and metric-specific denominators.
        for original,short in [('avg_delivery_days','delivery'),('avg_processing_days','processing'),('avg_transit_days','transit'),('avg_product_weight_g','weight')]:
            t=t.replace(f"AVERAGE('{table}'[{original}])",f"DIVIDE(SUM('{table}'[{short}_sum]), SUM('{table}'[{short}_n]))")
        for c in extras:
            if not re.search(r'\n\tcolumn '+re.escape(c)+r'\s',t):
                t+='\n\tcolumn '+c+'\n\t\tdataType: double\n\t\tsummarizeBy: sum\n\t\tsourceColumn: '+c+'\n'
        # Explicit types avoid locale-dependent inference and text-valued measures.
        coltypes=[]
        for block in re.split(r'\n\tcolumn ',t)[1:]:
            name=block.splitlines()[0].strip().strip("'");m=re.search(r'dataType: (\w+)',block)
            if name in out.columns and m:coltypes.append('{"'+name+'", '+('type text' if m.group(1)=='string' else 'type number')+'}')
        source='\t\t\tlet\n\t\t\t  Source = Csv.Document(File.Contents("'+str(outpath).replace('\\','/')+'"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n\t\t\t  Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n\t\t\t  Typed = Table.TransformColumnTypes(Headers, {'+','.join(coltypes)+'}, "en-US")\n\t\t\tin Typed\n'
        t=re.sub(r'(\tpartition .*?\n\t\tmode: import\n\t\tsource =\n).*?(?=\n\t(?:changedProperty|annotation|column)|\Z)',lambda m:m.group(1)+source,t,flags=re.S)
        p.write_text(t,encoding='utf-8')
        required=re.findall(r'sourceColumn: (.+)',t)
        assert set(required)<=set(out.columns),(table,set(required)-set(out.columns))
        validation.append({'table':table,'rows':len(out),'source_columns_checked':len(required)})
    mean=orders.loc[orders.eligible_delivery_days==1,'delivery_days'].mean()
    weighted=frames['State Performance'];assert abs(mean-12.558173691015053)<1e-10
    simple=con.execute('select avg(avg_delivery_days) from vw_state_delivery_performance').fetchone()[0]
    validation.append({'unweighted_state_average_days':simple,'correct_order_weighted_mean_days':mean})
# Recompute inherited static scatter reference lines from the same benchmark
# cohorts as the DAX measures. These are whole-snapshot, not slicer targets.
state=pd.read_csv(ROOT/'04_Data_Examples/clean/vw_state_delivery_performance_powerbi.csv')
seller=pd.read_csv(ROOT/'04_Data_Examples/clean/vw_seller_performance_powerbi.csv')
category=pd.read_csv(ROOT/'04_Data_Examples/clean/vw_category_performance_powerbi.csv')
st=state[state.eligible_orders>=300];se=seller[seller.eligible_orders>=100];ca=category[category.associated_orders>=300]
benchmarks={
 '130782c2884ad946537a':(st.delivery_sum.sum()/st.delivery_n.sum(),1-state.late_orders.sum()/state.eligible_orders.sum(),'days'),
 'a2001a7337c9b1312c7a':(se.processing_sum.sum()/se.processing_n.sum(),1-se.late_orders.sum()/se.eligible_orders.sum(),'days'),
 '2704a7eb02dbd19b17ea':(ca.weight_sum.sum()/ca.weight_n.sum(),ca.freight_value.sum()/ca.item_value.sum(),'g')}
for p in report.rglob('*.json'):
    j=json.loads(p.read_text(encoding='utf-8-sig'))
    for page,(x,y,unit) in benchmarks.items():
        if page in p.parts:
            objects=j.get('visual',{}).get('objects',{})
            for axis,value,label in [('xAxisReferenceLine',x,f'Benchmark: {x:,.2f} {unit}'),('y1AxisReferenceLine',y,f'Benchmark: {y:.2%}')]:
                for line in objects.get(axis,[]):
                    props=line['properties']
                    props['value']['expr']['Literal']['Value']=f'{value:.12f}D'
                    props['displayName']['expr']['Literal']['Value']="'"+label+"'"
    # Only labels are changed; no blanket replacement of field identifiers.
    s=json.dumps(j,ensure_ascii=False).replace('MBI806','MBI807')
    p.write_text(s,encoding='utf-8')
(ROOT/'04_Data_Examples/verification/powerbi_structural_checks.json').write_text(json.dumps({'checks':validation,'scope':'Structural and calculation checks only. Separate runtime evidence is in powerbi_desktop_acceptance.json. After any rebuild repeat Desktop acceptance before replacing that evidence.'},indent=2),encoding='utf-8')
print(json.dumps(validation,indent=2))
