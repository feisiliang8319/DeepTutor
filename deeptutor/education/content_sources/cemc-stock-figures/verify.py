from pathlib import Path
from fractions import Fraction
import json,hashlib
P=Path(__file__).parent/'specs'
def load(name):return json.loads((P/('stock-cemc-'+name+'-v1.json')).read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
maze=load('amazing-navigation')['grid'];cells=maze['cells'];assert len(cells)==maze['rows']==4 and all(len(r)==maze['cols']==8 for r in cells)
walk={(r,c) for r,row in enumerate(cells) for c,v in enumerate(row) if v!='grey'}
start=next((r,c) for r,c in walk if cells[r][c]=='A');end=next((r,c) for r,c in walk if cells[r][c]=='Z')
solutions=[]
def dfs(point,visited,moves):
 if point==end:
  if visited==walk:solutions.append(moves)
  return
 for label,dr,dc in [('N',-1,0),('E',0,1),('S',1,0),('W',0,-1)]:
  step=(point[0]+dr,point[1]+dc)
  if step in walk and step not in visited:dfs(step,visited|{step},moves+[label])
dfs(start,{start},[])
assert len(walk)==20 and len(solutions)==1
route='S E E N N W W N E E E E E S S E N N E'.split();assert solutions[0]==route
# Solve all available shape constraints exactly, not from the answer text.
grid=load('shape-sums')['grid'];symbols=['triangle','circle','square','hexagon'];equations=[]
for values,target in [(row,s) for row,s in zip(grid['cells'],grid['row_sums'])]+[(list(col),s) for col,s in zip(zip(*grid['cells']),grid['col_sums'])]:
 if target!='?':equations.append([Fraction(values.count(symbol)) for symbol in symbols]+[Fraction(target)])
a=[row[:] for row in equations];rank=0
for column in range(4):
 pivot=next((r for r in range(rank,len(a)) if a[r][column]),None)
 if pivot is None:continue
 a[rank],a[pivot]=a[pivot],a[rank];factor=a[rank][column];a[rank]=[v/factor for v in a[rank]]
 for r in range(len(a)):
  if r!=rank:
   factor=a[r][column];a[r]=[v-factor*w for v,w in zip(a[r],a[rank])]
 rank+=1
assert rank==4 and all(not any(r[:4]) and r[4]==0 for r in a[4:])
values=dict(zip(symbols,[r[4] for r in a[:4]]))
row_sums=[sum(values[s] for s in row) for row in grid['cells']];col_sums=[sum(values[s] for s in col) for col in zip(*grid['cells'])]
assert [row_sums[2],col_sums[1],col_sums[2]]==[13,12,22]
bars=load('test-results')['series'];assert sum(x['value'] for x in bars)==80 and max(bars,key=lambda x:x['value'])['category']=='B' and sum(x['value'] for x in bars[:6])==72
books=load('books-books-books')['rows'];scale=Fraction(28,next(x['count'] for x in books if x['label']=='Brandon'));assert scale==4 and sum(x['count'] for x in books)*scale==116
points=load('tracking-temperatures')['series'];temps=[x['value'] for x in points];jumps=[abs(b-a) for a,b in zip(temps,temps[1:])];assert max(temps)==23 and min(temps)==9 and max(jumps)==11 and jumps.index(max(jumps))==1
t=load('time-after-time')['time'];minutes=t['hour']*60+t['minute'];assert divmod(minutes+5*60+6,60)==(15,15) and divmod(minutes-(8*60+55),60)==(1,14)
proof={'method':'independent exact arithmetic, row-reduced linear system, and exhaustive grid-path search','maze':{'cells':len(walk),'solutions':len(solutions),'route':route},'shape_values':{k:str(v) for k,v in values.items()},'shape_missing_sums':[13,12,22],'bar_answers':[80,'B',72],'pictograph_answers':[4,116],'temperature_estimates':[23,9,11],'clock_answers':[306,'15:15','1:14'],'spec_hashes':{f.name:sha(f) for f in P.glob('stock-*.json')}}
expected=json.loads((Path(__file__).parent/'verification.json').read_text());assert proof==expected;print(json.dumps({'verified':6,'checks':proof},ensure_ascii=False))
