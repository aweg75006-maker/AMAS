"""registry.py 的单元测试（用 pytest 跑）。

这个文件专门验证「Harness 配置注册表」能正常工作：
注册表负责把 harness/manifests/default_research.json 这份工作流蓝图
加载、解析成内存对象，再供运行时按需取用。

怎么跑（在 backend/ 目录下，用你平时的 python 环境）：
    python -m pytest tests/test_harness_registry.py -v

pytest 的规则：
- 每个 `def test_xxx()` 都是一个「测试用例」；
- 里面的 `assert 某条件` 就是「检查点」——条件为 True 用例通过，
  为 False 则用例失败（红色），说明对应功能坏了。
"""

# 被测试的四个函数，都来自 app/harness/registry.py：
#   get_harness_manifest   —— 加载并解析整份 manifest（带缓存，进程内只解析一次）
#   get_harness_node       —— 按节点名取单个节点的配置
#   get_prompt_template    —— 按 prompt_id 加载 harness/prompts/*.txt 提示词模板
#   harness_fingerprint    —— 生成一份 manifest 快照，用于运行追踪/日志
from app.harness.registry import (
    get_harness_manifest,
    get_harness_node,
    get_prompt_template,
    harness_fingerprint,
)


def test_default_harness_manifest_maps_current_business_flow():
    """用例1：验证 manifest「能正确加载、并且内容对得上业务设计」。

    这是最核心的「正确加载」测试——确认从 JSON 读出来的内存对象
    包含预期的节点、提示词 id、修订轮数，以及 researcher 节点绑定的工具。
    """
    # 调一次注册表，把整份 manifest 解析成内存对象
    manifest = get_harness_manifest()

    # 检查工作流标识是 "research_report"
    assert manifest.workflow_id == "research_report"
    # 检查节点集合至少包含这 5 个（planner/researcher/writer/reviewer/refiner）
    assert set(manifest.nodes) >= {
        "planner",
        "researcher",
        "writer",
        "reviewer",
        "refiner",
    }
    # 检查 planner 节点绑定的提示词 id 是 planner.research.v1
    # （对应 harness/prompts/planner.research.v1.txt 那个文件）
    assert manifest.nodes["planner"].prompt_id == "planner.research.v1"
    # 检查 reviewer/refiner 最多修订轮数 = 3（对应 JSON 里的 max_revisions）
    assert manifest.max_revisions == 3
    # 把 researcher 节点允许用的工具，整理成 {工具名: 工具对象} 的字典，方便下面查
    researcher_tools = {tool.name: tool for tool in manifest.nodes["researcher"].tools}
    # researcher 必须能调用「网络搜索」工具
    assert "web.search" in researcher_tools
    # 并且该工具的超时设置必须是 45 秒（验证 tool 的字段也正确解析了）
    assert researcher_tools["web.search"].timeout_seconds == 45
    # researcher 还必须能调用这两个 RAG 相关工具
    assert "rag.retrieve_candidates" in researcher_tools
    assert "web.retrieve_candidates" in researcher_tools


def test_prompt_template_can_render_planner_prompt():
    """用例2：验证「提示词模板能从 .txt 文件加载、并正确填充变量」。

    确认 get_prompt_template 真的读到了 harness/prompts/planner.research.v1.txt，
    且用 query/critique/memory_context 三个变量渲染后，模板里的占位内容被正确替换。
    """
    # 取 planner 节点的配置，再拿它的 prompt_id 去加载提示词模板
    node = get_harness_node("planner")
    # .format(...) 把模板里的 {query} {critique} {memory_context} 占位符替换成实际值
    prompt = get_prompt_template(node.prompt_id).format(
        query="测试问题",
        critique="",
        memory_context="无历史",
    )

    # 渲染后的文本里应该包含了我们传入的 query 值
    assert "测试问题" in prompt
    # 并且模板原本就写死的指令文案「只返回关键词」也应该出现在结果里
    # （说明加载的是 planner 这份模板，而不是别的）
    assert "只返回关键词" in prompt


def test_harness_fingerprint_contains_node_prompt_ids():
    """用例3：验证「指纹快照」能完整记录节点配置。

    harness_fingerprint() 会生成一份 manifest 快照，运行时写进日志/追踪，
    用来记录「这次请求跑的是哪套配置版本」。这里确认快照里的关键字段对得上。
    """
    # 生成快照
    fingerprint = harness_fingerprint()

    # 快照里的 workflow_id 应为 "research_report"
    assert fingerprint["workflow_id"] == "research_report"
    # 快照里的修订轮数应为 3
    assert fingerprint["max_revisions"] == 3
    # 快照里的 nodes 下，writer 节点的 prompt_id 应为 writer.report.v1
    assert fingerprint["nodes"]["writer"]["prompt_id"] == "writer.report.v1"
