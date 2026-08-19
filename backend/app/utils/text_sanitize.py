"""文本清洗工具：剥离「孤立代理字符（lone surrogate）」。

背景（2026-08-19 实际事故）：
    用户从终端输入 / 粘贴的研究问题里混入了不可见的孤立代理字符
    （U+D800~U+DFFF，非法 Unicode 标量值）。它随 query 拼进提示词后，
    openai SDK 在序列化请求体时会执行 ``json.dumps(...).encode('utf-8')``
    （openai/_utils/_json.py 的 openapi_dumps），直接抛出：

        UnicodeEncodeError: 'utf-8' codec can't encode characters
        in position 55-56: surrogates not allowed

    该错误会让 planner 节点重试全部耗尽并中止整个工作流（重试用的是
    同一个脏 query，属于确定性失败，重试必然无效）。

    同理，LLM 返回内容、网页检索结果、RAG 文档块里也可能混入这类脏字符，
    任何后续 encode('utf-8') / json.dumps(ensure_ascii=False) /
    hashlib.sha256(text.encode()) 都会被它炸掉。

设计：
    在「LLM 调用边界」（budget_enforcer.wrap_llm_call）、
    「节点执行边界」（runtime.wrap_node）、「用户输入边界」（demo/API 入口）
    统一调用 strip_surrogates()，把脏字符在进入编码路径之前剥掉。
    合法的代理对（如 emoji）不受影响——CPython 的 utf-8 编码器会自动
    把成对代理合成合法字符，只有「落单」的代理才会被丢弃。
"""

from __future__ import annotations


def strip_surrogates(text: str) -> str:
    """剥离字符串中的孤立代理字符（无法编码为 UTF-8 的非法字符）。

    - 干净文本走零开销快速路径（先尝试严格编码，成功即原样返回）；
    - 含脏字符时用 ``encode('utf-8', 'ignore')`` 重新编解码，仅丢弃
      无法编码的孤立代理，其余内容（含合法 emoji）保持不变；
    - 非字符串输入原样返回，方便在不确定类型的字段上安全调用。
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        text.encode("utf-8")   # 快速路径：干净文本直接返回
        return text
    except UnicodeEncodeError:
        # 仅丢弃无法编码的字符（孤立代理等）
        return text.encode("utf-8", "ignore").decode("utf-8")


def sanitize_state_strings(state: dict) -> dict:
    """清洗 AgentState 顶层字符串字段（query / critique / human_input 等）。

    只处理「顶层 str 值」，不递归嵌套结构——因为嵌套列表/字典里
    的问题数据（如 LLM 返回）已在各自的生产边界被清洗过；
    这里是兜底，保证进入节点的顶层文本永远可安全编码。
    返回原 dict（就地修改），方便调用方连续使用。
    """
    for key, value in state.items():
        if isinstance(value, str):
            state[key] = strip_surrogates(value)
    return state
