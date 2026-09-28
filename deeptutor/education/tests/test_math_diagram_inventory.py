import pytest
from deeptutor.education.application.math_diagram_inventory import describe,sha


def test_roles_exact_offsets_and_code_is_inert():
    code='system("never run this");'
    row={'prompt':'text[asy]'+code+'[/asy]end','explanation':'No image.'}
    result=describe(row);part=result['fields']['prompt'][0]
    assert result['role']=='prompt_only' and result['execution']=='never_executed'
    assert row['prompt'][part['start']:part['end']]==code and part['sha256']==sha(code)
    row['explanation']='[asy]draw((0,0)--(1,1));[/asy]'
    assert describe(row)['role']=='prompt_and_solution'
    row['prompt']='No figure needed.'
    assert describe(row)['role']=='solution_only'


def test_unbalanced_blocks_are_not_counted_as_complete():
    for code in ['[asy]draw(0);','draw(0);[/asy]']:
        with pytest.raises(ValueError,match='Incomplete'):describe({'prompt':code,'explanation':''})
