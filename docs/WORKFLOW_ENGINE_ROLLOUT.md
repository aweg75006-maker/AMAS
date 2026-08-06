# LangGraph 工作流引擎

## 目标

IRIS 使用 LangGraph 作为唯一工作流执行引擎。其节点共用：

- 节点实现：planner、researcher、writer、reviewer、refiner
- Node Runtime：timeout、retry、结构化日志
- Tool Runtime / Tool Registry
- Researcher Policy
- Workflow Loop Policy
- workflow trace、tool trace、error event

## 配置方式

默认并固定使用 LangGraph：

```bash
WORKFLOW_ENGINE=langgraph
```

本地临时启动示例：

```bash
cd /Users/zhang/Downloads/chrome/IRIS-main/backend
WORKFLOW_ENGINE=langgraph conda run -n iris uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

如果不设置环境变量，当前默认值也是：

```bash
WORKFLOW_ENGINE=langgraph
```

## 诊断接口

查看当前运行时：

```bash
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/workflow-runtime
```

重点字段：

```json
{
  "runtime": {
    "workflow_engine": "langgraph",
    "diagnostics": {
      "active_engine": "langgraph",
      "available_engines": ["langgraph"],
      "route_decision_trace_enabled": false,
      "tool_trace_enabled": true,
      "node_trace_enabled": true,
      "rollback_engine": null
    },
    "registered_tools": [
      {"name": "rag.retrieve"},
      {"name": "rag.relevance_grade"},
      {"name": "web.search"}
    ]
  }
}
```

## 验证命令

启动依赖：

```bash
redis-server --daemonize yes
brew services start mysql
brew services start postgresql@18
```

运行全量测试：

```bash
cd /Users/zhang/Downloads/chrome/IRIS-main/backend
conda run -n iris pytest -q
```
