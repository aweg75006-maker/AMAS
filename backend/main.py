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





'''
    测试Agent功能是否正常
'''
# def main():
#     print("🚀 IRIS Agent 启动中...")
    
#     # 1. 创建图
#     app = create_graph()
    
#     # 2. 模拟用户输入
#     user_input = "2026年 AI Agent 的主要技术趋势是什么？"
#     initial_state = {"query": user_input}
    
#     # 3. 运行图
#     # invoke 会同步运行整个流程直到结束
#     result = app.invoke(initial_state)
    
#     # 4. 打印最终结果
#     print("\n" + "="*50)
#     print(" 最终报告生成完毕：")
#     print("="*50 + "\n")
#     print(result["final_report"])

# if __name__ == "__main__":
#     main()
