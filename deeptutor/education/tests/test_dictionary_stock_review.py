import pytest
from deeptutor.education.application.dictionary_stock_review import CONCEPTS,verify
# Exact retained lecture is a scope guard, not the answer oracle.
LECTURE='''Guide words appear on each page of a dictionary. They tell you the first word and last word on the page. The other words on the page come between the guide words in alphabetical order.
To put words in alphabetical order, put them in order by their first letters. If the first letters are the same, look at the second letters. If the second letters are the same, look at the third letters, and so on.'''
def question(word,lo,hi,answer):
 return {'library':'scienceqa','issues':[],'lecture':LECTURE,'prompt':f'Would you find the word {word} on a dictionary page with the following guide words?\n{lo} - {hi}','options':['yes','no'],'answer':answer}
def test_prefix_and_inclusive_boundaries():
 for word,answer in [('be','yes'),('bed','yes'),('bear','yes'),('bee','no')]:
  assert verify(question(word,'be','bed',answer))['answer']==answer

def test_wrong_answer_and_reversed_bounds_rejected():
 with pytest.raises(ValueError,match='contradicts'):verify(question('ant','cat','dog','yes'))
 with pytest.raises(ValueError,match='reversed'):verify(question('cat','dog','ant','no'))

def test_unknown_word_grammar_and_unresolved_assets_rejected():
 with pytest.raises(ValueError,match='grammar'):verify(question('ice-cream','a','z','yes'))
 q=question('ant','a','z','yes');q['issues']=['missing_figure']
 with pytest.raises(ValueError,match='structural'):verify(q)

def test_ambiguous_options_rejected():
 q=question('ant','a','z','yes');q['prompt']='Which word would you find on a dictionary page with the following guide words?\na - z';q['options']=['cat','dog'];q['answer']='cat'
 with pytest.raises(ValueError,match='unique'):verify(q)
