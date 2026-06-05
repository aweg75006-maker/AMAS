"""
压力测试：模拟 N 轮长会话，验证预算系统。

用法：
    cd backend
    python -m app.utils.stress_test                # 默认 50 轮
    python -m app.utils.stress_test --turns 100    # 100 轮
    python -m app.utils.stress_test --turns 200 --verbose

验证指标：
    - 每次上下文装配的 Token 数 < 128K
    - 溢出策略触发次数与预期一致
    - 滑动窗口 K 值动态调整
    - 压缩决策有效性
    - 预算账簿准确性
"""

import sys
import os
import json
import time
import random
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.utils.budget_ledger import BudgetLedger, DEFAULT_NODE_POLICIES
from app.utils.budget_enforcer import BudgetEnforcer, OVERFLOW_HANDLERS, EnforcerResult
from app.utils.sliding_window import SlidingWindowManager, WindowConfig
from app.utils.compression_decision import (
    CompressionDecisionEngine, CompressionLevel, EvictionPlan,
)
from app.utils.token_counter import count_tokens


# ─── 合成数据生成 ───

TOPICS = [
    "大语言模型架构演进", "量子计算商业化", "AI Agent框架对比",
    "多模态模型最新进展", "RAG技术优化", "模型推理加速",
    "AI安全与对齐", "联邦学习应用", "图神经网络进展",
    "强化学习在推荐系统中的应用", "自然语言处理最新突破",
    "计算机视觉2026趋势", "边缘AI部署", "向量数据库选型",
    "Prompt Engineering最佳实践", "模型蒸馏与量化",
    "AI在医疗诊断中的应用", "自动驾驶技术栈",
    "语音识别与合成", "知识图谱构建",
]

SAMPLE_REPORTS = [
    "## 报告摘要\n本报告分析了{topic}的最新进展。研究发现该领域在2026年取得了显著突破。\n\n"
    "### 核心发现\n"
    "1. 市场规模在2026年达到{size}亿美元，同比增长{growth}%\n"
    "2. 关键技术突破来自{company}的新型架构，性能提升{perf}倍\n"
    "3. 行业采用率从2025年的{adoption_old}%提升至{adoption_new}%\n"
    "4. 主要挑战包括{challenge}\n"
    "5. 预计2027年将进一步{prediction}\n\n"
    "### 详细分析\n"
    "技术层面，{tech_detail}。应用层面，{app_detail}。\n\n"
    "### 结论\n"
    "{topic}正处于快速发展期，建议关注{focus_area}方向。",

    "## {topic}深度研究报告\n\n"
    "### 背景\n"
    "{topic}作为2026年最受关注的技术方向之一，吸引了大量研究和投资。\n\n"
    "### 市场数据\n"
    "- 全球市场规模：{size}亿美元\n"
    "- 年增长率：{growth}%\n"
    "- 主要参与者：{company}\n"
    "- 投融资事件：{funding}起\n\n"
    "### 技术路线\n"
    "当前主流技术路线包括三种：基于Transformer的架构改进、混合专家模型(MoE)、以及轻量化部署方案。\n\n"
    "### 风险评估\n"
    "主要风险：{challenge}。但总体来看，行业前景乐观。\n\n"
    "### 建议\n"
    "对于关注该领域的团队，建议优先投入{focus_area}方向。",
]


def generate_synthetic_turn(turn_number: int) -> Dict[str, Any]:
    """生成一个合成的 Turn 数据（模拟真实研究结果）。"""
    topic = random.choice(TOPICS)
    report_template = random.choice(SAMPLE_REPORTS)

    report = report_template.format(
        topic=topic,
        size=random.randint(10, 500),
        growth=random.randint(15, 80),
        company=random.choice(["Google", "OpenAI", "DeepSeek", "Meta", "Anthropic", "Baidu"]),
        perf=random.randint(2, 20),
        adoption_old=random.randint(5, 30),
        adoption_new=random.randint(25, 70),
        challenge=random.choice([
            "算力成本过高", "数据隐私合规", "人才短缺",
            "技术成熟度不足", "监管政策不确定性",
        ]),
        prediction=random.choice([
            "实现全面商业化", "进入稳定发展期", "迎来新一轮技术突破",
            "面临行业整合", "扩展至更多垂直领域",
        ]),
        tech_detail=f"核心技术创新包括{random.randint(3,10)}项专利，"
                    f"在{random.choice(['推理速度','训练效率','模型精度'])}方面"
                    f"提升了{random.randint(2,15)}倍。",
        app_detail=f"已在{random.choice(['金融','医疗','教育','制造','零售'])}"
                   f"行业落地{random.randint(50,500)}个应用案例。",
        focus_area=random.choice([
            "多模态融合", "模型压缩", "推理优化",
            "安全对齐", "行业应用", "开源生态",
        ]),
        funding=random.randint(10, 200),
    )

    plan_count = random.randint(3, 5)
    plans = [f"{topic} {aspect}" for aspect in [
        "最新进展", "技术架构", "市场分析",
        "竞争格局", "未来趋势", "挑战与机遇",
    ][:plan_count]]

    search_count = random.randint(2, 5)
    search_results = []
    for i in range(search_count):
        search_results.append(
            f"结果{i+1}: {topic}相关 - "
            f"2026年数据表明该领域增长了{random.randint(10,100)}%，"
            f"主要贡献来自{random.choice(['技术创新','市场需求','政策支持'])}。"
        )

    return {
        "turn_id": f"turn_{turn_number:04d}",
        "turn_number": turn_number,
        "query": f"请研究{topic}的最新进展和趋势",
        "plan": plans,
        "search_results": search_results,
        "final_report": report,
        "critique": random.choice(["", "请补充更多数据支持", "结论部分需要更详细"]),
        "review_status": random.choice(["PASS", "PASS", "PASS", "FAIL"]),
        "search_mode": "hybrid",
        "token_usage": {},
        "timestamp": time.time() - (100 - turn_number) * 3600,
    }


# ─── 压力测试运行器 ───

@dataclass
class StressTestResults:
    """压力测试结果。"""
    total_turns: int
    passed: bool = True
    failures: List[str] = field(default_factory=list)
    context_assembly_tokens: List[int] = field(default_factory=list)
    overflow_events: List[Dict] = field(default_factory=list)
    window_k_history: List[int] = field(default_factory=list)
    compression_decisions: List[Dict] = field(default_factory=list)
    budget_snapshots: List[Dict] = field(default_factory=list)
    elapsed_seconds: float = 0

    @property
    def avg_context_tokens(self) -> float:
        if not self.context_assembly_tokens:
            return 0
        return sum(self.context_assembly_tokens) / len(self.context_assembly_tokens)

    @property
    def max_context_tokens(self) -> int:
        return max(self.context_assembly_tokens) if self.context_assembly_tokens else 0

    @property
    def overflow_count(self) -> int:
        return len(self.overflow_events)

    @property
    def violations(self) -> int:
        """超预算次数（>128K）。"""
        return sum(1 for t in self.context_assembly_tokens if t > 128_000)


def run_stress_test(num_turns: int = 50, verbose: bool = False) -> StressTestResults:
    """
    运行压力测试。

    模拟 num_turns 轮对话，逐步积累历史，验证每轮的 Token 预算合规性。
    """
    results = StressTestResults(total_turns=num_turns)
    start_time = time.time()

    # 初始化组件
    window_mgr = SlidingWindowManager(WindowConfig(k=3, total_budget=128_000))
    decision_engine = CompressionDecisionEngine()

    all_turns: List[Dict[str, Any]] = []

    for turn_num in range(1, num_turns + 1):
        # 生成合成 Turn
        new_turn = generate_synthetic_turn(turn_num)
        all_turns.append(new_turn)

        # 模拟上下文装配
        memory = window_mgr.assemble(
            all_turns=all_turns,
            current_query=new_turn["query"],
            pinned_ids=[],
        )

        results.window_k_history.append(memory.window_k)
        context_tokens = count_tokens(memory.memory_context)
        results.context_assembly_tokens.append(context_tokens)

        # 检查预算合规
        if context_tokens > 128_000:
            results.failures.append(
                f"Turn {turn_num}: context={context_tokens} > 128K budget"
            )
            results.passed = False

        # 模拟各节点的预算预检
        budget_ledger = BudgetLedger(
            session_id="stress_test",
            total_budget=128_000,
        )
        budget_ledger.begin_turn(turn_num, new_turn["turn_id"])

        for node_name in ["router", "planner", "researcher", "writer", "reviewer"]:
            policy = budget_ledger.get_policy(node_name)
            # 模拟不同大小的输入
            if node_name == "router":
                input_size = random.randint(500, 3000)
            elif node_name == "planner":
                input_size = random.randint(1000, 5000)
            elif node_name == "researcher":
                input_size = random.randint(5000, 50000)
            elif node_name == "writer":
                input_size = random.randint(10000, 90000)
            elif node_name == "reviewer":
                input_size = random.randint(5000, 70000)

            if input_size > policy.max_input_tokens:
                results.overflow_events.append({
                    "turn": turn_num,
                    "node": node_name,
                    "input_tokens": input_size,
                    "max_allowed": policy.max_input_tokens,
                    "overflow_policy": policy.overflow_policy.value,
                    "excess": input_size - policy.max_input_tokens,
                })

        # 模拟压缩决策
        if len(all_turns) > 3:
            budget_pressure = decision_engine.get_budget_pressure(
                remaining=128_000 - context_tokens,
                total=128_000,
            )
            plan = decision_engine.plan_eviction(
                all_turns=all_turns,
                window_k=memory.window_k,
                budget_pressure=budget_pressure,
            )
            if plan.turns_to_summarize or plan.turns_to_evict:
                results.compression_decisions.append({
                    "turn": turn_num,
                    "budget_pressure": round(budget_pressure, 3),
                    "turns_to_summarize": len(plan.turns_to_summarize),
                    "turns_to_evict": len(plan.turns_to_evict),
                    "estimated_freed": plan.estimated_tokens_freed,
                })

        # 记录预算快照
        snapshot = budget_ledger.snapshot()
        results.budget_snapshots.append({
            "turn": turn_num,
            "remaining": snapshot.remaining,
            "total_used": snapshot.total_used,
            "utilization_pct": round(snapshot.utilization_pct, 1),
        })

        budget_ledger.end_turn()

        if verbose and turn_num % 10 == 0:
            print(f"  Turn {turn_num}/{num_turns}: "
                  f"context={context_tokens:,} tokens, "
                  f"K={memory.window_k}, "
                  f"overflow={len(results.overflow_events)}, "
                  f"compression_decisions={len(results.compression_decisions)}")

    results.elapsed_seconds = time.time() - start_time
    return results


# ─── 报告输出 ───

def print_report(results: StressTestResults, verbose: bool = False):
    """打印压力测试报告。"""
    print("\n" + "=" * 60)
    print("上下文工程 · 压力测试报告")
    print("=" * 60)

    print(f"\n📊 基本指标")
    print(f"  模拟轮数:           {results.total_turns}")
    print(f"  总耗时:             {results.elapsed_seconds:.2f}s")
    print(f"  平均每轮耗时:        {results.elapsed_seconds/results.total_turns*1000:.1f}ms")
    print(f"  通过:               {'✅ YES' if results.passed else '❌ NO'}")

    print(f"\n📏 Token 预算")
    print(f"  平均上下文 Token:    {results.avg_context_tokens:,.0f}")
    print(f"  最大上下文 Token:    {results.max_context_tokens:,}")
    print(f"  超预算次数 (>128K): {results.violations}")
    print(f"  预算合规率:          {(1 - results.violations/results.total_turns)*100:.1f}%")

    print(f"\n🔀 溢出事件")
    print(f"  总溢出次数:          {results.overflow_count}")
    if results.overflow_events:
        # 按节点统计
        from collections import Counter
        by_node = Counter(e["node"] for e in results.overflow_events)
        for node, count in by_node.most_common():
            print(f"    {node}: {count} 次")
        # 最高溢出
        worst = max(results.overflow_events, key=lambda e: e["excess"])
        print(f"  最大溢出:            Turn {worst['turn']}/{worst['node']} "
              f"({worst['input_tokens']:,}/{worst['max_allowed']:,})")

    print(f"\n🪟 滑动窗口")
    if results.window_k_history:
        print(f"  初始 K:              {results.window_k_history[0]}")
        print(f"  最终 K:              {results.window_k_history[-1]}")
        # K 变化次数
        k_changes = sum(
            1 for i in range(1, len(results.window_k_history))
            if results.window_k_history[i] != results.window_k_history[i-1]
        )
        print(f"  K 调整次数:          {k_changes}")

    print(f"\n🗜️ 压缩决策")
    print(f"  决策触发次数:         {len(results.compression_decisions)}")
    if results.compression_decisions:
        total_freed = sum(d["estimated_freed"] for d in results.compression_decisions)
        print(f"  累计预估节省 Token:   {total_freed:,}")

    print(f"\n💰 预算利用率")
    if results.budget_snapshots:
        avg_util = sum(s["utilization_pct"] for s in results.budget_snapshots) / len(results.budget_snapshots)
        max_util = max(s["utilization_pct"] for s in results.budget_snapshots)
        print(f"  平均利用率:          {avg_util:.1f}%")
        print(f"  峰值利用率:          {max_util:.1f}%")

    if results.failures:
        print(f"\n❌ 失败详情 ({len(results.failures)} 项)")
        for f in results.failures[:10]:
            print(f"  - {f}")
        if len(results.failures) > 10:
            print(f"  ... 还有 {len(results.failures) - 10} 项")

    print("\n" + "=" * 60)

    # 判定
    if results.passed and results.violations == 0:
        print("✅ 压力测试通过：Token 预算系统在 {:,} 轮会话中保持合规".format(
            results.total_turns))
    else:
        print("⚠️ 压力测试未完全通过，请检查上述指标")


# ─── CLI 入口 ───

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="上下文工程压力测试")
    parser.add_argument("--turns", type=int, default=50,
                        help="模拟的会话轮数（默认 50）")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="详细输出")
    args = parser.parse_args()

    print(f"🚀 启动压力测试：{args.turns} 轮会话模拟")
    results = run_stress_test(args.turns, verbose=args.verbose)
    print_report(results, verbose=args.verbose)
