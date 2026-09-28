"""Offline stock processing: lossless records, bounded batches, explicit review holds.

Reads existing administrator KB Markdown only. Never fetches, calls models,
mutates academic state, approves content, or maps dataset difficulty to grades.
The resulting immutable catalog is a processing inventory, not a quiz bank.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

VERSION = 3
LIBRARIES = ('harp-competition', 'math-competition', 'scienceqa', 'qasc',
             'world-history-1500', 'us-newspapers-primary-source', 'im-g4-full', 'im-g4-u1')
BLOCKING = {'missing_prompt', 'missing_answer', 'missing_explanation', 'missing_figure',
            'unrendered_diagram', 'answer_not_in_options', 'ambiguous_options',
            'multiple_boxed_answers', 'malformed_boxed_answer', 'missing_options', 'answer_conflict'}


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def norm(value: str) -> str:
    # Case is meaningful in capitalization questions and mathematical symbols.
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip()


def clean(value: str) -> str:
    return re.sub(r'\n---\s*$', '', value).strip()


def sections(text: str, depth: int) -> list[tuple[str, str, int, int]]:
    hits = list(re.finditer(r'^' + '#' * depth + r' ([^\n]+)\n', text, re.M))
    return [(m[1].strip(), text[m.end():hits[i+1].start() if i+1<len(hits) else len(text)],
             m.start(), hits[i+1].start() if i+1<len(hits) else len(text))
            for i,m in enumerate(hits)]


def boxed(text: str) -> list[str]:
    """Preserve nested LaTeX braces, e.g. \\boxed{\\frac{1}{48}}."""
    result = []
    for m in re.finditer(r'\\(?:boxed|fbox)\s*\{', text):
        level, end = 1, m.end()
        while end < len(text) and level:
            c=text[end]
            escapes=0; cursor=end-1
            while cursor>=0 and text[cursor]=='\\': escapes+=1; cursor-=1
            if not escapes%2:
                if c=='{': level+=1
                elif c=='}': level-=1
            end+=1
        if level: raise ValueError('Unclosed boxed answer')
        value=text[m.end():end-1].strip()
        if value and value not in result: result.append(value)
    return result


def metadata(text: str) -> dict:
    return {m[1].strip().lower().replace(' ','_'):m[2].strip()
            for m in re.finditer(r'\*\*([^*\n]+):\*\*\s*([^\n]*?)(?=\s+\*\*|\n|$)',text)}


def has_unrendered_diagram(body: str) -> bool:
    if re.search(r'\[asy\]|\\begin\{(?:tikzpicture|picture)\}', body):
        return True
    # A factorial followed by square brackets (n![...]) is not Markdown media.
    # Recognize image destinations and defined shortcut references instead.
    for match in re.finditer(r'!\[([^\]\n]*)\](\s*(?:\([^\n]+?\)|\[[^\]\n]*\]))?', body):
        if match[2]:
            return True
        if match[1] and re.search(r'^\s{0,3}\[' + re.escape(match[1]) + r'\]:\s*\S+', body, re.M | re.I):
            return True
    return False


def question(library: str, title: str, body: str) -> dict:
    parts=sections(body,3)
    chunk={name:clean(value) for name,value,_,_ in parts}
    prompt=chunk.get('Problem',chunk.get('Question',''))
    options=[]
    answer=chunk.get('Answer','')
    if library=='world-history-1500':
        found=re.search(r'^### Answer\s*\n(.*)',body,re.M|re.S)
        answer=clean(found[1]) if found else ''
    lecture=chunk.get('Lecture','')
    solution='\n\n'.join(clean(value) for name,value,_,_ in parts
                          if name.startswith(('Solution','Explanation','Reasoning')))
    fields=metadata(body[:parts[0][2]] if parts else body)
    flags=[]
    if library in ('scienceqa','qasc'):
        opts=re.search(r'\n\*\*Options:\*\*\s*\n(.*?)\n\*\*Correct answer:\*\*',prompt,re.S)
        correct=re.search(r'\*\*Correct answer:\*\*\s*(.*)\Z',prompt,re.S)
        if opts:
            # Continuation lines are part of the same option, not lost text.
            options=[v.strip() for v in re.split(r'^- ',opts[1],flags=re.M)[1:]]
            prompt=prompt[:opts.start()].strip()
        if correct: answer=clean(correct[1])
        if not options: flags.append('missing_options')
        if len({norm(x) for x in options})!=len(options): flags.append('ambiguous_options')
        if norm(answer) not in [norm(x) for x in options]: flags.append('answer_not_in_options')
        context=re.search(r'\*\*Context:\*\*\s*(.*?)(?=^### |\Z)',body,re.S|re.M)
        if context: prompt=context[1].strip()+'\n\n'+prompt
    if library=='math-competition':
        try: answers=boxed(solution)
        except ValueError: answers=[];flags.append('malformed_boxed_answer')
        answer=answers[0] if len(answers)==1 else ''
        fields['answer_candidates']=answers
        if len(answers)>1: flags.append('multiple_boxed_answers')
    if library=='world-history-1500':
        # A long generated answer is not independent evidence or an explanation.
        flags.append('historical_fact_check')
    if 'original problem includes a figure that is not bundled' in body:
        flags.append('missing_figure')
    if has_unrendered_diagram(body):
        flags.append('unrendered_diagram')
    elif re.search(r'\b(?:diagram|figure|graph|picture|image)\s+(?:below|above|shown)|\b(?:shown|pictured)\s+(?:below|above)|in the (?:diagram|figure)|according to the (?:graph|picture)',prompt,re.I):
        flags.append('missing_figure')
    if not prompt: flags.append('missing_prompt')
    if not answer: flags.append('missing_answer')
    if not solution and library!='world-history-1500': flags.append('missing_explanation')
    grade=fields.get('grade','')
    if grade and not re.fullmatch(r'grade(?:[1-9]|1[0-2])',grade):
        raise ValueError('Unexpected source grade')
    return dict(kind='question',title=title,prompt=prompt,options=options,answer=answer,
                explanation=solution,lecture=lecture,metadata=fields,issues=flags,
                source_grade=grade,source_difficulty=fields.get('difficulty',''),
                grade_assignment=None,approval='unreviewed',rights='source_claim_only')


def parse_file(library: str, filename: str, text: str) -> list[dict]:
    if library not in LIBRARIES: raise ValueError('Unsupported stock library')
    if library.startswith('im-g4'):
        groups=defaultdict(list)
        unit=re.search(r'unit(\d+)-',filename)
        if not unit: raise ValueError('Unknown IM unit')
        for title,body,start,end in sections(text,2):
            lesson=re.fullmatch(r'Lesson (\d+) — (Preparation|Lesson Content)',title)
            if not lesson: raise ValueError('Unknown IM lesson heading: '+title)
            groups[int(lesson[1])].append((title,body,start,end))
        rows=[]
        for number,parts in groups.items():
            content='\n\n'.join('# '+p[0]+'\n'+clean(p[1]) for p in parts)
            issues=['lesson_requires_teaching_adaptation']
            if 'Teachers with a valid work email' in content: issues.append('teacher_material_not_bundled')
            rows.append(dict(kind='lesson',title=f'Grade 4 Unit {unit[1]} Lesson {number}',
                        prompt=content,answer='',explanation='',lecture='',options=[],metadata={},
                        source_grade='grade4',source_difficulty='',grade_assignment=None,
                        approval='unreviewed',rights='source_claim_only',issues=issues,
                        start=min(p[2] for p in parts),end=max(p[3] for p in parts),
                        family=f'IM:G4:U{unit[1]}:L{number}'))
        return rows
    if library=='math-competition' and not filename.startswith('math-'):
        return [dict(kind='lesson',title=text.splitlines()[0].lstrip('# '),prompt=text,
                     answer='',explanation='',lecture='',options=[],metadata={},source_grade='',
                     source_difficulty='',grade_assignment=None,approval='unreviewed',
                     rights='source_claim_only',issues=['existing_teaching_chapter'],start=0,end=len(text))]
    rows=[]
    records=sections(text,2)
    if library=='world-history-1500':
        # Generated answers can contain their own level-two headings. Only a
        # heading followed by the record's Question field starts a new record.
        headers=list(re.finditer(r'^## ([^\n]+)\n\s*### Question\s*\n',text,re.M))
        records=[(m[1],text[text.index('### Question',m.start()):headers[i+1].start() if i+1<len(headers) else len(text)],m.start(),headers[i+1].start() if i+1<len(headers) else len(text)) for i,m in enumerate(headers)]
    for title,body,start,end in records:
        if library=='us-newspapers-primary-source':
            data=metadata(body)
            row=dict(kind='primary_source',title=title,prompt=clean(body),answer='',explanation='',
                     lecture='',options=[],metadata=data,source_grade='',source_difficulty='',
                     grade_assignment=None,approval='unreviewed',rights='source_claim_only',
                     issues=['historical_context_required','ocr_review'])
        else: row=question(library,title,body)
        row.update(start=start,end=end)
        rows.append(row)
    declared=re.search(r'^(?:Problems in this file|Passages in this file|Entries): (\d+)\s*$',text,re.M)
    if not declared or len(rows)!=int(declared[1]):
        raise ValueError(f'Record count mismatch in {library}/{filename}: {len(rows)}')
    return rows


def state(row: dict) -> str:
    if row.get('duplicate_of'): return 'duplicate'
    if row['kind']!='question': return 'reference_only'
    if set(row['issues']) & BLOCKING: return 'needs_repair'
    if 'historical_fact_check' in row['issues']: return 'needs_fact_check'
    return 'needs_curriculum_review'


def apply_source_review(row: dict, review: dict) -> None:
    """Only exact source-bound corrections; never clear asset or approval gates."""
    if (review['source_raw_sha256']!=row['raw_sha256']
            or review['parsed_answer_before']!=row['answer']
            or review.get('approval')!='unreviewed'):
        raise ValueError('Source review no longer matches this record')
    if 'answer_candidates_before' in review and review['answer_candidates_before']!=row['metadata'].get('answer_candidates'):
        raise ValueError('Source answer candidates changed')
    cleared=set(review.get('cleared_issues',[]))
    if not cleared <= {'missing_answer','multiple_boxed_answers'}:
        raise ValueError('Source review cannot override other readiness gates')
    if 'answer' in review:
        if not isinstance(review['answer'],str) or not review['answer'].strip(): raise ValueError('Reviewed answer is empty')
        row['answer']=review['answer']
    if 'explanation' in review:
        row['explanation']='DeepTutor source correction: '+review['explanation']
    row['issues']=[issue for issue in row['issues'] if issue not in cleared]
    row['metadata']['source_review']=review
    if 'equivalent_answer_key' in review:
        row['answer_equivalence_key']=review['equivalent_answer_key']


def process(root: Path, output: Path, batch_size: int = 1000) -> dict:
    if not 1<=batch_size<=1000: raise ValueError('Batch size must be 1–1000')
    review_file=Path(__file__).parents[1]/'content_sources/stock-math-source-reviews-v1.json'
    review_blob=review_file.read_bytes() if review_file.exists() else b''
    reviews=json.loads(review_blob)['records'] if review_blob else {}
    reviewed_ids=set()
    files=[]
    for library in LIBRARIES:
        folder=root/library/'raw'
        for path in sorted(folder.glob('*.md')):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Source path escaped stock root')
            blob=path.read_bytes()
            if len(blob)>32*1024*1024: raise ValueError('Source file too large')
            files.append((library,path,blob,digest(blob)))
    if not files: raise ValueError('No supported stock files')
    manifest=[dict(library=lib,path=str(p.relative_to(root)),sha256=sha,bytes=len(blob))
              for lib,p,blob,sha in files]
    parser_sha256=digest(Path(__file__).read_bytes())
    identity=digest(json.dumps({'version':VERSION,'parser_sha256':parser_sha256,'review_sha256':digest(review_blob),'sources':manifest},sort_keys=True))
    folder=output/identity
    if (folder/'summary.json').exists():
        summary=json.loads((folder/'summary.json').read_text())
        if digest((folder/'catalog.sqlite3').read_bytes())!=summary['catalog_sha256']:
            raise ValueError('Catalog integrity mismatch')
        return summary
    # Never overwrite a partial run. Retain it for diagnostics and choose a new
    # output root to retry. A summary is written only after all validation passes.
    folder.mkdir(parents=True,exist_ok=False)
    conn=sqlite3.connect(folder/'catalog.sqlite3')
    conn.execute('CREATE TABLE records (id TEXT PRIMARY KEY, library TEXT, source_path TEXT, source_sha256 TEXT, kind TEXT, state TEXT, fingerprint TEXT, data_json TEXT)')
    conn.execute('CREATE INDEX stock_library_state ON records(library,state)')
    conn.execute('CREATE INDEX stock_fingerprint ON records(fingerprint)')
    totals=Counter(); sources=[]; pending=[]; batches=0
    # Keep exact source objects; record character spans reconstruct the original.
    objects=folder/'objects';objects.mkdir()
    for library,path,blob,sha in files:
        target=objects/(sha+'.md')
        if not target.exists(): target.write_bytes(blob)
        text=blob.decode('utf-8')
        rows=parse_file(library,path.name,text)
        preamble=text[:next(iter(re.finditer(r'^## ',text,re.M)),None).start()] if re.search(r'^## ',text,re.M) else text
        sources.append(dict(library=library,path=str(path.relative_to(root)),sha256=sha,
                            records=len(rows),source_statement=preamble.strip()))
        for row in rows:
            raw=text[row['start']:row['end']]
            row.update(library=library,source_path=str(path.relative_to(root)),source_sha256=sha,
                       raw_sha256=digest(raw),source_line=text.count('\n',0,row['start'])+1,
                       id=digest(str(path.relative_to(root))+':'+sha+':'+str(row['start'])),duplicate_of=None)
            if row['id'] in reviews:
                apply_source_review(row,reviews[row['id']]);reviewed_ids.add(row['id'])
            fingerprint_parts=[row['kind'],norm(row['prompt']),[norm(v) for v in row['options']]]
            # Two missing images can encode different questions despite identical
            # visible text. Their absence prevents a safe duplicate decision.
            if 'missing_figure' in row['issues']: fingerprint_parts.append(row['id'])
            fp=digest(json.dumps(fingerprint_parts,ensure_ascii=False))
            row['fingerprint']=fp
            row['state']=state(row)
            pending.append(row);totals[library]+=1
            if len(pending)>=batch_size:
                write_batch(conn,pending);pending=[];batches+=1
    if pending: write_batch(conn,pending);batches+=1
    # Cross-file and cross-library exact-normalized duplicates. Retain every source.
    groups=conn.execute('SELECT fingerprint FROM records GROUP BY fingerprint HAVING count(*)>1').fetchall()
    duplicates=0;conflicts=0
    for (fingerprint,) in groups:
        matches=[json.loads(r[0]) for r in conn.execute('SELECT data_json FROM records WHERE fingerprint=? ORDER BY rowid',(fingerprint,))]
        answers={r.get('answer_equivalence_key',norm(r['answer'].strip('$ '))) for r in matches if r['answer']}
        conflict=len(answers)>1
        # Prefer a copy without missing assets/answers; don't discard the best copy
        # solely because a lower-quality source appeared earlier in file order.
        matches.sort(key=lambda r:(len(set(r['issues']) & BLOCKING),not bool(r['explanation']),r['id']))
        keeper=matches[0]
        for i,row in enumerate(matches):
            if conflict: row['issues'].append('answer_conflict');conflicts+=1
            if i and not conflict: row['duplicate_of']=keeper['id'];duplicates+=1
            row['state']=state(row)
            conn.execute('UPDATE records SET state=?,data_json=? WHERE id=?',
                         (row['state'],json.dumps(row,ensure_ascii=False),row['id']))
    conn.commit()
    assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    library_summaries=[]
    all_issues=Counter(); families=set()
    for library in LIBRARIES:
        counts=Counter();issues=Counter();kinds=Counter()
        for (data,) in conn.execute('SELECT data_json FROM records WHERE library=?',(library,)):
            row=json.loads(data);counts[row['state']]+=1;issues.update(row['issues']);kinds[row['kind']]+=1
            if 'family' in row: families.add(row['family'])
        if sum(counts.values())!=totals[library]: raise ValueError('Stored count mismatch')
        all_issues.update(issues)
        library_summaries.append(dict(library=library,total=totals[library],states=dict(counts),issues=dict(issues),kinds=dict(kinds)))
    conn.close()
    summary=dict(schema_version=VERSION,parser_sha256=parser_sha256,review_sha256=digest(review_blob),source_reviews_applied=len(reviewed_ids),source_reviews_not_applicable=len(set(reviews)-reviewed_ids),snapshot_id=identity,created_at=datetime.now(timezone.utc).isoformat(),
                 source_files=len(files),source_bytes=sum(len(b) for _,_,b,_ in files),
                 records=sum(totals.values()),committed_batches=batches,batch_size=batch_size,
                 duplicate_records=duplicates,answer_conflict_records=conflicts,unique_im_lessons=len(families),
                 libraries=library_summaries,issues=dict(all_issues),formal_quiz_items_created=0,
                 source_manifest=manifest,catalog_sha256=digest((folder/'catalog.sqlite3').read_bytes()),
                 limitations=['Structural processing is not factual or teaching approval.',
                              'Duplicate matching is exact normalized text, not semantic deduplication.',
                              'Repository licenses are source claims, not verified item permissions.',
                              'Dataset difficulty is not student grade or mastery.'])
    (folder/'sources.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2))
    (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


def write_batch(conn: sqlite3.Connection, rows: list[dict]) -> None:
    with conn:
        conn.executemany('INSERT INTO records VALUES (?,?,?,?,?,?,?,?)',
            [(r['id'],r['library'],r['source_path'],r['source_sha256'],r['kind'],r['state'],
              r['fingerprint'],json.dumps(r,ensure_ascii=False)) for r in rows])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--batch-size',type=int,default=1000)
    args=parser.parse_args()
    summary=process(args.root,args.output,args.batch_size)
    print(json.dumps({k:v for k,v in summary.items() if k!='source_manifest'},ensure_ascii=False,indent=2))
