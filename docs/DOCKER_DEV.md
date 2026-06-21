# Docker 本地开发

使用 Docker Compose 启动 AMAS 的本地开发依赖：

```bash
docker compose up --build
```

服务地址：

- 前端：http://localhost:5173
- 后端：http://localhost:8000
- Redis：localhost:6379
- PostgreSQL：localhost:5432

后端默认读取 `backend/.env`。如果需要从零配置，可以参考根目录 `.env.example`，把模型、DashScope、Tavily 等密钥填入 `backend/.env`。

知识库元数据默认仍使用 Redis，便于本地快速启动。如果要切换到 PostgreSQL，在 `backend/.env` 或 shell 环境中配置：

```bash
KNOWLEDGE_METADATA_BACKEND=postgres
POSTGRES_DSN=postgresql://amas:<your-password>@postgres:5432/amas
POSTGRES_AUTO_MIGRATE=true
```

`POSTGRES_DSN` 包含密码，不要提交到仓库。向量数据目前仍由 Chroma 按知识库目录隔离存储；PostgreSQL 这一阶段只承载知识库和文档元数据。

后端启动时默认会执行 Alembic migration。也可以手动运行：

```bash
cd backend
alembic upgrade head
```

本地调试可启用默认测试账号：

```bash
SEED_DEFAULT_USER_ENABLED=true
SEED_DEFAULT_TENANT_NAME=Default Tenant
SEED_DEFAULT_USERNAME=<local-username>
SEED_DEFAULT_PASSWORD=<local-password>
```

默认账号会在首次登录时初始化；数据库只保存密码哈希，不保存明文密码。

登录成功后后端会签发 JWT。生产环境必须设置强随机 `JWT_SECRET_KEY`：

```bash
JWT_SECRET_KEY=<long-random-secret>
JWT_ACCESS_TOKEN_TTL_SECONDS=86400
```

常用命令：

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose down
```

注意：`docker compose config` 会展开 `backend/.env` 中的环境变量，请不要将该命令输出粘贴到公开 Issue、文档或聊天窗口。

清理本地开发数据卷：

```bash
docker compose down -v
```
