import json
from pathlib import Path
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from deeptutor.education.api.app import create_app
from deeptutor.education.application.content_stock import process
from deeptutor.education.application import stock_reader
from deeptutor.education.tests.test_content_stock import math_source
from deeptutor.education.tests.test_web_loop import web_db
from deeptutor.education.tests.test_free_learning_accounts import accounts, headers


def stage(root):
    raw=root/'input/math-competition/raw';raw.mkdir(parents=True)
    (raw/'math-a.md').write_text(math_source())
    report=process(root/'input',root/'content-stock/snapshots')
    (root/'content-stock/current.json').write_text(json.dumps({'snapshot_id':report['snapshot_id']}))
    return root/'content-stock',report


def test_reader_missing_broken_pointer_and_pagination(tmp_path):
    root,report=stage(tmp_path)
    assert stock_reader.summary(tmp_path/'absent')=={'available':False}
    assert stock_reader.summary(root)['records']==1
    data=stock_reader.records(root,'math-competition','needs_curriculum_review',0)
    assert data['total']==1
    row=stock_reader.record(root,data['items'][0]['id'])
    assert row['answer']=='42' and not row['grade_assignment']
    assert stock_reader.records(root,'','',1)['items']==[]
    for library,status,page in [('../other','',0),('','approved',0),('','',-1)]:
        with pytest.raises(HTTPException): stock_reader.records(root,library,status,page)
    (root/'current.json').write_text('{"snapshot_id":"../../private"}')
    with pytest.raises(HTTPException) as exc: stock_reader.summary(root)
    assert exc.value.status_code==503


def test_stock_routes_require_real_administrator(web_db,accounts):
    stage(Path(web_db).parent)
    client=TestClient(create_app(web_db,account_access=accounts[2]))
    base='/api/edu/content-admin/stock'
    admin=headers(accounts,'dtu-parent') # fixture role is admin until explicitly changed
    response=client.get(base+'/records',headers=admin)
    assert response.status_code==200,response.text
    identity=response.json()['items'][0]['id']
    paths=[base,base+'/records',base+'/records/'+identity]
    for path in paths:
        assert client.get(path).status_code==401
        assert client.get(path,headers=headers(accounts)).status_code==403
        assert client.get(path,headers=admin).status_code==200
    accounts[0]['dtu-parent']['role']='parent'
    for path in paths: assert client.get(path,headers=admin).status_code==403
