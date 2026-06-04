import { FormEvent, useMemo, useState } from "react";

import {
  AgentChatResponse,
  ChatMessage,
  FusedResult,
  createAnnotationSample,
  createRemediation,
  sendAgentMessage,
  uploadImage
} from "./api";

function ResultPanel({ result, analysisId, conversationId, onNotice }: {
  result: FusedResult | null;
  analysisId: string | null;
  conversationId: string | null;
  onNotice: (message: string) => void;
}) {
  async function handleAnnotation() {
    if (!analysisId) return;
    const sample = await createAnnotationSample(analysisId);
    onNotice(`已创建标注样本：${sample.sample_id}`);
  }

  async function handleRemediation(index: number) {
    if (!analysisId || !result) return;
    const task = await createRemediation({ analysisId, conversationId, hazard: result.hazards[index], index });
    onNotice(`已创建整改任务：${task.task_id}`);
  }

  if (!result) {
    return <div className="emptyState">暂无结构化结果</div>;
  }

  return (
    <div className="resultStack">
      <section>
        <h2>结构化结果</h2>
        <p>{result.summary}</p>
      </section>
      <section>
        <h3>明确隐患</h3>
        {result.hazards.length === 0 ? <p className="muted">暂无明确隐患</p> : result.hazards.map((hazard, index) => (
          <article className="resultItem" key={`${hazard.object_name}-${index}`}>
            <strong>{index + 1}. {hazard.object_name}</strong>
            <span>{hazard.hazard_type || hazard.status}</span>
            <p>{hazard.visual_evidence}</p>
            <small>{hazard.rule}</small>
            <button type="button" onClick={() => handleRemediation(index)} disabled={!analysisId}>创建整改</button>
          </article>
        ))}
      </section>
      <section>
        <h3>补证建议</h3>
        {result.uncertain_followups.length === 0 ? <p className="muted">暂无补证项</p> : result.uncertain_followups.map((item, index) => (
          <article className="resultItem" key={`${item.object_name}-${index}`}>
            <strong>{item.object_name}</strong>
            <p>{item.follow_up_question}</p>
            <small>{item.capture_suggestion}</small>
          </article>
        ))}
      </section>
      <button className="secondaryButton" type="button" onClick={handleAnnotation} disabled={!analysisId}>生成标注样本</button>
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "上传图片后，可以直接多轮追问隐患、依据、整改和报告。" }
  ]);
  const [question, setQuestion] = useState("分析这张图有没有施工安全隐患。");
  const [fileId, setFileId] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [latestResult, setLatestResult] = useState<FusedResult | null>(null);
  const [toolCalls, setToolCalls] = useState<AgentChatResponse["tool_calls"]>([]);
  const [busy, setBusy] = useState(false);

  const canSubmit = useMemo(() => question.trim().length > 0 && !busy, [busy, question]);

  function append(role: ChatMessage["role"], content: string) {
    setMessages((items) => [...items, { role, content }]);
  }

  async function handleUpload(file: File | null) {
    if (!file) return;
    setBusy(true);
    try {
      const payload = await uploadImage(file);
      setFileId(payload.file_id);
      setFileName(payload.filename);
      append("assistant", `已上传：${payload.filename}`);
    } catch (error) {
      append("assistant", error instanceof Error ? error.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    const message = question.trim();
    append("user", message);
    setBusy(true);
    try {
      const response = await sendAgentMessage({ conversationId, fileId, message });
      setConversationId(response.conversation_id);
      setAnalysisId(response.latest_analysis_id);
      setLatestResult(response.fused_result);
      setToolCalls(response.tool_calls);
      append("assistant", response.answer);
    } catch (error) {
      append("assistant", error instanceof Error ? error.message : "Agent 请求失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <aside className="leftPane">
        <h1>Safety Vision Agent</h1>
        <label className="uploadBox">
          <span>上传现场图片</span>
          <input aria-label="上传现场图片" type="file" accept="image/*" onChange={(event) => handleUpload(event.target.files?.[0] ?? null)} />
        </label>
        <dl className="metaList">
          <dt>图片</dt>
          <dd>{fileName || "未上传"}</dd>
          <dt>会话</dt>
          <dd>{conversationId || "未开始"}</dd>
          <dt>分析</dt>
          <dd>{analysisId || "暂无"}</dd>
        </dl>
      </aside>

      <section className="chatPane">
        <div className="messages" aria-live="polite">
          {messages.map((message, index) => (
            <div className={`message ${message.role}`} key={`${message.role}-${index}`}>{message.content}</div>
          ))}
        </div>
        <form className="composer" onSubmit={submit}>
          <input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="输入追问、整改或报告请求" />
          <button type="submit" disabled={!canSubmit}>{busy ? "处理中" : "发送"}</button>
        </form>
      </section>

      <aside className="rightPane">
        <ResultPanel result={latestResult} analysisId={analysisId} conversationId={conversationId} onNotice={(message) => append("assistant", message)} />
        <section className="toolBox">
          <h3>工具调用</h3>
          {toolCalls.length === 0 ? <p className="muted">暂无调用</p> : toolCalls.map((call, index) => (
            <div className="toolCall" key={`${call.tool}-${index}`}>
              <span>{call.tool}</span>
              <strong>{call.status}</strong>
            </div>
          ))}
        </section>
      </aside>
    </main>
  );
}
