"""分层记忆系统。

设计目标：在现有"Redis 回合记录 + Chroma 摘要向量 + SQLite 图状态"之上，
补齐记忆的完整生命周期：

- 分类（classification）：按内容特征区分 episodic / semantic / working，决定存储路径；
- 冷热分层（lifecycle + cold_store）：热记忆（向量可检索）→ 长期未访问 → 冷归档
  （仅保留记录）→ 超期 → 遗忘；protected 记录永不归档、永不删除；
- 图谱记忆（graph_store + extraction）：从对话中抽取 (实体)-[关系]->(实体)
  结构化知识，支持邻接查询；
- 多级检索（search）：热缓存 → 向量召回 → 图谱 → 冷归档 → 关键词兜底，
  命中冷数据自动"升温"。

所有存储均在本地（Redis / ChromaDB / SQLite），不引入额外第三方服务；
各子模块均可独立降级，异常不阻断主流程。

子模块按需显式导入（避免包初始化时拉起重依赖）：
    from app.utils.memory.lifecycle import MemoryLifecycleManager
    from app.utils.memory.classification import classify_memory
"""
