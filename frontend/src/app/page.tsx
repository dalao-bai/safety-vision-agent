"use client";

import { FormEvent, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
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
    summary?: string;
    fused_result?: {
      hazards?: Array<{ object_name: string; hazard_type?: string; visual_evidence: string; rule: string }>;
      detections?: Array<{ label: string; confidence: number; bbox: number[] }>;
      recommendations?: string[];
      summary?: string;
    };
  };
  error?: string;
};

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
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  async function uploadImage(file: File) {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${API_BASE}/api/files/images`, {
      method: "POST",
      body: form
    });
    if (!response.ok) {
      throw new Error("图片上传失败");
    }
    const payload = await response.json();
    setImagePath(payload.path);
    setMessages((items) => [...items, { role: "assistant", content: `已上传图片：${payload.filename}` }]);
  }

  async function pollTask(taskId: string) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const response = await fetch(`${API_BASE}/api/analysis/tasks/${taskId}`);
      const payload: TaskStatus = await response.json();
      setTaskStatus(payload);
      if (payload.status === "success" || payload.status === "failure" || payload.status === "failed") {
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
      if (!response.ok) {
        throw new Error("创建分析任务失败");
      }
      const analysis: AnalysisResponse = await response.json();
      setConversationId(analysis.conversation_id);
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
              </div>
            ))
          ) : (
            <div className="emptyState">暂无明确隐患结果。</div>
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
        </aside>
      </section>
    </main>
  );
}
