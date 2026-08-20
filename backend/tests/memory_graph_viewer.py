"""图谱记忆（SQLite 三元组）可视化工具。

SQLite 没有 Neo4j 那样的官方图谱浏览器，本工具把 triples 表渲染成
**交互式力导向图 HTML**：节点可拖拽、缩放、悬停看关系，接近 Neo4j Browser 体验。

三种输出方式（任选其一）：
  1. 默认：生成 memory_graph.html（自包含，内嵌数据 + vis-network CDN），浏览器打开即用；
  2. --csv：导出 triples.csv（subject,relation,object），可导入 Gephi / Excel / 其他图分析工具；
  3. 直接打印：不加参数时打印三元组清单（类似 sqlite3 查询）。

用法（在 backend/ 目录）：
    /opt/miniconda3/envs/iris/bin/python tests/memory_graph_viewer.py
    /opt/miniconda3/envs/iris/bin/python tests/memory_graph_viewer.py --limit 50 --output /tmp/graph.html
    /opt/miniconda3/envs/iris/bin/python tests/memory_graph_viewer.py --csv triples.csv

说明：
- 数据源默认 app/data/memory.db（settings.memory_db_path）；
- 节点 = subject/object 实体去重，节点大小随关联度（degree）增大；
- 边 = relation 标签，箭头指向 object；importance=high 的边加粗；
- HTML 依赖 CDN 上的 vis-network（https://cdnjs.cloudflare.com），需联网加载一次。
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# backend/ 根目录（脚本位于 tests/ 下）
BACKEND_DIR = Path(__file__).resolve().parents[1]

# 数据源：与 settings.memory_db_path 保持一致
DEFAULT_DB = BACKEND_DIR / "app" / "data" / "memory.db"

# vis-network CDN（https://cdnjs.cloudflare.com 在允许的 CDN 白名单内）
VIS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/standalone/umd/vis-network.min.js"

# 关系 → 边的颜色（同色系区分不同关系类型，便于快速扫图）
RELATION_COLORS = {
    "喜欢": "#D4537E", "偏好": "#D4537E", "讨厌": "#A32D2D", "不喜欢": "#A32D2D",
    "习惯": "#1D9E75", "擅长": "#1D9E75", "精通": "#1D9E75",
    "负责": "#378ADD", "管理": "#378ADD", "身份": "#378ADD", "属于": "#378ADD",
    "依赖": "#7F77DD", "相关": "#7F77DD", "属于": "#7F77DD",
}
DEFAULT_EDGE_COLOR = "#888780"


# ─── 数据读取 ───

def load_triples(db_path: Path, limit: int | None = None) -> list[dict]:
    """读取 triples 表全部三元组。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    sql = "SELECT id, thread_id, subject, relation, object, importance FROM triples"
    if limit:
        sql += " LIMIT ?"
        rows = conn.execute(sql, (limit,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def to_graph_data(triples: list[dict]) -> tuple[list, list]:
    """三元组 → (nodes, edges)，vis-network 可直接消费。

    节点：subject/object 去重；大小随关联度（相连边数）增大；
    边：relation 作为标签，importance=high 加粗。
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    # 第一遍：收集实体并统计关联度
    degree: dict[str, int] = defaultdict(int)
    for t in triples:
        for key in (t["subject"], t["object"]):
            degree[key] += 1

    # 第二遍：构造节点与边
    for t in triples:
        s, o, rel = t["subject"], t["object"], t["relation"]
        for name in (s, o):
            if name and name not in nodes:
                nodes[name] = {
                    "id": name,
                    "label": name,
                    "value": 5 + min(degree[name], 40),  # 节点大小随关联度
                    "title": f"{name}（关联 {degree[name]} 条关系）",
                }
        if s and o:
            edges.append({
                "from": s,
                "to": o,
                "label": rel,
                "color": {"color": RELATION_COLORS.get(rel, DEFAULT_EDGE_COLOR)},
                "width": 2.5 if t.get("importance") == "high" else 1.2,
                "arrows": "to",
                "font": {"size": 12, "align": "middle"},
            })

    return list(nodes.values()), edges


# ─── HTML 渲染（零 Python 依赖，浏览器端渲染）───

def render_html(nodes: list, edges: list) -> str:
    """生成自包含交互式图谱 HTML。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>IRIS 图谱记忆可视化</title>
<script src="{VIS_CDN}"></script>
<style>
  html, body {{ margin: 0; height: 100%; background: #fafafa; }}
  #header {{
    padding: 10px 16px; font-family: -apple-system, "PingFang SC", sans-serif;
    border-bottom: 1px solid #e5e5e5; background: #fff;
    display: flex; align-items: center; gap: 16px;
  }}
  #header h1 {{ font-size: 15px; margin: 0; font-weight: 500; }}
  #header span {{ font-size: 12px; color: #888; }}
  #graph {{ width: 100%; height: calc(100vh - 50px); }}
</style>
</head>
<body>
<div id="header">
  <h1>IRIS 图谱记忆（SQLite 三元组）</h1>
  <span>节点可拖拽 / 滚轮缩放 / 悬停查看关联度</span>
</div>
<div id="graph"></div>
<script>
var NODES = {json.dumps(nodes, ensure_ascii=False)};
var EDGES = {json.dumps(edges, ensure_ascii=False)};
var container = document.getElementById('graph');
var data = {{
  nodes: new vis.DataSet(NODES),
  edges: new vis.DataSet(EDGES)
}};
var options = {{
  nodes: {{ shape: 'dot', size: 14, font: {{ size: 14, color: '#333' }} }},
  edges: {{ smooth: {{ type: 'continuous' }} }},
  physics: {{ enabled: true, solver: 'forceAtlas2Based',
             forceAtlas2Based: {{ gravitationalConstant: -60 }},
             stabilization: {{ iterations: 300 }} }},
  interaction: {{ hover: true, tooltipDelay: 100 }}
}};
new vis.Network(container, data, options);
</script>
</body>
</html>"""


# ─── CSV 导出（给 Gephi / Excel）───

def render_csv(triples: list[dict]) -> str:
    """三元组 → CSV（Gephi 可直接导入的边表格式）。"""
    lines = ["source,target,relation,importance,thread_id"]
    for t in triples:
        # 简单转义：字段含逗号/引号时用引号包裹
        def esc(v: str) -> str:
            v = str(v)
            return f'"{v}"' if ("," in v or '"' in v) else v
        lines.append(
            f"{esc(t['subject'])},{esc(t['object'])},{esc(t['relation'])},"
            f"{esc(t.get('importance', ''))},{esc(t.get('thread_id', ''))}"
        )
    return "\n".join(lines)


# ─── 主流程 ───

def main() -> None:
    parser = argparse.ArgumentParser(description="IRIS 图谱记忆可视化")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径")
    parser.add_argument("--limit", type=int, default=None, help="最多读多少条三元组")
    parser.add_argument("--output", default=str(BACKEND_DIR / "memory_graph.html"),
                        help="HTML 输出路径")
    parser.add_argument("--csv", default=None, help="导出 CSV 到该路径（替代 HTML）")
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"数据库不存在: {db}")
        print("提示：先跑 tests/memory_demo.py 生成演示三元组，或用 --db 指定其他库。")
        sys.exit(1)

    triples = load_triples(db, args.limit)
    if not triples:
        print("triples 表为空——先运行 tests/memory_demo.py 生成图谱数据。")
        sys.exit(1)

    print(f"共 {len(triples)} 条三元组，来源: {db}")

    if args.csv:
        out = Path(args.csv)
        out.write_text(render_csv(triples), encoding="utf-8")
        print(f"已导出 CSV: {out}（可导入 Gephi / Excel）")
        return

    nodes, edges = to_graph_data(triples)
    out = Path(args.output)
    out.write_text(render_html(nodes, edges), encoding="utf-8")
    print(f"已生成交互式图谱: {out}")
    print(f"  节点 {len(nodes)} 个，边 {len(edges)} 条")
    print("用浏览器打开即可拖拽 / 缩放 / 悬停查看。")


if __name__ == "__main__":
    main()
