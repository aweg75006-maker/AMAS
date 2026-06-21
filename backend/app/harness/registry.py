from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.core.config import APP_DIR, settings
from app.core.exceptions import ConfigurationError


HARNESS_DIR = APP_DIR / "harness"
MANIFEST_DIR = HARNESS_DIR / "manifests"
PROMPT_DIR = HARNESS_DIR / "prompts"


@dataclass(frozen=True)
class HarnessTool:
    name: str
    timeout_seconds: float | None = None
    max_retries: int | None = None
    input_schema: str = ""
    output_schema: str = ""


@dataclass(frozen=True)
class HarnessNode:
    name: str
    prompt_id: str = ""
    model_type: str = "fast"
    timeout_seconds: float | None = None
    max_retries: int | None = None
    tools: tuple[HarnessTool, ...] = ()


@dataclass(frozen=True)
class HarnessManifest:
    workflow_id: str
    workflow_version: str
    prompt_version: str
    node_policy_version: str
    max_revisions: int
    nodes: dict[str, HarnessNode]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Harness manifest 不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Harness manifest JSON 格式无效：{path}") from exc


def _parse_tool(raw: str | dict[str, Any]) -> HarnessTool:
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
    data = _read_json(MANIFEST_DIR / settings.harness_manifest)
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
    return HarnessManifest(
        workflow_id=data.get("workflow_id", "research_report"),
        workflow_version=data.get("workflow_version", settings.workflow_version),
        prompt_version=data.get("prompt_version", settings.prompt_version),
        node_policy_version=data.get("node_policy_version", settings.node_policy_version),
        max_revisions=int(data.get("max_revisions", 3) or 3),
        nodes=nodes,
    )


def get_harness_node(node_name: str) -> HarnessNode:
    manifest = get_harness_manifest()
    try:
        return manifest.nodes[node_name]
    except KeyError as exc:
        raise ConfigurationError(f"Harness node 未配置：{node_name}") from exc


@lru_cache
def get_prompt_template(prompt_id: str) -> ChatPromptTemplate:
    path = PROMPT_DIR / f"{prompt_id}.txt"
    try:
        template = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Prompt 文件不存在：{path}") from exc
    return ChatPromptTemplate.from_template(template)


def harness_fingerprint() -> dict[str, object]:
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
