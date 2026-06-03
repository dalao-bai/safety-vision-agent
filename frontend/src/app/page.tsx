"use client";

import { FormEvent, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type Hazard = {
  object_id?: string;
  object_name: string;
  bbox?: number[];
  status?: string;
  hazard_type_id?: string | null;
  hazard_type?: string;
  visual_evidence: string;
  missing_evidence?: string | null;
  evidence_sufficiency?: string;
  uncertainty_reason?: string | null;
  rule: string;
};

type FollowUp = {
  object_name: string;
  uncertainty_reason: string;
  missing_evidence: string;
  follow_up_question: string;
  capture_suggestion: string;
};

type AnalysisResponse = {
  analysis_id: string;
  conversation_id: string;
  task_id: string;
  status: string;
};

type TaskStatus = {
  task_id: string;
  status: string;
  result?: {
    analysis_id?: string;
    summary?: string;
    fused_result?: {
      hazards?: Hazard[];
      uncertain_followups?: FollowUp[];
      detections?: Array<{ label: string; confidence: number; bbox: number[] }>;
      recommendations?: string[];
      summary?: string;
    };
  };
  error?: string;
};

type AnnotationObjectReview = {
  draft_object_index: number;
  decision: string;
  revised: Record<string, unknown>;
  note: string;
};

type AnnotationSample = {
  sample_id: string;
  analysis_id?: string;
  image_path: string;
  status: string;
  draft_json: {
    objects?: Array<Record<string, unknown> & { draft_object_index?: number; object_name?: string; status?: string }>;
  };
  review_json: {
    objects?: AnnotationObjectReview[];
  };
  accepted_record_json?: Record<string, unknown>;
};

async function requireOk(response: Response, fallback: string) {
  if (response.ok) return;
  let detail = fallback;
  try {
    const payload = await response.json();
    detail = payload.detail || fallback;
  } catch {
    detail = fallback;
  }
  throw new Error(detail);
}

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content: "上传施工现场图片后，我可以调用微调 VLM、YOLO 和规则检索工具进行隐患识别。"
    }
  ]);
  const [question, setQuestion] = useState("分析这张图有没有四口五临边隐患，并检查是否有人未佩戴安全帽。");
  const [imagePath, setImagePath] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [annotationSample, setAnnotationSample] = useState<AnnotationSample | null>(null);
  const [reviewObjects, setReviewObjects] = useState<AnnotationObjectReview[]>([]);
  const [isBusy, setIsBusy] = useState(false);

  async function uploadImage(file: File) {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${API_BASE}/api/files/images`, {
      method: "POST",
      body: form
    });
    await requireOk(response, "图片上传失败");
    const payload = await response.json();
    setImagePath(payload.path);
    setMessages((items) => [...items, { role: "assistant", content: `已上传图片：${payload.filename}` }]);
  }

  async function pollTask(taskId: string) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const response = await fetch(`${API_BASE}/api/analysis/tasks/${taskId}`);
      await requireOk(response, "查询任务状态失败");
      const payload: TaskStatus = await response.json();
      setTaskStatus(payload);
      if (payload.result?.analysis_id) {
        setAnalysisId(payload.result.analysis_id);
      }
      if (payload.status === "success" || payload.status === "failure" || payload.status === "failed") {
        if (payload.status === "failure" || payload.status === "failed") {
          throw new Error(payload.error || "分析任务失败");
        }
        return payload;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    throw new Error("任务等待超时");
  }

  async function submitQuestion(event: FormEvent) {
    event.preventDefault();
    if (!imagePath) {
      setMessages((items) => [...items, { role: "assistant", content: "请先上传一张图片。" }]);
      return;
    }

    setIsBusy(true);
    setMessages((items) => [...items, { role: "user", content: question }]);

    try {
      const response = await fetch(`${API_BASE}/api/analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: conversationId,
          image_path: imagePath,
          message: question
        })
      });
      await requireOk(response, "创建分析任务失败");
      const analysis: AnalysisResponse = await response.json();
      setConversationId(analysis.conversation_id);
      setAnalysisId(analysis.analysis_id);
      setTaskStatus({ task_id: analysis.task_id, status: analysis.status });

      const finished = await pollTask(analysis.task_id);
      const summary = finished.result?.summary || finished.result?.fused_result?.summary || "分析完成，但没有返回总结。";
      setMessages((items) => [...items, { role: "assistant", content: summary }]);
    } catch (error) {
      setMessages((items) => [
        ...items,
        { role: "assistant", content: error instanceof Error ? error.message : "分析失败" }
      ]);
    } finally {
      setIsBusy(false);
    }
  }

  async function createReview(index: number, decision: string) {
    if (!analysisId) return;
    try {
      const response = await fetch(`${API_BASE}/api/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          analysis_id: analysisId,
          item_type: "hazard",
          item_index: index,
          decision,
          note: decision === "accept" ? "前端确认隐患判断。" : "前端标记需要复核。"
        })
      });
      await requireOk(response, "记录人工复核失败");
      setMessages((items) => [...items, { role: "assistant", content: `已记录人工复核：${decision}` }]);
    } catch (error) {
      setMessages((items) => [
        ...items,
        { role: "assistant", content: error instanceof Error ? error.message : "人工复核失败" }
      ]);
    }
  }

  async function createAnnotationSample() {
    if (!analysisId) return;
    try {
      const response = await fetch(`${API_BASE}/api/annotations/from-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          analysis_id: analysisId,
          reason: "model_output_needs_revision",
          note: "前端标记需修正，进入标注反哺闭环。"
        })
      });
      await requireOk(response, "创建标注复核样本失败");
      const payload: AnnotationSample = await response.json();
      setAnnotationSample(payload);
      setReviewObjects(payload.review_json.objects || []);
      setMessages((items) => [...items, { role: "assistant", content: `已创建标注复核样本：${payload.sample_id}` }]);
    } catch (error) {
      setMessages((items) => [
        ...items,
        { role: "assistant", content: error instanceof Error ? error.message : "标注样本创建失败" }
      ]);
    }
  }

  async function saveAnnotationReview() {
    if (!annotationSample) return;
    try {
      const response = await fetch(`${API_BASE}/api/annotations/samples/${annotationSample.sample_id}/review`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_decision: "accept",
          review_status: "reviewed",
          objects: reviewObjects,
          note: "前端人工复核保存。"
        })
      });
      await requireOk(response, "保存标注复核失败");
      const payload: AnnotationSample = await response.json();
      setAnnotationSample(payload);
      setReviewObjects(payload.review_json.objects || []);
      setMessages((items) => [...items, { role: "assistant", content: "标注复核已保存。" }]);
    } catch (error) {
      setMessages((items) => [
        ...items,
        { role: "assistant", content: error instanceof Error ? error.message : "标注复核保存失败" }
      ]);
    }
  }

  async function commitAnnotationSample() {
    if (!annotationSample) return;
    try {
      const response = await fetch(`${API_BASE}/api/annotations/samples/${annotationSample.sample_id}/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_type: "sft", append_to_db: false })
      });
      await requireOk(response, "生成训练候选失败");
      const payload = await response.json();
      setMessages((items) => [
        ...items,
        { role: "assistant", content: `已生成训练候选：${payload.accepted_objects} 条对象记录。` }
      ]);
    } catch (error) {
      setMessages((items) => [
        ...items,
        { role: "assistant", content: error instanceof Error ? error.message : "生成训练候选失败" }
      ]);
    }
  }

  function updateReviewDecision(index: number, decision: string) {
    setReviewObjects((items) =>
      items.map((item, itemIndex) => (itemIndex === index ? { ...item, decision } : item))
    );
  }

  function updateReviewJson(index: number, value: string) {
    setReviewObjects((items) =>
      items.map((item, itemIndex) => {
        if (itemIndex !== index) return item;
        try {
          return { ...item, revised: JSON.parse(value) };
        } catch {
          return item;
        }
      })
    );
  }

  async function createRemediation(index: number, hazard: Hazard) {
    if (!analysisId) return;
    const title = `整改任务 ${index + 1}：${hazard.object_name}`;
    const recommendation = hazard.rule
      ? `请按规则依据落实整改：${hazard.rule}`
      : "请现场复核并补齐对应防护措施。";
    try {
      const response = await fetch(`${API_BASE}/api/remediations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: conversationId,
          analysis_id: analysisId,
          hazard_index: index,
          title,
          recommendation,
          hazard_json: hazard
        })
      });
      await requireOk(response, "创建整改任务失败");
      setMessages((items) => [...items, { role: "assistant", content: `已创建整改任务：${title}` }]);
    } catch (error) {
      setMessages((items) => [
        ...items,
        { role: "assistant", content: error instanceof Error ? error.message : "整改任务创建失败" }
      ]);
    }
  }

  const fused = taskStatus?.result?.fused_result;

  return (
    <main className="shell">
      <section className="workspace">
        <aside className="sidebar">
          <h1>Safety Vision Agent</h1>
          <p>多轮对话式施工安全隐患识别专家</p>
          <label className="uploadBox">
            <span>上传施工现场图片</span>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadImage(file);
              }}
            />
          </label>
          {imagePath ? <div className="pathText">{imagePath}</div> : null}
        </aside>

        <section className="chatPanel">
          <div className="messages">
            {messages.map((message, index) => (
              <div className={`message ${message.role}`} key={`${message.role}-${index}`}>
                {message.content}
              </div>
            ))}
          </div>

          <form className="composer" onSubmit={submitQuestion}>
            <input value={question} onChange={(event) => setQuestion(event.target.value)} />
            <button type="submit" disabled={isBusy}>{isBusy ? "分析中" : "发送"}</button>
          </form>
        </section>

        <aside className="resultPanel">
          <h2>分析结果</h2>
          <div className="statusBox">任务状态：{taskStatus?.status || "等待任务"}</div>

          <h3>明确隐患</h3>
          {fused?.hazards?.length ? (
            fused.hazards.map((item, index) => (
              <div className="resultCard" key={`${item.object_name}-${index}`}>
                <strong>{item.object_name}</strong>
                <p>{item.hazard_type || "隐患"}</p>
                <p>{item.visual_evidence}</p>
                <small>{item.rule}</small>
                <div className="actions">
                  <button type="button" onClick={() => void createReview(index, "accept")}>确认</button>
                  <button type="button" onClick={() => void createReview(index, "revise")}>需修正</button>
                  <button type="button" onClick={() => void createRemediation(index, item)}>生成整改</button>
                </div>
              </div>
            ))
          ) : (
            <div className="emptyState">暂无明确隐患结果。</div>
          )}

          <h3>证据不足追问</h3>
          {fused?.uncertain_followups?.length ? (
            fused.uncertain_followups.map((item, index) => (
              <div className="resultCard" key={`${item.object_name}-${index}`}>
                <strong>{item.object_name}</strong>
                <p>{item.follow_up_question}</p>
                <small>{item.capture_suggestion}</small>
              </div>
            ))
          ) : (
            <div className="emptyState">暂无证据不足追问。</div>
          )}

          <h3>检测结果</h3>
          {fused?.detections?.length ? (
            fused.detections.map((item, index) => (
              <div className="resultCard" key={`${item.label}-${index}`}>
                <strong>{item.label}</strong>
                <p>置信度：{item.confidence.toFixed(2)}</p>
              </div>
            ))
          ) : (
            <div className="emptyState">暂无 YOLO 检测结果。</div>
          )}

          <h3>标注反哺</h3>
          <div className="resultCard">
            <p>将需修正的模型输出转成标注复核样本，人工确认后生成训练候选数据。</p>
            <div className="actions">
              <button type="button" disabled={!analysisId} onClick={() => void createAnnotationSample()}>进入标注复核</button>
              <button type="button" disabled={!annotationSample} onClick={() => void saveAnnotationReview()}>保存复核</button>
              <button type="button" disabled={!annotationSample} onClick={() => void commitAnnotationSample()}>生成训练样本</button>
            </div>
            {annotationSample ? (
              <small>样本：{annotationSample.sample_id}，状态：{annotationSample.status}</small>
            ) : null}
          </div>

          {reviewObjects.length ? (
            reviewObjects.map((item, index) => (
              <div className="resultCard annotationCard" key={`annotation-${item.draft_object_index}`}>
                <strong>复核对象 {item.draft_object_index}</strong>
                <select value={item.decision} onChange={(event) => updateReviewDecision(index, event.target.value)}>
                  <option value="pending">待定</option>
                  <option value="accept">通过</option>
                  <option value="revise">修正</option>
                  <option value="reject">驳回</option>
                </select>
                <textarea
                  value={JSON.stringify(item.revised, null, 2)}
                  onChange={(event) => updateReviewJson(index, event.target.value)}
                />
              </div>
            ))
          ) : null}
        </aside>
      </section>
    </main>
  );
}
