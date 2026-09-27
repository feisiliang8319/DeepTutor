
import { t, useTeachingLocale } from "@/components/teaching/teaching-i18n";
import { apiFetch, apiUrl } from "@/lib/api";
export async function teachingApi<T>(path:string,init?:RequestInit):Promise<T>{
  const response=await apiFetch(apiUrl(path),init);const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:t("请求未完成，请重试。"));
  return data as T;
}
export const jsonBody=(value:unknown):RequestInit=>({method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(value)});
export type Account={id:string;username:string;role:string;parent_id:string|null;disabled:boolean;goal?:string};
export type Access={models:Array<{profile_id:string;model_id:string;label?:string}>;knowledge_bases:string[];features:string[]};
