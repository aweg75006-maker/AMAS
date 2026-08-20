"""分层记忆系统核心单元测试（pytest）。

覆盖范围（Phase 1：冷层存储 + 生命周期管理）：
- ColdMemoryStore：增删查、冷热标记、保护、候选扫描、模糊检索
- MemoryLifecycleManager：归档 / 升温 / 批量归档 / 遗忘 / 保护语义

隔离策略：
- 所有用例使用独立临时 SQLite 文件（tmp_path fixture），不碰真实数据；
- 温层（Chroma）用 FakeRetriever 替身，只验证"调用了对应索引/删除操作"，
  不连接真实 ChromaDB / DashScope，保证测试离线可跑。

怎么跑（在 backend/ 目录）：
    python -m pytest tests/test_memory_system.py -v
"""

import pytest

from app.utils.memory.cold_store import (
    ColdMemoryStore,
    LABEL_HOT,
    LABEL_COLD,
)
from app.utils.memory.graph_store import GraphMemoryStore
from app.utils.memory.lifecycle import MemoryLifecycleManager


# ─── 温层替身 ───

class FakeRetriever:
    """记录调用的温层替身：index / delete_turn 只记账，不真正向量化。"""

    def __init__(self):
        self.indexed: list[str] = []    # 已索引的 id
        self.deleted: list[str] = []    # 已删除的 id

    def index(self, summary) -> bool:
        self.indexed.append(summary.turn_id)
        return True

    def delete_turn(self, turn_id: str) -> bool:
        self.deleted.append(turn_id)
        return True


@pytest.fixture
def store(tmp_path):
    """独立临时冷层存储。"""
    return ColdMemoryStore(db_path=tmp_path / "test_memory.db")


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    """注入 FakeRetriever 的生命周期管理器。"""
    mgr = MemoryLifecycleManager(cold_store=ColdMemoryStore(db_path=tmp_path / "test_memory.db"))
    fake = FakeRetriever()
    mgr._retriever = fake
    mgr._retriever_ok = True
    return mgr, fake


# ─── ColdMemoryStore ───

def test_add_and_get(store):
    """写入后可读回，content 保持 dict 结构。"""
    store.add("m1", "t1", "episodic", {"query_gist": "查一下", "key_facts": ["A"]}, "high")
    rec = store.get_by_id("m1")
    assert rec is not None
    assert rec["thread_id"] == "t1"
    assert rec["event_type"] == "episodic"
    assert rec["content"]["query_gist"] == "查一下"
    assert rec["importance"] == "high"
    assert rec["cold_label"] == LABEL_HOT
    assert rec["protected"] == 0


def test_search_by_thread(store):
    """按线程过滤 + 倒序返回。"""
    store.add("m1", "t1", "episodic", {"query_gist": "one"})
    store.add("m2", "t1", "semantic", {"query_gist": "two"})
    store.add("m3", "t2", "episodic", {"query_gist": "three"})
    rows = store.search(thread_id="t1")
    assert [r["id"] for r in rows] == ["m2", "m1"]
    rows = store.search(thread_id="t2")
    assert [r["id"] for r in rows] == ["m3"]


def test_cold_hot_lifecycle(store):
    """冷热标记往返。"""
    store.add("m1", "t1", "episodic", {"query_gist": "x"})
    store.mark_cold("m1")
    assert store.get_by_id("m1")["cold_label"] == LABEL_COLD
    store.mark_hot("m1")
    assert store.get_by_id("m1")["cold_label"] == LABEL_HOT


def test_protected_memory_never_candidate(store):
    """受保护记忆不会出现在归档候选里。"""
    store.add("m1", "t1", "episodic", {"query_gist": "x"})
    store.mark_protected("m1")
    store.add("m2", "t1", "episodic", {"query_gist": "y"})
    # 把 last_accessed 拨到很久以前，确保会被扫描到
    store.update_access("m2")
    with store._connect() as conn:  # 直接改时间模拟"很久没访问"
        conn.execute("UPDATE events SET last_accessed='2000-01-01T00:00:00' WHERE id IN ('m1','m2')")
    candidates = store.get_cold_candidates(days=10)
    assert [c["id"] for c in candidates] == ["m2"]


def test_search_cold_like(store):
    """冷层模糊检索 + 不命中热层。"""
    store.add("m1", "t1", "episodic", {"query_gist": "北京天气"})
    store.mark_cold("m1")
    store.add("m2", "t1", "episodic", {"query_gist": "上海房价"})
    hits = store.search_cold("北京")
    assert [h["id"] for h in hits] == ["m1"]


def test_get_cold_records_only_cold(store):
    """遗忘候选只含冷归档且超期。"""
    store.add("m1", "t1", "episodic", {"query_gist": "x"})
    store.mark_cold("m1")
    store.add("m2", "t1", "episodic", {"query_gist": "y"})  # 热记忆不算
    with store._connect() as conn:
        conn.execute("UPDATE events SET created_at='2000-01-01T00:00:00'")
    old = store.get_cold_records(days=30)
    assert [c["id"] for c in old] == ["m1"]


# ─── MemoryLifecycleManager ───

def test_archive_removes_vector_and_marks_cold(lifecycle):
    """归档 = 删温层索引 + 冷层标 cold。"""
    mgr, fake = lifecycle
    mgr.cold.add("m1", "t1", "episodic", {"query_gist": "x"})
    mgr.archive("m1")
    assert "m1" in fake.deleted
    assert mgr.cold.get_by_id("m1")["cold_label"] == LABEL_COLD


def test_warm_up_reindexes_and_marks_hot(lifecycle):
    """升温 = 按冷层记录重建索引 + 标 hot。"""
    mgr, fake = lifecycle
    content = {"query_gist": "苹果公司", "key_facts": ["库克"], "conclusions": [], "topic_tags": ["科技"]}
    mgr.cold.add("m1", "t1", "episodic", content)
    mgr.cold.mark_cold("m1")
    mgr.warm_up("m1")
    assert "m1" in fake.indexed
    assert mgr.cold.get_by_id("m1")["cold_label"] == LABEL_HOT


def test_scheduled_archive_skips_protected(lifecycle):
    """批量归档跳过受保护记忆。"""
    mgr, fake = lifecycle
    mgr.cold.add("p1", "t1", "episodic", {"query_gist": "protected"})
    mgr.cold.mark_protected("p1")
    mgr.cold.add("m2", "t1", "episodic", {"query_gist": "normal"})
    with mgr.cold._connect() as conn:
        conn.execute("UPDATE events SET last_accessed='2000-01-01T00:00:00'")
    archived = mgr.scheduled_archive()
    assert archived == ["m2"]
    assert mgr.cold.get_by_id("p1")["cold_label"] == LABEL_HOT


def test_scheduled_forget_only_old_cold(lifecycle):
    """遗忘只删超期冷归档，热记忆/受保护的不删。"""
    mgr, fake = lifecycle
    mgr.cold.add("old1", "t1", "episodic", {"query_gist": "old"})
    mgr.cold.mark_cold("old1")
    mgr.cold.add("protected", "t1", "episodic", {"query_gist": "p"})
    mgr.cold.mark_cold("protected")
    mgr.cold.mark_protected("protected")
    mgr.cold.add("hot", "t1", "episodic", {"query_gist": "h"})
    with mgr.cold._connect() as conn:
        conn.execute("UPDATE events SET created_at='2000-01-01T00:00:00'")
    deleted = mgr.scheduled_forget()
    assert deleted == ["old1"]
    assert mgr.cold.get_by_id("old1") is None
    assert mgr.cold.get_by_id("protected") is not None
    assert mgr.cold.get_by_id("hot") is not None


# ─── 分类（Phase 2）───

def test_classify_semantic_on_preference():
    """含偏好/关系等长期知识信号 → semantic。"""
    from app.utils.memory.classification import classify_memory
    assert classify_memory("用户偏好使用 Python 编写脚本") == "semantic"
    assert classify_memory("", topic_tags=["关系"]) == "semantic"


def test_classify_working_on_tool():
    """含工具/任务信号 → working。"""
    from app.utils.memory.classification import classify_memory
    assert classify_memory("使用搜索工具查询最新论文") == "working"


def test_classify_episodic_default():
    """普通研究回合 → episodic。"""
    from app.utils.memory.classification import classify_memory
    assert classify_memory("量子计算的容错阈值是多少") == "episodic"


# ─── 记录器（Phase 2）───

def test_recorder_roundtrip(tmp_path):
    """记录器把 TurnSummary 路由进冷层：id/类型/重要度/内容完整。"""
    from app.utils.summarizer import TurnSummary
    from app.utils.memory.recorder import MemoryRecorder

    store = ColdMemoryStore(db_path=tmp_path / "test_memory.db")
    recorder = MemoryRecorder(cold_store=store)
    summary = TurnSummary(
        turn_id="t100", turn_number=5,
        query_gist="用户偏好用 Python 做数据处理",
        key_facts=["pandas 熟悉"], conclusions=["选型 Python"], topic_tags=["编程"],
        importance_score=0.85,
    )
    mid = recorder.record_summary("sess1", summary)
    assert mid == "t100"
    rec = store.get_by_id("t100")
    assert rec["thread_id"] == "sess1"
    assert rec["event_type"] == "semantic"      # 命中偏好词
    assert rec["importance"] == "high"          # 0.85 → high
    assert rec["content"]["turn_number"] == 5


def test_recorder_importance_mapping(tmp_path):
    """重要度三档映射。"""
    from app.utils.summarizer import TurnSummary
    from app.utils.memory.recorder import MemoryRecorder

    store = ColdMemoryStore(db_path=tmp_path / "test_memory.db")
    recorder = MemoryRecorder(cold_store=store)
    for tid, score, expect in [("a", 0.8, "high"), ("b", 0.5, "medium"), ("c", 0.2, "low")]:
        s = TurnSummary(turn_id=tid, turn_number=1, query_gist="x", importance_score=score)
        recorder.record_summary("s", s)
        assert store.get_by_id(tid)["importance"] == expect


# ─── 压缩调度器接入（Phase 2 集成）───

def test_scheduler_writes_cold_layer(tmp_path, monkeypatch):
    """调度器压缩后，冷层出现对应记忆记录（与温层索引同 id）。"""
    import asyncio
    from app.utils.summarizer import TurnSummary
    from app.utils.compression_scheduler import CompressionScheduler
    from app.utils.memory.cold_store import ColdMemoryStore

    # 用临时冷层替换全局记录器
    store = ColdMemoryStore(db_path=tmp_path / "test_memory.db")
    from app.utils.memory import recorder as recorder_mod
    fake_recorder = recorder_mod.MemoryRecorder(cold_store=store)
    monkeypatch.setattr(recorder_mod, "_recorder", fake_recorder)

    class FakeSummarizer:
        def summarize(self, turn):
            class R:
                success = True
                tokens_saved = 10
                summary = TurnSummary(
                    turn_id=turn.get("turn_id"), turn_number=turn.get("turn_number", 0),
                    query_gist=turn.get("query", "?")[:50],
                )
            return R()

    sched = CompressionScheduler(redis_client=None)
    sched._summarizer = FakeSummarizer()
    # 跳过融合与真实温层索引
    class FakeRetriever:
        _summaries = {}
        def index(self, summary): return True
        def delete_turn(self, tid): return True
    sched._retriever = FakeRetriever()
    sched._trigger_fusion = lambda sid: ""

    turns = [
        {"turn_id": f"t{i}", "turn_number": i, "query": f"第{i}个问题"}
        for i in range(5)
    ]
    asyncio.run(sched.schedule("sessX", turns, window_k=3))
    # 窗口外 2 个 turn 应写入冷层
    assert store.get_by_id("t0") is not None
    assert store.get_by_id("t1") is not None
    assert store.get_by_id("t3") is None  # 窗口内不压缩
    assert store.get_by_id("t0")["thread_id"] == "sessX"


# ─── 图谱存储（Phase 3）───

@pytest.fixture
def graph(tmp_path):
    """独立临时图谱库。"""
    from app.utils.memory.graph_store import GraphMemoryStore
    return GraphMemoryStore(db_path=tmp_path / "test_graph.db")


def test_graph_add_and_query_by_relation(graph):
    """写入三元组后可按键查询。"""
    graph.add_relationship("张三", "负责", "前端组")
    graph.add_relationship("张三", "喜欢", "Python")
    rows = graph.search_by_relation("负责")
    assert len(rows) == 1
    assert rows[0]["subject"] == "张三" and rows[0]["object"] == "前端组"
    assert graph.count() == 2


def test_graph_search_relations_1hop(graph):
    """1 跳查询：模糊匹配节点或关系。"""
    graph.add_relationship("李四", "上级", "张三")
    graph.add_relationship("王五", "同事", "李四")
    # 按节点命中
    hits = graph.search_relations("张三", depth=1)
    assert len(hits) == 1
    assert hits[0]["nodes"] == ["李四", "张三"]
    assert hits[0]["relations"] == ["上级"]
    # 按关系命中
    hits = graph.search_relations("上级", depth=1)
    assert len(hits) == 1


def test_graph_search_relations_substring(graph):
    """模糊匹配必须是子串包含（修复：% 误卷入比较串导致退化为精确匹配）。"""
    graph.add_relationship("用户", "身份", "前端组负责人")
    graph.add_relationship("用户", "偏好", "使用 Python 进行数据处理")
    # 查询词是实体/关系的一部分也应命中（等价 SQL LIKE '%前端%'）
    hits = graph.search_relations("前端", depth=1)
    assert len(hits) == 1
    assert hits[0]["nodes"] == ["用户", "前端组负责人"]
    hits = graph.search_relations("Python", depth=1)
    assert len(hits) == 1
    assert hits[0]["relations"] == ["偏好"]


def test_graph_search_relations_empty_query(graph):
    """空查询词直接返回空，不误命中全部边。"""
    graph.add_relationship("A", "喜欢", "B")
    assert graph.search_relations("", depth=1) == []


def test_graph_search_relations_2hop(graph):
    """2 跳查询：沿邻接扩展。"""
    graph.add_relationship("李四", "上级", "张三")
    graph.add_relationship("张三", "负责", "前端组")
    hits = graph.search_relations("李四", depth=2)
    assert len(hits) == 2  # 李四→张三 与 李四→张三→前端组
    depth2 = [h for h in hits if len(h["nodes"]) == 3]
    assert depth2 and depth2[0]["nodes"] == ["李四", "张三", "前端组"]


def test_graph_dedup_and_delete(graph):
    """重复三元组不重复插入；删除生效。"""
    graph.add_relationship("A", "喜欢", "B")
    graph.add_relationship("A", "喜欢", "B")
    assert graph.count() == 1
    graph.delete_relationship("A", "喜欢", "B")
    assert graph.count() == 0


# ─── 图谱抽取（Phase 3）───

@pytest.fixture
def extractor(tmp_path):
    """注入 fake LLM 的抽取器。"""
    from app.utils.memory.extraction import KnowledgeExtractor

    store = ColdMemoryStore(db_path=tmp_path / "test_memory.db")
    graph = GraphMemoryStore(db_path=tmp_path / "test_graph.db")
    ex = KnowledgeExtractor(graph_store=graph, cold_store=store)
    return ex, store, graph


async def _seed_memories(store, n: int, query: str = "用户偏好使用 Python"):
    """预置 n 条记忆。"""
    for i in range(n):
        store.add(f"m{i}", "sessK", "episodic", {
            "query_gist": query, "key_facts": [f"事实{i}"], "conclusions": [],
        })


def test_consolidate_extracts_and_protects(extractor, monkeypatch):
    """抽取成功 → 写图谱 + 来源记忆打保护标。"""
    import asyncio
    ex, store, graph = extractor
    asyncio.run(_seed_memories(store, 10))

    # 注入 fake LLM：返回 2 个三元组
    async def fake_ainvoke(self, messages):
        class Resp:
            content = '[{"subject":"用户","relation":"喜欢","object":"Python"},{"subject":"用户","relation":"习惯","object":"晚上跑步"}]'
        return Resp()
    monkeypatch.setattr("app.utils.llm.get_llm", lambda t: type("L", (), {"ainvoke": fake_ainvoke})())

    result = asyncio.run(ex.consolidate_thread("sessK"))
    assert result["consolidated"] == 2
    assert graph.count() == 2
    assert len(graph.search_by_relation("喜欢")) == 1
    # 来源记忆已保护
    assert store.get_by_id("m0")["protected"] == 1


def test_consolidate_skips_below_threshold(extractor, monkeypatch):
    """记忆太少不触发抽取。"""
    import asyncio
    ex, store, graph = extractor
    asyncio.run(_seed_memories(store, 3))  # < memory_consolidate_min_turns(10)
    called = {"n": 0}

    async def fake_ainvoke(self, messages):
        called["n"] += 1
        class Resp:
            content = '[]'
        return Resp()
    monkeypatch.setattr("app.utils.llm.get_llm", lambda t: type("L", (), {"ainvoke": fake_ainvoke})())

    result = asyncio.run(ex.consolidate_thread("sessK"))
    assert result["skipped"] is True
    assert called["n"] == 0  # LLM 未被调用
    assert graph.count() == 0


def test_consolidate_noise_filtered(extractor, monkeypatch):
    """LLM 返回噪音（非 dict / 空字段）时丢弃。"""
    import asyncio
    ex, store, graph = extractor
    asyncio.run(_seed_memories(store, 10, query="查一下RAG是什么"))

    async def fake_ainvoke(self, messages):
        class Resp:
            content = '[{"subject":"","relation":"喜欢","object":"Python"}, "噪音", {"subject":"用户","relation":"喜欢","object":"Python"}]'
        return Resp()
    monkeypatch.setattr("app.utils.llm.get_llm", lambda t: type("L", (), {"ainvoke": fake_ainvoke})())

    result = asyncio.run(ex.consolidate_thread("sessK"))
    assert result["consolidated"] == 1  # 只写入合法三元组
    assert graph.count() == 1


# ─── 多级检索（Phase 4）───

class FakeVecRetriever:
    """温层替身：可配置返回结果或抛异常。"""
    def __init__(self, turns=None, error=False):
        self.turns = turns or []
        self.error = error
    def retrieve(self, query, top_k=3):
        if self.error:
            raise RuntimeError("vector down")
        from app.utils.cross_turn_retriever import RetrievalResult
        return RetrievalResult(query=query, retrieved_turns=self.turns, context_text="")


def _make_turn(tid: str):
    """构造一个检索结果替身。"""
    from app.utils.cross_turn_retriever import RetrievedTurn
    return RetrievedTurn(
        turn_id=tid, turn_number=1, query_gist=f"历史问题{tid}",
        key_facts=[], conclusions=[], topic_tags=[], importance_score=0.5,
        relevance_score=0.9, summary_text=f"摘要 {tid}",
    )


class FakeRedis:
    """Redis 替身：内存字典 + 调用计数。"""
    def __init__(self):
        self.data = {}
        self.get_calls = 0
    async def get(self, key):
        self.get_calls += 1
        return self.data.get(key)
    async def set(self, key, value, ex=None):
        self.data[key] = value


async def test_search_vector_first(tmp_path, monkeypatch):
    """温层有结果时优先返回语义结果，不落冷层/图谱。"""
    from app.utils.memory.search import MemorySearchService
    monkeypatch.setattr(
        "app.utils.cross_turn_retriever.CrossTurnRetriever",
        lambda: FakeVecRetriever(turns=[_make_turn("t-vec")]),
    )
    svc = MemorySearchService(
        cold_store=ColdMemoryStore(db_path=tmp_path / "m.db"),
        graph_store=GraphMemoryStore(db_path=tmp_path / "g.db"),
    )
    results = await svc.search("苹果公司", top_k=3)
    assert len(results) == 1
    assert results[0]["id"] == "t-vec"
    assert results[0]["type"] == "semantic"


async def test_search_graph_fallback(tmp_path, monkeypatch):
    """温层不可用时回退图谱。"""
    from app.utils.memory.search import MemorySearchService
    monkeypatch.setattr(
        "app.utils.cross_turn_retriever.CrossTurnRetriever",
        lambda: FakeVecRetriever(error=True),
    )
    svc = MemorySearchService(
        cold_store=ColdMemoryStore(db_path=tmp_path / "m.db"),
        graph_store=GraphMemoryStore(db_path=tmp_path / "g.db"),
    )
    svc.graph.add_relationship("用户", "喜欢", "Python")
    results = await svc.search("用户", top_k=3)
    assert len(results) == 1
    assert results[0]["type"] == "graph"
    assert "Python" in results[0]["content"]


async def test_search_cold_warms_up(tmp_path, monkeypatch):
    """温层/图谱都未命中 → 冷层关键词兜底，且记录被升温（标 hot）。"""
    from app.utils.memory.search import MemorySearchService
    monkeypatch.setattr(
        "app.utils.cross_turn_retriever.CrossTurnRetriever",
        lambda: FakeVecRetriever(error=True),
    )
    store = ColdMemoryStore(db_path=tmp_path / "m.db")
    store.add("cold1", "s1", "episodic", {"query_gist": "去年的营收分析结论"})
    store.mark_cold("cold1")
    svc = MemorySearchService(cold_store=store, graph_store=GraphMemoryStore(db_path=tmp_path / "g.db"))
    results = await svc.search("营收", top_k=3)
    assert len(results) == 1
    assert results[0]["id"] == "cold1"
    assert results[0]["type"] == "episodic"
    assert store.get_by_id("cold1")["cold_label"] == LABEL_HOT  # 已升温


async def test_search_cache_roundtrip(tmp_path, monkeypatch):
    """首次检索回填缓存，二次检索直接命中缓存（不重复走各层）。"""
    from app.utils.memory.search import MemorySearchService
    redis = FakeRedis()
    monkeypatch.setattr(
        "app.utils.cross_turn_retriever.CrossTurnRetriever",
        lambda: FakeVecRetriever(turns=[_make_turn("t-vec")]),
    )
    svc = MemorySearchService(
        cold_store=ColdMemoryStore(db_path=tmp_path / "m.db"),
        graph_store=GraphMemoryStore(db_path=tmp_path / "g.db"),
    )
    first = await svc.search("苹果公司", top_k=3, redis=redis)
    assert len(first) == 1
    assert "mem:search:苹果公司:3" in redis.data      # 缓存已回填
    # 第二次：换一个温层替身（若走了温层会返回空），应仍命中缓存
    monkeypatch.setattr(
        "app.utils.cross_turn_retriever.CrossTurnRetriever",
        lambda: FakeVecRetriever(error=True),
    )
    second = await svc.search("苹果公司", top_k=3, redis=redis)
    assert second == first


# ─── 维护调度（Phase 5）───

async def test_maintenance_run_once(tmp_path, monkeypatch):
    """一轮维护 = 归档 + 遗忘 + 图谱抽取，且不抛异常。"""
    from app.utils.memory.scheduler import MemoryMaintenanceScheduler

    store = ColdMemoryStore(db_path=tmp_path / "m.db")
    # 一条"很久没访问"的热记忆 → 会被归档
    store.add("old-hot", "s1", "episodic", {"query_gist": "旧话题"})
    # 一条"超期冷归档" → 会被遗忘
    store.add("expired-cold", "s1", "episodic", {"query_gist": "过期"})
    store.mark_cold("expired-cold")

    sched = MemoryMaintenanceScheduler(cold_store=store)
    # 抽取器用替身：直接返回空结果，验证不阻塞
    class FakeExtractor:
        async def consolidate_thread(self, thread_id):
            return {"consolidated": 0, "triples": []}
    sched._extractor = FakeExtractor()

    with store._connect() as conn:
        conn.execute("UPDATE events SET last_accessed='2000-01-01T00:00:00' WHERE id='old-hot'")
        conn.execute("UPDATE events SET created_at='2000-01-01T00:00:00' WHERE id='expired-cold'")

    result = await sched.run_once()
    assert "old-hot" in result["archived"]
    assert "expired-cold" in result["forgotten"]
    assert store.get_by_id("old-hot")["cold_label"] == LABEL_COLD
    assert store.get_by_id("expired-cold") is None
