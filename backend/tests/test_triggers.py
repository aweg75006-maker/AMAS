"""P3 被动触发（Webhook + Cron）相关测试。"""
import asyncio
from datetime import datetime

import pytest

import app.integrations.feishu as feishu_mod
from app.core.config import settings
from app.services.trigger_scheduler import compute_next_run_at


def _coro_ok():
    async def _impl():
        return {"status": "succeeded"}

    return _impl()


# ─── 飞书通知器（不触网）───


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _RecordingAsyncClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, **kwargs):
        self.calls.append((url, json))
        return _FakeResponse({"code": 0, "msg": "success"})


@pytest.fixture
def fake_httpx(monkeypatch):
    fake = _RecordingAsyncClient()
    monkeypatch.setattr(feishu_mod.httpx, "AsyncClient", lambda *a, **k: fake)
    return fake


def test_feishu_disabled_without_webhook_returns_false(fake_httpx, monkeypatch):
    monkeypatch.setattr(settings, "feishu_webhook_url", None)
    notifier = feishu_mod.FeishuNotifier(webhook_url=None)
    assert notifier.enabled is False
    assert fake_httpx.calls == []
    # 不应发送任何请求
    result = asyncio.run(notifier.send_text("hi"))
    assert result is False
    assert fake_httpx.calls == []


def test_feishu_send_text_posts_to_webhook(fake_httpx):
    notifier = feishu_mod.FeishuNotifier(webhook_url="https://example.com/hook")
    ok = asyncio.run(notifier.send_text("hello"))
    assert ok is True
    assert len(fake_httpx.calls) == 1
    url, payload = fake_httpx.calls[0]
    assert url == "https://example.com/hook"
    assert payload == {"msg_type": "text", "content": {"text": "hello"}}


def test_feishu_send_card_builds_interactive_card(fake_httpx):
    notifier = feishu_mod.FeishuNotifier(webhook_url="https://example.com/hook")
    ok = asyncio.run(
        notifier.send_card("研究完成", "**摘要**", url="https://x/y", url_text="打开")
    )
    assert ok is True
    _url, payload = fake_httpx.calls[0]
    assert payload["msg_type"] == "interactive"
    assert payload["card"]["header"]["title"]["content"] == "研究完成"
    assert payload["card"]["elements"][0]["text"]["content"] == "**摘要**"
    # 含跳转按钮
    assert payload["card"]["elements"][1]["actions"][0]["url"] == "https://x/y"


def test_feishu_handles_rejected_response(fake_httpx, monkeypatch):
    # 模拟飞书返回错误码
    class _RejectClient(_RecordingAsyncClient):
        async def post(self, url, json=None, **kwargs):
            self.calls.append((url, json))
            return _FakeResponse({"code": 19021, "msg": "sign match fail"})

    reject = _RejectClient()
    monkeypatch.setattr(feishu_mod.httpx, "AsyncClient", lambda *a, **k: reject)
    notifier = feishu_mod.FeishuNotifier(webhook_url="https://example.com/hook")
    ok = asyncio.run(notifier.send_text("hi"))
    assert ok is False


import asyncio  # noqa: E402  (放在使用处之后，保持可读性)


# ─── 调度时间计算 ───


def test_compute_next_run_interval():
    base = 1_000_000.0
    assert compute_next_run_at({"type": "interval", "seconds": 3600}, base) == base + 3600
    assert compute_next_run_at({"type": "interval", "seconds": 0}, base) is None


def test_compute_next_run_daily_rolls_to_next_day():
    dt = datetime(2026, 1, 1, 10, 0, 0)
    nxt = compute_next_run_at({"type": "daily", "hour": 9, "minute": 0}, dt.timestamp())
    assert datetime.fromtimestamp(nxt) == datetime(2026, 1, 2, 9, 0, 0)


def test_compute_next_run_daily_later_same_day():
    dt = datetime(2026, 1, 1, 8, 0, 0)
    nxt = compute_next_run_at({"type": "daily", "hour": 9, "minute": 30}, dt.timestamp())
    assert datetime.fromtimestamp(nxt) == datetime(2026, 1, 1, 9, 30, 0)


def test_compute_next_run_cron_daily():
    dt = datetime(2026, 1, 1, 10, 0, 0)
    nxt = compute_next_run_at({"type": "cron", "expr": "0 9 * * *"}, dt.timestamp())
    assert datetime.fromtimestamp(nxt) == datetime(2026, 1, 2, 9, 0, 0)


def test_compute_next_run_cron_every_15_min():
    dt = datetime(2026, 1, 1, 10, 7, 0)
    nxt = compute_next_run_at({"type": "cron", "expr": "*/15 * * * *"}, dt.timestamp())
    assert datetime.fromtimestamp(nxt) == datetime(2026, 1, 1, 10, 15, 0)


def test_compute_next_run_cron_invalid_expr():
    assert compute_next_run_at({"type": "cron", "expr": "bad expr"}, 1_000_000.0) is None
    assert compute_next_run_at({"type": "unknown"}, 1_000_000.0) is None


# ─── Webhook 接口 ───


def test_webhook_disabled_without_token(client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_trigger_token", None)
    resp = client.post("/api/triggers/webhook", json={"token": "x", "query": "q"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "WEBHOOK_TRIGGER_DISABLED"


def test_webhook_rejects_bad_token(client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_trigger_token", "test-token")
    resp = client.post("/api/triggers/webhook", json={"token": "wrong", "query": "q"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "WEBHOOK_TRIGGER_UNAUTHORIZED"


def test_webhook_accepts_and_dispatches(client, monkeypatch):
    monkeypatch.setattr(settings, "webhook_trigger_token", "test-token")
    captured = {}

    async def fake_run(*, query, context, **kwargs):
        captured["query"] = query
        captured["context"] = context
        return {"status": "succeeded", "run_id": "run_x", "final_report": "R", "error": None}

    monkeypatch.setattr("app.api.routes_triggers.run_research_and_notify", fake_run)

    resp = client.post(
        "/api/triggers/webhook",
        json={"token": "test-token", "query": "研究X", "notify": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["trigger_id"]
    # 后台任务应在请求周期内执行完毕（TestClient 会跑完 background tasks）
    assert captured.get("query") == "研究X"
    assert captured["context"].auth_source == "webhook"


# ─── Cron 任务管理接口 ───


AUTH_HEADERS = {"X-Tenant-ID": "default", "X-User-ID": "tester"}


def test_cron_job_crud_and_run_now(client, monkeypatch):
    # create
    resp = client.post(
        "/api/triggers/cron/jobs",
        json={"query": "每日简报", "schedule": {"type": "interval", "seconds": 3600}},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    job = resp.json()["job"]
    job_id = job["job_id"]
    assert job["enabled"] is True
    assert job["next_run_at"] is not None

    # list
    resp = client.get("/api/triggers/cron/jobs", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert any(j["job_id"] == job_id for j in resp.json()["items"])

    # get
    resp = client.get(f"/api/triggers/cron/jobs/{job_id}", headers=AUTH_HEADERS)
    assert resp.status_code == 200

    # update
    resp = client.patch(
        f"/api/triggers/cron/jobs/{job_id}",
        json={"enabled": False, "query": "每日简报v2"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["job"]["enabled"] is False
    assert resp.json()["job"]["query"] == "每日简报v2"

    # run now（立即执行，绕过调度）
    monkeypatch.setattr(
        "app.api.routes_triggers.run_research_and_notify",
        lambda **kwargs: _coro_ok(),
    )
    resp = client.post(f"/api/triggers/cron/jobs/{job_id}/run", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    # delete
    resp = client.delete(f"/api/triggers/cron/jobs/{job_id}", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    resp = client.get(f"/api/triggers/cron/jobs/{job_id}", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_cron_create_rejects_invalid_schedule(client):
    resp = client.post(
        "/api/triggers/cron/jobs",
        json={"query": "x", "schedule": {"type": "cron", "expr": "bad"}},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CRON_SCHEDULE_INVALID"
