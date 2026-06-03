# 架构说明

## 总体原则

本项目采用工具编排式 Agent 架构：

```text
用户多轮对话
-> Agent 理解意图
-> Agent 调用 VLM、YOLO、规则检索、报告生成等工具
-> Agent 融合证据
-> Agent 返回解释、建议和报告
```

微调 VLM 不是对话大脑，而是四口五临边视觉隐患识别工具。Agent 负责调度、记忆、追问、融合和解释。

## 模块

```text
Frontend Chat UI
  ↓
FastAPI Backend
  ↓
SafetyExpertAgent
  ├── Intent Router
  ├── Memory Manager
  ├── Tool Planner
  ├── VLM Hazard Tool
  ├── YOLO Helmet Tool
  ├── Rule Retrieval Tool
  ├── Evidence Fusion Tool
  ├── Annotation Feedback Tool
  └── Report Generator
```

## 标注反哺闭环

人工复核学习闭环独立于正常推理链路：

```text
FusedResult
-> AnnotationSample draft
-> Human review accept / revise / reject
-> accepted_records images.jsonl / objects.jsonl
-> TrainingCandidate
```

`backend/app/annotation_pipeline/` 保存了从研究项目复制来的四口五临边 API 辅助标注流水线，保留批量草标、规则匹配、复核图、浏览器审核台和 accepted_records 转换能力。Agent 当前 API 先接入“从分析结果进入标注复核”的单样本闭环，后续批量图片草标可继续复用这套代码。

## 第一版边界

- 支持图片级按需分析。
- 支持多轮追问和历史结果引用。
- 支持 VLM、YOLO 和规则检索工具。
- 支持人工复核后的训练数据候选生成。
- 不做 VLM 后台实时视频逐帧巡检。
- 视频分析和人员轨迹作为后续扩展。
