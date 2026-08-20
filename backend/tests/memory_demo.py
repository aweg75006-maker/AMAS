"""记忆系统真实效果测试脚本。

用法（在 backend/ 目录，需要已配置 LLM API Key + Redis 已启动）：
    /opt/miniconda3/envs/iris/bin/python tests/memory_demo.py

流程（每步打印中间态，方便你直观看到"记忆系统到底记住了什么、怎么查出来的"）：

    [Step 1] 造 13 条带真实感的回合数据（含用户偏好/关系信号）
    [Step 2] 走生产链路 CompressionScheduler.schedule()：
            真实 LLM 摘要 → 温层 Chroma 索引 → 冷层 SQLite 记录（同 turn_id）
    [Step 3] 打印冷层记录：分类结果 / 重要度 / 冷热标签
    [Step 4] 真实 LLM 图谱抽取（consolidate_thread）→ 打印抽取出的三元组
    [Step 5] 多级检索：MemorySearchService.search() → 打印命中层（向量/图谱/冷层）
    [Step 6] 冷热迁移演示：archive（热→冷）→ warm_up（冷→热）
    [Step 7] 图谱邻接查询：search_relations() → 打印 1~2 跳路径
    [Step 8] 汇总统计 + 清理演示数据（--clean 时删除）

注意事项：
- 会真实调用 LLM（约 10 次摘要 + 1 次抽取），耗时和 token 消耗取决于所选模型；
- 数据写入默认记忆库 app/data/memory.db 的独立 thread（demo-<时间戳>），
  不影响真实会话；--clean 可一键清理本次演示数据；
- 温层（Chroma）索引会真实写入 turn_memory collection，与冷层同 turn_id，
  用 --clean 会一并删除对应向量索引。
"""

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

# 让脚本可直接从 backend/ 下以 tests/memory_demo.py 运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.summarizer import TurnSummary  # noqa: E402
from app.utils.memory.cold_store import ColdMemoryStore, LABEL_HOT, LABEL_COLD  # noqa: E402
from app.utils.memory.graph_store import GraphMemoryStore  # noqa: E402
from app.utils.memory.lifecycle import MemoryLifecycleManager  # noqa: E402
from app.utils.memory.extraction import get_extractor  # noqa: E402
from app.utils.memory.search import get_memory_search  # noqa: E402

# 温层：直接复用生产 CrossTurnRetriever
from app.utils.cross_turn_retriever import CrossTurnRetriever  # noqa: E402

SEP = "=" * 72
SUB = "-" * 56


def step(n: int, title: str) -> None:
    """打印步骤标题。"""
    print(f"\n{SEP}\n[Step {n}] {title}\n{SEP}")


def build_turns() -> list[dict]:
    """构造 13 条回合数据（前几条含偏好/关系信号，其余为中性研究回合）。"""
    turns = []
    specs = [
        # (query, final_report 片段) —— 前 4 条带稳定知识信号，供图谱抽取
        ("用户偏好使用 Python 做数据处理",
         "调研结论：用户长期使用 Python + pandas 处理数据，熟悉 DataFrame 操作，"
         "不习惯用 R。"),
        ("用户负责前端组的管理工作",
         "背景：用户是前端组负责人，管理 8 人团队，负责技术选型和排期。"),
        ("用户不喜欢频繁开会",
         "用户偏好：讨厌长会，习惯用异步文档同步进度，每周只接受一次站会。"),
        ("用户习惯晚上跑步锻炼",
         "生活偏好：用户习惯每晚 9 点跑步 5 公里，周末常去爬山。"),
        # 中性研究回合
        ("RAG 检索增强生成的核心原理是什么", "RAG 通过检索外部知识注入上下文，降低幻觉。"),
        ("LangGraph 的状态管理机制", "LangGraph 用 TypedDict + reducer 管理图状态。"),
        ("BM25 与向量检索的区别", "BM25 稀疏字面匹配，向量稠密语义匹配，二者互补。"),
        ("ChromaDB 的持久化方式", "ChromaDB 以本地目录持久化向量与元数据。"),
        ("CrossEncoder 重排的原理", "CrossEncoder 将 query 与 doc 拼接编码打分。"),
        ("Agent 的 token 预算管理", "通过预估与上限控制每个节点的 token 消耗。"),
        ("HITL 人工介入的实现", "用 interrupt 挂起节点，Command(resume) 恢复。"),
        ("SQLite 作为本地存储的取舍", "零依赖、单文件，适合中小规模数据。"),
        ("多智能体协作的模式", "规划-执行-审查-精修的流水线协作模式。"),
    ]
    for i, (q, report) in enumerate(specs):
        turns.append({
            "turn_id": f"demo-turn-{i}",
            "turn_number": i,
            "query": q,
            "plan": [q[:12]],
            "search_results": [{"title": q, "text": report[:200]}],
            "final_report": report,
            "critique": "",
        })
    return turns


def pretty(rec: dict) -> str:
    """把冷层记录渲染成一行可读文本。"""
    c = rec.get("content") or {}
    gist = str(c.get("query_gist", ""))[:36]
    return (f"id={rec['id']:<16} type={rec['event_type']:<9} "
            f"imp={rec['importance']:<6} label={rec['cold_label']:<4} "
            f"protect={rec['protected']} | {gist}")


async def run_demo(clean: bool) -> None:
    thread_id = f"demo-{uuid.uuid4().hex[:8]}"
    print(f"演示会话（thread）: {thread_id}")
    print(f"记忆库文件: {ColdMemoryStore().db_path}\n")

    cold = ColdMemoryStore()
    graph = GraphMemoryStore()
    retriever = CrossTurnRetriever()
    lifecycle = MemoryLifecycleManager(cold_store=cold)

    # ── Step 1：造数据 ──
    step(1, "构造 13 条回合数据（前 4 条含用户偏好/关系信号）")
    turns = build_turns()
    for t in turns[:4]:
        print(f"  {t['turn_id']:<16} {t['query']}")

    # ── Step 2：走生产链路压缩调度 ──
    step(2, "CompressionScheduler.schedule() 真实压缩（LLM 摘要 → 温层索引 → 冷层写入）")
    from app.utils.compression_scheduler import CompressionScheduler

    scheduler = CompressionScheduler(redis_client=None)
    # window_k=3：窗口外 10 条都会被真实 LLM 摘要
    result = await scheduler.schedule(thread_id, turns, window_k=3)
    print(f"  摘要生成 {result['summarized']} 条，温层索引 {result['indexed']} 条，"
          f"节省 {result['tokens_saved']} tokens，fusion={result['fusion_triggered']}")
    if result.get("errors"):
        print(f"  部分失败: {result['errors'][:2]}")

    # ── Step 3：查看冷层记录 ──
    step(3, "冷层记录（分类 / 重要度 / 冷热标签）")
    rows = cold.search(thread_id=thread_id, limit=15)
    if not rows:
        print("  ⚠ 冷层没有记录（检查上文是否有报错）")
    for r in rows:
        print("  " + pretty(r))
    print(f"  冷层该会话共 {len(rows)} 条")

    # ── Step 4：真实 LLM 图谱抽取 ──
    step(4, "consolidate_thread() 图谱抽取（LLM 提炼偏好/关系三元组）")
    extractor = get_extractor()
    # 冷却表全局共享，先清掉本 thread 的冷却标记保证本次必然执行
    extractor._last_consolidate.pop(thread_id, None)
    ex_result = await extractor.consolidate_thread(thread_id)
    if ex_result["skipped"]:
        print("  跳过（记忆不足或冷却中）")
    print(f"  抽取成功 {ex_result['consolidated']} 条三元组:")
    for t in ex_result["triples"]:
        print(f"    ({t['subject']}) -[{t['relation']}]-> ({t['object']})")
    if ex_result["consolidated"] == 0:
        print("  未抽出三元组：可检查 LLM 返回或对话素材是否含稳定知识信号")

    # ── Step 5：多级检索 ──
    step(5, "多级检索 memory.search()（Redis 缓存 → 向量 → 图谱 → 冷层）")
    from app.utils.redis_client import get_redis
    redis = await get_redis()
    svc = get_memory_search()
    for q in ["用户偏好什么编程语言", "RAG 的原理是什么", "喜欢晚上做什么"]:
        results = await svc.search(q, thread_id=thread_id, top_k=3, redis=redis)
        print(f"  query: {q}")
        if not results:
            print("    → 无结果")
        for r in results:
            print(f"    [{r['type']:<8} score={r['score']}] {r['content'][:70]}")
        print()

    # ── Step 6：冷热迁移演示 ──
    step(6, "冷热迁移：archive（热→冷）→ warm_up（冷→热）")
    if rows:
        mid = rows[0]["id"]
        print(f"  选中记忆: {mid}")
        lifecycle.archive(mid)
        rec = cold.get_by_id(mid)
        print(f"  archive 后 cold_label = {rec['cold_label']}（Chroma 索引已删）")
        lifecycle.warm_up(mid)
        rec = cold.get_by_id(mid)
        print(f"  warm_up 后 cold_label = {rec['cold_label']}（Chroma 索引已重建）")

    # ── Step 7：图谱查询 ──
    step(7, "图谱邻接查询 graph.search_relations()")
    for node in ["用户", "前端", "Python"]:
        paths = graph.search_relations(node, depth=2)
        print(f"  query: {node}")
        if not paths:
            print("    → 无匹配路径")
        for p in paths[:3]:
            print(f"    {' → '.join(p['nodes'])}   (关系: {' → '.join(p['relations'])})")
        print()

    # ── Step 8：汇总 ──
    step(8, "汇总")
    print(f"  冷层记录总数: {cold.count()}  图谱三元组总数: {graph.count()}")
    print(f"  温层（Chroma turn_memory）索引数: {retriever.count_indexed()}")

    if clean:
        print(f"\n清理演示数据（thread={thread_id}）...")
        for r in cold.search(thread_id=thread_id, limit=100):
            cold.delete(r["id"])
            retriever.delete_turn(r["id"])   # 同步删温层向量索引
        n = graph.delete_by_thread(thread_id)
        print(f"  已清理冷层记录、温层索引与 {n} 条图谱三元组")
    else:
        print(f"\n（数据已保留在记忆库中，可用 --clean 下次清理；thread_id={thread_id}）")


def main() -> None:
    parser = argparse.ArgumentParser(description="记忆系统真实效果测试")
    parser.add_argument("--clean", action="store_true", help="结束后清理本次演示数据")
    args = parser.parse_args()
    t0 = time.time()
    try:
        asyncio.run(run_demo(args.clean))
    except KeyboardInterrupt:
        print("\n已中断")
    print(f"\n耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
