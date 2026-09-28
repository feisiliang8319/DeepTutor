from copy import deepcopy
import json
from pathlib import Path

import pytest

from deeptutor.education.application import stock_math_repairs as repairer

ROOT = Path(__file__).parents[1]/'content_sources'


def rows():
    return json.loads((ROOT/'g4-stock-v1-input.json').read_text())


def test_all_existing_templates_get_linked_complete_candidate_revisions():
    original=rows();before=deepcopy(original);pack=repairer.package(original)
    assert original==before
    assert len(pack['items'])==138 and len({x['id'] for x in pack['items']})==138
    for old,new in zip(original,pack['items']):
        assert new['derived_from_item_id']==old['id'] and new['id']!=old['id']
        assert new['explanation'].strip() and new['expected_answer']
        assert new['explanation']!=new['expected_answer']
        assert new['rubric_json']['stock_repair']['source_content_hash']==old['content_hash']
        assert 'status' not in new and 'reviewer' not in new


def test_protractor_contradiction_is_fixed_without_changing_its_angle():
    selected=[x for x in rows() if 'protractor_measure' in x['id']]
    assert len(selected)==4
    for old in selected:
        new=repairer.repair(old)
        assert 'At the position of the other ray' in new['prompt']
        assert 'At that same ray position' not in new['prompt']
        assert repairer.numbers(new['expected_answer'])[0]==repairer.numbers(old['expected_answer'])[0]


def test_equation_prompts_are_not_reduced_to_numeric_only_grading():
    selected=[x for x in rows() if 'unknown_side' in x['id'] or 'solve_unknown_angle' in x['id']]
    assert len(selected)==8
    for old in selected:
        new=repairer.repair(old)
        assert new['item_type']=='multi_step' and 'x=' in new['expected_answer']
        assert new['rubric_json']['stock_repair']['required_reasoning']


def test_known_ambiguous_pattern_answer_is_completed():
    old=next(x for x in rows() if x['id']=='synth-g4-oa-c5-pattern_features-016')
    new=repairer.repair(old)
    assert new['expected_answer']=='4, 8, 12, 16, 20, 24; all terms are even.'


@pytest.mark.parametrize('change',[{'status':'production'}, {'source_ref':'unverified imported source'},
                                 {'explanation':'Already complete'}, {'content_scope':'PRIVATE_INTERNAL'}])
def test_ineligible_sources_are_not_silently_repaired(change):
    old=deepcopy(rows()[0]);old.update(change)
    with pytest.raises(ValueError):repairer.repair(old)


def test_math_disagreement_and_unrecognized_template_fail_closed():
    old=deepcopy(next(x for x in rows() if 'round_any_place' in x['id']))
    old['expected_answer']='123'
    with pytest.raises(ValueError,match='disagrees'):repairer.repair(old)
    old['knowledge_node_id']='node-unknown'
    with pytest.raises(ValueError,match='No verified'):repairer.repair(old)


def test_pack_content_is_reproducible():
    frozen=json.loads((ROOT/'stock-math-repairs-138.json').read_text())
    assert repairer.package(rows())==frozen
