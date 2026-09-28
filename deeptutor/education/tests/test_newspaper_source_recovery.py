import copy,hashlib,json,sqlite3
from pathlib import Path
import pytest
from deeptutor.education.application.newspaper_source_recovery import identity,page_metadata,alto_diagnostics,verify_recovery,build
URL='https://chroniclingamerica.loc.gov/lccn/sn83025881/1800-01-01/ed-1/seq-4.json'
ASSET='/service/sgp/sgpbatches/batch_dlc_laperm_ver01/data/sn83025881/print/1800010101/0004.xml'
XML=b'<alto xmlns="http://schema.ccs-gmbh.com/ALTO"><Layout><Page WIDTH="100" HEIGHT="200" PHYSICAL_IMG_NR="4"><PrintSpace><TextBlock><TextLine WIDTH="90"><String ID="a" CONTENT="Old"/><String ID="b" CONTENT="text"/></TextLine></TextBlock></PrintSpace></Page></Layout></alto>'
def doc():
 return {'item':{'id':'http://www.loc.gov/item/sn83025881/1800-01-01/ed-1/','date':'1800-01-01'},'pagination':{'current':4},'segment_id':ASSET,'page':[{'mimetype':'text/xml','url':'https://tile.loc.gov/storage-services'+ASSET}]}
def fixture(root):
 key=identity(URL);folder=root/key['page_id'];folder.mkdir(parents=True)
 blobs={'page.json':json.dumps(doc()).encode(),'page.xml':XML};urls={'page.json':key['resource_url'],'page.xml':'https://tile.loc.gov/storage-services'+ASSET};files={}
 for name,blob in blobs.items():
  (folder/name).write_bytes(blob);files[name]={'sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob),'url':urls[name]}
 (folder/'receipt.json').write_text(json.dumps({'original_url':URL,'files':files}));return folder

def test_valid_but_not_approved(tmp_path):
 r=verify_recovery(fixture(tmp_path),URL)
 assert r['diagnostics']['words']==2 and r['diagnostics']['lines_wider_than_70_percent']==1
 assert r['diagnostics']['character_accuracy']=='not_measured' and r['student_approval']=='unchanged'
@pytest.mark.parametrize('kind',['domain','edition','page','date','asset','segment','traversal'])
def test_metadata_mismatch(kind):
 d=doc()
 if kind=='domain':d['item']['id']=d['item']['id'].replace('www.loc.gov','evil.example')
 if kind=='edition':d['item']['id']=d['item']['id'].replace('ed-1','ed-2')
 if kind=='page':d['pagination']['current']=3
 if kind=='date':d['item']['date']='1801-01-01'
 if kind=='asset':d['page'][0]['url']='http://127.0.0.1/secret.xml'
 if kind=='segment':d['segment_id']=ASSET.replace('0004','0005')
 if kind=='traversal':d['page'][0]['url']=d['page'][0]['url'].replace('/print/','/print/../');d['segment_id']=d['segment_id'].replace('/print/','/print/../')
 with pytest.raises(ValueError):page_metadata(URL,d)
@pytest.mark.parametrize('blob',[b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///secret">]>'+XML,XML.replace(b'NR="4"',b'NR="3"'),XML.replace(b'ID="b"',b'ID="a"'),XML.replace(b'WIDTH="100"',b'WIDTH="nan"')])
def test_invalid_xml(blob):
 with pytest.raises(ValueError):alto_diagnostics(blob,4)
def test_asset_tampering(tmp_path):
 f=fixture(tmp_path);(f/'page.xml').write_bytes(XML+b' ')
 with pytest.raises(ValueError):verify_recovery(f,URL)
@pytest.mark.parametrize('bad',[URL+'?next=1',URL.replace('https://','http://'),URL.replace('loc.gov','loc.gov.evil.example'),URL.replace('1800-01-01','1800-02-31')])
def test_bad_stock_reference(bad):
 with pytest.raises(ValueError):identity(bad)
def test_catalog_keeps_content_permissions_and_all_other_rows(tmp_path):
 recovery=tmp_path/'recovery';f=fixture(recovery);key=identity(URL);base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
 raw=b'Original damaged excerpt';source=hashlib.sha256(raw).hexdigest();(base/'objects'/(source+'.md')).write_bytes(raw)
 old={'id':'x','library':'us-newspapers-primary-source','source_sha256':source,'prompt':'damaged original','answer':'','state':'reference_only','approval':'unreviewed','issues':['ocr_review','historical_context_required'],'metadata':{'newspaper_page_inventory':{'page_id':key['page_id']}}}
 other={**old,'id':'y','library':'math'}
 with sqlite3.connect(base/'catalog.sqlite3') as db:
  db.execute('create table records(id text primary key, library text, data_json text)')
  db.executemany('insert into records values(?,?,?)',[(r['id'],r['library'],json.dumps(r)) for r in [old,other]])
 (base/'summary.json').write_text(json.dumps({'snapshot_id':'base','catalog_sha256':hashlib.sha256((base/'catalog.sqlite3').read_bytes()).hexdigest(),'committed_batches':117,'records':2}))
 (base/'newspaper-page-queue.json').write_text(json.dumps({'pages':[{'page_id':key['page_id'],'source_page_url':URL,'passages_count':1,'passages':[{'record_id':'x'}]}]}))
 (base/'prior-review.json').write_bytes(b'unchanged')
 result=build(base,recovery,tmp_path/'output');target=tmp_path/'output'/result['snapshot_id']
 with sqlite3.connect(target/'catalog.sqlite3') as db:rows={x[0]:json.loads(x[1]) for x in db.execute('select id,data_json from records')}
 updated=rows['x'];updated['metadata'].pop('newspaper_source_recovery');assert updated==old and rows['y']==other
 assert (target/'prior-review.json').read_bytes()==b'unchanged' and result['committed_batches']==118
 assert result['newspaper_source_recovery']['student_approved']==0
 with pytest.raises(ValueError,match='already linked'):build(target,recovery,tmp_path/'output2')

@pytest.mark.parametrize('old,new',[('1800010101','1800010201'),('0004.xml','0005.xml')])
def test_asset_date_or_sequence_mismatch(old,new):
 d=doc();d['segment_id']=d['segment_id'].replace(old,new);d['page'][0]['url']=d['page'][0]['url'].replace(old,new)
 with pytest.raises(ValueError,match='filename'):page_metadata(URL,d)

def test_official_field_filter_is_allowed_but_arbitrary_query_is_not(tmp_path):
 f=fixture(tmp_path);p=f/'receipt.json';r=json.loads(p.read_text());r['files']['page.json']['url']+='&at=item,pagination,page,segment_id';p.write_text(json.dumps(r));assert verify_recovery(f,URL)['page_id']==identity(URL)['page_id']
 r['files']['page.json']['url']+='&redirect=https://evil.example';p.write_text(json.dumps(r))
 with pytest.raises(ValueError,match='URL mismatch'):verify_recovery(f,URL)
