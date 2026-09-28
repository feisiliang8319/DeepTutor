from collections import deque,Counter
from fractions import Fraction
from functools import lru_cache
from itertools import combinations,permutations,product
from pathlib import Path
import json,math,hashlib,sys
W=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent
sources=json.loads((W/'public-domain-processed/public-domain-records.json').read_text())
# Source identities/spans reproduced from local immutable editions.
selected=[63,263,264,267,285,362,364,391,519,529]
for index in selected:
 r=sources[index];data=(W/r['source_path']).read_bytes();assert hashlib.sha256(data).hexdigest()==r['source_sha256']
 text=data.decode().replace('\r\n','\n')
 for span in r['metadata']['spans']:assert hashlib.sha256(text[span['start']:span['end']].encode()).hexdigest()==span['sha256']
# Exact clock rates: after t minutes, all displayed counts divisible by720.
clock=[]
for half_days in range(1,1441):
 t=720*half_days
 if Fraction(t*1441,1440)%720==0 and Fraction(t*1439,1440)%720==0:clock.append(half_days)
assert clock[0]==1440
# 12-person one-factorization generated afresh by rotating 11 places.
a=list(range(12));days=[]
for _ in range(11):
 days.append([(a[i],a[-1-i]) for i in range(6)]);a=[a[0],a[-1],*a[1:-1]]
pairs=[tuple(sorted(x)) for day in days for x in day]
assert len(set(pairs))==math.comb(12,2)==66
assert all(sorted(x for pair in day for x in pair)==list(range(12)) for day in days)
# Source mixed doubles schedule: validate all partners once and opponents twice.
letters='ABCDEFGHIJKL';base=[('AB','IL'),('EJ','GK'),('FH','CD')]
rotate=lambda s,k:''.join('A' if c=='A' else letters[1+(letters.index(c)-1+k)%11] for c in s)
schedule=[[(rotate(a,k),rotate(b,k)) for a,b in base] for k in range(11)]
partners=Counter();opponents=Counter()
for day in schedule:
 assert sorted(''.join(a+b for a,b in day))==list(letters)
 for aa,bb in day:
  partners[tuple(sorted(aa))]+=1;partners[tuple(sorted(bb))]+=1
  for a,b in product(aa,bb):opponents[tuple(sorted((a,b)))]+=1
assert set(partners.values())=={1} and len(partners)==66
assert set(opponents.values())=={2} and len(opponents)==66
# Four-bell sequence: permutations, adjacent-position movement and circular end runs.
bells=[tuple(map(int,line.split())) for line in sources[267]['explanation'].splitlines() if len(line.split())==4 and all(x.isdigit() for x in line.split())]
assert len(bells)==len(set(bells))==24
for i,now in enumerate(bells):
 nxt=bells[(i+1)%24];third=bells[(i+2)%24]
 assert all(abs(now.index(b)-nxt.index(b))<=1 for b in (1,2,3,4))
 assert now[0]!=nxt[0] or nxt[0]!=third[0]
 assert now[-1]!=nxt[-1] or nxt[-1]!=third[-1]
# Cube rotations: all signed permutation matrices with determinant +1.
axes=[(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]
rots=[]
for perm in permutations(range(3)):
 sign=(-1)**sum(perm[i]>perm[j] for i in range(3) for j in range(i+1,3))
 for signs in product((-1,1),repeat=3):
  if sign*math.prod(signs)!=1:continue
  rots.append(tuple(axes.index(tuple(signs[i]*v[perm[i]] for i in range(3))) for v in axes))
assert len(set(rots))==24
labelings=[x for x in permutations(range(1,7)) if all(x[i]+x[i+1]==7 for i in (0,2,4))]
canonical=lambda x:min(tuple(x[r[i]] for i in range(6)) for r in rots)
assert len(labelings)==48 and len({canonical(x) for x in labelings})==2
# Ideal equal-volume transfer, explicit ideal-mixture assumptions.
V=Fraction(1000);q=Fraction(25)
blue_in_first=q*V/(V+q);red_in_second=q-q*q/(V+q)
assert blue_in_first==red_in_second and (V-blue_in_first)/blue_in_first==40
# Jug puzzle: each pour stops when source empties or recipient fills; BFS proves minimum.
capacities=(10,10,5,4);start=(10,10,0,0);seen={start:None};queue=deque([start]);target=None
while queue:
 state=queue.popleft()
 if state[2:]==(3,3):target=state;break
 for i,j in permutations(range(4),2):
  amount=min(state[i],capacities[j]-state[j])
  if not amount:continue
  nxt=list(state);nxt[i]-=amount;nxt[j]+=amount;nxt=tuple(nxt)
  if nxt not in seen:seen[nxt]=state;queue.append(nxt)
assert target is not None
path=[]
while target is not None:path.append(target);target=seen[target]
path.reverse();assert len(path)-1==11
# Pebble parity game: state includes player-to-move and first player's collected parity.
@lru_cache(None)
def first_wins(remaining,turn,parity):
 if remaining==0:return parity==1
 results=[first_wins(remaining-t,1-turn,parity^(t%2) if turn==0 else parity) for t in range(1,min(3,remaining)+1)]
 return any(results) if turn==0 else all(results)
winning_first_moves=[t for t in (1,2,3) if first_wins(15-t,1,t%2)]
assert winning_first_moves==[2] and not first_wins(13,0,0)
# Seven people: all15 unordered neighbor pairs for each person.
seatings=[line.split() for line in sources[519]['explanation'].splitlines() if len(line.split())==7 and sorted(line.split())==list('ABCDEFG')]
neighbors={c:[] for c in 'ABCDEFG'}
for seating in seatings:
 for i,c in enumerate(seating):neighbors[c].append(tuple(sorted((seating[i-1],seating[(i+1)%7]))))
assert len(seatings)==15 and all(len(set(v))==15 for v in neighbors.values())
# Thirteen people: six disjoint Hamiltonian cycles from nonzero differences modulo prime13.
rings=[[i*step%13 for i in range(13)] for step in range(1,7)]
edges=[tuple(sorted((ring[i],ring[(i+1)%13]))) for ring in rings for i in range(13)]
assert all(len(set(x))==13 for x in rings) and len(edges)==len(set(edges))==78
proof={'source_records':[sources[i]['id'] for i in selected],'clock_days':720,'pairing_days':days,'team_schedule':schedule,'bell_sequence':bells,'fixed_cube_labelings':48,'rotation_classes':2,'ideal_mixture_ratio':'40:1','jug_minimum_pours':11,'jug_path':path,'pebble_15_first_moves':winning_first_moves,'pebble_13_first_player_wins':False,'seven_person_seatings':seatings,'thirteen_person_rings':rings,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scope':'Independent mathematical verification of selected models and constructions; no full-source, grade, or rights approval.'}
(W/'historical-batch2-math-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in proof.items() if k not in ('pairing_days','team_schedule','bell_sequence','jug_path','seven_person_seatings','thirteen_person_rings','source_records')}))
