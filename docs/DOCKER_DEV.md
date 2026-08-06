# Docker Local Development

The demo uses Redis for session and knowledge-base metadata. It has no PostgreSQL, account, or authentication dependency.

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Redis: localhost:6379

To remove local demo data:

```bash
docker compose down -v
```
