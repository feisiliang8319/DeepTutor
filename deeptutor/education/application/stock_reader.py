"""Read the operator-built stock catalog. Administrator API only."""
import json
from pathlib import Path
import re
import sqlite3
from fastapi import HTTPException

STATES={'duplicate','needs_repair','needs_fact_check','reference_only','needs_curriculum_review'}


def snapshot(root: Path):
    pointer=root/'current.json'
    if not pointer.exists(): return None
    try:
        identity=json.loads(pointer.read_text())['snapshot_id']
        if not isinstance(identity,str) or not re.fullmatch(r'[a-f0-9]{64}',identity): raise ValueError('Bad identity')
        folder=root/'snapshots'/identity
        if folder.is_symlink() or not folder.resolve().is_relative_to(root.resolve()): raise ValueError('Bad path')
        summary=json.loads((folder/'summary.json').read_text())
        if summary['snapshot_id']!=identity: raise ValueError('Mismatched identity')
        if not (folder/'catalog.sqlite3').is_file(): raise ValueError('Missing catalog')
        return folder,summary
    except (OSError,ValueError,KeyError,TypeError):
        raise HTTPException(503,'Stock catalog is incomplete; operator verification required') from None


def summary(root: Path):
    current=snapshot(root)
    if current is None: return {'available':False}
    return {'available':True,**{k:v for k,v in current[1].items() if k!='source_manifest'}}


def records(root: Path, library: str, status: str, page: int):
    if not 0<=page<=10000 or status not in STATES|{''}: raise HTTPException(400,'Invalid stock filter')
    current=snapshot(root)
    if current is None: return {'items':[],'total':0,'page':page}
    folder,report=current
    if library not in {r['library'] for r in report['libraries']}|{''}: raise HTTPException(400,'Unknown library')
    query='WHERE 1=1';args=[]
    if library: query+=' AND library=?';args.append(library)
    if status: query+=' AND state=?';args.append(status)
    conn=sqlite3.connect((folder/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True)
    try:
        count=conn.execute('SELECT count(*) FROM records '+query,args).fetchone()[0]
        data=conn.execute('SELECT data_json FROM records '+query+' ORDER BY rowid LIMIT 20 OFFSET ?',[*args,page*20])
        fields=('id','library','title','source_path','source_line','state','issues','source_grade','source_difficulty')
        items=[]
        for (value,) in data:
            row=json.loads(value);items.append({**{k:row[k] for k in fields},'preview':row['prompt'][:360]})
        return {'items':items,'total':count,'page':page}
    finally: conn.close()


def record(root: Path, identity: str):
    if not re.fullmatch(r'[a-f0-9]{64}',identity): raise HTTPException(400,'Invalid record')
    current=snapshot(root)
    if current is None: raise HTTPException(404,'Stock catalog unavailable')
    conn=sqlite3.connect((current[0]/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True)
    try:
        row=conn.execute('SELECT data_json FROM records WHERE id=?',(identity,)).fetchone()
        if row is None: raise HTTPException(404,'Stock record not found')
        return json.loads(row[0])
    finally: conn.close()
