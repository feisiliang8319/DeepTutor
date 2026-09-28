"""Lossless pairing of already-local historical puzzle books; no web or models.

This is a reference inventory, not a student-facing publication or exam bank.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import argparse,hashlib,json,re

BOOKS={'amusements-in-mathematics.txt':('Amusements in Mathematics',430,'Henry Ernest Dudeney','16713'),
       'canterbury-puzzles.txt':('The Canterbury Puzzles',114,'Henry Ernest Dudeney','27635'),
       'tangled-tale.txt':('A Tangled Tale',10,'Lewis Carroll','29042')}
HEADER=re.compile(r'^(\d+)\.?[ \t]*--[ \t]*([_"“]?[A-Z][^\n]+)',re.M)
def sha(text):return hashlib.sha256(text.encode() if isinstance(text,str) else text).hexdigest()
def ranges(text,start,end,pattern):
 hits=list(pattern.finditer(text,start,end))
 return [(m,text[m.end():hits[i+1].start() if i+1<len(hits) else end].strip(),m.start(),hits[i+1].start() if i+1<len(hits) else end) for i,m in enumerate(hits)]
def numbered(text,filename):
 split=re.search(r'^SOLUTIONS\.?[ \t]*$',text,re.M)
 if not split:raise ValueError('Missing solutions boundary')
 end=re.search(r'^INDEX\.|^\*\*\* END OF ',text[split.end():],re.M)
 if not end:raise ValueError('Missing end boundary')
 end=split.end()+end.start()
 def group(start,stop,question):
  result={}
  for m,body,a,b in ranges(text,start,stop,HEADER):
   number=int(m[1]);title=m[2];note=''
   if filename=='amusements-in-mathematics.txt' and question and number==384 and title=='THE CROSS TARGET.':
    number=284;note='Source misnumbers Cross Target as 384 between 283 and 285; matched to solution 284 by title. Original bytes retained.'
   if number in result:raise ValueError('Repeated puzzle number')
   result[number]={'title':title.strip('_'),'body':body,'start':a,'end':b,'printed_number':m[1],'note':note}
  return result
 questions=group(0,split.start(),True);answers=group(split.end(),end,False)
 expected=BOOKS[filename][1]
 if set(questions)!=set(range(1,expected+1)):raise ValueError('Incomplete numbered problems')
 missing=set(questions)-set(answers)
 if missing!=({163} if filename.startswith('amusements') else set()):raise ValueError('Unexpected missing solution')
 if set(answers)-set(questions):raise ValueError('Orphan solutions')
 for i,a in answers.items():
  if re.sub(r'\W','',a['title']).casefold()!=re.sub(r'\W','',questions[i]['title']).casefold():
   known={('amusements-in-mathematics.txt',33):('PUZZLE IN REVERSALS.','A PUZZLE IN REVERSALS.'),('canterbury-puzzles.txt',7):("The Clerk of Oxenford's Puzzle.","Clerk of Oxenford's Puzzle."),('canterbury-puzzles.txt',44):('The Riddle of the Sack Wine.','The Riddle of the Sack of Wine.')}
   if (questions[i]['title'],a['title'])!=known.get((filename,i)):raise ValueError('Question/answer title mismatch')
   questions[i]['note']='Original question and solution titles differ by a grammatical article/preposition; paired by exact known number/title variants.' 
 return questions,answers

def tangled(text):
 qpat=re.compile(r'^KNOT ([IVX]+)\.[ \t]*$',re.M);apat=re.compile(r'^ANSWERS TO KNOT ([IVX]+)\.[ \t]*$',re.M)
 split=re.search(r'^APPENDIX\.[ \t]*$',text,re.M);end=re.search(r'^THE END[ \t]*$',text,re.M)
 if not split or not end:raise ValueError('Missing narrative boundary')
 expected=['I','II','III','IV','V','VI','VII','VIII','IX','X']
 def group(pattern,start,stop):
  rr=ranges(text,start,stop,pattern)
  if [m[1] for m,_,_,_ in rr]!=expected:raise ValueError('Missing or duplicated knots')
  return {i+1:{'title':'Knot '+m[1],'body':body,'start':a,'end':b,'printed_number':m[1],'note':''} for i,(m,body,a,b) in enumerate(rr)}
 return group(qpat,0,split.start()),group(apat,split.end(),end.start())

def parse_book(path):
 if path.name not in BOOKS or path.is_symlink() or not path.is_file():raise ValueError('Unsupported book')
 blob=path.read_bytes();text=blob.decode('utf-8').replace('\r\n','\n');title,count,author,ebook=BOOKS[path.name]
 questions,answers=tangled(text) if path.name=='tangled-tale.txt' else numbered(text,path.name)
 result=[]
 for number,q in questions.items():
  a=answers.get(number);issues=['historical_context_required','lesson_requires_teaching_adaptation']
  both=q['body']+'\n'+(a['body'] if a else '')
  # ASCII figure descriptions are retained, but never assumed equivalent to the
  # original drawing. An operator must check the whole dependency before use.
  if re.search(r'\[Illustration|\b(?:diagram|illustration|figures?\s+\d|figure below)',both,re.I):issues.append('missing_figure')
  if re.search(r'\b(?:tobacco|smoke|penknife|pistol|murder|killed|suicide|shooting)\b',both,re.I):issues.append('age_context_review')
  if re.search(r'\b(?:shillings?|farthings?|halfpenn|guineas?|doubloons?)\b',both,re.I):issues.append('historical_units')
  if not a:issues.append('inline_activity_no_separate_solution')
  spans=[{'role':'prompt','start':q['start'],'end':q['end'],'sha256':sha(text[q['start']:q['end']])}]
  if a:spans.append({'role':'solution','start':a['start'],'end':a['end'],'sha256':sha(text[a['start']:a['end']])})
  record=dict(id=sha(path.name+':'+sha(blob)+':'+str(number)),library='historical-puzzle-books',kind='lesson' if not a or path.name=='tangled-tale.txt' else 'historical_puzzle',title=f'{title} · {number} · {q["title"]}',prompt=q['body'],answer='',explanation=a['body'] if a else '',lecture='',options=[],source_path='public-domain/'+path.name,source_sha256=sha(blob),raw_sha256=sha(text[q['start']:q['end']]),source_line=text.count('\n',0,q['start'])+1,start=q['start'],end=q['end'],source_grade='',source_difficulty='',grade_assignment=None,approval='unreviewed',rights='public_domain_source_claim_US',issues=issues,state='reference_only',duplicate_of=None,metadata={'author':author,'book':title,'number':number,'printed_number':q['printed_number'],'source_url':'https://www.gutenberg.org/ebooks/'+ebook,'spans':spans,'source_note':q['note'],'pedagogical_review':'pending','answer_contract':'original worked solution retained; no final-answer extraction','normalization':'CRLF converted to LF for character spans; original bytes retained by source hash'})
  result.append(record)
 return result

def process(root,output):
 root=root.resolve();records=[];manifest=[]
 for name in BOOKS:
  p=root/name
  if not p.resolve().is_relative_to(root):raise ValueError('Book outside allowed source root')
  rows=parse_book(p);records.extend(rows);manifest.append({'path':name,'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size,'records':len(rows)})
 summary={'source_files':3,'records':len(records),'paired_worked_solutions':sum(bool(r['explanation']) for r in records),'original_in_text_activity':1,'source_numbering_corrections':sum(r['metadata']['printed_number']!=str(r['metadata']['number']) and r['metadata']['book']!='A Tangled Tale' for r in records),'title_variant_pairings':3,'issues':dict(Counter(i for r in records for i in r['issues'])),'formal_quiz_items_created':0,'source_manifest':manifest,'status':'reference_inventory_pending_adaptation'}
 output.mkdir(parents=True,exist_ok=True)
 for filename,value in [('public-domain-records.json',records),('public-domain-summary.json',summary)]:
  target=output/filename
  payload=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
  if target.exists() and target.read_text()!=payload:raise ValueError('Output exists with different contents')
  target.write_text(payload)
 return summary


def extend_catalog(base: Path, books: Path, output: Path) -> dict:
    """Create a new immutable admin-only snapshot; never activate it automatically."""
    import shutil,sqlite3
    from datetime import datetime,timezone
    if base.is_symlink() or not re.fullmatch('[a-f0-9]{64}',base.name):raise ValueError('Invalid base snapshot')
    original=json.loads((base/'summary.json').read_text())
    if original['snapshot_id']!=base.name or sha((base/'catalog.sqlite3').read_bytes())!=original['catalog_sha256']:raise ValueError('Base snapshot mismatch')
    if any(s['library']=='historical-puzzle-books' for s in original['libraries']):raise ValueError('Book catalog already added; use the existing receipt')
    additions=[];sources=[]
    for filename in BOOKS:
        p=books/filename
        additions.extend(parse_book(p))
        sources.append({'library':'historical-puzzle-books','path':'public-domain/'+filename,'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size})
    parser_sha=sha(Path(__file__).read_bytes())
    identity=sha(json.dumps({'base':base.name,'parser_sha256':parser_sha,'sources':sources},sort_keys=True))
    target=output/identity
    if target.exists():
        done=json.loads((target/'summary.json').read_text())
        if done['catalog_sha256']!=sha((target/'catalog.sqlite3').read_bytes()):raise ValueError('Existing snapshot corrupt')
        return done
    # A failure leaves an unactivated directory for inspection; never overwrite.
    target.mkdir(parents=True)
    shutil.copytree(base/'objects',target/'objects')
    for source in sources:
        p=books/Path(source['path']).name
        (target/'objects'/(source['sha256']+'.txt')).write_bytes(p.read_bytes())
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(target/'catalog.sqlite3') as dest:
        source.backup(dest)
        before=dest.execute('select count(*) from records').fetchone()[0]
        if before!=original['records']:raise ValueError('Base record count mismatch')
        for row in additions:
            row['fingerprint']=sha(json.dumps([row['kind'],row['source_sha256'],row['metadata']['number']]))
            dest.execute('insert into records values (?,?,?,?,?,?,?,?)',(row['id'],row['library'],row['source_path'],row['source_sha256'],row['kind'],row['state'],row['fingerprint'],json.dumps(row,ensure_ascii=False)))
        dest.commit()
        if dest.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity check failed')
        if dest.execute('select count(*) from records').fetchone()[0]!=before+554:raise ValueError('Unexpected final count')
        # Every old JSON row, including existing duplicate links, must be exact.
        for a,b in zip(source.execute('select id,data_json from records order by id'),dest.execute("select id,data_json from records where library!='historical-puzzle-books' order by id"),strict=True):
            if a!=b:raise ValueError('Existing record changed')
    issues=Counter(original['issues']);issues.update(i for row in additions for i in row['issues'])
    summary={**original,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'supplement_parser_sha256':parser_sha,'source_files':original['source_files']+3,'source_bytes':original['source_bytes']+sum(s['bytes'] for s in sources),'records':original['records']+554,'committed_batches':original['committed_batches']+1,'source_manifest':original['source_manifest']+sources,'issues':dict(issues),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'libraries':original['libraries']+[{'library':'historical-puzzle-books','total':554,'states':{'reference_only':554},'issues':dict(Counter(i for row in additions for i in row['issues'])),'kinds':dict(Counter(row['kind'] for row in additions))}],'supplement_note':'554 historical references, including ten narrative knots and one instructional activity; not 554 approved questions. Source and worked solutions paired, age/figure/curriculum review pending.'}
    provenance=json.loads((base/'sources.json').read_text())
    (target/'sources.json').write_text(json.dumps(provenance+sources,ensure_ascii=False,indent=2))
    (target/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--base-snapshot',type=Path)
    a=p.parse_args()
    result=extend_catalog(a.base_snapshot,a.root,a.output) if a.base_snapshot else process(a.root,a.output)
    print(json.dumps({k:v for k,v in result.items() if k!='source_manifest'},ensure_ascii=False,indent=2))
