"""检索子任务 DAG 的组装、校验与调度（S6 骨架）。

===============================================================================
【为什么需要这个模块 —— 一句话讲清这次升级的核心】
===============================================================================
改造前：Planner 输出的是 `list[str]` 关键词（用逗号切分 LLM 的自然语言回答），
Researcher 拿到后是一个**串行 for 循环**。问题有四条：
    ① 没有依赖关系 —— 无法表达"第二条检索要用第一条的结果"；
    ② 没有并发 —— 一条慢一条快也只能排队；
    ③ 失败只打一行 warning，状态不落库，前端看不到；
    ④ 用户无法干预 —— 不能"第 3 条不用查了"。

本模块把检索子任务表达成一张 DAG，于是四件事同时解决：
依赖、并发、失败隔离、可勾选确认。

===============================================================================
【面试要点：两层拓扑，分工明确】
===============================================================================
外层（LangGraph 主图）拓扑**固定**  → 换来可复现 + checkpoint 可恢复；
内层（本模块的检索子任务 DAG）**动态** → 换来召回覆盖（按问题拆不同检索面）。

===============================================================================
【移植说明与 D1/D5 决策】
===============================================================================
本模块形态移植自参考实现 ai-picture-editor/backend/app/agent/plan.py（122 行，8 个函数），
但有两处必须改：

  D1（语言基线）：原实现用 `enum.StrEnum` / `datetime.UTC`（均 Python 3.11+），
      而本项目 config.py 声明 3.10+（README 第 286 行；HITL 需 3.11+，但语法基线保守取 3.10）。
      → 这里一律用**纯字符串常量**，不用 enum，不用 datetime.UTC。
      验收门禁第 5 条会 grep "StrEnum|datetime import UTC" 兜底。

  D5（规模上限）：原实现硬编码 `MAX_STEPS = 8`，但本项目有 BudgetLedger（128K token）。
      硬编码会和预算互相打脸 —— 预算快见底时还硬跑 8 条检索。
      → 把上限从模块常量改成**入参**，由 `resolve_max_steps(budget_state)` 按剩余预算推导。

===============================================================================
【四项校验（validate_plan 的核心，面试可直接讲）】
===============================================================================
    ① 工具存在性 —— 模型编的工具名要在启动期就被拒
    ② 参数模型校验 —— 复用 S1 的 validate_params，与 LLM function schema 同源
    ③ 依赖补全 —— 模型没写 depends_on 时**默认串行**（见 assemble 的精髓）
    ④ Kahn 判环 —— 成环会让调度死循环，必须在组装期拦掉

===============================================================================
⚠️ Demo 阶段实现状态
===============================================================================
本文件是**骨架**：函数签名、状态常量、算法要点与边界条件均已就位，
但函数体留空（`pass`）。逐函数实现要点写在每个函数的 docstring 与注释里，
照着填即可。`resolve_max_steps` 已给出完整实现（只有 5 行，作为参考风格）。
"""

from __future__ import annotations

from typing import Any

# ─── 步骤状态机（7 态）─────────────────────────────────────────────────────
# 用纯字符串常量而不是 enum（决策 D1：兼容 3.10 语法基线）。
# 这些值会直接落进 state 并推给前端，所以也是前端文案映射的唯一来源。
PENDING = "pending"        # 刚组装出来，还没轮到
WAITING = "waiting"        # 依赖已满足但需要人工确认（S9 的选择式检查点）
QUEUED = "queued"          # 整轮判定为"等人确认"
RUNNING = "running"        # 正在执行
SUCCEEDED = "succeeded"    # 成功终结
FAILED = "failed"          # 失败终结
CANCELED = "canceled"      # 主动取消或被跳过（如 document 模式跳过网络任务）

# 未终结的状态集合：只要还存在任一此类步骤，整轮就还没跑完
_OPEN = frozenset({PENDING, WAITING, QUEUED, RUNNING})
# 会让后继步骤永久阻塞的状态：依赖失败 → 后继永远不就绪，这是"失败隔离"的正确表现
_BLOCKED = frozenset({FAILED, CANCELED})

DEFAULT_MAX_STEPS = 8


class PlanError(Exception):
    """计划非法（超长 / 依赖不存在 / 成环 / 工具或参数非法）。

    继承自 Exception，由节点侧统一捕获 ——
    计划问题绝不能把整轮研究炸掉，应当降级回"按关键词串行检索"。
    """


def resolve_max_steps(budget_state: dict[str, Any] | None = None) -> int:
    """按剩余预算推导本轮允许的最大任务数（决策 D5，参考项目没有这个函数）。

    硬编码 8 会和 BudgetLedger 的 128K 预算互相打脸：
    预算已经烧掉大半时，还硬跑 8 条检索 = 把剩下的预算一次性抽干。

    规则：
      · 没有预算信息 → 用默认上限（保持与旧行为一致，便于灰度）；
      · 预算耗尽（remaining <= 0）→ 返回 1，不返回 0 ——
        "跑最小规模"好过"完全不跑"，否则报告会因为零证据而生成不出来；
      · 否则按 remaining // 单任务预估成本 收敛，并夹在 [1, DEFAULT_MAX_STEPS] 之间。
    """
    if not budget_state:
        return DEFAULT_MAX_STEPS

    remaining = int(budget_state.get("remaining") or 0)
    if remaining <= 0:
        return 1  # 预算耗尽也要能跑最小规模

    # 单条检索任务的预估 token 成本（含工具返回 + LLM 判断）
    avg_task_cost = 4_000
    return max(1, min(DEFAULT_MAX_STEPS, remaining // avg_task_cost))


def assemble(raw: list[dict], *, max_steps: int = DEFAULT_MAX_STEPS) -> list[dict]:
    """补全步骤 id、顺序依赖与初始状态，并拒绝超长或成环的计划。

    【★ 移植精髓，别改】：`depends = [steps[-1]["id"]] if steps else []`
    也就是**模型没写 depends_on 时默认串行**，而不是默认全部并发。
    为什么这是精髓：默认全并发会让 N 条检索互相踩（同一份预算、同一个知识库、
    同一批候选去重竞争），而默认串行是安全的、行为可预期的。
    只有模型明确写了 depends_on 或者后续显式声明无依赖，才允许并发。

    【实现要点】
      1. 先做规模检查：`len(raw) > max_steps` → raise PlanError("...超过...")
         （注意报错文案里要含"超过"，单测用 match="超过" 断言）
      2. 逐条补全，缺 id 的按 s1/s2/s3... 生成
      3. 补 depends_on：显式写了就用，没写就取上一步的 id（默认串行）
      4. 校验依赖指向的步骤确实存在 → 不存在则 raise PlanError("...不存在的步骤...")
         （关键字"不存在的步骤"同样被单测断言）
      5. 全部初始状态设为 PENDING，run_id / error 等运行时字段留空
      6. 最后调用 _cyclic() 判环 → 成环则 raise PlanError("...循环依赖...")
      7. 返回装配好的步骤列表（每个元素是 plain dict，可安全进 checkpoint）

    【为什么用 plain dict 而不是 dataclass】
    这些步骤会写进 LangGraph state 并落 SQLite checkpoint，
    plain dict 的序列化最省心（不引入自定义 encoder）。
    """
    pass  # TODO(S6): 按上面 7 步实现，逐行对照参考实现 plan.py:22-51


def validate_plan(raw: list[dict], *, max_steps: int = DEFAULT_MAX_STEPS) -> list[dict]:
    """工具存在性 + 参数模型校验 + assemble 三合一。

    【与参考实现 validate() 的唯一差异】
    参数校验走 S1 建好的 `validate_params()`（app/tools/validation.py），
    所以"服务端校验"与"给模型看的 function schema"永远出自同一份 Pydantic 模型，
    不存在两套真相各自漂移的可能。

    【实现要点】
      1. 逐条用 `get_tool_registry().get(step["tool"])` 取 spec；
         未注册会由 registry 抛 ConfigurationError（工具存在性校验）
      2. 拿到 spec 后调 `validate_params(spec, step.get("params") or {})`；
         失败会抛 InvalidToolParams —— 节点侧统一降级处理
      3. 用 spec.name **规范化回写** `step["tool"]`：
         防止模型写别名（例如漏了前缀），保证下游调度拿到的是规范名
      4. 最后交给 `assemble(raw, max_steps=max_steps)` 做依赖补全 + 判环

    注意：函数名刻意叫 `validate_plan` 而不是 `validate`，
    避免与 S1 的 `validate_params` 在 import 处混淆。
    """
    pass  # TODO(S6): 按上面 4 步实现，对照参考实现 plan.py:54-60


def ready(steps: list[dict]) -> list[dict]:
    """返回当前可以立即下发的步骤（扇出入口）。

    【为什么返回 list 而不是 set】
    set 的迭代顺序不稳定，会让测试断言和执行顺序都变得不确定。
    保持 list（按 steps 原始顺序）便于测试与日志阅读。

    【实现要点】
    遍历 steps，逐个交给 `_is_ready(step, by_id)` 判定，收集通过者。
    by_id 是 {id: step} 的索引，先建好再遍历，避免 O(n²)。
    """
    pass  # TODO(S6): 对照参考实现 plan.py:63-65


def settle(steps: list[dict]) -> str:
    """把整轮 DAG 的状态汇总成一个状态（供调度循环决定继续还是收尾）。

    【判定优先级 —— 顺序不能变，否则语义会错】
      1. 还存在 FAILED → 返回 FAILED
         （失败优先于取消：能反映"真的出问题了"，而不是"用户主动跳过"）
      2. 还存在 _OPEN 状态：
         · 若**全部**未终结步骤都是 WAITING（且没有 QUEUED/RUNNING）
           → 返回 QUEUED（这就是"整轮在等人确认"的态，S9 依赖它）
         · 否则 → 返回 RUNNING
      3. 全部终结 → 返回 SUCCEEDED

    注意第 2 步的"全 WAITING 判 QUEUED"是参考实现里的**特别处理**，
    少了它，S9 的检索计划确认点在调度循环里会被误判成 RUNNING 而空转。
    """
    pass  # TODO(S6): 对照参考实现 plan.py:68-81


def needs_confirm(steps: list[dict]) -> bool:
    """是否需要人工确认（S9 的选择式检查点）。

    阈值是 `len(steps) > 1`：**单任务不打扰用户**。
    这条阈值判断是"两级 HITL"的基础 —— 只有多任务时才值得让人做选择，
    否则每次研究都弹一个"要不要执行这 1 条"的确认，体验是负分。
    """
    pass  # TODO(S6): len(steps) > 1


def cancel_remaining(steps: list[dict]) -> list[dict]:
    """取消尚未开始的步骤，已在进行中的不动。

    【只动 PENDING / WAITING】
    RUNNING 的步骤**不能杀** —— 它已经在线程池里跑了，
    强行改状态会让"实际执行中"和"状态说已取消"不一致，用户看到的重试也会重复执行。
    所以取消的语义是"不再下发新任务"，而不是"中断正在跑的任务"。

    返回新的列表（不要就地改传入对象，调用方可能还持有旧引用）。
    """
    pass  # TODO(S6): 对照参考实现 plan.py:88-92


def _is_ready(step: dict, by_id: dict[str, dict]) -> bool:
    """单个步骤是否就绪（三个条件全满足才算）。

    条件一：自己的状态是 PENDING（还没被下发过）
    条件二：没有 run_id —— 已有 run_id 说明正在执行或已完成，重复下发会跑两遍
    条件三：所有 depends_on 指向的步骤都是 SUCCEEDED
            （依赖 FAILED/CANCELED 时永远不就绪，这就是失败隔离的正确表现）
    """
    pass  # TODO(S6): 对照参考实现 plan.py:95-101


def _cyclic(steps: list[dict]) -> bool:
    """Kahn 算法判环，返回 bool。

    【★ 注意：返回 bool，不要顺手改成返回拓扑序】
    参考实现的契约就是"只告诉你有没有环"，返回序是另一种语义，
    改了会让调用方的判断逻辑跟着漂移。

    【为什么必须判环】
    有环时 `ready()` 永远返回空、`settle()` 永远返回 RUNNING →
    调度循环 while True 死转，前端永远停在"执行中"。

    【实现要点（Kahn）】
      1. 统计每个节点的入度（= len(depends_on)）
      2. 入度为 0 的进队列
      3. 反复取出队首、把它的后继入度减 1，减到 0 就入队
      4. 计数弹出的节点数；若 < 总节点数 → 存在环 → 返回 True

    自环（t1 depends_on t1）也要能被判出来 —— 入度处理会让它永远进不了队列。
    """
    pass  # TODO(S6): 对照参考实现 plan.py:104-122
