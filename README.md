# 🌐 AMAS (Advanced Multi-Agent System)

> **在线体验**: [https://www.iflowcc.xyz/](https://www.iflowcc.xyz/)

**AMAS** 是一个基于 **Agentic Workflow（智能体工作流）** 的自动化深度调研与报告生成系统。它摒弃了传统单向 RAG 的线性问答模式，通过构建多节点状态机，实现了从**意图识别、路径规划、动态检索、深度撰写到自我审查与局部微调**的全自动闭环。

### 演示截图

#### 1. 系统主界面
![AMAS 主界面](./docs/demo1.png)

#### 2. 报告生成效果
![AMAS 报告生成](./docs/demo2.png)

---

## ✨ 核心特性

* 🧠 **Agentic 工作流引擎** — 基于 LangGraph 的图结构状态机，支持条件分支与循环流转。内置 Router、Planner、Researcher、Writer、Reviewer、Refiner 六个异构节点协同工作。

* 🛡️ **防幻觉与动态路由** — 本地文档检索后由裁判节点实时评估相关性。无关文档自动触发**熔断机制**（纯文档模式终止并警告）或**智能降级**（混合模式自动切换全网搜索）。

* 🔄 **会话级记忆与断点续跑** — 实现单次会话级持久化，配合意图识别节点精准区分"开启新课题"与"修改现有报告"。

* ⚡ **全异步架构与流式传输** — FastAPI 全异步架构 + SSE 技术，将 Agent 内部状态流转与报告打字机效果低延迟推送到前端。

* 🎨 **现代化交互体验** — Vue 3 + Tailwind CSS 构建，含仿 iOS Siri "呼吸灯"思考动效，深度整合 KaTeX 完美渲染数学公式。

---

## 🏗️ 系统架构

```text
User Input
    ↓
Intent Router
    ├── NEW_TOPIC → Task Planner
    └── REFINE    → Content Refiner → Final Output

Task Planner → Deep Researcher → Relevance Grader
    ├── Doc Only & Not Relevant → Stop & Warn
    ├── Hybrid & Not Relevant   → Web Search → Writer
    └── Relevant                → Writer → Reviewer
        ├── FAIL → Back to Planner (Self-Correction Loop)
        └── PASS → Final Output
```

---

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| **API 框架** | Python 3.10+, FastAPI, Uvicorn |
| **Agent 架构** | LangChain, LangGraph, LangGraph Checkpoint |
| **向量检索** | ChromaDB, HuggingFace Embeddings |
| **核心 LLM** | 阿里云百炼 DashScope (Qwen-Max, DeepSeek-R1) |
| **网络搜索** | Tavily Search API |
| **前端** | Vue 3 (Composition API), Tailwind CSS, Vite |
| **内容渲染** | markdown-it, markdown-it-katex (KaTeX) |

---

## 🚀 快速开始

### 后端

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 在 backend/.env 中配置 API Keys:
# OPENAI_API_KEY=sk-...
# TAVILY_API_KEY=tvly-...

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

---

## 📂 目录结构

```
AMAS/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI 路由与 SSE 流式分发
│   │   ├── graph/        # LangGraph 核心逻辑（节点、状态机、拓扑）
│   │   ├── rag/          # 文档解析、向量化与检索引擎
│   │   └── tools/        # Tavily 搜索工具
│   ├── main.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/   # Vue 组件
│   │   ├── services/     # API 请求封装
│   │   └── App.vue       # 主页面
│   └── package.json
└── README.md
```

---

## 💡 研发心得

构建 AMAS 的过程中，最大的挑战在于**打破传统大模型黑盒调用的不可控性**。通过 LangGraph 状态机，系统获得了在执行过程中"反思"与"动态纠错"的能力；通过 SSE 流式传输实现了 Agent 内部状态的可视化。该项目是对 Agentic System 底层运行机制、异步并发控制与前后端流式交互的一次深度工程实践。
