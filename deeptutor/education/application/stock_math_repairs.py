"""Explain and verify the bounded, self-authored G4 stock templates.

No network, credential access, database mutation, approval or student inference.
Unknown templates fail closed. The output is a linked candidate revision.
"""
from fractions import Fraction as F
import hashlib
import json
import math
import re


def numbers(text):
    return [int(x.replace(',', '')) for x in re.findall(r'\d+(?:,\d{3})*', text)]


def fractions(text):
    return [(int(a),int(b)) for a,b in re.findall(r'(\d+)/(\d+)',text)]


def check(value, expected):
    if value != expected:
        raise ValueError(f'Existing answer disagrees with calculation: {value!r} != {expected!r}')


def relation(a,b):
    return '>' if a>b else '<' if a<b else '='


GEOMETRY = {
 'DRAW_IDENTIFY_LINES': [
  'Mark two endpoints for a segment. For a ray, mark one endpoint and an arrow showing continuation in one direction. Draw parallel lines with the same direction and constant separation; their extended lines do not meet. Endpoint and arrow markings distinguish the objects even when all strokes on paper are finite.',
  'Perpendicular lines intersect at a 90-degree angle; mark a small square at the intersection. An obtuse angle has a turn greater than 90 degrees but less than 180 degrees. Compare the opening with a right angle, not the lengths of the drawn arms.',
  'Count endpoints and directions of continuation: a segment has two endpoints, a ray has one endpoint and continues one way, and a line has no endpoints and continues both ways. A short drawing represents an infinite object using arrows; its ink length is not the length of the ray or line.'
 ],
 'IDENTIFY_IN_FIGURES': [
  'There are two opposite-side pairs, and both pairs are parallel. Each of the four corners is a right angle. Adjacent sides meet at those right angles, so adjacent pairs are perpendicular; opposite parallel sides are not perpendicular.',
  'Any two sides of a triangle share a vertex, so they intersect and cannot be parallel. The two sides forming the stated 90-degree angle are perpendicular. Having one perpendicular pair does not make the other two angles right angles.',
  'The description explicitly gives one opposite-side pair that never meets and another pair that does meet when extended. Therefore there is exactly one parallel pair. The absence of right angles is separate from the parallel-side count.'
 ],
 'CLASSIFY_BY_LINES': [
  'Both a square and a rectangle require two pairs of parallel opposite sides. The stated shape has exactly one pair, so both are ruled out; the matching option is trapezoid. This example satisfies either the inclusive or exclusive convention for trapezoids.',
  'Four right angles identify a rectangle. A square is a special rectangle whose four sides are all equal. The question explicitly says not all sides are equal, so this rectangle is not a square.',
  'One right angle alone does not determine the shape. A rectangle requires two parallel pairs and four right angles; a trapezoid requires at least one parallel pair. Zero parallel pairs rules out both options.'
 ],
 'RIGHT_TRIANGLES': [
  'A triangle with one 90-degree angle is a right triangle. Two 90-degree angles would use the entire 180-degree sum, leaving a zero-degree third angle; that would collapse the shape, so a nondegenerate triangle cannot have two right angles.',
  'The 90-degree angle makes it a right triangle. Subtracting 90 from the full 180-degree angle sum leaves 90 degrees for the other two angles; indeed 40+50=90. Angles whose measures add to 90 degrees are complementary.',
  'The given 90-degree angle makes this a right triangle. One different example has angles 90, 45 and 45 degrees: all are positive and their sum is 180. Other valid examples must also have one 90-degree angle and two positive angles adding to 90.'
 ],
 'LINE_SYMMETRY': [
  'A symmetry line must fold the whole square exactly onto itself. Both diagonals work, and both lines joining opposite-side midpoints work, for four lines in total. A general tilted line does not pair all vertices and sides correctly.',
  'The two lines through opposite-side midpoints reflect each long side onto the other long side and each short side onto itself or its counterpart. A diagonal would have to exchange unequal adjacent side lengths, so it is not a symmetry line. There are two symmetry lines.',
  'For each of the three vertices, the line to the opposite-side midpoint exchanges the other two vertices and matches the equal sides. These are three distinct lines. Each works because all sides and all angles of the triangle are equal.',
  'A reflection axis of a triangle must fix one vertex and exchange the other two. That would force the two sides from the fixed vertex to have equal lengths. A scalene triangle has no equal side lengths, so it has no symmetry line.'
 ]
}


def explain(row):
    p=row['prompt']; answer=row['expected_answer']; node=row['knowledge_node_id'].removeprefix('node-')
    n=numbers(p); fs=fractions(p); kind=row['item_type']; corrected=p
    index=int(row['id'].rsplit('-',1)[1]); leaf=node.rsplit('.',1)[-1]
    if node.startswith('G4.G.'):
        if leaf not in GEOMETRY or index>=len(GEOMETRY[leaf]): raise ValueError('Unrecognized geometry template')
        return answer,GEOMETRY[leaf][index],corrected,kind,'geometric definition and necessary properties'
    if leaf=='COMPARISON_EQUATION':
        total,a,b=n[:3];check(a*b,total);check(numbers(answer),[a,b])
        text=f'{total} consists of {a} groups of {b}, so {total}÷{b}={a}. It also consists of {b} groups of {a}, so {total}÷{a}={b}. The two blanks are {a} and {b}; each multiplier compares the total with the specific quantity named after “as many as”.'
    elif leaf=='REPRESENT_VERBAL':
        a,b=n;check(numbers(answer),[a,b,a*b]);text=f'“{a} times as many as {b}” means {a} equal groups of {b}. Therefore the equation is {a}×{b}={a*b}. Multiplying the two quantities expresses the comparison; adding {a}+{b} would mean “{a} more than”.'
    elif leaf=='MULT_VS_ADD':
        a,b,c=n;check(b,c);check(numbers(answer)[:2],[a*b,a+b])
        answer=f'Noah: {a*b}; Priya: {a+b}; Noah’s comparison is multiplicative.'
        text=f'Lin’s {a} stickers are the reference amount. Noah has {b} groups of that amount: {a}×{b}={a*b}. Priya has only {b} extra stickers: {a}+{b}={a+b}. “Times as many” multiplies the reference quantity, whereas “more than” adds a fixed difference.'
    elif leaf=='REMAINDER_INTERP':
        a,b=n;q,r=divmod(a,b);count=q+bool(r);check(numbers(answer)[0],count)
        container=re.search(r'carried in (\w+)',p)[1]
        answer=f'{count} {container}; {a}÷{b}={q} remainder {r}.'
        text=f'{q} full {container} carry {q*b}, leaving {r}. Because everything must be carried, the remainder needs one additional container when it is nonzero. Thus {count} are needed. Check: {count}×{b}={count*b} is enough, while {(count-1)*b} from {count-1} containers is not.'
    elif leaf=='PATTERN_FEATURES':
        step,start,count=n;seq=[start+i*step for i in range(count)];check(numbers(answer)[:count],seq)
        feature='parity alternates' if step%2 else ('all terms are even' if start%2==0 else 'all terms are odd')
        answer=', '.join(map(str,seq))+f'; {feature}.'
        text=f'Begin with {start} as the first term, then add {step} to obtain each following term: '+', '.join(map(str,seq))+f'. Adding an {"odd" if step%2 else "even"} number {"switches" if step%2 else "preserves"} parity, so {feature}. The starting term counts as term 1; do not apply the rule once before listing it.'
    elif leaf=='PLACE_TEN_TIMES':
        value=n[0];a=(value//1000%10)*1000;b=(value//100%10)*100;check(F(a,b),F(10));check(numbers(answer),[10])
        text=f'The thousands digit represents {a}, and the hundreds digit represents {b}. Their ratio is {a}÷{b}=10. A digit one place to the left has ten times the value when the digit itself is the same; the digit and the value it represents are different ideas.'
    elif leaf=='READ_WRITE_FORMS':
        value=n[0];terms=[int(d)*10**i for i,d in reversed(list(enumerate(str(value)[::-1]))) if d!='0'];check(sum(terms),value);check(numbers(answer),terms)
        text='Read the value of each nonzero digit: '+' + '.join(map(str,terms))+f' = {value}. A zero digit contributes zero in its place and may be omitted from the sum, but the place value of every other digit must stay fixed. Adding the expanded terms reconstructs the original number.'
    elif leaf=='ROUND_ANY_PLACE':
        value=n[0];place=10000 if 'ten thousand' in p else 1000 if 'thousand' in p else 100
        lower=value//place*place;upper=lower+place;mid=lower+place//2;rounded=lower if value<mid else upper;check(F(answer),F(rounded))
        text=f'The adjacent multiples of {place} are {lower} and {upper}; their midpoint is {mid}. Since {value} is {"below" if value<mid else "at or above"} the midpoint, it rounds to {rounded}. Digits to the right become zero; rounding changes the approximation, not merely the displayed punctuation.'
    elif leaf in ('MULT_2BY2','MULT_4BY1'):
        a,b=n;check(F(answer),F(a*b));tens=b//10*10;ones=b%10
        if tens:parts=f'{a}×({tens}+{ones})={a*tens}+{a*ones}={a*b}'
        else:
            place=10**(len(str(a))-1);leading=a//place*place;rest=a-leading
            parts=f'({leading}+{rest})×{b}={leading*b}+{rest*b}={a*b}'
        text=f'Use place value and the distributive property: {parts}. Each partial product keeps its place value. The two partial products together account for every group in the original multiplication.'
    elif node=='G4.NBT.B5.EXPLAIN_MODELS':
        a,b=n;at,ao=a//10*10,a%10;bt,bo=b//10*10,b%10;parts=[at*bt,at*bo,ao*bt,ao*bo];check(numbers(answer),parts+[a*b])
        text=f'Divide one side into {at}+{ao} and the other into {bt}+{bo}. The four non-overlapping rectangles have areas {at}×{bt}={parts[0]}, {at}×{bo}={parts[1]}, {ao}×{bt}={parts[2]}, and {ao}×{bo}={parts[3]}. Their areas add to {sum(parts)}; label each region so no cross-product is omitted.'
    elif node=='G4.NBT.B6.EXPLAIN_MODELS':
        a,b=n;q,r=divmod(a,b);check(numbers(answer)[:2],[q,r])
        text=f'{b}×{q}={b*q}; subtracting from {a} leaves {r}. Thus the whole-number quotient is {q} with remainder {r}. The check {b}×{q}+{r}={a} reconstructs the dividend, and {r}<{b} confirms that another complete group cannot be formed.'
    elif leaf=='AREA_PERIMETER_FORMULA':
        a,b=n;check(re.findall(r'= (\d+)',answer),[str(a*b),str(2*(a+b))])
        text=f'The area counts square units covering the interior: {a}×{b}={a*b}. The perimeter counts linear units along all four sides: {a}+{b}+{a}+{b}={2*(a+b)}. Area uses squared units; perimeter uses the original length unit. They measure different things even though both use the same side lengths.'
    elif leaf=='UNKNOWN_SIDE':
        area,side=n;value=F(area,side);check(F(answer),value);check(value.denominator,1)
        answer=f'{side}×x={area}; x={value} units.';kind='multi_step'
        text=f'Area equals the product of the two side lengths, so {side}×x={area}. Divide both sides by {side}: x={area}÷{side}={value}. Check by multiplying {side}×{value}={area}. The result is a length in units, not an area in square units.'
    elif leaf=='ANGLE_CONCEPT':
        divisor=2 if 'half turn?' in p else 4 if 'quarter turn?' in p else 3 if 'third turn?' in p else 1
        value=360//divisor;check(F(answer),F(value));text=f'A full turn contains 360 one-degree turns. The requested turn is 1/{divisor} of a full turn, so its measure is 360÷{divisor}={value} degrees. The angle measures the amount of turning; extending the arms would not change it.'
    elif leaf=='DEGREE_MEASURE':
        value=n[0];check(F(answer),F(value));text=f'Each one-degree turn contributes exactly 1 degree. Therefore {value} such turns make an angle of {value} degrees, and an angle of that measure contains {value} one-degree turns. This remains true for a turn greater than 180 degrees; it is then a reflex angle.'
    elif leaf=='PROTRACTOR_MEASURE':
        start_scale=re.search(r'0 on the (inner|outer) scale',p)[1];readings=re.findall(r'(inner|outer) scale reads (\d+)',p);values=dict((k,int(v)) for k,v in readings)
        check(sum(values.values()),180);value=values[start_scale];check(numbers(answer)[0],value)
        corrected=p.replace('At that same ray position,','At the position of the other ray,')
        answer=f'{value} degrees, using the {start_scale} scale whose zero is aligned with the starting ray.'
        text=f'First locate zero on the starting ray; that identifies the {start_scale} scale. Follow the same scale to where the other ray crosses the protractor and read {value} degrees. The other printed scale runs in the opposite direction, so using it would measure a different turn. The starting ray itself must read zero on the chosen scale.'
    elif leaf=='SKETCH_ANGLE':
        value=n[0];category='acute' if value<90 else 'right' if value==90 else 'obtuse' if value<180 else 'straight';check(answer.split()[0],category)
        text=f'{value} degrees is {"less than 90" if value<90 else "exactly 90" if value==90 else "between 90 and 180" if value<180 else "exactly 180"}, so it is a {category} angle. Use that classification to estimate the opening before reading the protractor. Keep the centre on the vertex and align the zero mark with the starting ray; the lengths of the rays do not determine the angle.'
    elif leaf=='ADDITIVE_ANGLE':
        whole,a,b=n;check(a+b,whole);check(numbers(answer)[:3],[a,b,whole]);text=f'The two parts share the vertex, do not overlap, and fill the original angle. Their measures therefore add: {a}+{b}={a+b}={whole} degrees. The non-overlap and full-coverage conditions are why the addition represents the whole angle.'
    elif leaf=='SOLVE_UNKNOWN_ANGLE':
        whole=n[0];known=n[1:];value=whole-sum(known);check(F(answer),F(value));known_text='+'.join(map(str,known));answer=f'{known_text}+x={whole}; x={value} degrees.';kind='multi_step'
        text=f'The parts make the stated total turn, so {known_text}+x={whole}. The known parts sum to {sum(known)} degrees; subtract them from the whole to get x={whole}−{sum(known)}={value}. Check {sum(known)}+{value}={whole}.'
    elif leaf=='EQUIVALENT_MODEL':
        (a,b),(c,d)=fs[:2];factor=F(d,b);check(F(a,b),F(c,d));check(factor.denominator,1);check(numbers(answer)[0],factor.numerator)
        text=f'Multiply both numerator and denominator by {factor}: {a}×{factor}={c} and {b}×{factor}={d}. Each original part is split into {factor} equal smaller pieces, and the selected pieces increase by the same factor. The amount of the same whole stays unchanged: {a}/{b}={c}/{d}.'
    elif leaf=='GENERATE_EQUIVALENT':
        a,b=fs[0];factor=int(re.search(r'by (\d+)',p)[1]);check(answer,f'{a*factor}/{b*factor}');text=f'Multiply both numbers by {factor}: ({a}×{factor})/({b}×{factor})={a*factor}/{b*factor}. The number of selected pieces and the total number of equal pieces grow together, so their ratio stays the same. Multiplying only the numerator would change the fraction’s value.'
    elif leaf in ('COMPARE_UNLIKE','JUSTIFY_COMPARISON'):
        (a,b),(c,d)=fs[:2];den=math.lcm(b,d);left=a*(den//b);right=c*(den//d);sign=relation(left,right)
        if sign not in answer:raise ValueError('Fraction comparison disagrees with old answer')
        text=f'Use equal-sized parts with denominator {den}: {a}/{b}={left}/{den} and {c}/{d}={right}/{den}. Since {left}{sign}{right}, we have {a}/{b}{sign}{c}/{d}. When comparing actual portions, use wholes of the same size; equal denominators then mean equal-sized pieces, so comparing their counts is meaningful.'
    elif leaf=='ADD_SUB_MIXED':
        match=re.search(r'(\d+) (\d+)/(\d+) ([+-]) (\d+) (\d+)/(\d+)',p);w,a,b,op,v,c,d=match.groups();w,a,b,v,c,d=map(int,[w,a,b,v,c,d]);check(b,d);left=w*b+a;right=v*b+c;num=left+right if op=='+' else left-right;q,r=divmod(num,b);check(answer,f'{q} {r}/{b}')
        text=f'Convert the mixed numbers to {b}ths: {w} {a}/{b}={left}/{b} and {v} {c}/{b}={right}/{b}. Then {left}/{b}{op}{right}/{b}={num}/{b}. Grouping every {b} parts into a whole gives {q} {r}/{b}. The denominator stays {b} because the size of each part has not changed.'
    elif leaf=='DECOMPOSE':
        a,b=fs[0];pairs=[(1,a-1),(2,a-2)];parts=fractions(answer);check(parts,[(1,b),(a-1,b),(a,b),(2,b),(a-2,b),(a,b)])
        text=f'Keep the denominator {b}, and split the numerator {a} in two different ways: 1+{a-1}={a} and 2+{a-2}={a}. Therefore 1/{b}+{a-1}/{b}={a}/{b}, and 2/{b}+{a-2}/{b}={a}/{b}. Each equation joins the same-sized pieces; other distinct valid decompositions may also be accepted.'
    elif leaf=='SUM_OF_UNIT_FRACTIONS':
        a,b=fs[0];check(answer.count('+')+1,a);check(fractions(answer),[(1,b)]*a);text=f'The unit fraction 1/{b} is one of {b} equal parts of a whole. The fraction {a}/{b} means {a} of those parts, so add 1/{b} exactly {a} times. The count of addends is {a}; the denominator remains {b}.'
    elif node=='G4.NF.B3.WORD_PROBLEMS':
        (a,b),(c,d)=fs[:2];check(b,d);subtract='cut off' in p or 'ate ' in p;num=a-c if subtract else a+c;check(F(answer),F(num,b));op='−' if subtract else '+'
        text=f'The amounts use the same-sized {b}ths of the same whole. {"Subtract the amount removed" if subtract else "Add the amounts combined"}: {a}/{b}{op}{c}/{b}={num}/{b}. The denominator stays {b}, because the unit size has not changed. Check that the result is {"less than the starting amount" if subtract else "at least as large as either amount added"}.'
    elif leaf=='FRACTION_AS_MULTIPLE':
        a,b=fs[0];check(numbers(answer),[a,1,b]);text=f'{a}/{b} consists of {a} copies of the unit fraction 1/{b}. Repeated addition of those copies is represented by {a}×(1/{b}). The multiplier counts selected parts; it does not change the size of one part.'
    elif node=='G4.NF.B4.MULTIPLY_BY_WHOLE' or node=='G4.NF.B4.WORD_PROBLEMS':
        if leaf=='MULTIPLY_BY_WHOLE':k,a,b=n[:3]
        else:
            a,b=fs[0];k=n[2]
        value=F(k*a,b);check(F(answer.split('=')[0].strip()),value)
        text=f'Each group contains {a}/{b}, and there are {k} equal groups. That is {k}×{a}={k*a} copies of 1/{b}, so the total is {k*a}/{b}. The denominator stays {b}; only the number of parts increases. Grouping {b} parts into each whole gives the mixed-number form shown in the answer.'
    elif leaf=='TENTHS_TO_HUNDREDTHS':
        (a,b),(c,d)=fs[:2];check((b,d),(10,100));check(fractions(answer)[-1],(a*10+c,100));text=f'Each tenth is ten hundredths, so {a}/10={a*10}/100. Now both addends count hundredths: {a*10}/100+{c}/100={a*10+c}/100. Convert the unit size first; adding the original numerators without conversion would mix different-sized parts.'
    elif leaf=='DECIMAL_NOTATION':
        if fs:
            a,b=fs[0];check(F(answer),F(a,b));text=f'The denominator {b} names the place value. {a}/{b} is {a} hundredths, written {answer}; a zero in the tenths place is necessary when there are fewer than ten hundredths. Multiplying the decimal by {b} recovers the numerator {a}.'
        else:
            value=F(re.search(r'\d+\.\d+',p)[0]);check(F(fractions(answer)[0][0],fractions(answer)[0][1]),value)
            text=f'Read the digits by place value: {str(float(value))} represents {value*100} hundredths. Write the requested denominator and count its unit fractions; multiplying numerator and denominator together converts tenths into hundredths without changing the value. Check the fraction by division to recover the decimal.'
    elif leaf=='COMPARE_DECIMALS':
        a,b=re.findall(r'\d+\.\d+',p)[:2];sign=relation(F(a),F(b));check(answer,f'{a} {sign} {b}');ai,bi=F(a)*100,F(b)*100
        text=f'Express both numbers in hundredths: {a} is {ai} hundredths and {b} is {bi} hundredths. Since {ai}{sign}{bi}, {a}{sign}{b}. A trailing zero changes the written precision but not the value; compare equal place values rather than the number of decimal digits.'
    else:raise ValueError('No verified explanation template for '+node)
    return answer,text,corrected,kind,'exact arithmetic and source-template review'


def repair(row):
    if (row['status']!='candidate' or row['explanation'] or not row['expected_answer']
            or not row['id'].startswith(('synth-','fill-'))
            or not row['source_ref'].startswith('self-authored') or row['content_scope']!='BUNDLED'):
        raise ValueError('Not an eligible incomplete self-authored candidate')
    answer,explanation,prompt,kind,verification=explain(row)
    fields=('knowledge_node_id','difficulty','content_scope','source_ref','license_note','attribution_text','figure_spec_id','choices_json')
    result={key:row.get(key) for key in fields}
    rubric=json.loads(row.get('rubric_json') or '{}')
    rubric['stock_repair']={'source_content_hash':row['content_hash'],
        'source_prompt_sha256':hashlib.sha256(row['prompt'].encode()).hexdigest(),
        'verification':verification,'method_version':'g4-stock-repair-v1',
        'required_reasoning':explanation,'approval':'pending'}
    result.update(id=row['id']+'-stock-r1',derived_from_item_id=row['id'],item_type=kind,
                  prompt=prompt,expected_answer=answer,explanation=explanation,
                  explanation_source='derived',rubric_json=rubric)
    return result


def package(rows):
    selected=[r for r in rows if r['id'].startswith(('synth-','fill-'))]
    if not selected:raise ValueError('No eligible records')
    versions={r['course_version_id'] for r in selected}
    if len(versions)!=1:raise ValueError('One course per repair batch')
    return {'schema_version':1,'course_version_id':versions.pop(),
            'source_name':f'存量数学修订 · {len(selected)}题补全讲解与题意校正 · v1',
            'items':[repair(r) for r in selected]}
