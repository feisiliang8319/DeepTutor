"use client";
import { useEffect, useRef, useState } from "react";
import { education } from "./education-api";
import { t } from "./teaching-i18n";

type Library={library:string;total:number;states:Record<string,number>};
type Summary={available:boolean;records:number;source_files:number;committed_batches:number;duplicate_records:number;unique_im_lessons:number;created_at:string;libraries:Library[]};
type RecordRow={id:string;title:string;preview:string;source_path:string;source_line:number;state:string;issues:string[];source_grade:string;source_difficulty:string};
type Detail=RecordRow & {prompt:string;answer:string;explanation:string;lecture:string;options:string[];source_sha256:string;metadata:Record<string,unknown>};
const labels:Record<string,string>={needs_repair:"待补全或修复",needs_curriculum_review:"待课程与教学审核",needs_fact_check:"待事实核对",reference_only:"教材与参考素材",duplicate:"重复来源已关联"};
const issues:Record<string,string>={missing_figure:"原图缺失",unrendered_diagram:"图形待转换",missing_answer:"答案待核对",missing_explanation:"讲解待补全",answer_conflict:"答案文本不一致",multiple_boxed_answers:"多个结论待整理",historical_fact_check:"史实需交叉核对",historical_context_required:"保留历史语境",ocr_review:"文字识别待复核",lesson_requires_teaching_adaptation:"课堂材料需改编",teacher_material_not_bundled:"部分教师材料未收录",existing_teaching_chapter:"已有教学讲义",answer_not_in_options:"答案与选项不匹配",malformed_boxed_answer:"答案格式待修复",missing_options:"选项缺失",ambiguous_options:"选项重复"};
const control="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-sm disabled:opacity-50";
export default function StockProcessingPanel(){
 const detailRef=useRef<HTMLDivElement>(null);
 const [data,setData]=useState<Summary|null>(null),[error,setError]=useState(""),[open,setOpen]=useState(false);
 const [library,setLibrary]=useState(""),[status,setStatus]=useState("needs_repair"),[page,setPage]=useState(0);
 const [rows,setRows]=useState<RecordRow[]>([]),[total,setTotal]=useState(0),[loading,setLoading]=useState(false),[detail,setDetail]=useState<Detail|null>(null),[detailLoading,setDetailLoading]=useState(false);
 useEffect(()=>{let cancelled=false;education<Summary>("content-admin/stock").then(v=>{if(!cancelled)setData(v);}).catch(e=>{if(!cancelled)setError(e.message);});return()=>{cancelled=true;};},[]);
 useEffect(()=>{if(!open)return;let cancelled=false;setLoading(true);setError("");setRows([]);setTotal(0);setDetail(null);setDetailLoading(false);
  education<{items:RecordRow[];total:number}>(`content-admin/stock/records?library=${encodeURIComponent(library)}&status=${status}&page=${page}`).then(v=>{if(!cancelled){setRows(v.items);setTotal(v.total);}}).catch(e=>{if(!cancelled)setError(e.message);}).finally(()=>{if(!cancelled)setLoading(false);});return()=>{cancelled=true;};
 },[open,library,status,page]);
 // Detail is fetched within the selected record's own effect so a late response
 // can never replace a newer selection or a changed filter.
 const [selection,setSelection]=useState("");
 useEffect(()=>{setSelection("");},[library,status,page]);
 useEffect(()=>{if(!selection){setDetail(null);return;}let cancelled=false;setDetailLoading(true);setError("");
  education<Detail>(`content-admin/stock/records/${selection}`).then(v=>{if(!cancelled)setDetail(v);}).catch(e=>{if(!cancelled)setError(e.message);}).finally(()=>{if(!cancelled)setDetailLoading(false);});return()=>{cancelled=true;};
 },[selection]);
 useEffect(()=>{if(detail&&!detailLoading){detailRef.current?.focus({preventScroll:true});detailRef.current?.scrollIntoView({block:"nearest"});}},[detail,detailLoading]);
 if(!data&&!error)return <p role="status" className="text-sm">{t("正在读取存量加工结果…")}</p>;
 if(data&&!data.available)return <p className="text-sm text-[var(--muted-foreground)]">{t("尚无存量加工批次。")}</p>;
 return <section className="border-b border-[var(--border)] pb-7">
  <h2 className="text-xl font-semibold">{t("现有资料加工")}</h2>
  <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--muted-foreground)]">{t("先整理已有资料，再补充新来源。这里展示逐条拆解、去重和完整性检查的结果；通过结构检查仍需教学审核，不能直接用于正式测试。")}</p>
  {error&&<p role="alert" className="mt-4 text-sm">{error}</p>}
  {data&&<><div className="my-5 flex flex-wrap gap-x-8 gap-y-3 text-sm">
   {[[data.source_files,"份原始文件"],[data.records,"条资料记录"],[data.committed_batches,"批已处理"],[data.duplicate_records,"条重复来源"]].map(([value,label])=><p key={label}><strong className="mr-2 text-xl tabular-nums">{Number(value).toLocaleString()}</strong>{t(String(label))}</p>)}
  </div><p className="mb-5 text-xs leading-6 text-[var(--muted-foreground)]">{t("记录包含题目、教材课时和文献片段，不能合计为试题数量。IM教材共{{count}}个独立课时，单元一的另一份版本保留来源关联。",{count:data.unique_im_lessons})}</p>
  <button className={control} aria-expanded={open} onClick={()=>setOpen(v=>!v)}>{t(open?"收起加工清单":"查看加工清单")}</button>
  {open&&<div className="mt-5 space-y-5"><div className="grid gap-4 sm:grid-cols-2">
   <label className="min-w-0 text-sm">{t("资料来源")}<select className={`${control} mt-2 w-full`} value={library} onChange={e=>{setLibrary(e.target.value);setPage(0);}}><option value="">{t("全部现有资料")}</option>{data.libraries.map(x=><option key={x.library} value={x.library}>{x.library} · {x.total.toLocaleString()}</option>)}</select></label>
   <label className="min-w-0 text-sm">{t("加工状态")}<select className={`${control} mt-2 w-full`} value={status} onChange={e=>{setStatus(e.target.value);setPage(0);}}><option value="">{t("全部状态")}</option>{Object.entries(labels).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}</select></label>
  </div><p role="status" className="text-sm text-[var(--muted-foreground)]">{loading?t("正在读取存量加工结果…"):t("共{{count}}条记录",{count:total})}</p>
  {!loading&&<div className="divide-y divide-[var(--border)]">{rows.map(row=><article key={row.id} className="py-4"><button className="w-full text-left text-sm font-medium leading-7 underline decoration-[var(--border)] underline-offset-4" onClick={()=>{setDetail(null);setSelection(selection===row.id?"":row.id);}}>{row.title}</button><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[var(--muted-foreground)]">{row.preview}</p><p className="mt-2 break-words text-xs leading-6">{t(labels[row.state]||row.state)}{row.issues.length>0&&" · "+row.issues.map(v=>t(issues[v]||v)).join(" · ")}</p></article>)}</div>}
  <div className="flex flex-wrap items-center gap-3"><button className={control} disabled={loading||page===0} onClick={()=>setPage(v=>v-1)}>{t("上一页")}</button><span className="text-sm">{page+1} / {Math.max(1,Math.ceil(total/20))}</span><button className={control} disabled={loading||(page+1)*20>=total} onClick={()=>setPage(v=>v+1)}>{t("下一页")}</button></div>
  {detailLoading&&<p role="status">{t("正在读取存量加工结果…")}</p>}
  {detail&&!detailLoading&&<div ref={detailRef} tabIndex={-1} className="rounded-2xl bg-[var(--secondary)] p-5"><div className="flex justify-between gap-4"><h3 className="font-semibold">{t("原始记录与提取结果")}</h3><button className={control} onClick={()=>setSelection("")}>{t("关闭")}</button></div><dl className="mt-4 space-y-4 text-sm leading-7">{[["题目或原文",detail.prompt],["选项",detail.options.join("\n")],["参考答案",detail.answer],["解题讲解",detail.explanation],["知识背景",detail.lecture],["来源定位",`${detail.source_path}:${detail.source_line}`]].map(([label,value])=><div key={label}><dt className="font-medium">{t(label)}</dt><dd className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words">{value||t("尚未补齐")}</dd></div>)}</dl><p className="mt-4 text-xs">{t("原始年级和难度仅为来源标签，不代表学生定级或审核通过。")}</p></div>}
  </div>}</>}
 </section>;
}
