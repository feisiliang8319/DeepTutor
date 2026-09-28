from fractions import Fraction as F
from pathlib import Path
from itertools import product
import hashlib,json,sys
T=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent
rows=json.loads((T/'public-domain-processed/public-domain-records.json').read_text());numbers=[1,3,5,6,8,9,11,14]
selected=[next(r for r in rows if r['metadata']['book']=='Amusements in Mathematics' and r['metadata']['number']==n) for n in numbers]
for r in selected:
 data=(T/r['source_path']).read_bytes();assert hashlib.sha256(data).hexdigest()==r['source_sha256'];text=data.decode().replace('\r\n','\n')
 for span in r['metadata']['spans']:assert hashlib.sha256(text[span['start']:span['end']].encode()).hexdigest()==span['sha256']
# Exhaustive positive counts, with upper bounds supplied by the budget.
stamps=[(x,6*x,z) for x in range(1,8) for z in range(1,25) if 4*x+2*(6*x)+5*z==120]
assert stamps==[(5,30,8)]
# Solve the three simultaneous hypothetical transfers with exact row reduction.
a=[[F(1),F(-2),F(0),F(-15)],[F(0),F(1),F(-3),F(-52)],[F(-6),F(0),F(1),F(-21)]]
for col in range(3):
 pivot=next(i for i in range(col,3) if a[i][col]);a[col],a[pivot]=a[pivot],a[col];d=a[col][col];a[col]=[v/d for v in a[col]]
 for i in range(3):
  if i!=col:
   factor=a[i][col];a[i]=[x-factor*y for x,y in zip(a[i],a[col])]
j,h,d=[r[-1] for r in a];assert (j,h,d)==(7,11,21) and j+5==2*(h-5) and h+13==3*(d-13) and d+3==6*(j-3)
# Recover and replay all seven conservative doubling transfers.
v=[128]*7
for donor in reversed(range(7)):
 assert all(v[i]%2==0 for i in range(7) if i!=donor)
 for i in range(7):
  if i!=donor:v[i]//=2
 v[donor]+=sum(v[i] for i in range(7) if i!=donor)
initial=v[:];assert initial==[449,225,113,57,29,15,8]
states=[initial[:]]
for donor in range(7):
 payment=sum(v[i] for i in range(7) if i!=donor);assert v[donor]>=payment
 v[donor]-=payment
 for i in range(7):
  if i!=donor:v[i]*=2
 assert min(v)>=0 and sum(v)==896;states.append(v[:])
assert v==[128]*7
assert [states[i+1][i] for i in range(7)]==[2,4,8,16,32,64,128]
packets=[(a,b) for a in range(1,37) for b in range(2,23) if 3*a+5*b==110]
assert packets==[(5,19),(10,16),(15,13),(20,10),(25,7),(30,4)]
# Invert each affine spending operation; replay enforces nonnegative integer gifts.
x=1
for extra in (3,2,1):x=2*(x+extra)
assert x==42;remainders=[x];gifts=[]
for extra in (1,2,3):
 gift=F(x,2)+extra;assert gift.denominator==1 and 0<=gift<=x;x-=gift;gifts.append(int(gift));remainders.append(int(x))
assert x==1 and gifts==[22,12,7]
p=F(1,5);s=600;cost1=s/(1+p);cost2=s/(1-p);loss=cost1+cost2-2*s
assert (cost1,cost2,loss,loss/(cost1+cost2))==(500,750,50,F(1,25))
for numerator in range(1,10):
 p=F(numerator,10);cost=s/(1+p)+s/(1-p);assert (cost-2*s)/cost==p*p
people=[n for n in range(3,83) if F(80,n-2)-F(80,n)==2]
assert people==[10]
# The exact factor relation bounds all possible positive quarter-grid solutions.
factors=[(a,16//a) for a in range(1,17) if 16%a==0 and a<=16//a]
pairs=[((F(a)+4)/4,(F(b)+4)/4) for a,b in factors]
assert pairs==[(F(5,4),F(5)),(F(3,2),F(3)),(F(2),F(2))]
assert all(x+y==x*y for x,y in pairs) and min(x+y for x,y in pairs if x+y>4)==F(9,2)
proof={'source_records':[r['id'] for r in selected],'source_numbers':numbers,'stamps':stamps,'initial_group_counts':[int(j),int(h),int(d)],'seven_transfer_states':states,'packet_combinations':packets,'reverse_spending_remainders':remainders,'gifts':gifts,'equal_resale_costs':[str(cost1),str(cost2)],'resale_loss':str(loss),'resale_loss_rate':'1/25','people':people,'quarter_grid_pairs':[[str(x),str(y)] for x,y in pairs],'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scope':'Exact mathematics under rewritten explicit conditions; no grade, rights or formal assessment approval.'}
(T/'historical-batch4-math-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'source_spans_verified':16,'mathematical_tasks_verified':8,'stamps':stamps,'initial_counts':[int(j),int(h),int(d)],'packet_combinations':len(packets),'minimum_next_sum':'9/2'}))
