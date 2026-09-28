from deeptutor.education.application.content_stock import question


def issues(text):
    return question('harp-competition','synthetic',f'### Problem\nCompute a value.\n### Answer\n10\n### Solution\n{text}\n')['issues']


def test_factorial_followed_by_brackets_is_not_a_picture():
    assert 'unrendered_diagram' not in issues(r'\[n![n+1+(n+2)(n+1)]=440n!\]')


def test_real_diagram_syntax_remains_held():
    for text in ['[asy]draw((0,0)--(1,1));[/asy]', r'\begin{tikzpicture}x\end{tikzpicture}', '![triangle](figure.svg)', '![triangle][shape]', '![shape]\n\n[shape]: figure.svg', '![shape][]\n\n[shape]: figure.svg']:
        assert 'unrendered_diagram' in issues(text), text
