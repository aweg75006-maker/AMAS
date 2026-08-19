"""Harness 配置注册表（registry）。

职责：把 ``harness/manifests/*.json``（即 Harness Manifest，工作流蓝图）
加载并解析成内存中的数据结构（dataclass），再提供若干「取数」函数，
供**图谱构建、节点执行、工具绑定、运行追踪**等模块在运行时按需调用。

设计要点：
- manifest 是「外部化控制面板」，本文件是「唯一数据源」；
- 所有读取入口（get_harness_manifest / get_harness_node / get_prompt_template）
  都带 @lru_cache，整个进程只从磁盘解析一次，之后复用内存对象；
- 改了 manifest 文件后需重启进程才能生效（缓存不会自动失效）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.core.config import APP_DIR, settings
from app.core.exceptions import ConfigurationError


# harness 模块根目录：backend/app/harness
HARNESS_DIR = APP_DIR / "harness"
# manifest（工作流蓝图 JSON）所在目录：harness/manifests/
MANIFEST_DIR = HARNESS_DIR / "manifests"
# 提示词模板目录：harness/prompts/（节点用 prompt_id 从这里加载 .txt）
PROMPT_DIR = HARNESS_DIR / "prompts"


@dataclass(frozen=True)
class HarnessTool:
    """单个工具在 manifest 中的声明（一份「工具契约」）。

    注意「声明」与「实现」分离：这里只描述工具叫什么、超时/重试、
    输入/输出 schema；真正可调用的函数实现在 app/tools/ 里，
    由 tools/runtime.py 按 name 绑定到节点。
    """

    name: str                               # 工具名，对应 tools 注册表里的 key
    timeout_seconds: float | None = None    # 单次调用超时（秒），None 表示用全局默认
    max_retries: int | None = None          # 失败重试次数，None 表示用全局默认
    input_schema: str = ""                  # 输入参数描述，如 "query:string, knowledge_base_id:string"
    output_schema: str = ""                 # 输出结构描述，如 "documents:list"


@dataclass(frozen=True)
class HarnessNode:
    """manifest 里配置的一个工作流节点（planner/researcher/writer/...）。"""

    name: str                               # 节点名
    prompt_id: str = ""                     # 提示词模板 id，对应 prompts/{prompt_id}.txt；
                                           #   为空表示节点不走提示词（如 researcher 子图）
    model_type: str = "fast"                # 模型档位："fast"（快/便宜）或 "smart"（强/贵）
    timeout_seconds: float | None = None    # 节点整体超时（秒）
    max_retries: int | None = None          # 节点失败重试次数
    tools: tuple[HarnessTool, ...] = ()     # 该节点允许调用的工具集合（仅 researcher 等会用到）


@dataclass(frozen=True)
class HarnessManifest:
    """整份 Harness Manifest 解析后的内存表示（不可变）。"""

    workflow_id: str                        # 工作流标识，如 "research_report"
    workflow_version: str                   # 工作流版本戳（可追溯）
    prompt_version: str                     # 提示词版本戳
    node_policy_version: str                # 节点策略版本戳
    max_revisions: int                     # reviewer/refiner 最多迭代修订轮数
    nodes: dict[str, HarnessNode]           # 节点名 -> 节点配置


def _read_json(path: Path) -> dict[str, Any]:
    """读取并解析一个 JSON 配置文件；文件缺失或格式错误时抛出 ConfigurationError。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Harness manifest 不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Harness manifest JSON 格式无效：{path}") from exc


def _parse_tool(raw: str | dict[str, Any]) -> HarnessTool:
    """把一个工具的原始声明解析成 HarnessTool。

    manifest 里工具可以写成简写字符串（只有名字），
    也可以写成完整对象（含 timeout/retry/schema）。两种写法都支持。
    """
    if isinstance(raw, str):
        return HarnessTool(name=raw)
    return HarnessTool(
        name=raw.get("name", ""),
        timeout_seconds=raw.get("timeout_seconds"),
        max_retries=raw.get("max_retries"),
        input_schema=raw.get("input_schema", ""),
        output_schema=raw.get("output_schema", ""),
    )


@lru_cache
def get_harness_manifest() -> HarnessManifest:
    """加载并解析 Harness Manifest（带缓存，进程内只解析一次）。

    文件路径 = MANIFEST_DIR / settings.harness_manifest
    （默认即 harness/manifests/default_research.json）。
    把 JSON 里的 nodes 逐个解析成 HarnessNode，顶层版本戳各有兜底默认值。
    """
    data = _read_json(MANIFEST_DIR / settings.harness_manifest)
    # 逐个节点解析成 HarnessNode（工具列表经 _parse_tool 展开）
    nodes = {}
    for name, raw in data.get("nodes", {}).items():
        nodes[name] = HarnessNode(
            name=name,
            prompt_id=raw.get("prompt_id", ""),
            model_type=raw.get("model_type", "fast"),
            timeout_seconds=raw.get("timeout_seconds"),
            max_retries=raw.get("max_retries"),
            tools=tuple(_parse_tool(tool) for tool in raw.get("tools", [])),
        )
    # 组装成不可变的整体 manifest；各版本字段提供默认值兜底
    return HarnessManifest(
        workflow_id=data.get("workflow_id", "research_report"),
        workflow_version=data.get("workflow_version", settings.workflow_version),
        prompt_version=data.get("prompt_version", settings.prompt_version),
        node_policy_version=data.get("node_policy_version", settings.node_policy_version),
        max_revisions=int(data.get("max_revisions", 3) or 3),
        nodes=nodes,
    )


def get_harness_node(node_name: str) -> HarnessNode:
    """按节点名取单个节点的配置；未配置则抛 ConfigurationError。"""
    manifest = get_harness_manifest()
    try:
        return manifest.nodes[node_name]
    except KeyError as exc:
        raise ConfigurationError(f"Harness node 未配置：{node_name}") from exc


@lru_cache
def get_prompt_template(prompt_id: str) -> ChatPromptTemplate:
    """按 prompt_id 加载提示词模板（harness/prompts/{prompt_id}.txt）。

    返回 langchain 的 ChatPromptTemplate，供节点用 .format(...) 填充变量。
    带缓存：同一 prompt_id 只从磁盘读一次 ✅。
    """
    path = PROMPT_DIR / f"{prompt_id}.txt"
    try:
        template = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Prompt 文件不存在：{path}") from exc
    return ChatPromptTemplate.from_template(template)


def harness_fingerprint() -> dict[str, object]:
    """生成一份 manifest 快照，用于运行追踪/日志，记录「这次跑的是哪套配置版本」。"""
    manifest = get_harness_manifest()
    return {
        "workflow_id": manifest.workflow_id,
        "workflow_version": manifest.workflow_version,
        "prompt_version": manifest.prompt_version,
        "node_policy_version": manifest.node_policy_version,
        "harness_manifest": settings.harness_manifest,
        "max_revisions": manifest.max_revisions,
        "nodes": {
            name: {
                "prompt_id": node.prompt_id,
                "model_type": node.model_type,
                "timeout_seconds": node.timeout_seconds,
                "max_retries": node.max_retries,
                "tools": [
                    {
                        "name": tool.name,
                        "timeout_seconds": tool.timeout_seconds,
                        "max_retries": tool.max_retries,
                        "input_schema": tool.input_schema,
                        "output_schema": tool.output_schema,
                    }
                    for tool in node.tools
                ],
            }
            for name, node in manifest.nodes.items()
        },
    }
