"""Closed, independently calculated checks; never execute original drawing code."""
from pathlib import Path
from fractions import Fraction as F
from itertools import combinations, permutations, product
import hashlib,json,sys
D=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent/'math-eight-figures'
sha=lambda x:hashlib.sha256(x).hexdigest()
result=[]
for entry in json.loads((D/'manifest.json').read_text()):
 specfile=D/(entry['id']+'.json');svgfile=D/(entry['id']+'.svg')
 assert sha(specfile.read_bytes())==entry['spec_sha256'] and sha(svgfile.read_bytes())==entry['svg_sha256']
 s=json.loads(specfile.read_text());d=s['data'];kind=s['kind']
 if kind=='l-shape':
  L=d['given_lengths'];de=L['BC']-L['FA'];missing=L['AB']*L['BC']-d['given_area'];ef=F(missing,de);answer=str(de+ef);assert answer=='9'
  reasoning='外接矩形面积 8×9=72，缺口面积 72−52=20；DE=9−5=4，所以 EF=20÷4=5，DE+EF=9。图形不按比例绘制，不能量图求值。'
  proof={'DE':de,'EF':str(ef),'missing_area':missing}
 elif kind=='speed-points':
  ratios={n:F(str(y))/F(str(x)) for n,(x,y) in d['points'].items()};answer=max(ratios,key=ratios.get);assert answer=='Evelyn'
  reasoning='平均速度等于距离除以时间，对应从原点到该点的射线斜率。Evelyn 的斜率最大。坐标数值只用于检查图形，不给原题额外添加刻度。'
  proof={'distance_per_time':{k:str(v) for k,v in ratios.items()}}
 elif kind=='opposite-cube':
  faces=d['visible_adjacent_faces'];solutions=[]
  for n in range(max(0,max(faces)-5),min(faces)+1):
   numbers=set(range(n,n+6))
   if not set(faces)<=numbers:continue
   for opposites in permutations(numbers-set(faces)):
    if len({a+b for a,b in zip(faces,opposites)})==1:solutions.append({'minimum':n,'opposites':opposites,'sum':sum(numbers)})
  assert solutions==[{'minimum':11,'opposites':(12,16,13),'sum':81}];answer='81';proof={'complete_assignments':solutions}
  reasoning='含有 11、14、15 的六个连续非负整数只有 10–15 或 11–16。前一组的对面和为 25，会使 11 与 14 相对，但图中两面相邻，矛盾。因此六面为 11–16，总和为 81。'
 elif kind=='growing-squares':
  assert d['side_lengths']==[1,2,3];answer=str(7*7-6*6);assert answer=='13';proof={'sixth':36,'seventh':49}
  reasoning='第 n 个正方形用 n² 块。第七个比第六个多 7²−6²=49−36=13 块。'
 elif kind=='six-dots':
  tris=[];flat=[]
  for a,b,c in combinations(d['points'],3):
   (tris if (b[0]-a[0])*(c[1]-a[1])!=(b[1]-a[1])*(c[0]-a[0]) else flat).append([a,b,c])
  assert len(tris)==18 and len(flat)==2;answer='18';proof={'all_triples':len(tris)+len(flat),'collinear':flat}
  reasoning='任取三个点共有 C(6,3)=20 组；上下两行各有一组三点共线，不能构成三角形。其余 20−2=18 组均有效。'
 elif kind=='spinners':
  outcomes=list(product(d['spinner_A'],d['spinner_B']));even=[x for x in outcomes if x[0]*x[1]%2==0];answer=str(F(len(even),len(outcomes)));assert answer=='2/3';proof={'equally_likely_outcomes':len(outcomes),'even_products':len(even)}
  reasoning='在两次转动相互独立的前提下，积为奇数必须两者都为奇数，概率为 (2/4)×(2/3)=1/3。因此偶数积的概率为 2/3。'
 elif kind=='symbol-grid':
  lines=[[3*r+c for c in range(3)] for r in range(3)]+[[3*r+c for r in range(3)] for c in range(3)]+[[0,4,8],[2,4,6]]
  valid=[bits for bits in product([0,1],repeat=9) if any(all(bits[i]==0 for i in line) for line in lines) and any(all(bits[i]==1 for i in line) for line in lines)]
  assert len(valid)==84;answer='84';proof={'complete_configurations':512,'qualifying_configurations':84,'lines':lines}
  reasoning='两种符号的整条直线不能相交，所以只能是互异的平行行，或互异的平行列。按行计：三行全为同种符号行但两种符号都出现，有 2³−2=6 种；恰有一行圆、一行三角、另一行混合，有 3×2×(2³−2)=36 种，共 42 种。按列同理 42 种，两类不能重叠，总计 84。原解析用 C(9,3)=84 只是数值巧合，理由不成立。'
 elif kind=='dartboard':
  ri=d['inner_radius'];ro=d['outer_radius'];n=d['equal_sectors'];wi=F(ri*ri,ro*ro*n);wo=F(ro*ro-ri*ri,ro*ro*n)
  values=[(v,wi) for v in d['inner_values_upper_left_upper_right_bottom']]+[(v,wo) for v in d['outer_values_upper_left_upper_right_bottom']]
  assert sum(p for _,p in values)==1
  odd=sum(p for v,p in values if v%2);even=1-odd
  p=sum(p*q for (a,p),(b,q) in product(values,repeat=2) if (a+b)%2);answer=str(p);assert p==F(35,72);proof={'odd_single_throw':str(odd),'even_single_throw':str(even),'two_throw_joint_probability':str(p),'independence_required':True}
  reasoning='每个内区占全圆 1/12，每个外环区占 1/4。一次得奇数的概率为 1/12+1/4+1/4=7/12，得偶数为 5/12。在两次投掷独立的前提下，奇数和概率为 2×(7/12)×(5/12)=35/72。面积不是概率，必须除以全盘面积。'
 else:raise AssertionError(kind)
 result.append({**entry,'source_raw_sha256':s['source_raw_sha256'],'source_sha256':s['source_sha256'],'answer':answer,'reasoning_zh':reasoning,'independent_check':proof,'status':'closed_math_check_passed','publication':'held_for_source_rights_and_curriculum_review'})
payload={'checker_sha256':sha(Path(__file__).read_bytes()),'scope':'Eight manually transcribed diagrams and closed mathematical answers. Source rights, grade suitability, source figure parity and formal Quiz approval remain separate. Original drawing code not executed.','records':result}
(D/'independent-math-proof.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checked':len(result),'proof_sha256':sha((D/'independent-math-proof.json').read_bytes()),'answers':[x['answer'] for x in result]}))
