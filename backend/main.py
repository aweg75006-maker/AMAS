import uuid
from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from app.api.router import router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger, reset_request_id, set_request_id

configure_logging()
logger = get_logger("iris.main")
logger.info("config_loaded", extra={"config": settings.safe_summary()})


app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    token = set_request_id(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        reset_request_id(token)


app.include_router(router, prefix="/api")

@app.get("/")
def health_check():
    return {
        "status": "running",
        "environment": settings.environment,
        "model_config": f"{settings.llm_fast_model} + {settings.llm_smart_model}",
    }

if __name__ == "__main__":
    logger.info("backend_starting")
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
    )
