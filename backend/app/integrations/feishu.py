"""
飞书自定义机器人通知。

向飞书群机器人 webhook 推送「文本」或「消息卡片」。
所有发送均为 best-effort：网络异常 / 飞书返回错误码只记日志，不抛出，
避免通知失败影响主流程（研究任务）。

文档：https://open.feishu.cn/document/client-docs/bot-v3/add-message
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger


logger = get_logger("iris.integrations.feishu")

DEFAULT_TIMEOUT_SECONDS = 8.0


class FeishuNotifier:
    """飞书自定义机器人通知器。

    webhook_url 缺省时读取 ``settings.feishu_webhook_url``，便于通过构造参数注入
    （测试或不同接收群场景）。``enabled`` 反映当前是否具备推送能力。
    """

    def __init__(self, webhook_url: Optional[str] = None) -> None:
        self.webhook_url = webhook_url or settings.feishu_webhook_url

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    async def send_text(self, text: str) -> bool:
        """发送纯文本消息。"""
        return await self._post({"msg_type": "text", "content": {"text": text}})

    async def send_card(
        self,
        title: str,
        content_markdown: str,
        *,
        url: Optional[str] = None,
        url_text: str = "查看详情",
    ) -> bool:
        """发送消息卡片（支持 markdown 正文，可选跳转按钮）。"""
        elements: list[dict] = [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": content_markdown},
            }
        ]
        if url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": url_text},
                            "type": "primary",
                            "url": url,
                        }
                    ],
                }
            )
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": title[:50]},
            },
            "elements": elements,
        }
        return await self._post({"msg_type": "interactive", "card": card})

    async def _post(self, payload: dict) -> bool:
        if not self.webhook_url:
            logger.info("feishu_notify_skipped_no_webhook")
            return False
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                resp = await client.post(self.webhook_url, json=payload)
                data = resp.json()
                if data.get("code", 0) != 0:
                    logger.warning(
                        "feishu_notify_rejected",
                        extra={
                            "code": data.get("code"),
                            "msg": data.get("msg"),
                            "url": self.webhook_url[:40],
                        },
                    )
                    return False
                return True
        except Exception as exc:  # best-effort：通知失败不应阻断主流程
            logger.warning(
                "feishu_notify_error",
                extra={"error": str(exc), "url": (self.webhook_url or "")[:40]},
            )
            return False
