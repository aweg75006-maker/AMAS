"""图谱记忆存储：SQLite 三元组表（轻量知识图谱）。

以 (subject)-[relation]->(object) 三元组表达结构化知识（用户偏好、实体关系、
明确态度等），支持按实体/关系做 1~2 跳邻接遍历查询。

设计取舍：
- 用 SQLite 单表替代独立图数据库（Neo4j）：对"偏好/关系"这类小规模知识，
  邻接遍历用 SQL 迭代即可完成，避免引入重型服务；
- 查询语义与图库一致：模糊匹配（节点名或关系类型包含查询词）+ 路径返回
  （nodes + relations 列表），方便注入 Prompt 或做关系推理。
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.core.config import settings


class GraphMemoryStore:
    """SQLite 三元组图谱存储。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else settings.memory_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ─── 建表 ───

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS triples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    object TEXT NOT NULL,
                    importance TEXT DEFAULT 'medium',
                    protected INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'llm_extraction',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object)"
            )
            # 唯一约束：同一 (subject, relation, object) 只保留一份
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_triples_uniq "
                "ON triples(subject, relation, object)"
            )

    # ─── 写入 ───

    def add_relationship(
        self,
        subject: str,
        relation: str,
        obj: str,
        thread_id: str = "default",
        source: str = "llm_extraction",
        importance: str = "medium",
    ) -> None:
        """新增一条三元组（重复的 (s,r,o) 不重复插入）。"""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO triples "
                "(thread_id, subject, relation, object, importance, protected, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                (thread_id, subject, relation, obj, importance, source, now),
            )

    # ─── 查询 ───

    def search_relations(
        self, node_name: str, depth: int = 2, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """按实体/关系模糊搜索，返回 1~depth 跳的路径。

        Args:
            node_name: 查询词（匹配 subject / object / relation 任一包含即命中）
            depth: 邻接扩展跳数（1~2 足够覆盖偏好/关系类知识）
            limit: 返回路径条数上限

        Returns:
            [{"nodes": [n1, n2, ...], "relations": [r1, r2, ...]}, ...]
            与图数据库查询结果结构一致，便于下游直接使用。
        """
        if depth < 1:
            depth = 1
        if not node_name:
            return []
        # 所有边
        edges = self._all_edges()
        if not edges:
            return []

        # 1. 种子路径：任何边的 subject / object / relation 包含查询词即命中
        #    （子串包含判断，等价于 SQL LIKE '%node_name%'）
        seeds = [
            e for e in edges
            if node_name in e["subject"] or node_name in e["object"]
            or node_name in e["relation"]
        ]
        paths: List[Dict[str, Any]] = [
            {"nodes": [e["subject"], e["object"]], "relations": [e["relation"]]}
            for e in seeds
        ]

        # 2. 邻接扩展：保留全部深度的路径（1 跳、2 跳…depth 跳），
        #    对每条现有路径的末端节点再向外找一跳（避免成环重复访问）。
        frontier = list(paths)          # 当前参与扩展的路径
        for _ in range(depth - 1):
            extended = []
            for p in frontier:
                tail = p["nodes"][-1]
                for e in edges:
                    if e["subject"] == tail and e["object"] not in p["nodes"]:
                        extended.append({
                            "nodes": p["nodes"] + [e["object"]],
                            "relations": p["relations"] + [e["relation"]],
                        })
                    elif e["object"] == tail and e["subject"] not in p["nodes"]:
                        extended.append({
                            "nodes": p["nodes"] + [e["subject"]],
                            "relations": p["relations"] + [e["relation"]],
                        })
            if not extended:
                break
            paths = paths + extended   # 追加新深度路径，保留浅层路径
            frontier = extended

        # 3. 去重（nodes 序列相同视为同一条）并按长度截断
        seen, unique = set(), []
        for p in paths:
            key = "|".join(p["nodes"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)
            if len(unique) >= limit:
                break
        return unique

    def search_by_relation(self, relation: str, limit: int = 20) -> List[Dict[str, Any]]:
        """按关系类型直接查询（如"负责"、"喜欢"）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT subject, relation, object, importance FROM triples "
                "WHERE relation LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{relation}%", limit),
            ).fetchall()
        return [
            {"subject": r[0], "relation": r[1], "object": r[2], "importance": r[3]}
            for r in rows
        ]

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM triples").fetchone()
        return int(row[0]) if row else 0

    def delete_by_thread(self, thread_id: str) -> int:
        """删除某会话产生的全部三元组（调试/清理用）。返回删除条数。"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM triples WHERE thread_id = ?", (thread_id,)
            )
            return cur.rowcount

    def delete_relationship(self, subject: str, relation: str, obj: str) -> None:
        """删除指定三元组。"""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM triples WHERE subject = ? AND relation = ? AND object = ?",
                (subject, relation, obj),
            )

    # ─── 工具 ───

    def _all_edges(self) -> List[Dict[str, Any]]:
        """取出全部三元组（图谱规模小，全量内存遍历即可）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT subject, relation, object FROM triples"
            ).fetchall()
        return [
            {"subject": r[0], "relation": r[1], "object": r[2]}
            for r in rows
        ]
