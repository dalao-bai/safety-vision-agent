const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type Hazard = {
  object_id?: string;
  object_name: string;
  bbox?: number[];
  status?: string;
  hazard_type?: string | null;
  visual_evidence: string;
  rule: string;
};

export type FusedResult = {
  hazards: Hazard[];
  detections: Array<{ label: string; confidence: number; bbox: number[] }>;
  uncertain_items: Hazard[];
  uncertain_followups: Array<{
    object_name: string;
    follow_up_question: string;
    capture_suggestion: string;
  }>;
  summary: string;
  recommendations: string[];
};

export type AgentChatResponse = {
  conversation_id: string;
  answer: string;
  latest_analysis_id: string | null;
  fused_result: FusedResult | null;
  tool_calls: Array<{ tool: string; status: string; output?: unknown }>;
  artifacts: Record<string, unknown>;
  errors: Array<Record<string, unknown>>;
};

export type UploadResponse = {
  file_id: string;
  filename: string;
  path: string;
};

export async function requireOk(response: Response, fallback: string) {
  if (response.ok) return;
  let detail = fallback;
  try {
    const payload = await response.json();
    detail = typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    detail = fallback;
  }
  throw new Error(detail);
}

export async function uploadImage(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/files/images`, { method: "POST", body: form });
  await requireOk(response, "图片上传失败");
  return response.json();
}

export async function sendAgentMessage(input: {
  conversationId: string | null;
  fileId: string | null;
  message: string;
}): Promise<AgentChatResponse> {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: input.conversationId,
      file_id: input.fileId,
      message: input.message
    })
  });
  await requireOk(response, "Agent 请求失败");
  return response.json();
}

export async function createAnnotationSample(analysisId: string) {
  const response = await fetch(`${API_BASE}/api/annotations/from-analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      analysis_id: analysisId,
      reason: "model_output_needs_revision",
      note: "Agent 控制台标记进入标注反哺。"
    })
  });
  await requireOk(response, "创建标注样本失败");
  return response.json();
}

export async function createRemediation(input: { analysisId: string; conversationId: string | null; hazard: Hazard; index: number }) {
  const response = await fetch(`${API_BASE}/api/remediations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: input.conversationId,
      analysis_id: input.analysisId,
      hazard_index: input.index,
      title: `整改任务 ${input.index + 1}：${input.hazard.object_name}`,
      recommendation: input.hazard.rule || "请现场复核并补齐防护措施。",
      hazard_json: input.hazard
    })
  });
  await requireOk(response, "创建整改任务失败");
  return response.json();
}
