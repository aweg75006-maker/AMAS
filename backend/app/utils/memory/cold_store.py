"""冷层记忆存储：SQLite 事件表。

职责：作为记忆的"事实底座"，与热层（Chroma 向量索引）解耦——
Chroma 索引删了（归档）记录仍在，冷层永不丢，直到被遗忘机制清理。

每条记录携带生命周期字段：
- cold_label:  hot（向量可检索）| cold（已归档，仅保留记录）
- protected:  1 表示受保护，永不归档、永不删除
- last_accessed / access_count: 访问热度，驱动冷热迁移
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.core.config import settings

# 冷热标签常量
LABEL_HOT = "hot"
LABEL_COLD = "cold"


class ColdMemoryStore:
    """SQLite 冷层存储：单表 events，内容以 JSON 落盘。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else settings.memory_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ─── 建表 ───

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """短连接上下文：自动提交 + 关闭（SQLite 适合每次操作新建连接）。"""
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        """创建 events 表与常用索引（幂等）。"""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance TEXT DEFAULT 'low',
                    created_at TEXT NOT NULL,
                    last_accessed TEXT,
                    access_count INTEGER DEFAULT 1,
                    cold_label TEXT DEFAULT 'hot',
                    protected INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_thread ON events(thread_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)"
            )

    # ─── 写入 ───

    def add(
        self,
        memory_id: str,
        thread_id: str,
        event_type: str,
        content: Dict[str, Any],
        importance: str = "low",
    ) -> None:
        """新增一条记忆（同 id 覆盖）。"""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO events "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory_id,
                    thread_id,
                    event_type,
                    json.dumps(content, ensure_ascii=False),
                    importance,
                    now,
                    now,
                    1,
                    LABEL_HOT,
                    0,
                ),
            )

    # ─── 查询 ───

    def get_by_id(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """按 id 取记录（无则 None）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE id = ?", (memory_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def search(
        self,
        thread_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """按线程/类型过滤，创建时间倒序。"""
        query = "SELECT * FROM events WHERE 1=1"
        params: List[Any] = []
        if thread_id:
            query += " AND thread_id = ?"
            params.append(thread_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_cold(self, keyword: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """冷归档记录的模糊检索（LIKE 关键词匹配）。"""
        limit = limit or settings.memory_cold_search_limit
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE cold_label = ? "
                "AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (LABEL_COLD, f"%{keyword}%", limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        """记录总数。"""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0]) if row else 0

    # ─── 生命周期字段操作 ───

    def update_access(self, memory_id: str) -> None:
        """记录一次访问（刷新 last_accessed 并累加 access_count）。"""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET last_accessed = ?, "
                "access_count = access_count + 1 WHERE id = ?",
                (now, memory_id),
            )

    def mark_cold(self, memory_id: str) -> None:
        """标为冷归档。"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET cold_label = ? WHERE id = ?",
                (LABEL_COLD, memory_id),
            )

    def mark_hot(self, memory_id: str) -> None:
        """标回热记忆。"""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET cold_label = ?, last_accessed = ?, "
                "access_count = access_count + 1 WHERE id = ?",
                (LABEL_HOT, now, memory_id),
            )

    def mark_protected(self, memory_id: str) -> None:
        """标记受保护：永不归档、永不删除。"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET protected = 1 WHERE id = ?", (memory_id,)
            )

    def get_cold_candidates(self, days: int = 10) -> List[Dict[str, Any]]:
        """候选归档：超过 days 天未访问、未保护、且当前为热记忆。"""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE last_accessed < ? "
                "AND protected = 0 AND cold_label != ?",
                (cutoff, LABEL_COLD),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_cold_records(self, days: int = 30) -> List[Dict[str, Any]]:
        """候选遗忘：已是冷归档、超过 days 天、且未保护。"""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE cold_label = ? "
                "AND created_at < ? AND protected = 0",
                (LABEL_COLD, cutoff),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete(self, memory_id: str) -> None:
        """物理删除一条记录。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM events WHERE id = ?", (memory_id,))

    # ─── 工具 ───

    @staticmethod
    def _row_to_dict(row: tuple) -> Dict[str, Any]:
        """sqlite 行 → dict（content 反序列化为 dict）。"""
        cols = [
            "id", "thread_id", "event_type", "content", "importance",
            "created_at", "last_accessed", "access_count", "cold_label", "protected",
        ]
        d = dict(zip(cols, row))
        try:
            d["content"] = json.loads(d["content"])
        except (json.JSONDecodeError, TypeError):
            d["content"] = {}
        return d
