"""Group existing newspaper excerpts by source page, without inventing article boundaries.

No downloading, OCR correction, historical truth/age rating, or student approval.
An exact page reference enables later comparison with the existing scan.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from urllib.parse import urlsplit


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()


def describe(row, original):
    if row['kind']!='primary_source' or row['library']!='us-newspapers-primary-source':
        raise ValueError('Not a newspaper source')
    if sha(original)!=row['raw_sha256']:
        raise ValueError('Original source span changed')
    header=re.match(r'## (\d{4}-\d{2}-\d{2}) — passage ([1-9]\d*)\n',original)
    meta=re.search(r'\*\*Published:\*\* (\d{4}-\d{2}-\d{2})  \*\*Source page:\*\* (\S+)\s*\n',original)
    if not header or not meta or header[1]!=meta[1]:
        raise ValueError('Date/header metadata mismatch')
    if row['metadata'].get('published')!=meta[1] or row['metadata'].get('source_page')!=meta[2]:
        raise ValueError('Parsed metadata changed')
    date.fromisoformat(meta[1])
    u=urlsplit(meta[2])
    match=re.fullmatch(r'/lccn/((?:sn)?(?:\d{8}|\d{10}))/(\d{4}-\d{2}-\d{2})/ed-([1-9]\d*)/seq-([1-9]\d*)\.json',u.path)
    if u.scheme!='https' or u.netloc!='chroniclingamerica.loc.gov' or u.query or u.fragment or not match or match[2]!=meta[1]:
        raise ValueError('Unsupported or mismatched source page')
    content_start=meta.end()
    while content_start<len(original) and original[content_start].isspace():content_start+=1
    content_end=len(original)
    terminal=re.search(r'\n---\s*\Z',original)
    if terminal:content_end=terminal.start()
    while content_end>content_start and original[content_end-1].isspace():content_end-=1
    body=original[content_start:content_end]
    if not body:raise ValueError('Empty newspaper excerpt')
    # Diagnostics are measurements, not estimates of OCR accuracy.
    tokens=re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)*",body)
    odd=sum(1 for c in body if not (c.isalnum() or c.isspace()) and c not in '.,;:!?\'"-—–()[]{}%&/£$+*=<>')
    identity=f'{match[1]}/{match[2]}/ed-{match[3]}/seq-{match[4]}'
    return {
        'page_id':sha(identity),'page_key':identity,'source_page_url':meta[2],
        'published':meta[1],'newspaper_lccn':match[1],'edition':int(match[3]),
        'page_sequence':int(match[4]),'passage_sequence_in_file':int(header[2]),
        'body_span_in_source':{'start':row['start']+content_start,'end':row['start']+content_end,'sha256':sha(body)},
        'diagnostics':{'characters':len(body),'alphabetic_tokens':len(tokens),
            'isolated_letters_except_a_i':sum(len(t)==1 and t.lower() not in {'a','i'} for t in tokens),
            'nonstandard_punctuation_characters':odd,'replacement_characters':body.count('\ufffd')},
        'article_boundaries':'unknown_do_not_join_excerpts',
        'scan_comparison':'pending','ocr_correction':'not_performed',
        'historical_context':'pending','student_approval':'unchanged',
    }


def build(base, output):
    base=Path(base).resolve();summary=json.loads((base/'summary.json').read_text())
    if summary['snapshot_id']!=base.name or sha((base/'catalog.sqlite3').read_bytes())!=summary['catalog_sha256']:
        raise ValueError('Base snapshot changed')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        rows=[json.loads(x[0]) for x in db.execute("select data_json from records where library='us-newspapers-primary-source' order by id")]
    if len(rows)!=25341 or any('newspaper_page_inventory' in r['metadata'] for r in rows):
        raise ValueError('Unexpected or already processed population')
    objects={};pages={};updates={};decades=Counter();exact_groups=defaultdict(list)
    for row in rows:
        source=row['source_sha256']
        if source not in objects:
            blob=(base/'objects'/(source+'.md')).read_bytes()
            if sha(blob)!=source:raise ValueError('Original source changed')
            objects[source]=blob.decode()
        original=objects[source][row['start']:row['end']]
        info=describe(row,original)
        span=info['body_span_in_source']
        if sha(objects[source][span['start']:span['end']])!=span['sha256']:raise ValueError('Body span changed')
        page=pages.setdefault(info['page_id'],{k:info[k] for k in ('page_id','page_key','source_page_url','published','newspaper_lccn','edition','page_sequence')})
        page.setdefault('passages',[]).append({'record_id':row['id'],'source_sha256':source,'raw_sha256':row['raw_sha256'],'source_path':row['source_path'],'source_line':row['source_line'],'passage_sequence_in_file':info['passage_sequence_in_file'],'body_span_in_source':span,'diagnostics':info['diagnostics']})
        decades[info['published'][:3]+'0s']+=1
        exact_groups[(info['page_id'],span['sha256'])].append(row['id'])
        row['metadata']={**row['metadata'],'newspaper_page_inventory':info};updates[row['id']]=row
    if len(pages)!=7236:raise ValueError('Source page count changed')
    duplicates=[ids for ids in exact_groups.values() if len(ids)>1]
    for page in pages.values():
        page['passages'].sort(key=lambda x:x['passage_sequence_in_file'])
        page.update(passages_count=len(page['passages']),review_status='scan_and_historical_context_pending',article_boundaries='unknown_do_not_join_excerpts')
    identity=sha(json.dumps({'base':base.name,'processor':sha(Path(__file__).read_bytes())},sort_keys=True))
    target=Path(output)/identity;shutil.copytree(base,target)
    with sqlite3.connect(target/'catalog.sqlite3') as db:
        for row in updates.values():db.execute('update records set data_json=? where id=?',(json.dumps(row,ensure_ascii=False),row['id']))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity failure')
        changed=0
        with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
            for a,b in zip(old.execute('select data_json from records order by id'),db.execute('select data_json from records order by id'),strict=True):
                a,b=json.loads(a[0]),json.loads(b[0])
                if a==b:continue
                changed+=1
                if a['id'] not in updates or {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}!={'metadata'}:raise ValueError('Unrelated field changed')
                if {k:v for k,v in b['metadata'].items() if k!='newspaper_page_inventory'}!=a['metadata']:raise ValueError('Previous metadata changed')
        if changed!=25341:raise ValueError('Changed population mismatch')
    queue={'scope':'Existing source-page inventory only; excerpts kept separate; all OCR/context/age/rights gates retained.','pages':sorted(pages.values(),key=lambda x:x['page_key']),'exact_same_page_duplicate_groups':duplicates}
    (target/'newspaper-page-queue.json').write_text(json.dumps(queue,ensure_ascii=False,indent=2)+'\n')
    report={**summary,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':summary['committed_batches']+1,'newspaper_page_inventory':{'passages':len(rows),'source_pages':len(pages),'source_files':len(objects),'by_decade':dict(sorted(decades.items())),'same_page_exact_duplicate_groups':len(duplicates),'queue_sha256':sha((target/'newspaper-page-queue.json').read_bytes()),'ocr_corrected':0,'student_approved':0}}
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return {k:report[k] for k in ('snapshot_id','base_snapshot_id','catalog_sha256','committed_batches','newspaper_page_inventory')}
