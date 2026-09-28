from collections import Counter
from fractions import Fraction
from itertools import combinations, product
from pathlib import Path
import datetime, hashlib, json, math, sys
W=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent
sources=json.loads((W/'public-domain-processed/public-domain-records.json').read_text())
numbers=[57,59,114,121,126,127,389,397,416]
selected=[next(r for r in sources if r['metadata']['book']=='Amusements in Mathematics' and r['metadata']['number']==n) for n in numbers]
for r in selected:
 data=(W/r['source_path']).read_bytes();assert hashlib.sha256(data).hexdigest()==r['source_sha256']
 text=data.decode().replace('\r\n','\n')
 for s in r['metadata']['spans']:assert hashlib.sha256(text[s['start']:s['end']].encode()).hexdigest()==s['sha256']
# Minute-by-minute search independently recovers the unique time in one day.
times=[m for m in range(1440) if Fraction(m,4)+Fraction(1440-m,2)==m]
assert times==[576]
# Relative angular motion in true minutes, with a normal 12:1 gear ratio.
rate=Fraction(720,11*65)
assert (6*rate-Fraction(1,2)*rate)*65==360
watch_gain=(rate-1)*60;assert watch_gain==Fraction(60,143)
# Search all possible smaller b in N=2(b^2-1), not just quoted solutions.
square_candidates=[]
for b in range(2,986):
 n=2*(b*b-1);a=math.isqrt(n+1)
 if a*a==n+1:square_candidates.append({'N':n,'a':a,'b':b})
assert [x['N'] for x in square_candidates]==[48,1680,57120,1940448]
# Every one of the20 orders of three increases and three decreases.
orders=[]
for ups in combinations(range(6),3):
 value=Fraction(64)
 for i in range(6):value*=Fraction(3,2) if i in ups else Fraction(1,2)
 assert value==27;orders.append(ups)
# Leading digit3 moved to end: prove no shorter length works by divisibility.
rotation_trials=[]
for k in range(1,16):
 numerator=9*10**k-6
 rotation_trials.append({'following_digits':k,'remainder_mod17':numerator%17})
 if numerator%17==0:
  x=numerator//17;n=3*10**k+x
  assert k==15 and 0<=x<10**k and n==3529411764705882
  assert 2*int(str(n)[1:]+str(n)[0])==3*n
assert all(x['remainder_mod17'] for x in rotation_trials[:-1])
# Same-remainder divisors enumerated exhaustively up to minimum difference.
values=[701,1059,1417,2312]
divisors=[d for d in range(1,359) if len({x%d for x in values})==1]
assert divisors==[1,179] and values[0]%179==164
assert math.gcd(*(x-values[0] for x in values[1:]))==179
# Counts ordered both working, left working only, right working only, both faulty.
tables=[]
for a,b,c,d in product(range(8),repeat=4):
 if c+d==4 and b+d==5 and a+c==2 and a+b==3:tables.append([a,b,c,d])
assert tables==[[0,3,2,2],[1,2,1,3],[2,1,0,4]]
assert all(sum(x)==7 for x in tables)
# Ordered dice outcomes, including exhaustive disjoint pairs of reachable odd sums.
counts=Counter(map(sum,product(range(1,7),repeat=3)))
odds=list(range(5,18,2));pairs=list(combinations(odds,2));equal=[]
for a,b in combinations(pairs,2):
 if set(a).isdisjoint(b) and sum(counts[s] for s in a)==sum(counts[s] for s in b):equal.append([a,b])
assert equal==[[(5,9),(13,15)]] and sum(counts[s] for s in (5,9))==31
# Proleptic Gregorian calendar; 2001-01-01 is supplied as the anchor in the task.
assert datetime.date(2001,1,1).weekday()==0
weekdays={year:datetime.date(year,1,1).weekday() for year in (2001,2101,2201,2301,2401)}
assert list(weekdays.values())==[0,5,3,1,0]
assert sum(366 if y%4==0 and (y%100!=0 or y%400==0) else 365 for y in range(2001,2401))==146097
assert 146097%7==0
assert {datetime.date(y,1,1).weekday() for y in range(1,10000,100)}=={0,1,3,5}
proof={'source_records':[x['id'] for x in selected],'source_numbers':numbers,'time_after_noon_minutes':times[0],'watch_gain_minutes_per_hour':str(watch_gain),'square_candidates':square_candidates,'percentage_order_count':len(orders),'final_level':27,'rotation_trials':rotation_trials,'rotation_number':n,'same_remainder_divisors':divisors,'remainder':164,'robot_tables':tables,'dice_sum_counts':dict(sorted(counts.items())),'equal_disjoint_odd_sum_pairs':equal,'century_weekdays_monday_zero':weekdays,'gregorian_cycle_days':146097,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scope':'Exact mathematical checks under explicit supplied assumptions; no automatic grade, rights, or formal assessment approval.'}
(W/'historical-batch3-math-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'source_spans_verified':18,'mathematical_tasks_verified':9,'dice_equal_pairs':equal,'watch_gain':str(watch_gain),'rotation_minimum':n,'robot_tables':tables}))
