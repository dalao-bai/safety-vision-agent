import { useState, useRef } from "react";
import type { FormEvent } from "react";
import { sendChat, ApiError } from "./api";
import type { AnalysisResult, ChatResponse, ToolCallSummary } from "./types";

interface TranscriptEntry {
  role: "user" | "assistant";
  content: string;
}

const RISK_LABEL: Record<string, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
};

export default function App() {
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [message, setMessage] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [toolCalls, setToolCalls] = useState<ToolCallSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canSubmit = message.trim().length > 0 && !loading;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    const sentMessage = message.trim();
    setTranscript((t) => [...t, { role: "user", content: sentMessage }]);
    setMessage("");
    setError(null);
    setLoading(true);

    try {
      const resp: ChatResponse = await sendChat({
        message: sentMessage,
        conversationId,
        image,
      });
      setConversationId(resp.conversation_id);
      setTranscript((t) => [...t, { role: "assistant", content: resp.answer }]);
      if (resp.analysis) setAnalysis(resp.analysis);
      setToolCalls(resp.tool_calls ?? []);
      // Image is consumed by the first turn; clear it for follow-ups.
      setImage(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "网络错误,请重试。";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>工地安全隐患识别 Agent</h1>
        <p className="subtitle">上传施工现场照片,识别安全隐患并追问依据、排序与整改建议。</p>
      </header>

      <main className="layout">
        <section className="conversation" aria-label="对话">
          <div className="transcript">
            {transcript.length === 0 && (
              <p className="empty-hint">上传一张施工现场照片并提问开始。</p>
            )}
            {transcript.map((entry, i) => (
              <div key={i} className={`bubble ${entry.role}`}>
                <span className="role-tag">{entry.role === "user" ? "你" : "助手"}</span>
                <div className="bubble-content">{entry.content}</div>
              </div>
            ))}
            {loading && <div className="bubble assistant loading">分析中…</div>}
          </div>

          {error && (
            <div className="error-banner" role="alert">
              {error}
            </div>
          )}

          <form className="composer" onSubmit={handleSubmit}>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              aria-label="选择施工现场照片"
              onChange={(e) => setImage(e.target.files?.[0] ?? null)}
            />
            <textarea
              value={message}
              placeholder="例如:请识别这张图的安全隐患"
              aria-label="消息输入"
              onChange={(e) => setMessage(e.target.value)}
              rows={2}
            />
            <button type="submit" disabled={!canSubmit}>
              {loading ? "发送中…" : "发送"}
            </button>
          </form>
        </section>

        <aside className="analysis-panel" aria-label="分析结果">
          <h2>最新分析</h2>
          {!analysis && <p className="empty-hint">尚无分析结果。</p>}
          {analysis && (
            <>
              <p className="summary">{analysis.summary}</p>
              {analysis.needs_followup && analysis.followup_question && (
                <p className="followup">需要补充:{analysis.followup_question}</p>
              )}
              <ul className="hazard-list">
                {analysis.hazards.map((h, i) => (
                  <li key={i} className={`hazard risk-${h.risk_level}`}>
                    <div className="hazard-head">
                      <span className="hazard-name">{h.name}</span>
                      <span className="risk-badge">{RISK_LABEL[h.risk_level] ?? h.risk_level}</span>
                    </div>
                    <div className="hazard-loc">位置:{h.location}</div>
                    <div className="hazard-basis">依据:{h.basis}</div>
                    <div className="hazard-fix">整改:{h.remediation}</div>
                    <div className="hazard-conf">置信度:{(h.confidence * 100).toFixed(0)}%</div>
                  </li>
                ))}
              </ul>
            </>
          )}

          {toolCalls.length > 0 && (
            <details className="tool-debug">
              <summary>工具调用 ({toolCalls.length})</summary>
              <ul>
                {toolCalls.map((tc, i) => (
                  <li key={i}>
                    {tc.tool_name} — {tc.status}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </aside>
      </main>
    </div>
  );
}
