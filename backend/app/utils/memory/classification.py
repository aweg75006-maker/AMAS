"""记忆分类：按内容特征为记忆打类型标签，决定存储与检索路径。

类型定义（规则式，无需 LLM，零成本）：
- episodic  : 事件型记忆——"某次研究任务做了什么"，对应单次回合摘要；
- semantic  : 语义型记忆——"用户/领域的稳定知识、偏好、关系"，可跨任务复用；
- working   : 工作型记忆——"当前任务上下文"，生命周期短（本系统回合即落库，保留该类型以兼容检索语义）。

规则优先级：先看是否有长期知识信号（偏好/关系/态度词）→ semantic；
再看是否有工具/任务信号 → working；默认 episodic。

说明：分类结果目前主要用于冷层打标与多级检索的类型过滤，
不改变既有的"回合→摘要→向量索引"主链路。
"""

from typing import Optional

# 长期知识信号词：命中即认为该记忆含可跨任务复用的稳定知识
_SEMANTIC_KEYWORDS = (
    "偏好", "喜欢", "不喜欢", "讨厌", "习惯", "经常", "总是", "禁忌",
    "prefer", "favorite", "habit", "relation", "关系", "属于", "是.*的上级",
    "负责", "擅长", "精通",
)

# 工作型信号词：明确的单次任务/操作
_WORKING_KEYWORDS = (
    "搜索", "查询", "运行", "执行", "创建", "生成", "搜索工具", "调用工具",
    "search", "run", "execute", "tool",
)

# 类型常量
TYPE_EPISODIC = "episodic"
TYPE_SEMANTIC = "semantic"
TYPE_WORKING = "working"


def classify_memory(text: str, topic_tags: Optional[list] = None) -> str:
    """按文本（query/摘要）与标签分类记忆。

    Args:
        text: 待分类文本（query_gist 或摘要拼接文本）
        topic_tags: 回合主题标签（可为空）

    Returns:
        TYPE_EPISODIC / TYPE_SEMANTIC / TYPE_WORKING 之一
    """
    source = text or ""
    tags = " ".join(topic_tags or [])

    # 1. 长期知识信号 → semantic
    if any(kw in source or kw in tags for kw in _SEMANTIC_KEYWORDS):
        return TYPE_SEMANTIC

    # 2. 工作型信号 → working
    if any(kw in source for kw in _WORKING_KEYWORDS):
        return TYPE_WORKING

    # 3. 默认 → episodic
    return TYPE_EPISODIC
