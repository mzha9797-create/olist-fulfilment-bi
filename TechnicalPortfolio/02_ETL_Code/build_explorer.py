"""Build an order-grain historical exploration page. Refresh/save in Desktop after running."""
from pathlib import Path
import json, sqlite3, copy
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT/'03_Dashboards/MBI807_Fulfilment_Project'
REPORT=PROJECT/'MBI807_Fulfilment.Report/definition/pages'
MODEL=PROJECT/'MBI807_Fulfilment.SemanticModel/definition'
with sqlite3.connect(ROOT/'01_Database/fulfilment.sqlite') as con:
    f=pd.read_sql_query('''SELECT order_id,customer_state,order_status,
      substr(order_purchase_timestamp,1,10) purchase_date,
      substr(order_purchase_timestamp,1,7) purchase_month,
      item_count,item_value,freight_value,eligible_on_time,
      CASE WHEN eligible_on_time=1 THEN 1-on_time_delivery ELSE 0 END late_flag,
      CASE WHEN eligible_delivery_days=1 THEN delivery_days END valid_delivery_days
      FROM order_fulfilment''',con)
assert len(f)==99441 and f.order_id.is_unique
assert f.eligible_on_time.sum()==96470 and f.late_flag.sum()==6534
csv=ROOT/'04_Data_Examples/clean/order_explorer.csv';f.to_csv(csv,index=False)
types={c:('string' if c in ['order_id','customer_state','order_status','purchase_date','purchase_month'] else 'double') for c in f.columns}
measures={'Orders':('COUNTROWS(\'Order Explorer\')','#,0'),
 'Eligible Orders':("SUM('Order Explorer'[eligible_on_time])",'#,0'),
 'Late Orders':("SUM('Order Explorer'[late_flag])",'#,0'),
 'On-time Rate':('IF([Eligible Orders] > 0, 1 - DIVIDE([Late Orders], [Eligible Orders]))','0.00%'),
 'Late Rate':('DIVIDE([Late Orders], [Eligible Orders])','0.00%'),
 'Coverage':('DIVIDE([Eligible Orders], [Orders])','0.00%'),
 'Mean Delivery Days':("AVERAGE('Order Explorer'[valid_delivery_days])",'0.00')}
t="table 'Order Explorer'\n"
for name,(expr,fmt) in measures.items():t+=f"\n\tmeasure '{name}' = {expr}\n\t\tformatString: {fmt}\n"
for c,typ in types.items():t+=f'\n\tcolumn {c}\n\t\tdataType: {typ}\n\t\tsummarizeBy: none\n\t\tsourceColumn: {c}\n'
coltypes=','.join('{"'+c+'", '+('type text' if typ=='string' else 'type number')+'}' for c,typ in types.items())
t+="\n\tpartition 'Order Explorer' = m\n\t\tmode: import\n\t\tsource =\n\t\t\tlet\n\t\t\t Source = Csv.Document(File.Contents(\""+csv.as_posix()+"\"),[Delimiter=\",\",Encoding=65001,QuoteStyle=QuoteStyle.Csv]),\n\t\t\t Headers = Table.PromoteHeaders(Source,[PromoteAllScalars=true]),\n\t\t\t Typed = Table.TransformColumnTypes(Headers,{"+coltypes+"},\"en-US\")\n\t\t\tin Typed\n"
for name in measures:
    t=t.replace("measure '"+name+"'", "measure 'Explorer "+name+"'").replace('['+name+']','[Explorer '+name+']')
(MODEL/'tables/Order Explorer.tmdl').write_text(t,encoding='utf8')
p=MODEL/'model.tmdl';t=p.read_text(encoding='utf-8-sig')
if "ref table 'Order Explorer'" not in t:t+="\nref table 'Order Explorer'\n"
p.write_text(t,encoding='utf8')
pageid='operations_explorer';page=REPORT/pageid;page.mkdir(exist_ok=True)
template=REPORT/'130782c2884ad946537a'
pg=json.loads((template/'page.json').read_text());pg.update(name=pageid,displayName='Operations Explorer')
(page/'page.json').write_text(json.dumps(pg,indent=2))
def field(name,measure=False):return {('Measure' if measure else 'Column'):{'Expression':{'SourceRef':{'Entity':'Order Explorer'}},'Property':('Explorer '+name if measure else name)}}
def projection(name,measure=False):return {'field':field(name,measure),'queryRef':'Order Explorer.'+('Explorer '+name if measure else name),'nativeQueryRef':name}
def lit(v):return {'expr':{'Literal':{'Value':v}}}
def visual(name,typ,pos,queries,title,objects=None):
    obj={'$schema':'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.12.0/schema.json','name':name,
      'position':dict(zip(['x','y','width','height'],pos),z=0,tabOrder=0),
      'visual':{'visualType':typ,'query':{'queryState':{role:{'projections':projs} for role,projs in queries.items()}},
      'visualContainerObjects':{'title':[{'properties':{'show':lit('true'),'text':lit("'"+title+"'"),'fontSize':lit('16D')}}],
        'background':[{'properties':{'show':lit('true'),'color':{'solid':{'color':lit("'#FFFFFF'")}},'transparency':lit('0D')}}]},'drillFilterOtherVisuals':True}}
    if objects:obj['visual']['objects']=objects
    folder=page/'visuals'/name;folder.mkdir(parents=True,exist_ok=True);(folder/'visual.json').write_text(json.dumps(obj,indent=2))
# Copy the supported native card definition, changing only bound fields and position.
card=json.loads((template/'visuals/07e3f016640ba905594b/visual.json').read_text())
for i,name in enumerate(['Orders','Eligible Orders','Late Orders','On-time Rate','Coverage']):
    s=json.dumps(card).replace('State Performance','Order Explorer').replace('Late Orders','Explorer '+name)
    o=json.loads(s);o['name']='kpi_'+str(i);o['position'].update(x=35+i*374,y=150,width=360,height=150)
    for item in o['visual'].get('objects',{}).get('label',[]):
        if 'text' in item.get('properties',{}):item['properties']['text']=lit("'"+name+"'")
    for proj in o['visual']['query']['queryState']['Data']['projections']:proj['displayName']=name
    if name in ['On-time Rate','Coverage']:
        s=json.dumps(o).replace('#,0','0.00%');o=json.loads(s)
        for item in o['visual'].get('objects',{}).get('value',[]):
            item.get('properties',{})['labelPrecision']=lit('2L')
    folder=page/'visuals'/o['name'];folder.mkdir(parents=True,exist_ok=True);(folder/'visual.json').write_text(json.dumps(o,indent=2))
for i,col in enumerate(['purchase_month','customer_state']):
    visual('filter_'+col,'slicer',(35+i*650,35,620,90),{'Values':[projection(col)]},'Purchase month' if i==0 else 'Customer state',
       {'data':[{'properties':{'mode':lit("'Dropdown'")}}],'selection':[{'properties':{'singleSelect':lit('false'),'selectAllCheckboxEnabled':lit('true')}}]})
visual('monthly_late','lineChart',(35,325,1130,340),{'Category':[projection('purchase_month')],'Y':[projection('Late Rate',True)]},'Late rate by purchase month (eligible orders only)')
visual('monthly_coverage','lineChart',(1185,325,700,340),{'Category':[projection('purchase_month')],'Y':[projection('Coverage',True)]},'Eligibility coverage by purchase month')
visual('order_details','tableEx',(35,690,1850,340),{'Values':[projection(c) for c in ['order_id','purchase_date','customer_state','order_status','item_count','eligible_on_time','late_flag','valid_delivery_days']]},'Historical order details | 2016–2018 snapshot; incomplete edge cohorts require caution',
       {'columnHeaders':[{'properties':{'fontSize':lit('12D')}}],'values':[{'properties':{'fontSize':lit('11D')}}],'total':[{'properties':{'totals':lit('false')}}]})
p=REPORT/'pages.json';meta=json.loads(p.read_text())
if pageid not in meta['pageOrder']:meta['pageOrder'].append(pageid)
p.write_text(json.dumps(meta,indent=2))
print(json.dumps({'orders':len(f),'eligible':int(f.eligible_on_time.sum()),'late':int(f.late_flag.sum()),'page':pageid}))
