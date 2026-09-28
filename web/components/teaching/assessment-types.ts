import { t } from './teaching-i18n';
export type FoundationFollowup={status:'offered'|'declined'|'in_progress'|'completed'|'awaiting_review';exam_id?:string;count:number;minutes:number};
export type AssessmentResult={status:string;diagnostic_only?:boolean;foundation_followup?:FoundationFollowup;percent?:number;band?:string;passed:boolean;pending?:number;threshold?:number;promotion?:{status:string;from_grade?:number;to_grade?:number;missing_core?:string[];next_course_ready?:boolean;review_required?:boolean}|null};
export type Exam={set_id:string;learner_id:string;course_version_id:string;kind:string;grade:number;deadline:number;server_now:number;minutes:number;submitted:boolean;draft:Record<string,string>;draft_revision:number;items:Array<{id:string;prompt:string;choices?:unknown;figure_url?:string;points:number}>;result:AssessmentResult|null};
export const modeNames=()=>({checkin:t('轻量回顾'),daily:t('日常测试'),unit:t('单元测试'),final:t('期末测试'),promotion:t('提前晋级'),competition:t('STEM竞赛'),foundation:t('基础补测')});
export function promotionText(result:AssessmentResult){
 const p=result.promotion;
 if(result.status!=='final')return t('评分尚待复核，不会触发晋级。');
 if(result.diagnostic_only)return t('基础补测仅用于发现知识缺口，不改变已获得的晋级。');
 if(p?.review_required)return t('原晋级依据发生变化，请家长复核学习安排。');
 if(p?.status==='promoted')return t('本学科已升至 {{grade}} 年级。',{grade:p.to_grade})+(p.next_course_ready?'':t('对应年级课程尚待发布或分配。'));
 if(p?.status==='parent_confirmation')return t('已取得晋级资格，等待家长确认。');
 if(p?.status==='coverage_required')return t('已达到分数要求，仍需补齐对应年级的基础知识考核。');
 if(p?.status==='placement_changed')return t('学习年级已变化，本次结果不会重复晋级。');
 return result.passed?t('本次测试已达标。'):t('先到 Chat 订正，再开始新的测试。');
}

export function foundationText(followup:FoundationFollowup){
 if(followup.status==='declined')return t('本轮已结束，未进行基础补测。基础掌握情况仍待验证。');
 if(followup.status==='completed')return t('基础补测已完成，讲解与补弱建议已进入 Chat。');
 if(followup.status==='awaiting_review')return t('基础补测评分待复核，不影响已获得的晋级。');
 if(followup.status==='in_progress')return t('基础补测正在进行，刷新后可继续。');
 return t('基础知识尚未补测，不等于已经掌握。');
}
