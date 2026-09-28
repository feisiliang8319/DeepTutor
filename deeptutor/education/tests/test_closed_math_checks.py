from fractions import Fraction as F
import pytest
from deeptutor.education.application.closed_math_checks import evaluate,check,Unsupported

@pytest.mark.parametrize('text,result',[(r'-2^2',-4),(r'(-2)^2',4),(r'2^{-3}',F(1,8)),(r'\frac12+\dfrac{1}{3}',F(5,6)),(r'\sqrt{\frac{49}{4}}',F(7,2)),(r'\sqrt[3]{27}',3),(r'16^{7/4}',128),(r'\left\lceil-\frac{5}{3}\right\rceil',-1),(r'\lfloor-1.2\rfloor',-2),(r'\frac{11!-10!}{9!}',100),(r'3(2+1)(4-1)',27),(r'|{-34.1}|',F(341,10)),(r'2^{3^2}',512)])
def test_exact_numbers_precedence_and_domains(text,result):assert evaluate(text)==result

@pytest.mark.parametrize('text',[r'\input{secret}',r'__import__("os")',r'\sqrt{-1}',r'\sqrt{2}',r'(-27)^{5/3}',r'2^23',r'3!!',r'2 \frac12',r'2+3x',r'2^{300}',r'201!',r'1/0',r'0^0',r'1..2',r'1 2',r'6/2(1+2)',r'\frac{1}{2}trailing'])
def test_unsupported_never_guessed_or_executed(text):
    with pytest.raises(Unsupported):evaluate(text)

def test_question_scope_and_mismatch_reporting():
    row={'prompt':'What is the value of $2+3$?','answer':'$6$','issues':[]};before=repr(row)
    assert check(row)['status']=='mismatch' and repr(row)==before
    row['prompt']='What is $2+3$? Explain using a drawing.';assert check(row) is None
    row['prompt']='What is $2+3$?';row['issues']=['missing_figure'];assert check(row) is None

def test_fractional_expression_equality_not_string_equality():
    assert check({'prompt':'Evaluate $1/3+1/6$.','answer':r'\frac12','issues':[]})['status']=='match'
