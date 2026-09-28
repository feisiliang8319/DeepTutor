import hashlib,json,sqlite3
import pytest
from deeptutor.education.application.historical_adaptation_links import build

def fixture(tmp_path):
    sha=lambda x:hashlib.sha256(x).hexdigest()
    base=tmp_path/'base';base.mkdir();(base/'objects').mkdir()
    blob=b'Question\r\nSolution\r\n';text=blob.decode().replace('\r\n','\n');source=sha(blob)
    spans=[{'start':0,'end':len(text),'sha256':sha(text.encode())}]
    (base/'objects'/(source+'.txt')).write_bytes(blob)
    row={'id':'one','library':'historical-puzzle-books','source_sha256':source,'metadata':{'spans':spans,'pedagogical_review':'pending'},'state':'reference_only','approval':'unreviewed','prompt':'Question','answer':''}
    with sqlite3.connect(base/'catalog.sqlite3') as db:
        db.execute('create table records (id text,data_json text)');db.execute('insert into records values (?,?)',('one',json.dumps(row)))
    (base/'summary.json').write_text(json.dumps({'snapshot_id':'base','catalog_sha256':sha((base/'catalog.sqlite3').read_bytes()),'committed_batches':5}))
    (base/'prior-queue.json').write_text('unchanged')
    package=tmp_path/'package.json';package.write_text(json.dumps({'items':[{'id':'candidate','expected_answer':'42','explanation':'derived','rubric_json':{'source_record_id':'one','source_sha256':source,'source_spans':spans}}]}))
    proof=tmp_path/'proof.json';proof.write_text(json.dumps({'package_sha256':sha(package.read_bytes()),'verified_tasks':1}))
    return base,package,proof,row

def test_links_keep_original_approval_source_and_previous_evidence(tmp_path):
    base,package,proof,row=fixture(tmp_path);before=(base/'catalog.sqlite3').read_bytes()
    result=build(base,[(package,proof)],tmp_path/'output');target=tmp_path/'output'/result['snapshot_id']
    assert (base/'catalog.sqlite3').read_bytes()==before and (target/'prior-queue.json').read_text()=='unchanged'
    with sqlite3.connect(target/'catalog.sqlite3') as db:saved=json.loads(db.execute('select data_json from records').fetchone()[0])
    link=saved['metadata'].pop('checked_teaching_adaptation')
    assert saved==row and link['candidate_item_id']=='candidate'
    with pytest.raises(ValueError,match='already linked'):build(target,[(package,proof)],tmp_path/'again')

def test_rejects_unbound_proof_duplicate_source_and_changed_source_bytes(tmp_path):
    base,package,proof,row=fixture(tmp_path)
    with pytest.raises(ValueError,match='Duplicate artifact'):build(base,[(package,proof),(package,proof)],tmp_path/'duplicate')
    package.write_text(package.read_text()+' ')
    with pytest.raises(ValueError,match='Unbound'):build(base,[(package,proof)],tmp_path/'unbound')
    package.write_text(package.read_text()[:-1])
    (base/'objects'/(row['source_sha256']+'.txt')).write_text('changed')
    with pytest.raises(ValueError,match='Source bytes'):build(base,[(package,proof)],tmp_path/'tampered')
