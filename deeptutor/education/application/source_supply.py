"""Repeatable, operator-run source intake. No timer or automatic approval.

Fetch an explicitly catalogued public PDF, keep immutable bytes and page-bound
problem/solution records, then build candidates from a reviewed adaptation map.
Production intake always uses the existing administrator API and its transaction.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 20 * 1024 * 1024
SOURCE_HOST = 'cemc.uwaterloo.ca'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized(text: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text)).strip()


def source_url(url: str) -> None:
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != SOURCE_HOST or p.port not in (None, 443)
            or p.username or p.password or p.query or p.fragment
            or not p.path.startswith('/sites/default/files/documents/')
            or not p.path.lower().endswith('.pdf')):
        raise ValueError('Source must be a catalogued CEMC HTTPS document')


class SourceRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        source_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_pdf(url: str) -> bytes:
    source_url(url)
    opener = build_opener(SourceRedirect())
    request = Request(url, headers={'User-Agent':'DeepTutor-Content-Intake/1.0'})
    with opener.open(request, timeout=45) as response:
        source_url(response.url)
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or not data.startswith(b'%PDF-'):
        raise ValueError('Source is too large or is not a PDF')
    return data


def store(root: Path, data: bytes, suffix: str) -> Path:
    folder = root / 'objects'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (sha(data) + suffix)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError('Stored source object is corrupt')
    else:
        with target.open('xb') as f:
            f.write(data)
    return target


def extract_pages(pages: list[str], band: str) -> list[dict]:
    if band not in ('A','B','C','D','E'):
        raise ValueError('Unknown CEMC grade band')
    header = f'Problem {band} and Solution'
    records = {}
    for start, page in enumerate(pages):
        if header not in page:
            continue
        end = start + 1
        while end < len(pages):
            following = pages[end]
            # A booklet alternates problem-only pages and worked solutions.
            # Stop at the next problem OR section cover, retaining continuation
            # pages. Stopping only at the next solution contaminates this one.
            if ('Problem of the Week' in following or header in following
                    or re.search(r'Take me to the\s+cover', following)):
                break
            end += 1
        text = '\n'.join(pages[start:end])
        title = text.split(header, 1)[1].strip().splitlines()[0].strip()
        problem = re.search(r'^\s*Problem\s*$', text, re.M)
        solution = re.search(r'^\s*Solution\s*$', text, re.M)
        if not title or not problem or not solution or problem.end() >= solution.start():
            raise ValueError(f'Incomplete problem/solution at PDF page {start+1}')
        record = {'title':title,'page':start+1,'end_page':end,
                  'problem':text[problem.end():solution.start()].strip(),
                  'solution':text[solution.end():].strip()}
        if not record['problem'] or not record['solution']:
            raise ValueError(f'Empty source text at PDF page {start+1}')
        record['text_sha256'] = sha((normalized(record['problem'])+'\n'+normalized(record['solution'])).encode())
        key = normalized(title).casefold()
        if key in records:
            if records[key]['text_sha256'] != record['text_sha256']:
                raise ValueError(f'Ambiguous repeated source title: {title}')
            records[key]['repeated_pages'].append(start+1)
        else:
            record['repeated_pages'] = []
            records[key] = record
    if not records:
        raise ValueError('No paired problems found; source layout changed')
    return list(records.values())


def stage(recipe: dict, output: Path, getter=fetch_pdf) -> dict:
    source = recipe['source']
    if (recipe.get('schema_version') != 1
            or not re.fullmatch(r'[a-z0-9-]{1,80}', source['id'])
            or not re.fullmatch(r'[a-f0-9]{64}', source['sha256'])):
        raise ValueError('Invalid source recipe identity or version')
    source_url(source['url'])
    if source.get('license') != 'CC BY-NC 4.0':
        raise ValueError('This connector requires the confirmed CEMC license')
    data = getter(source['url'])
    if len(data) > MAX_BYTES or not data.startswith(b'%PDF-'):
        raise ValueError('Invalid PDF source')
    path = store(output, data, '.pdf')
    if sha(data) != source['sha256']:
        raise ValueError('Source version changed; retained new bytes for review, no candidates built')
    import pymupdf
    with pymupdf.open(path) as document:
        pages = [p.get_text() for p in document]
    records = extract_pages(pages, source['band'])
    result = {'source':source,'pdf_path':str(path),'pages':len(pages),'records':records,
              'state':'staged_not_approved','retrieved_at':datetime.now(timezone.utc).isoformat()}
    blob = json.dumps(result, ensure_ascii=False, indent=2).encode()
    path = store(output, blob, '.json')
    return {**result,'receipt_path':str(path)}


def build_package(recipe: dict, staged: dict) -> dict:
    if staged['source'] != recipe['source']:
        raise ValueError('Staged source does not match this adaptation map')
    records = {normalized(r['title']).casefold():r for r in staged['records']}
    source = recipe['source']
    result = []
    seen = set()
    for adaptation in recipe['adaptations']:
        original = records[normalized(adaptation['title']).casefold()]
        if (original['page'] != adaptation['page']
                or original['text_sha256'] != adaptation['source_text_sha256']):
            raise ValueError('Source page/text changed; adaptation must be checked again')
        if (adaptation.get('visual_check') != 'self_contained_adaptation'
                or not adaptation.get('verification_note')):
            raise ValueError('Page review and adaptation verification are required')
        key = adaptation['key']
        if not re.fullmatch(r'[a-z0-9-]{1,80}',key) or key in seen:
            raise ValueError('Invalid or duplicate adaptation key')
        seen.add(key)
        row = {field:adaptation[field] for field in ('knowledge_node_code','item_type','prompt','expected_answer','explanation','difficulty')}
        for field in ('prompt','expected_answer','explanation'):
            if not isinstance(row[field],str) or not row[field].strip():
                raise ValueError('Incomplete adaptation')
        row.update(id=source['id']+'-'+key+'-v1',content_scope='BUNDLED',explanation_source='derived',
                   source_ref=f"{source['url']}#page={original['page']} | {original['title']} | {adaptation['part']}",
                   license_note='CC BY-NC 4.0; https://cemc.uwaterloo.ca/copyright ; noncommercial educational use only.',
                   attribution_text=f"Centre for Education in Mathematics and Computing, University of Waterloo. {source['label']}. Chinese adaptation by DeepTutor; selected subproblem and response format may be modified. Original PDF SHA256 {source['sha256']}. No CEMC endorsement.",
                   rubric_json={'source_problem_family':source['id']+':'+normalized(original['title']),
                                'source_grade_band':source['grade_band'],'intended_use':'advanced_extension',
                                'verification_note':adaptation['verification_note'],'difficulty_calibration':'pending'})
        result.append(row)
    if not 1 <= len(result) <= 1000:
        raise ValueError('Expected 1–1000 candidate adaptations')
    return {'schema_version':1,'course_version_id':recipe['course_version_id'],
            'source_name':recipe['source_name'],'items':result,
            'known_limits':['Candidate intake only; no approval, quiz classification or grade promotion.',
                            'Source publisher grade band is not a student placement decision.']}


def ingest(client, package: dict, *, apply: bool = False) -> dict:
    # The caller supplies an authenticated API client. Never read credentials,
    # write education.db, classify an exam or approve an item from this module.
    response = client.post('/api/edu/content-admin/import/preview', json=package)
    response.raise_for_status()
    preview = response.json()
    if preview['errors']:
        raise ValueError('Import preview rejected; no write attempted')
    if not apply:
        return {'state':'preview','result':preview}
    response = client.post('/api/edu/content-admin/import', json=package)
    response.raise_for_status()
    return {'state':'candidates_imported','result':response.json()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    recipe = json.loads(args.recipe.read_text(encoding='utf-8'))
    staged = stage(recipe,args.output)
    package = build_package(recipe,staged)
    path = store(args.output,json.dumps(package,ensure_ascii=False,indent=2).encode(),'.json')
    print(json.dumps({'source_records':len(staged['records']),'candidate_items':len(package['items']),
                      'package_path':str(path),'source_receipt':staged['receipt_path'],
                      'production_changed':False},ensure_ascii=False))


if __name__ == '__main__':
    main()
