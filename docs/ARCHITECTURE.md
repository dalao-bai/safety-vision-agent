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
  └── Report Generator
```

## 第一版边界

- 支持图片级按需分析。
- 支持多轮追问和历史结果引用。
- 支持 VLM、YOLO 和规则检索工具。
- 不做 VLM 后台实时视频逐帧巡检。
- 视频分析和人员轨迹作为后续扩展。
