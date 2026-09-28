const endpoint = "/api/v1/teaching/intelligence";
const errorText: Record<string, string> = {
  source_not_allowed: "此来源不在获准的主库文件范围内。",
  too_many_documents: "此库文件过多，请先按课程整理资料。",
  material_too_large: "文件超过20 MB，请先拆分资料。",
  text_unavailable: "未能提取文字，请先完成 OCR 或导入文本版本。",
  possible_personal_data: "片段含疑似个人信息或密钥，已阻止外发。",
  review_not_found: "未找到这条资料建议记录。",
  export_confirmation_required: "请先确认所示片段可外发且不含个人信息。",
  preview_expired: "预览已过期或已处理，请重新预览。",
  material_changed: "资料已更新，请重新预览并确认新片段。",

  invalid_key: "密钥无效，请检查后重新保存。",
  not_configured: "请先保存 Jev 专用 API Key。",
  rate_limited: "服务繁忙或调用受限，请稍后重试。",
  timeout: "连接超时，请稍后重试。",
  provider_unavailable: "暂时无法连接 TypeSafe，请稍后重试。",
  invalid_response: "服务返回格式异常，连接测试未通过。",
  test_inconclusive: "已收到回复，但样例判断未通过，请稍后重试。",
  configuration_changed: "密钥已变更，请重新测试。",
  invalid_request: "提交格式有误，请检查密钥。",
};
export async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(endpoint + path, {
    method, credentials: "same-origin", cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(response.status === 401 || response.status === 403
    ? "请以管理员身份重新登录。"
    : errorText[data?.detail?.code] || "操作未完成，请稍后重试。");
  return data as T;
}
