import pytest
from deeptutor.education.application.scienceqa_answer_checks import formula_elements, verify


def speed_question(options, answer=None):
    return {'prompt': 'Compare the motion of two ships. Which ship was moving at a higher speed?', 'options': options, 'answer': answer or options[0], 'issues': []}


def test_speed_uses_exact_ratio_and_not_largest_distance():
    options = ['a ship that moved 0.3miles west in 0.1hours', 'a ship that moved 1,200miles east in 500hours']
    assert verify(speed_question(options), 'speed')['rates'] == ['3', '12/5']


@pytest.mark.parametrize('other', ['a ship that moved 6miles in 2hours', 'a ship that moved 1kilometers in 1hour', 'a ship that moved 1miles in 0hours'])
def test_speed_holds_ties_mixed_units_and_zero_duration(other):
    with pytest.raises(ValueError):
        verify(speed_question(['a ship that moved 3miles in 1hour', other]), 'speed')


def test_formula_symbols_are_case_sensitive_and_all_input_is_parsed():
    assert formula_elements('Co') == ['Co']
    assert formula_elements('CO') == ['C', 'O']
    for unsupported in ['Xx2', 'H0', 'NaCl!', 'Ca(OH)2', '2H2O']:
        with pytest.raises(ValueError):
            formula_elements(unsupported)


def test_formula_does_not_use_answer_or_unrelated_substance():
    q = {'prompt': 'Select the elementary substance.', 'options': ['oxygen (O2)', 'water (H2O)'], 'answer': 'water (H2O)'}
    with pytest.raises(ValueError, match='answer mismatch'):
        verify(q, 'formula')
    q['prompt'] = 'The chemical formula for water is H2O.\n\nComplete the statement.\nOxygen is ().'
    q.update(options=['a compound', 'an elementary substance'], answer='a compound')
    with pytest.raises(ValueError, match='Unsupported formula question'):
        verify(q, 'formula')


def genetics_question():
    return {'prompt': 'In a group of plants, the allele for red flowers (r) is dominant over the allele for white flowers (R).\nAlex has the heterozygous genotype Rr for the flower color gene.\n\nBased on this information, what is Alex\'s phenotype for the flower color trait?', 'options': ['red flowers', 'white flowers'], 'answer': 'red flowers'}


def test_explicit_dominance_not_uppercase_convention():
    q = genetics_question(); q['prompt'] = q['prompt'].replace('the allele', 'The allele', 1)
    result = verify(q, 'genetics')
    assert result['dominant'] == 'r' and result['answer'] == 'red flowers'


@pytest.mark.parametrize('old,new', [('heterozygous', 'homozygous'), ('Alex has', 'Blair has'), ('flower color gene', 'stem height gene'), ('plants', 'humans')])
def test_genetics_rejects_conflicting_or_out_of_scope_premises(old, new):
    q = genetics_question(); q['prompt'] = q['prompt'].replace('the allele', 'The allele', 1).replace(old, new)
    with pytest.raises(ValueError):
        verify(q, 'genetics')


def test_existing_hold_and_ambiguous_options_are_not_cleared():
    options = ['a ship that moved 3miles in 1hour', 'a ship that moved 2miles in 1hour']
    q = speed_question(options); q['issues'] = ['missing_figure']
    with pytest.raises(ValueError, match='structural hold'):
        verify(q, 'speed')
    q['issues'] = []; q['options'] = [options[0], options[0]]
    with pytest.raises(ValueError, match='ambiguous options'):
        verify(q, 'speed')
