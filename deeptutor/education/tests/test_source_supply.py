import calendar
from copy import deepcopy
from datetime import date
from fractions import Fraction as F
from itertools import product
import json
from pathlib import Path

import httpx
import pytest

from deeptutor.education.application import source_supply as supply

DATA = Path(__file__).parents[1] / 'content_sources'
URL = 'https://cemc.uwaterloo.ca/sites/default/files/documents/2026/source.pdf'


@pytest.mark.parametrize('url', [
    'http://cemc.uwaterloo.ca/sites/default/files/documents/2026/a.pdf',
    'https://evil.test/sites/default/files/documents/2026/a.pdf',
    'https://cemc.uwaterloo.ca.evil.test/sites/default/files/documents/a.pdf',
    'https://user:password@cemc.uwaterloo.ca/sites/default/files/documents/a.pdf',
    URL + '?key=x', URL + '#page=5', URL.replace('.pdf', '.html'),
    URL.replace('.ca/', '.ca:8443/'),
])
def test_source_boundary(url):
    with pytest.raises(ValueError): supply.source_url(url)


def test_redirect_cannot_leave_catalogued_host():
    request = supply.Request(URL)
    with pytest.raises(ValueError):
        supply.SourceRedirect().redirect_request(request, None, 302, '', {}, 'https://evil.test/a.pdf')


def test_problem_only_page_stops_solution_but_continuation_is_retained():
    pages = ['Problem of the Week\nProblem B\nFirst question',
             'Problem B and Solution\nFirst\nProblem\nFirst question\nSolution\nFirst step',
             'A second solution step',
             'Problem of the Week\nProblem B\nUNRELATED NEXT QUESTION',
             'Problem B and Solution\nSecond\nProblem\nSecond question\nSolution\nSecond answer',
             'Take me to the\ncover']
    records = supply.extract_pages(pages, 'B')
    assert records[0]['solution'] == 'First step\nA second solution step'
    assert (records[0]['page'], records[0]['end_page']) == (2, 3)
    assert 'UNRELATED' not in json.dumps(records)
    assert records[1]['solution'] == 'Second answer'


def test_duplicate_pages_are_one_source_family_and_conflicts_fail():
    page = 'Problem B and Solution\nSame title\nProblem\nA question\nSolution\nAn answer'
    rows = supply.extract_pages([page, page], 'B')
    assert len(rows) == 1 and rows[0]['repeated_pages'] == [2]
    with pytest.raises(ValueError, match='Ambiguous'):
        supply.extract_pages([page, page.replace('An answer', 'A different answer')], 'B')
    with pytest.raises(ValueError, match='Incomplete'):
        supply.extract_pages([page.replace('Solution\nAn answer', 'Missing answer')], 'B')


def test_immutable_objects_and_changed_source_fail_before_build(tmp_path):
    data = b'%PDF-new source bytes'
    path = supply.store(tmp_path, data, '.pdf')
    assert supply.store(tmp_path, data, '.pdf') == path
    recipe = {'schema_version': 1, 'source': {'id': 'fixture', 'url': URL,
              'license': 'CC BY-NC 4.0', 'sha256': '0' * 64}}
    with pytest.raises(ValueError, match='version changed'):
        supply.stage(recipe, tmp_path, getter=lambda _: data)
    assert path.read_bytes() == data
    path.write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='corrupt'):
        supply.store(tmp_path, data, '.pdf')


def recipe_and_staged():
    recipe = json.loads((DATA / 'cemc-b-2025-26.recipe.json').read_text())
    staged = {'source': deepcopy(recipe['source']), 'records': [
        {'title': row['title'], 'page': row['page'], 'text_sha256': row['source_text_sha256']}
        for row in recipe['adaptations']]}
    return recipe, staged


def test_candidate_build_binds_versions_and_requires_complete_adaptation():
    recipe, staged = recipe_and_staged()
    package = supply.build_package(recipe, staged)
    assert len(package['items']) == len({r['id'] for r in package['items']}) == 20
    for row in package['items']:
        assert row['source_ref'].startswith(recipe['source']['url'] + '#page=')
        assert 'CC BY-NC' in row['license_note'] and row.get('status') is None
        assert row['rubric_json']['difficulty_calibration'] == 'pending'
    changed = deepcopy(staged); changed['records'][0]['text_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='page/text changed'): supply.build_package(recipe, changed)
    changed = deepcopy(recipe); changed['adaptations'][0]['visual_check'] = 'unchecked'
    with pytest.raises(ValueError, match='review'): supply.build_package(changed, staged)
    changed = deepcopy(recipe); changed['adaptations'][1]['key'] = changed['adaptations'][0]['key']
    with pytest.raises(ValueError, match='duplicate'): supply.build_package(changed, staged)


def test_api_preview_failure_never_imports_and_apply_is_explicit():
    calls = []
    preview_errors = ['bad node']
    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'errors': list(preview_errors), 'inserted': 20})
    with httpx.Client(transport=httpx.MockTransport(respond), base_url='https://example.test') as client:
        with pytest.raises(ValueError, match='preview rejected'): supply.ingest(client, {}, apply=True)
        assert calls == ['/api/edu/content-admin/import/preview']
        calls.clear(); preview_errors.clear()
        assert supply.ingest(client, {})['state'] == 'preview'
        assert calls == ['/api/edu/content-admin/import/preview']
        calls.clear()
        assert supply.ingest(client, {}, apply=True)['state'] == 'candidates_imported'
        assert calls == ['/api/edu/content-admin/import/preview', '/api/edu/content-admin/import']


def test_twenty_answers_with_independent_exact_arithmetic_and_enumeration():
    recipe, _ = recipe_and_staged()
    answers = {r['key']: F(r['expected_answer']) for r in recipe['adaptations']}
    found = {}
    found['smoothie-count'] = sum(sum(v) == 3 for v in product(range(4), repeat=4))
    grains = [n for n in range(10000, 100000) if n % 2 == 0 and sum(map(int, str(n))) == 15 and (n + 50) // 100 * 100 == 51200]
    assert grains == [51162, 51180, 51216, 51234]
    found['grain-constraints'] = len(grains)
    per_row = max(n for n in range(100) if 3*n + F(1,2)*(n-1) + 1 <= F(155,2))
    found['stamped-squares'] = per_row ** 2
    solutions = [(c, s, t) for c, s, t in product(range(30), repeat=3) if 3*c == 24 and s*c+s == 36 and t*s+t == 25]
    assert solutions == [(8, 4, 5)]; found['symbol-equations'] = solutions[0][2]
    found['seed-budget'] = max(n for n in range(100) if 269*n+900 <= 5300)
    # Conditions 3 and 5 have disjoint intervals. The given two-fraction
    # construction covers every condition; finite decimals use their usual form.
    values = [(1,2), (8,6)]
    predicates = [lambda a,b:b%3==0,
        lambda a,b:all(int(d)%2==0 for d in str(a)+str(b)),
        lambda a,b:1<F(a,b)<F(3,2), lambda a,b:b%2==0,
        lambda a,b:F(1,4)<F(a,b)<F(3,5),
        lambda a,b:F(a,b) in (F(1,2),F(4,3)),
        lambda a,b:a%2==0, lambda a,b:abs(F(a,b)-F(3,4))<abs(F(a,b)-F(11,20))]
    assert all(any(p(a,b) for a,b in values) for p in predicates)
    assert F(3,5) < 1; found['fraction-cover'] = 2
    found['relay-expectation'] = F(sum([20,6,12,10]),4)
    found['even-products'] = sum(a*b%2==0 for a,b in product(range(1,7),repeat=2))
    found['coin-outcomes'] = sum(len(set(v))==2 for v in product([0,1],repeat=3))
    found['juice-shortfall'] = 31*250-sum([500,1800,1450,350,2400])
    found['calendar-types'] = len({(date(y,1,1).weekday(),calendar.isleap(y)) for y in range(2000,2400)})
    found['equal-perimeters'] = sum(any(2*(a+b)==3*s for a,b in product(range(1,11),repeat=2)) for s in (4,5,6,7))
    found['water-spill'] = F(45)/F('1.5') * (F('3.5')-F('1.5'))
    coins = [(d,q,l) for d,q,l in product(range(1,10),repeat=3) if d+q+l==9 and 10*d+25*q+100*l==225]
    assert coins == [(5,3,1)]; found['coin-constraints'] = coins[0][0]
    nums = sorted(map(F,['2.04','1.02','85/100','175/100','7/4','9/8','0.91','46/20','0.091','14/25','3/5','1.1']))
    found['largest-gap'] = max(b-a for a,b in zip(nums,nums[1:]))
    scores = [n for n in range(11) if 5+4*n-3*(10-n)==10]
    assert scores == [5]; found['quiz-score'] = scores[0]
    diffs = [n-(n//10)*(n%10) for n in range(10,100)]
    found['digit-difference'] = max(diffs)-min(diffs)
    found['broken-key-product'] = 82*816
    found['rebound-steps'] = next(n for n in range(1,100) if 6*F(9,10)**n<2)
    found['break-even'] = F(50*8+30-30*10,20)
    assert found == answers


def test_original_lesson_examples():
    assert len({tuple(sorted(v)) for v in product('RBG', repeat=2)}) == 6
    assert sum(0 in v for v in product(range(3), repeat=3)) == 19
    assert [n for n in range(10,80) if n%2==0 and sum(map(int,str(n)))==11] == [38,56,74]
    assert [n for n in range(460,481) if (n+5)//10*10==470 and n%2==0] == [466,468,470,472,474]
    assert F('.75')*1000+250==1000
    assert F(24*5+12-12*7,12)==4
    assert [n for n in range(13) if n*5+(12-n)*2==39] == [5]
    assert next(n for n in range(10) if 8*F(1,2)**n<1)==4
