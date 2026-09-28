import json,sqlite3
from pathlib import Path
import pytest
from deeptutor.education.application.math_reasoning_reviews import patch_document,build,sha
from deeptutor.education.application.content_stock import parse_file

def fixture():
 text='# fixture\nProblems in this file: 2\n\n## Grid\n\n### Problem\n\nQuestion [asy]inert[/asy]\n\n### Answer\n\n$6$\n\n### Solution 1 of 2\n\nA previously correct solution.\n\n### Solution 2 of 2\n\nAn invalid argument.\n\n---\n\n## Next\n\n### Problem\n\n1+1\n\n### Answer\n\n2\n\n### Solution\n\nAn earlier correction retained.\n'
 r={'title':'Grid','answer_before':'$6$','explanation_before':'A previously correct solution.\n\nAn invalid argument.','explanation_after':'A previously correct solution.\n\nA checked argument.'}
 return text,r

def test_replaces_only_selected_solution():
 text,r=fixture();new=patch_document('harp-counting-and-probability.md',text,[r])
 assert new==text.replace('An invalid argument.','A checked argument.')
 with pytest.raises(ValueError):patch_document('harp-counting-and-probability.md',new,[r])
@pytest.mark.parametrize('kind',['answer','explanation','missing','duplicate','headings','solution_count'])
def test_reject_ambiguous_or_stale_review(kind):
 text,r=fixture()
 if kind=='answer':r['answer_before']='7'
 if kind=='explanation':r['explanation_before']='different'
 if kind=='missing':r['title']='absent'
 if kind=='duplicate':text=text+text
 if kind=='headings':r['explanation_after']='A previously correct solution.\n\nWrong\n### Answer\n7'
 if kind=='solution_count':r['explanation_after']='Only one solution'
 with pytest.raises(ValueError):patch_document('harp-counting-and-probability.md',text,[r])
def test_build_preserves_prior_revision_source_and_gates(tmp_path):
 current,r=fixture();original=current.replace('An earlier correction retained.','Original bad explanation.')
 base=tmp_path/'base';base.mkdir();(base/'objects').mkdir();source=sha(original);revised=sha(current)
 for blob in (original,current):(base/'objects'/(sha(blob)+'.md')).write_text(blob)
 filename='harp-counting-and-probability.md';path='harp-competition/raw/'+filename
 source_rows=parse_file('harp-competition',filename,original);rows=[]
 for i,a in enumerate(source_rows):
  a.update(id=str(i),library='harp-competition',source_path=path,source_sha256=source,raw_sha256=sha(original[a['start']:a['end']]),state='needs_repair',approval='unreviewed',rights='source_claim_only')
  if i==1:a['explanation']='An earlier correction retained.';a['metadata']['prior_review']={'retained':True}
  rows.append(a)
 recipe={'library':'harp-competition','records':[{**r,**{k:rows[0][k] for k in ('id','source_path','source_sha256','raw_sha256')}}]}
 with sqlite3.connect(base/'catalog.sqlite3') as db:
  db.execute('create table records(id text primary key,data_json text)');db.executemany('insert into records values(?,?)',[(a['id'],json.dumps(a)) for a in rows])
 (base/'summary.json').write_text(json.dumps({'snapshot_id':'base','catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':118}))
 (base/'math-figure-revised-documents.json').write_text(json.dumps([{'source_path':path,'revised_sha256':revised}]))
 (base/'prior-review.json').write_text('keep');rp=tmp_path/'recipe.json';rp.write_text(json.dumps(recipe))
 result=build(base,rp,tmp_path/'out');target=tmp_path/'out'/result['snapshot_id']
 assert result['changed_documents'][0]['expected_current_sha256']==revised
 assert (target/'math-reasoning-revised-documents'/filename).read_text()==current.replace('An invalid argument.','A checked argument.')
 assert (target/'objects'/(source+'.md')).read_text()==original and (target/'prior-review.json').read_text()=='keep'
 with sqlite3.connect(target/'catalog.sqlite3') as db:updated=[json.loads(x[0]) for x in db.execute('select data_json from records order by id')]
 assert updated[1]==rows[1];a=updated[0];a['metadata'].pop('math_reasoning_review');a['explanation']=rows[0]['explanation'];assert a==rows[0]
 with pytest.raises(ValueError,match='already applied'):build(target,rp,tmp_path/'out2')
