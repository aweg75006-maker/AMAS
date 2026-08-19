"""runtime.py 真实场景体验脚本：在「真实工作流」上感受 人工打断 / 重试 / 超时。

与「玩具 Demo」的区别：这里不再用假函数打印两句话，而是
  - 直接编译真实的 LangGraph 工作流（planner / researcher / writer 都是生产代码）；
  - 重试 / 超时包裹的是真实的 LLM 调用（get_llm()，和 writer 节点同款）；
  - 人工打断发生在真实流水线「写报告前」，你注入的意见会真的进入 writer 的提示词、体现在最终报告里。

运行方式（用你平时的 python，二选一）：
    # 在 backend/ 目录下：
    python tests/demo_runtime.py
    # 或在 backend/tests/ 目录下：
    python demo_runtime.py

然后按菜单输入 1 / 2 / 3 选择要体验的效果，q 退出。

注意：
- 本脚本为「真实联网」模式，会消耗 API 额度（Tavily / OpenAI / DashScope），
  与你之前跑 researcher.py 那次一样。
- 「人工打断(HITL)」依赖 LangGraph 的原生 interrupt，需要 Python 3.11+；
  在更低版本上会自动提示并跳过。
- 「重试 / 超时」在任意版本均可正常运行。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# 路径引导：让脚本直接运行时也能 import 到 app.*
# 本文件位于 backend/tests/，而 app 包在 backend/，所以要往上层一级（parents[1]）把 backend 加进 sys.path。
_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, END
from langgraph.types import Command

from app.core.config import settings
from app.graph.nodes.planner import plan_node
from app.graph.nodes.researcher import research_node
from app.graph.nodes.writer import write_node
from app.graph.nodes.refiner import refine_node
from app.graph.nodes.router import route_query
from app.graph.graph import route_after_research
from app.graph.runtime import WorkflowNodeExecutionError, wrap_node
from app.graph.state import AgentState
from app.utils.llm import get_llm
# 剥离终端输入里可能混入的孤立代理字符（脏字节），否则 LLM 请求序列化会直接炸
from app.utils.text_sanitize import strip_surrogates


# ---------------------------------------------------------------------------
# 辅助：打印工作流流过的节点，便于看到「真实节点在跑」
# ---------------------------------------------------------------------------
def _print_event(event: dict) -> None:
    for key, _value in event.items():
        if key == "__interrupt__":
            print("  ⏸  工作流已暂停（interrupt 触发，等待人工输入）")
        elif key in ("planner", "researcher", "writer", "reviewer", "refiner", "router"):
            print(f"  ▶  {key} 节点执行完成（真实代码）")
        else:
            print(f"  · {key}")


# ---------------------------------------------------------------------------
# 真实流水线的「精简版」：planner → researcher → writer → END
# 复用了生产代码里的节点与路由函数，只把 writer 设为终点，
# 这样 HITL 闸门正好落在「写报告前」，且不会继续消耗 reviewer 的额外调用。
# ---------------------------------------------------------------------------
def _create_trimmed_graph(memory=None):
    workflow = StateGraph(AgentState)
    workflow.add_node("planner", wrap_node("planner", plan_node))
    workflow.add_node("researcher", wrap_node("researcher", research_node))
    workflow.add_node("writer", wrap_node("writer", write_node))
    workflow.add_node("refiner", wrap_node("refiner", refine_node))
    workflow.set_conditional_entry_point(
        route_query,
        {"planner": "planner", "refiner": "refiner"},
    )
    workflow.add_edge("planner", "researcher")
    workflow.add_conditional_edges(
        "researcher",
        route_after_research,
        {"writer": "writer", END: END},
    )
    workflow.add_edge("writer", END)
    workflow.add_edge("refiner", END)
    return workflow.compile(checkpointer=memory)


# ---------------------------------------------------------------------------
# 1) 人工打断（HITL）：真实流水线跑到 writer 前暂停，人注入意见，writer 据此成稿
# ---------------------------------------------------------------------------
async def demo_hitl() -> None:
    if sys.version_info < (3, 11):
        print("⚠️  当前是 Python %d.%d，LangGraph 原生 interrupt 需要 3.11+，此演示跳过。"
              % (sys.version_info[:2]))
        print("    请用 Python 3.11+ 的环境再跑这一项。")
        return

    # 限制 researcher 的真实检索迭代次数，控制 API 调用量（仍是真实检索）
    settings.rag_max_retrieval_iterations = 1

    graph = _create_trimmed_graph(memory=InMemorySaver())
    config = {"configurable": {"thread_id": "demo-hitl-live"}}

    query = strip_surrogates(
        input("请输入研究问题（直接回车用默认示例）：").strip()
    ) or "2024 年中国新能源汽车出口的主要市场与增长数据"
    print(f"\n>>> 启动真实流水线：planner → researcher →（在 writer 写报告前暂停）")
    print("    planner / researcher 会发起真实 LLM 与网络检索，请稍候……\n")

    # 第一次运行：跑到 writer 前会被 interrupt 挂起
    events = [e async for e in graph.astream(
        {"query": query, "hitl_pause_before": "writer"},
        config=config,
    )]
    for e in events:
        _print_event(e)

    if not any("__interrupt__" in e for e in events):
        print("❌ 未触发 writer 前的暂停（可能路由到了 refiner）。")
        return

    print("\n=== 工作流已在 writer（写报告）前暂停，等待你注入意见 ===")
    guidance = strip_surrogates(
        input("请输入你对报告的补充 / 修改要求（例如：重点分析欧洲市场、去掉亚洲部分）：\n> ").strip()
    )
    if not guidance:
        guidance = "（无额外要求，按已有证据正常成稿）"

    print(f"\n>>> 用你的要求恢复流水线，writer 将据此成稿：{guidance!r}")
    resumed = [e async for e in graph.astream(
        Command(resume={"human_input": guidance}),
        config=config,
    )]
    for e in resumed:
        _print_event(e)

    final_state = await graph.aget_state(config)
    report = final_state.values.get("final_report", "")
    print("\n========== 最终报告（前 600 字）==========")
    print(report[:600] if report else "（无报告输出）")
    print("============================================")
    print(f"[校验] 你注入的意见 human_input = {final_state.values.get('human_input')!r}")
    print("[校验] writer 节点会把该意见拼成「【人工补充要求】…」写入提示词；")
    print("       若最终报告体现了你的要求，说明 HITL 在真实流水线中真实生效。")


# ---------------------------------------------------------------------------
# 2) 重试（retry）：包裹「真实 LLM 调用」，第 1 次瞬时故障，自动重试拿到真实结果
# ---------------------------------------------------------------------------
async def demo_retry() -> None:
    # 该节点不在 manifest 中，走 settings 全局兜底配置
    settings.workflow_node_timeout_seconds = 60
    settings.workflow_node_max_retries = 2
    settings.workflow_retry_backoff_seconds = 0

    calls = {"n": 0}

    def real_llm_with_transient_failure(_state: AgentState) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            print("  · 第 1 次真实 LLM 调用遭遇瞬时故障（模拟 429 / 网络抖动），抛出异常")
            raise RuntimeError("Temporary API error: 429 Too Many Requests")
        print("  · 第 2 次真实 LLM 调用成功")
        resp = get_llm("fast").invoke(
            [HumanMessage(content="用一句话回答：水的化学式是什么？")]
        )
        return {"answer": resp.content}

    wrapped = wrap_node("demo_retry_live", real_llm_with_transient_failure)
    print(">>> 包裹真实 LLM 调用的节点：第 1 次失败 → 自动重试 → 第 2 次拿到真实结果")
    result = await wrapped({"query": "hello"})
    print(f"  真实 LLM 返回：{result.get('answer')}")
    print(f"  -> 重试标记 _workflow_retry = {result.get('_workflow_retry')}")


# ---------------------------------------------------------------------------
# 3) 超时（timeout）：包裹「真实 LLM 调用」，超时阈值远低于真实耗时 → 护栏中断
# ---------------------------------------------------------------------------
async def demo_timeout() -> None:
    settings.workflow_node_timeout_seconds = 0.01   # 远低于一次真实 LLM 调用耗时
    settings.workflow_node_max_retries = 0
    settings.workflow_retry_backoff_seconds = 0

    def real_llm_slow(_state: AgentState) -> dict:
        # 真实 LLM 调用，正常需要数秒，但上面超时设成 0.01s → 必然超时
        resp = get_llm("smart").invoke(
            [HumanMessage(content="请写一段约 300 字、关于 2024 年中国新能源汽车出口的介绍。")]
        )
        return {"answer": resp.content}

    wrapped = wrap_node("demo_timeout_live", real_llm_slow)
    print(">>> 包裹真实 LLM 调用的节点：超时设为 0.01s（远低于真实调用耗时）")
    try:
        await wrapped({"query": "hello"})
        print("❌ 预期应抛出超时异常，但没有")
    except WorkflowNodeExecutionError as exc:
        print("✅ 护栏如期触发：真实 LLM 调用被强制中断，流程不会卡死")
        print(f"   node_name   = {exc.node_name}")
        print(f"   error_code  = {exc.error_code}")
        print(f"   attempts    = {exc.attempts}")
        print(f"   duration_ms = {exc.duration_ms}")


def main() -> None:
    print("=" * 64)
    print("runtime.py 真实场景体验（wrap_node 的三种运行时能力）")
    print("=" * 64)
    print("说明：本脚本为「真实联网」模式，会消耗 API 额度。")
    while True:
        print("\n请选择要体验的效果：")
        print("  1) 人工打断 (HITL)   —— 真实流水线跑到 writer 前暂停，你注入意见后成稿")
        print("  2) 重试 (retry)      —— 包裹真实 LLM 调用，第1次故障→自动重试拿真实结果")
        print("  3) 超时 (timeout)    —— 包裹真实 LLM 调用，超时远低于耗时→护栏中断不卡死")
        print("  q) 退出")
        choice = input("选择：").strip().lower()
        if choice == "1":
            asyncio.run(demo_hitl())
        elif choice == "2":
            asyncio.run(demo_retry())
        elif choice == "3":
            asyncio.run(demo_timeout())
        elif choice == "q":
            print("再见 👋")
            break
        else:
            print("无效选择，请输入 1/2/3 或 q。")


if __name__ == "__main__":
    main()
