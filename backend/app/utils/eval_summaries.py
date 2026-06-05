"""
摘要质量评测脚本。

用法：
    cd backend
    python -m app.utils.eval_summaries              # 使用内置测试用例
    python -m app.utils.eval_summaries --session_id iris_xxx  # 使用真实会话数据

指标：
    - fact_retention: 关键事实保留率（目标 > 70%）
    - compression_ratio: 压缩比（目标 > 10:1）
    - summary_tokens: 摘要 Token 数（目标 < 500）
    - overall_score: 综合评分（目标 > 0.7）

输出：
    - 每个 Turn 的详细评分
    - 全局统计（均值、中位数、达标率）
"""

import sys
import os
import json
import time
from typing import List, Dict, Any

# 确保 backend 在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.utils.summarizer import TurnSummarizer, SummaryEvaluator, TurnSummary
from app.utils.token_counter import count_tokens


# ─── 内置测试用例 ───

BUILTIN_TEST_CASES = [
    {
        "turn_id": "test_turn_001",
        "turn_number": 1,
        "query": "2026年大语言模型的主要技术突破有哪些？",
        "plan": ["LLM技术突破2026", "大模型架构创新", "推理优化最新进展"],
        "search_results": [
            "2026年，混合专家模型(MoE)架构成为主流，GPT-5采用16个专家的MoE架构，激活参数达到2万亿",
            "推理速度提升显著：DeepSeek-R2的推理延迟从500ms降至50ms，吞吐量提升10倍",
            "多模态融合取得突破：GPT-5 Vision在MMMU基准测试上达到92.3%准确率",
            "长上下文窗口扩展至1000万tokens（Google Gemini 3.0），且\"迷失中间\"问题得到有效缓解",
            "模型蒸馏技术使7B模型性能接近70B模型，部署成本降低90%",
        ],
        "final_report": """## 2026年大语言模型技术突破总结

### 1. 架构创新：MoE成为主流
2026年，混合专家（Mixture of Experts）架构从实验性技术转变为行业标准。OpenAI的GPT-5采用了16个专家的MoE架构，激活参数达2万亿，但每次推理仅激活约200B参数，实现了性能与效率的平衡。Google的Gemini 3.0同样采用MoE设计，专家数量达32个。

### 2. 推理优化：速度提升10倍
推理效率是2026年最大的突破方向。DeepSeek-R2通过FlashAttention-4和量化KV缓存技术，将单次推理延迟从500ms降至50ms，吞吐量提升10倍。推测解码（Speculative Decoding）技术已广泛部署，平均加速比达3-5倍。

### 3. 多模态融合：视觉-语言一体化
GPT-5 Vision和Gemini 3.0 Ultra实现了真正的多模态融合。MMMU基准测试准确率达到92.3%，较2025年提升了8个百分点。视频理解能力从分钟级扩展到小时级。

### 4. 超长上下文：1000万Token窗口
Google Gemini 3.0率先支持1000万Token上下文窗口。同时，通过\"注意力汇聚\"技术，模型在长文档中定位信息的精度提升至95%，有效解决了\"迷失中间\"问题。

### 5. 小型化与部署：7B媲美70B
通过多阶段蒸馏和量化感知训练，7B参数模型在多项基准上达到2025年70B模型的水平。部署成本降低90%，使得端侧LLM成为现实。

### 结论
2026年是大语言模型从\"规模竞赛\"转向\"效率竞赛\"的关键转折点。MoE架构、推理优化和模型小型化三大趋势将决定下一阶段的竞争格局。
""",
        "critique": "",
    },
    {
        "turn_id": "test_turn_002",
        "turn_number": 2,
        "query": "量子计算在2026年的商业化进展如何？",
        "plan": ["量子计算商业化2026", "量子计算公司融资", "量子优越性最新成果"],
        "search_results": [
            "IBM发布1121量子比特Condor处理器，量子体积达到1024，错误率降至0.01%",
            "Google Quantum AI实现100个逻辑量子比特的容错量子计算，纠错码开销降低至3:1",
            "量子计算融资2026年达到120亿美元，较2025年增长40%",
            "制药公司辉瑞使用量子计算机模拟了含50个原子的分子反应，加速药物发现",
            "中国科学技术大学实现255光子量子计算优越性实验",
        ],
        "final_report": """## 2026年量子计算商业化进展

### 1. 硬件里程碑
IBM在2026年发布了1121量子比特的Condor处理器，量子体积达1024，错误率降至0.01%，标志着量子计算进入\"实用级\"阶段。Google Quantum AI实现了100个逻辑量子比特的容错计算，纠错码开销降至3:1。

### 2. 行业应用突破
制药行业是最早获益的领域：辉瑞使用IBM量子计算机模拟了含50个原子的分子反应，将候选药物筛选时间从18个月缩短至3个月。金融行业方面，摩根大通使用量子算法优化投资组合，夏普比率提升12%。

### 3. 市场与投资
全球量子计算融资在2026年达到120亿美元，同比增长40%。量子计算即服务（QCaaS）市场预计2028年达到500亿美元。

### 结论
量子计算在2026年从\"实验室\"走向\"数据中心\"，虽然通用容错量子计算机仍需5-10年，但在特定领域的量子优势已开始产生实际商业价值。
""",
        "critique": "",
    },
    {
        "turn_id": "test_turn_003",
        "turn_number": 3,
        "query": "对比分析MoE架构和Dense架构的优劣",
        "plan": ["MoE vs Dense架构对比", "MoE训练技巧", "Dense架构最新进展"],
        "search_results": [
            "MoE优势：相同计算预算下模型容量更大，但存在负载不均衡问题",
            "Dense优势：训练稳定性好，推理延迟可预测，但参数效率较低",
            "DeepSeek R2采用改进的MoE架构，通过动态专家路由将负载均衡度提升至95%",
            "Meta Llama 4坚持Dense架构，证明在充足数据下Dense模型仍具竞争力",
        ],
        "final_report": """## MoE vs Dense 架构对比分析

### MoE架构优势
- 相同计算预算下模型容量可扩大5-10倍
- 实际推理成本仅为同等Dense模型的20-30%
- 适合多任务学习，专家可自然分工

### MoE架构劣势
- 负载不均衡导致部分专家\"过劳\"、部分\"闲置\"
- 训练不稳定，需要特殊的辅助损失函数
- 推理时需要加载全部专家权重，内存需求大

### Dense架构优势
- 训练过程稳定，超参数调优简单
- 推理延迟可预测，适合实时应用
- 模型压缩和部署工具链成熟

### Dense架构劣势
- 参数效率低，大量参数处理\"简单\"token
- 扩展受限于计算预算

### 结论
MoE和Dense不是\"谁取代谁\"的关系。MoE适合追求极致性能的云端场景，Dense适合延迟敏感或资源受限场景。2026年的趋势是\"混合\"：训练用MoE，推理时蒸馏为Dense。
""",
        "critique": "",
    },
]


# ─── 评测主函数 ───

def evaluate_builtin_cases() -> Dict[str, Any]:
    """使用内置测试用例评测摘要质量。"""
    print("=" * 60)
    print("摘要质量评测 — 内置测试用例")
    print("=" * 60)

    summarizer = TurnSummarizer(model_type="fast")
    evaluator = SummaryEvaluator(model_type="smart")

    results = []
    total_tokens_saved = 0
    total_raw_tokens = 0
    total_summary_tokens = 0

    for i, case in enumerate(BUILTIN_TEST_CASES):
        print(f"\n--- Turn {i+1}: {case['query'][:60]}... ---")

        # 生成摘要
        start = time.time()
        summary_result = summarizer.summarize(case)
        elapsed = time.time() - start

        # 评测
        eval_result = evaluator.evaluate(case, summary_result.summary)
        eval_result["elapsed_seconds"] = round(elapsed, 2)
        eval_result["turn_id"] = case["turn_id"]
        eval_result["query"] = case["query"][:80]

        results.append(eval_result)

        total_tokens_saved += summary_result.tokens_saved
        total_raw_tokens += summary_result.summary.raw_tokens
        total_summary_tokens += summary_result.summary.summary_tokens

        # 打印单项结果
        status = "✅" if eval_result["overall_score"] >= 0.7 else "⚠️"
        print(f"  {status} 整体评分: {eval_result['overall_score']:.3f}")
        print(f"     事实保留率: {eval_result['fact_retention']:.1%}")
        print(f"     压缩比: {summary_result.summary.compression_ratio:.1f}x")
        print(f"     摘要tokens: {summary_result.summary.summary_tokens}")
        print(f"     耗时: {elapsed:.1f}s")
        if summary_result.success:
            print(f"     关键事实: {summary_result.summary.key_facts[:2]}...")

    # 汇总统计
    scores = [r["overall_score"] for r in results]
    fact_scores = [r["fact_retention"] for r in results]
    avg_score = sum(scores) / len(scores) if scores else 0
    median_score = sorted(scores)[len(scores)//2] if scores else 0
    passing = sum(1 for s in scores if s >= 0.7)

    print("\n" + "=" * 60)
    print("汇总统计")
    print("=" * 60)
    print(f"测试样本数:         {len(results)}")
    print(f"达标率 (≥0.7):      {passing}/{len(results)} ({passing/len(results)*100:.0f}%)")
    print(f"平均整体评分:        {avg_score:.3f}")
    print(f"中位数整体评分:       {median_score:.3f}")
    print(f"平均事实保留率:       {sum(fact_scores)/len(fact_scores):.1%}" if fact_scores else "N/A")
    print(f"总原始tokens:        {total_raw_tokens:,}")
    print(f"总摘要tokens:        {total_summary_tokens:,}")
    print(f"总节省tokens:        {total_tokens_saved:,}")
    print(f"总压缩比:            {total_raw_tokens/total_summary_tokens:.1f}x" if total_summary_tokens > 0 else "N/A")

    return {
        "results": results,
        "summary": {
            "sample_count": len(results),
            "pass_rate": passing / len(results) if results else 0,
            "avg_score": avg_score,
            "median_score": median_score,
            "avg_fact_retention": sum(fact_scores) / len(fact_scores) if fact_scores else 0,
            "total_tokens_saved": total_tokens_saved,
            "total_compression_ratio": total_raw_tokens / total_summary_tokens if total_summary_tokens > 0 else 0,
        },
    }


def evaluate_session(session_id: str) -> Dict[str, Any]:
    """使用真实会话数据评测（通过 Redis 加载）。"""
    import asyncio
    from app.utils.redis_client import get_redis
    from app.utils.session_manager import SessionManager

    async def _eval():
        redis = await get_redis()
        mgr = SessionManager(redis)

        turn_ids = await redis.get_turn_ids(session_id)
        if not turn_ids:
            print(f"会话 {session_id} 无 Turn 数据")
            return {"error": "No turns found"}

        print(f"加载了 {len(turn_ids)} 个 Turn")

        summarizer = TurnSummarizer(model_type="fast")
        evaluator = SummaryEvaluator(model_type="smart")

        results = []
        for tid in turn_ids:
            turn_data = await redis.get_turn(session_id, tid)
            if not turn_data:
                continue

            print(f"\n--- 评测 {tid}... ---")
            result = summarizer.summarize(turn_data)
            eval_result = evaluator.evaluate(turn_data, result.summary)
            eval_result["turn_id"] = tid
            results.append(eval_result)

            print(f"  整体评分: {eval_result['overall_score']:.3f}, "
                  f"事实保留: {eval_result['fact_retention']:.1%}")

        return {"results": results, "session_id": session_id}

    return asyncio.run(_eval())


# ─── CLI 入口 ───

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="摘要质量评测工具")
    parser.add_argument(
        "--session_id", type=str, default=None,
        help="使用真实会话数据评测（需要 Redis 连接）"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="将结果输出到 JSON 文件"
    )
    args = parser.parse_args()

    if args.session_id:
        report = evaluate_session(args.session_id)
    else:
        report = evaluate_builtin_cases()

    # 输出 JSON（可选）
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n评测结果已保存至: {args.output}")

    # 总结
    if "summary" in report:
        s = report["summary"]
        print(f"\n最终结论: "
              f"达标率 {s['pass_rate']:.0%}, "
              f"平均评分 {s['avg_score']:.3f}, "
              f"节省 {s['total_tokens_saved']:,} tokens")
