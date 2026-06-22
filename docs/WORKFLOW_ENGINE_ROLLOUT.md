# Workflow Engine 灰度切换指南

## 目标

IRIS 当前支持两套工作流执行引擎：

- `python`：默认引擎，纯 Python Harness/Loop Engine
- `langgraph`：保留为回滚引擎

两套引擎共用：

- 节点实现：planner、researcher、writer、reviewer、refiner
- Node Runtime：timeout、retry、结构化日志
- Tool Runtime / Tool Registry
- Researcher Policy
- Workflow Loop Policy
- workflow trace、tool trace、error event

## 配置方式

默认使用纯 Python 引擎：

```bash
WORKFLOW_ENGINE=python
```

回滚到 LangGraph：

```bash
WORKFLOW_ENGINE=langgraph
```

本地临时启动示例：

```bash
cd /Users/zhang/Downloads/chrome/IRIS-main/backend
WORKFLOW_ENGINE=python conda run -n iris uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

如果不设置环境变量，当前默认值也是：

```bash
WORKFLOW_ENGINE=python
```

## 灰度建议

推荐顺序：

1. 默认使用 `WORKFLOW_ENGINE=python` 跑后端测试
2. 测试环境保持 `python`
3. 验证 `/api/chat` SSE 输出、chat history、tool runs、route decisions
4. 小流量环境保持 `python`
5. 稳定后移除 LangGraph 依赖和 checkpoint 代码

回滚默认值：

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
    "workflow_engine": "python",
    "diagnostics": {
      "active_engine": "python",
      "available_engines": ["langgraph", "python"],
      "route_decision_trace_enabled": true,
      "tool_trace_enabled": true,
      "node_trace_enabled": true,
      "rollback_engine": "langgraph",
      "python_engine_ready": true
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

只验证双引擎对齐：

```bash
cd /Users/zhang/Downloads/chrome/IRIS-main/backend
conda run -n iris pytest -q tests/test_workflow_engine_parity.py
```

只验证 Python Engine：

```bash
cd /Users/zhang/Downloads/chrome/IRIS-main/backend
conda run -n iris pytest -q tests/test_python_workflow_engine.py tests/test_chat_workflow_engine_switch.py
```

## 当前差异

`python` 引擎额外支持完整 route decision trace：

```text
__start__ -> planner/refiner
planner -> researcher
researcher -> writer/__end__
writer -> reviewer
reviewer -> planner/writer/__end__
refiner -> __end__
```

这些决策会写入：

```text
workflow_route_decisions
```

LangGraph 路径目前仍保留为回滚通道，但 route decision trace 不如 Python Engine 完整。

## 回滚条件

出现以下情况时先回滚到 `langgraph`：

- Python Engine SSE 顺序异常
- workflow history 未入库
- route decision trace 写入异常影响主链路
- reviewer loop 出现非预期循环
- chat 最终报告缺失

回滚只需要改环境变量：

```bash
WORKFLOW_ENGINE=langgraph
```

## 后续替换路线

1. 保持双引擎对齐测试持续通过
2. 默认使用 `python`
3. 增强 route decision 可视化/API
4. 观察稳定后移除 LangGraph 依赖和 checkpoint 代码
