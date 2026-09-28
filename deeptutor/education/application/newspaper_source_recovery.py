"""Bind recovered LOC page assets to existing stock, without approving OCR text."""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def identity(url):
    u = urlsplit(url)
    m = re.fullmatch(r'/lccn/((?:sn)?(?:\d{8}|\d{10}))/(\d{4}-\d{2}-\d{2})/ed-([1-9]\d*)/seq-([1-9]\d*)\.json', u.path)
    if u.scheme != 'https' or u.netloc != 'chroniclingamerica.loc.gov' or u.query or u.fragment or not m:
        raise ValueError('Unsupported existing page reference')
    lccn, published, edition, sequence = m.groups()
    date.fromisoformat(published)
    key = f'{lccn}/{published}/ed-{edition}/seq-{sequence}'
    return {'page_id': sha(key.encode()), 'page_key': key, 'published': published,
            'lccn': lccn, 'edition': int(edition), 'sequence': int(sequence),
            'resource_url': f'https://www.loc.gov/resource/{lccn}/{published}/ed-{edition}/?sp={sequence}&fo=json'}


def page_metadata(original_url, document):
    key = identity(original_url)
    item = document.get('item', {})
    expected = f'/item/{key["lccn"]}/{key["published"]}/ed-{key["edition"]}/'
    item_url = urlsplit(item.get('id', ''))
    if item_url.scheme not in {'http', 'https'} or item_url.netloc != 'www.loc.gov' or item_url.path != expected or item_url.query or item_url.fragment:
        raise ValueError('LOC item/edition does not match stock')
    if item.get('date') != key['published'] or document.get('pagination', {}).get('current') != key['sequence']:
        raise ValueError('LOC date or page mismatch')
    urls = [x['url'] for x in document.get('page', []) if x.get('mimetype') == 'text/xml']
    if len(urls) != 1:
        raise ValueError('Missing or ambiguous ALTO asset')
    u = urlsplit(urls[0])
    segment = document.get('segment_id')
    if (u.scheme != 'https' or u.netloc != 'tile.loc.gov' or u.query or u.fragment
            or not u.path.startswith('/storage-services/service/sgp/')
            or not u.path.endswith('.xml') or u.path != '/storage-services' + str(segment)
            or f'/{key["lccn"]}/' not in u.path or any(x in u.path for x in ('..', '%', '\\'))):
        raise ValueError('ALTO asset is not bound to the selected LOC page')
    issue_folder = key['published'].replace('-', '') + f"{key['edition']:02d}"
    if f'/{issue_folder}/' not in u.path or u.path.rsplit('/', 1)[-1] != f"{key['sequence']:04d}.xml":
        raise ValueError('ALTO filename does not match the selected issue and sequence')
    return {**key, 'original_url': original_url, 'alto_url': urls[0], 'title': item.get('title', '')}


def alto_diagnostics(blob, sequence):
    if len(blob) > 20_000_000 or re.search(br'<!\s*(?:DOCTYPE|ENTITY)', blob, re.I):
        raise ValueError('Unsafe or oversized ALTO XML')
    # LOC ALTO is UTF-8. Reject alternate encodings before XML entity handling.
    text = blob.decode('utf-8-sig')
    root = ET.fromstring(text)
    namespace = root.tag.split('}')[0].lstrip('{') if '}' in root.tag else ''
    if namespace not in {'http://schema.ccs-gmbh.com/ALTO', 'http://www.loc.gov/standards/alto/ns-v2#', 'http://www.loc.gov/standards/alto/ns-v3#', 'http://www.loc.gov/standards/alto/ns-v4#'}:
        raise ValueError('Unknown ALTO namespace')
    tag = lambda name: f'{{{namespace}}}{name}'
    pages = list(root.iter(tag('Page')))
    if len(pages) != 1 or int(pages[0].get('PHYSICAL_IMG_NR', '-1')) != sequence:
        raise ValueError('ALTO physical page mismatch')
    page = pages[0]
    width, height = float(page.get('WIDTH', '0')), float(page.get('HEIGHT', '0'))
    if not (0 < width < 1_000_000 and 0 < height < 1_000_000):
        raise ValueError('Invalid page dimensions')
    words = list(page.iter(tag('String')))
    ids = [w.get('ID') for w in words]
    if not words or any(not w.get('CONTENT') for w in words) or not all(ids) or len(ids) != len(set(ids)):
        raise ValueError('Empty words or missing/duplicate word IDs')
    lines = list(page.iter(tag('TextLine')))
    wide_lines = sum(float(line.get('WIDTH', '0')) > width * .70 for line in lines)
    return {'words': len(words), 'lines': len(lines), 'blocks': len(list(page.iter(tag('TextBlock')))),
            'page_width': width, 'page_height': height, 'lines_wider_than_70_percent': wide_lines,
            'layout_review_required': True, 'character_accuracy': 'not_measured',
            'article_boundaries': 'not_verified', 'scan_comparison': 'pending'}


def verify_recovery(folder, expected_url):
    folder = Path(folder)
    receipt = json.loads((folder / 'receipt.json').read_text())
    if receipt['original_url'] != expected_url:
        raise ValueError('Recovery refers to a different stock page')
    blobs = {name: (folder / name).read_bytes() for name in ('page.json', 'page.xml')}
    for name, blob in blobs.items():
        if sha(blob) != receipt['files'][name]['sha256'] or len(blob) != receipt['files'][name]['bytes']:
            raise ValueError('Recovered asset changed')
    bound = page_metadata(expected_url, json.loads(blobs['page.json']))
    if receipt['files']['page.json']['url'] not in {bound['resource_url'], bound['resource_url'] + '&at=item,pagination,page,segment_id'} or receipt['files']['page.xml']['url'] != bound['alto_url']:
        raise ValueError('Recovery URL mismatch')
    diagnostic = alto_diagnostics(blobs['page.xml'], bound['sequence'])
    return {**bound, 'files': receipt['files'], 'diagnostics': diagnostic,
            'recovery_status': 'original_page_recovered_ocr_pending', 'student_approval': 'unchanged'}


def build(base, recovery_root, output):
    base, recovery_root = Path(base).resolve(), Path(recovery_root).resolve()
    summary = json.loads((base / 'summary.json').read_text())
    if summary['snapshot_id'] != base.name or sha((base / 'catalog.sqlite3').read_bytes()) != summary['catalog_sha256']:
        raise ValueError('Base catalog changed')
    queue = json.loads((base / 'newspaper-page-queue.json').read_text())
    pages = {p['page_id']: p for p in queue['pages']}
    recoveries = {}
    for folder in sorted(recovery_root.iterdir()):
        if not folder.is_dir() or not (folder / 'receipt.json').exists():
            continue
        if folder.name not in pages:
            raise ValueError('Recovery is outside existing stock')
        recoveries[folder.name] = verify_recovery(folder, pages[folder.name]['source_page_url'])
    if not recoveries:
        raise ValueError('No verified recovery receipts')
    with sqlite3.connect((base / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        rows = [json.loads(x[0]) for x in db.execute("select data_json from records where library='us-newspapers-primary-source'")]
    updates = {}
    for row in rows:
        p = row['metadata']['newspaper_page_inventory']
        if p['page_id'] not in recoveries:
            continue
        if 'newspaper_source_recovery' in row['metadata']:
            raise ValueError('Page recovery already linked')
        if sha((base / 'objects' / (row['source_sha256'] + '.md')).read_bytes()) != row['source_sha256']:
            raise ValueError('Original stock source changed')
        recovery = recoveries[p['page_id']]
        row['metadata'] = {**row['metadata'], 'newspaper_source_recovery': recovery}
        updates[row['id']] = row
    expected = {x['record_id'] for k in recoveries for x in pages[k]['passages']}
    if set(updates) != expected:
        raise ValueError('Recovered-page population mismatch')
    fingerprint = sha(json.dumps(recoveries, sort_keys=True).encode())
    new_id = sha(json.dumps({'base': base.name, 'recovery': fingerprint, 'processor': sha(Path(__file__).read_bytes())}, sort_keys=True).encode())
    target = Path(output) / new_id
    shutil.copytree(base, target)
    for key in recoveries:
        destination = target / 'newspaper-recovered-pages' / key
        destination.mkdir(parents=True, exist_ok=False)
        for name in ('page.json', 'page.xml', 'receipt.json'):
            shutil.copy2(recovery_root / key / name, destination / name)
        if verify_recovery(destination, pages[key]['source_page_url']) != recoveries[key]:
            raise ValueError('Copied recovery changed')
    with sqlite3.connect(target / 'catalog.sqlite3') as db:
        for row in updates.values():
            db.execute('update records set data_json=? where id=?', (json.dumps(row, ensure_ascii=False), row['id']))
        db.commit()
        if db.execute('pragma integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Catalog integrity failure')
        with sqlite3.connect((base / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True) as old:
            changed = 0
            for left, right in zip(old.execute('select data_json from records order by id'), db.execute('select data_json from records order by id'), strict=True):
                a, b = json.loads(left[0]), json.loads(right[0])
                if a == b:
                    continue
                changed += 1
                original_metadata = {k: v for k, v in b['metadata'].items() if k != 'newspaper_source_recovery'}
                if b['id'] not in updates or {**b, 'metadata': original_metadata} != a:
                    raise ValueError('Unrelated content, state or approval changed')
            if changed != len(updates):
                raise ValueError('Changed row count mismatch')
    receipt_file = target / 'newspaper-source-recoveries.json'
    previous = json.loads(receipt_file.read_text()) if receipt_file.exists() else {'pages': {}}
    if previous['pages'].keys() & recoveries.keys():
        raise ValueError('Recovery receipt overwritten')
    previous['pages'].update(recoveries)
    receipt_file.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + '\n')
    report = {**summary, 'snapshot_id': new_id, 'base_snapshot_id': base.name,
              'created_at': datetime.now(timezone.utc).isoformat(), 'catalog_sha256': sha((target / 'catalog.sqlite3').read_bytes()),
              'committed_batches': summary['committed_batches'] + 1,
              'newspaper_source_recovery': {'pages': len(previous['pages']),
                'passages': sum(pages[k]['passages_count'] for k in previous['pages']),
                'batch_pages': len(recoveries), 'batch_passages': len(updates),
                'receipts_sha256': sha(receipt_file.read_bytes()), 'ocr_approved': 0, 'student_approved': 0}}
    (target / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return {k: report[k] for k in ('snapshot_id', 'base_snapshot_id', 'catalog_sha256', 'committed_batches', 'newspaper_source_recovery')}
