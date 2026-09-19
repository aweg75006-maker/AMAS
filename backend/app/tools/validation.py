"""工具参数校验入口（S1）。

设计目标：**界面调用与 Agent 调用走同一套规则**。
不管参数是从前端表单来的、从 Planner 来的、还是从重试逻辑来的，
都要过 ``validate_params()`` 这一关，避免"同一个工具，走不同入口行为不一致"。

错误处理策略
============
校验失败抛出 ``InvalidToolParams``（一个语义明确的业务异常），而不是让
Pydantic 的 ``ValidationError`` 直接冒到上层。
- 原因 1：调用方（图节点）需要的是"能判断出这是参数问题、可以降级或回喂给模型"，
  而不是去解析 Pydantic 的错误树。
- 原因 2：``InvalidToolParams`` 的 message 是**给人看的**，可以直接写进日志或响应体。
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.core.logging import get_logger
from app.tools.registry import ToolSpec

logger = get_logger("iris.tools.validation")


class InvalidToolParams(Exception):
    """可直接展示给调用方的参数错误（参数缺失 / 类型不符 / 不满足约束）。"""


def validate_params(spec: ToolSpec, payload: dict[str, Any]) -> dict[str, Any]:
    """按工具自己声明的参数模型校验并规范化入参。

    返回值是**规范化后的新字典**，而不是原 payload 的改写，理由有三：

    1. 原 payload 可能来自图状态，就地改写有污染风险；
    2. ``model_dump(mode="json")`` 会把 datetime / Enum 等转成 JSON 原生类型，
       后面进快照、写日志、做 ``json.dumps`` 都不会炸；
    3. 模型的默认值 / 类型强转（如 ``"5"`` → ``5``）会体现在返回值里，
       下游 handler 拿到的一定是"合法且类型正确"的数据。

    未声明 ``params`` 的工具**原样放行** —— 这是 S1 期间的兼容开关：
    5 个研究工具不会在同一刻全部迁移完，旧工具必须还能跑。
    等到所有工具都声明了 ``params``，这个分支自然就成了兜底。
    """
    # 没有声明参数模型的工具：不做任何校验，直接把原始 payload 交给 handler
    if spec.params is None:
        logger.debug("工具 %s 未声明 params 模型，跳过参数校验", spec.name)
        return payload

    try:
        model = spec.params.model_validate(payload)
    except ValidationError as exc:
        # 只把第一条错误暴露出去：用户不需要一次看到 5 条校验失败，
        # 修一条看一条的体验反而更好，也更符合"可直接展示"的定位。
        message = f"{spec.name}: {_first_error(exc)}"
        logger.warning("工具参数校验失败：%s（原始参数键：%s）", message, sorted(payload.keys()))
        raise InvalidToolParams(message) from exc

    # mode="json" 保证返回值是可 JSON 序列化的原生类型
    return model.model_dump(mode="json")


def _first_error(exc: ValidationError) -> str:
    """从 Pydantic 的 ValidationError 里提炼出第一条错误，拼成人话。

    形制对齐参考实现 ``ai-picture-editor/backend/app/services/tools.py:116-119``：
    输出形如 ``query：String should have at least 1 character``。

    ``loc`` 是错误位置元组，例如 ``("query",)``；嵌套模型的 loc 会带多段
    （如 ``("document_context", 0)``），所以用 "." 拼起来而不是直接取 ``[0]``。
    极端情况下 loc 为空元组（模型级错误），这时用"参数"兜底，避免输出 "" 开头。
    """
    error = exc.errors()[0]
    field = ".".join(str(part) for part in error["loc"]) or "参数"
    return f"{field}：{error['msg']}"
