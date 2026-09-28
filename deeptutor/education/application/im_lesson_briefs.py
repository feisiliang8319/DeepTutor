"""Extract source-bound teaching goals from already-local IM lessons, offline."""
from __future__ import annotations
from pathlib import Path
from collections import Counter
import argparse,hashlib,json,re,sqlite3
COUNTS={1:8,2:17,3:20,4:23,5:18,6:25,7:16,8:10,9:12}
TITLES={1:'因数与倍数',2:'分数等值与比较',3:'分数运算',4:'小数与多位数',5:'倍数比较与测量',6:'多位数乘除法',7:'角与角度测量',8:'平面图形性质',9:'综合运用'}
def sha(x):return hashlib.sha256(x.encode() if isinstance(x,str) else x).hexdigest()
def extract(row,text):
 identity=re.fullmatch(r'IM:G4:U(\d+):L(\d+)',row['family'])
 if not identity:raise ValueError('Unknown lesson identity')
 unit,lesson=map(int,identity.groups())
 raw=text[row['start']:row['end']]
 if sha(raw)!=row['raw_sha256']:raise ValueError('Lesson source span changed')
 sections=list(re.finditer(r'^## Lesson (\d+) — (Preparation|Lesson Content)\s*$',raw,re.M))
 if [(int(m[1]),m[2]) for m in sections]!=[(lesson,'Preparation'),(lesson,'Lesson Content')]:raise ValueError('Expected one paired preparation/content section')
 prep=raw[sections[0].end():sections[1].start()];offset=row['start']+sections[0].end();evidence={}
 def field(name,pattern,required=True):
  hits=list(re.finditer(pattern,prep,re.S))
  if len(hits)!=1:
   if not hits and not required:return ''
   raise ValueError('Ambiguous/missing '+name+' for '+row['family'])
  m=hits[0];value=m[1].strip();a=offset+m.start(1);b=offset+m.end(1)
  evidence[name]={'start':a,'end':b,'sha256':sha(text[a:b])}
  return value
 title=field('title',r'\nLesson '+str(lesson)+r'\n([^\n]+)\n')
 purpose=field('purpose',r'\nLesson Purpose\n+(.*?)\n+Lesson Narrative\n')
 goals=field('goals',r'\nLearning Goals\n+(.*?)\n+(?:Required Materials|Required Preparation|\*\*\[Grade|CCSS Standards|Lesson Timeline)')
 if 'Teacher Facing' not in goals or 'Student Facing' not in goals:raise ValueError('Goal audience is missing')
 teacher,student=goals.split('Student Facing',1);teacher=teacher.removeprefix('Teacher Facing').strip();student=student.strip()
 materials=field('materials',r'\nRequired Materials\n+(.*?)\n+(?:Required Preparation|\*\*\[Grade)',required=False)
 standards=field('standards',r'\nCCSS Standards\n+(.*?)\n+Lesson Timeline\n')
 groups={};category=None
 for line in standards.splitlines():
  line=line.strip()
  if not line:continue
  if line in ('Building On','Addressing','Building Towards'):category=line;groups.setdefault(category,[])
  elif category and re.fullmatch(r'(?:\d\.[A-Z]+(?:\.[A-Za-z0-9]+)*|MP\d+)',line):groups[category].append(line)
  else:raise ValueError('Unparsed standard: '+line)
 if not groups:raise ValueError('Standards empty')
 gated=len(re.findall(r'\nStudent Response\s*\n+Teachers with a valid work email',raw))
 return {'record_id':row['id'],'family':row['family'],'unit':unit,'lesson':lesson,'source_grade':4,'title':title,'optional':'(optional)' in title,'purpose':purpose,'teacher_goals':teacher,'student_goal':student,'materials':materials,'standards':groups,'gated_response_sections':gated,'source_path':row['source_path'],'source_sha256':row['source_sha256'],'source_line':row['source_line'],'source_url':f'https://curriculum.illustrativemathematics.org/k5/teachers/grade-4/unit-{unit}/','evidence':evidence,'scope':'teaching_reference_not_exam','teaching_adaptation':'pending','source_rights':'CC BY 4.0 statement in retained source; logos and third-party images excluded'}

def build(snapshot,output):
 if snapshot.is_symlink():raise ValueError('Invalid snapshot')
 snapshot=snapshot.resolve()
 summary=json.loads((snapshot/'summary.json').read_text())
 if sha((snapshot/'catalog.sqlite3').read_bytes())!=summary['catalog_sha256']:raise ValueError('Catalog checksum mismatch')
 with sqlite3.connect((snapshot/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as c:rows=[json.loads(x[0]) for x in c.execute("select data_json from records where library='im-g4-full' order by rowid")]
 briefs=[];objects={}
 for row in rows:
  obj=snapshot/'objects'/(row['source_sha256']+'.md')
  if obj.is_symlink():raise ValueError('Unexpected source link')
  if row['source_sha256'] not in objects:
   blob=obj.read_bytes()
   if sha(blob)!=row['source_sha256']:raise ValueError('Source object changed')
   objects[row['source_sha256']]=blob.decode('utf-8')
  briefs.append(extract(row,objects[row['source_sha256']]))
 if dict(Counter(x['unit'] for x in briefs))!=COUNTS:raise ValueError('Incomplete unit inventory')
 for unit,count in COUNTS.items():
  if sorted(x['lesson'] for x in briefs if x['unit']==unit)!=list(range(1,count+1)):raise ValueError('Duplicate/missing lesson')
 report={'source_snapshot':summary['snapshot_id'],'source_files':len(objects),'lessons':len(briefs),'optional_lessons':sum(x['optional'] for x in briefs),'units':COUNTS,'gated_student_response_sections':sum(x['gated_response_sections'] for x in briefs),'all_source_evidence_spans_verified':True,'formal_items_created':0,'lesson_briefs':briefs}
 output.mkdir(parents=True,exist_ok=True)
 payloads={'im-stock-lesson-map-v1.json':json.dumps(report,ensure_ascii=False,indent=2)+'\n'}
 for unit in COUNTS:
  selected=[x for x in briefs if x['unit']==unit];title=TITLES[unit]
  chapter=f'# IM 四年级第{unit}单元：{title} · 课时目标索引\n\n这是现有教材的教学参考索引。按原始课时顺序整理目标与标准，保留英文原文以便回查。它不是测试题，也不代表学生已经掌握这些目标。源课时的教师答案和部分图形没有随文字文件完整收录；不能从本索引推定这些资料已齐全。\n\n'
  for x in selected:
   chapter+=f'## 第{x["lesson"]}课：{x["title"]}\n\n课时编号：{x["family"]}。'+('原书标记为选修拓展。' if x['optional'] else '')+'\n\n教学目的（原文）：'+x['purpose']+'\n\n教师目标（原文）：\n'+x['teacher_goals']+'\n\n学生目标（原文）：'+x['student_goal']+'\n\n'
   for k,label in [('Building On','源书列出的已有知识'),('Addressing','本课处理的标准'),('Building Towards','后续指向')]:
    if k in x['standards']:chapter+=label+'：'+', '.join(x['standards'][k])+'。\n\n'
   if x['materials']:chapter+='所需材料（原文）：\n'+x['materials']+'\n\n'
   chapter+=f'材料状态：本课文字中有{x["gated_response_sections"]}处学生作答参考仅显示登录提示，未取得完整教师答案；正式出题需另行补全条件、解答和审核。\n\n来源：{x["source_path"]}:{x["source_line"]}；原文 SHA256：{x["source_sha256"]}。\n\n'
  chapter+=f'## 来源与许可\nIllustrative Mathematics K–5 Math v.I (2021), Grade 4 Unit {unit}。本机存量记录的来源：{selected[0]["source_url"]}\n源文件注明 CC BY 4.0。此文由 DeepTutor 提取目标、整理顺序并添加中文说明；未使用标志、原图或取得受登录限制的教师材料，不代表获得原作者背书。源书列出的标准保持原样，不将领域/簇级标签误作已审核的细粒度知识点。\n'
  payloads[f'stock-im-g4-unit{unit}-lesson-guide-v1.md']=chapter
 for name,text in payloads.items():
  p=output/name
  if p.exists() and p.read_text()!=text:raise ValueError('Output changed; keep prior version and use a new output directory')
  p.write_text(text)
 return {k:v for k,v in report.items() if k!='lesson_briefs'}
def enrich_catalog(base: Path, lesson_map: Path, output: Path) -> dict:
    """Attach source-bound goals to existing admin records; do not approve them."""
    import shutil
    from datetime import datetime,timezone
    base=base.resolve()
    previous=json.loads((base/'summary.json').read_text())
    report=json.loads(lesson_map.read_text())
    if report['source_snapshot']!=base.name or previous['snapshot_id']!=base.name:raise ValueError('Lesson map belongs to another snapshot')
    if sha((base/'catalog.sqlite3').read_bytes())!=previous['catalog_sha256']:raise ValueError('Base catalog checksum mismatch')
    identity=sha(json.dumps({'base':base.name,'map_sha256':sha(lesson_map.read_bytes()),'parser_sha256':sha(Path(__file__).read_bytes())},sort_keys=True))
    target=output/identity
    if target.exists():raise ValueError('Snapshot already exists; inspect its receipt')
    target.mkdir(parents=True);shutil.copytree(base/'objects',target/'objects');shutil.copy2(base/'sources.json',target/'sources.json')
    by_id={b['record_id']:b for b in report['lesson_briefs']}
    if len(by_id)!=149:raise ValueError('Incomplete lesson map')
    with sqlite3.connect((base/'catalog.sqlite3').as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(target/'catalog.sqlite3') as b:
        a.backup(b)
        for record_id,brief in by_id.items():
            found=b.execute('select data_json from records where id=?',(record_id,)).fetchone()
            if not found:raise ValueError('Lesson record missing')
            row=json.loads(found[0])
            if row['source_sha256']!=brief['source_sha256'] or row['family']!=brief['family']:raise ValueError('Lesson source changed')
            source=(base/'objects'/(brief['source_sha256']+'.md')).read_bytes()
            if sha(source)!=brief['source_sha256']:raise ValueError('Source object changed')
            text=source.decode('utf-8')
            for span in brief['evidence'].values():
                if sha(text[span['start']:span['end']])!=span['sha256']:raise ValueError('Source evidence changed')
            row['metadata']={**row['metadata'],'lesson_brief':brief}
            row['lecture']='课时：'+brief['title']+'\n\n教学目的（源文）：'+brief['purpose']+'\n\n教师目标（源文）：'+brief['teacher_goals']+'\n\n学生目标（源文）：'+brief['student_goal']+'\n\n源书标准：'+json.dumps(brief['standards'],ensure_ascii=False)+f"\n\n教师作答参考未收录：{brief['gated_response_sections']}处。保持教学参考状态，未审核为正式考题。"
            b.execute('update records set data_json=? where id=?',(json.dumps(row,ensure_ascii=False),record_id))
        b.commit()
        if b.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity failure')
        changed=0
        for old,new in zip(a.execute('select data_json from records order by id'),b.execute('select data_json from records order by id'),strict=True):
            old=json.loads(old[0]);new=json.loads(new[0])
            if old==new:continue
            fields={k for k in old.keys()|new.keys() if old.get(k)!=new.get(k)}
            if old['id'] not in by_id or fields!={'metadata','lecture'}:raise ValueError('Unexpected record modification')
            changed+=1
        if changed!=149:raise ValueError('Unexpected changed count')
    result={**previous,'snapshot_id':identity,'base_snapshot_id':base.name,'created_at':datetime.now(timezone.utc).isoformat(),'catalog_sha256':sha((target/'catalog.sqlite3').read_bytes()),'committed_batches':previous['committed_batches']+1,'im_lesson_briefs':149,'im_gated_response_sections':report['gated_student_response_sections'],'im_map_sha256':sha(lesson_map.read_bytes()),'im_brief_parser_sha256':sha(Path(__file__).read_bytes()),'im_brief_note':'Original 149 lesson bodies, source identities and review states retained. Added goal/standard provenance and explicit teacher-answer gaps; not formal quiz content.'}
    (target/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (target/'im-lesson-map.json').write_bytes(lesson_map.read_bytes())
    return {k:v for k,v in result.items() if k!='source_manifest'}

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.snapshot,a.output),ensure_ascii=False,indent=2))
