import json
import pytest
from deeptutor.education.application.math_figure_reviews import CORRECTION,patch_document,sha,safe_artifact

def test_patch_first_solution_retains_other_solutions_and_next_question():
    first='Invalid first argument.';second='A correct second argument.';third='Another correct argument.'
    text=f'# fixture\nProblems in this file: 2\n\n## Grid\n\n### Problem\n\nQuestion [asy]inert[/asy]\n\n### Answer\n\n$84$\n\n### Solution 1 of 3\n\n{first}\n\n### Solution 2 of 3\n\n{second}\n\n### Solution 3 of 3\n\n{third}\n\n---\n\n## Next\n\n### Problem\n\n1+1\n\n### Answer\n\n2\n\n### Solution\n\nTwo.\n'
    recipe={'source_title':'Grid','explanation_before_sha256':sha(first+'\n\n'+second+'\n\n'+third),'answer_before':'$84$'}
    after,explanation=patch_document('harp-counting-and-probability.md',text,recipe)
    assert explanation==CORRECTION+'\n\n'+second+'\n\n'+third
    assert after.split('## Next')[1]==text.split('## Next')[1]
    with pytest.raises(ValueError):patch_document('harp-counting-and-probability.md',after,recipe)

@pytest.mark.parametrize('svg',['<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>','<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>','<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.org"/></svg>','<svg xmlns="http://www.w3.org/2000/svg" fill="url(https://example.org)"/>'])
def test_external_or_executable_svg_rejected(tmp_path,svg):
    spec={'source_record_id':'r','source_raw_sha256':'raw','source_sha256':'source','data':{},'kind':'symbol-grid'};blob=json.dumps(spec).encode();key='stock-math-grid-v1'
    (tmp_path/(key+'.json')).write_bytes(blob);(tmp_path/(key+'.svg')).write_text(svg)
    review={'id':key,'source_record_id':'r','source_raw_sha256':'raw','source_sha256':'source','data':{},'kind':'symbol-grid','svg_sha256':sha(svg),'spec_sha256':sha(blob)}
    with pytest.raises(ValueError):safe_artifact(tmp_path,review)

def test_artifact_hash_or_source_tampering_rejected(tmp_path):
    key='stock-math-grid-v1';(tmp_path/(key+'.svg')).write_text('<svg/>')
    with pytest.raises(ValueError):safe_artifact(tmp_path,{'id':key,'svg_sha256':'wrong'})
