from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from app.graph.graph import create_graph
import json
import asyncio
import os
import shutil
from app.rag.engine import process_documents, reset_knowledge_base, UPLOAD_DIR
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# ─── 上下文工程（Phase 1）───
from app.utils.context_assembler import ContextAssembler
from app.utils.budget_ledger import BudgetLedger

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(CURRENT_DIR, "checkpoints.db")
router = APIRouter()

# 全局 ContextAssembler 实例（懒初始化 Redis）
_assembler: Optional[ContextAssembler] = None


async def get_assembler() -> ContextAssembler:
    """获取 ContextAssembler 单例。"""
    global _assembler
    if _assembler is None:
        _assembler = ContextAssembler(total_budget=128_000)
    return _assembler


# ─── 请求模型 ───

class ChatRequest(BaseModel):
    query: str
    search_mode: str = "hybrid"     # 默认为混合搜索
    thread_id: Optional[str] = None  # 可选：LangGraph thread_id
    session_id: Optional[str] = None  # 新增：持久化会话 ID（服务端管理）


class SessionResponse(BaseModel):
    session_id: str
    created_at: float
    last_active: float
    turns_count: int
    total_budget: int
    total_estimated_tokens: int
    total_actual_tokens: int
    compression_savings: int
    status: str
    recent_turn_ids: List[str] = []


# ─── 文档管理端点 ───

@router.post("/clear")
async def clear_endpoint():
    try:
        reset_knowledge_base()
        return {"message": "知识库已重置", "status": "success"}
    except Exception as e:
        print(f"清空失败: {e}")
        return {"message": f"清空失败: {str(e)}", "status": "error"}


@router.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """批量上传接口"""
    if len(files) > 5:
        raise HTTPException(status_code=400, detail="一次最多只能上传 5 个文件")

    try:
        reset_knowledge_base()

        saved_paths = []
        for file in files:
            file_path = os.path.join(UPLOAD_DIR, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            saved_paths.append(file_path)

        chunks_num = process_documents(saved_paths)

        return {
            "status": "success",
            "file_count": len(files),
            "chunks_stored": chunks_num,
            "message": "文档解析完成，知识库构建成功"
        }
    except Exception as e:
        print(f"上传处理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── 会话管理端点（新增）───

@router.post("/sessions")
async def create_session():
    """创建新会话。前端在首次使用时调用。"""
    assembler = await get_assembler()
    await assembler._init()
    session = await assembler.session_mgr.create_session()
    return {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "total_budget": session.total_budget,
        "status": session.status,
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情。"""
    assembler = await get_assembler()
    info = await assembler.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return SessionResponse(**info)


# ─── 聊天端点（核心）───

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    多轮研究聊天端点。

    上下文工程 (Phase 1):
    - 服务端管理 session_id，支持跨页面刷新的对话持久化
    - 每次请求记录 Turn 到 Redis（或内存降级）
    - Token 预算在 ContextAssembler 中追踪
    """
    assembler = await get_assembler()

    # ─── 阶段一：会话层准备 ───
    initial_state, ledger = await assembler.prepare(
        query=request.query,
        search_mode=request.search_mode,
        session_id=request.session_id,
    )

    session_id = initial_state["session_id"]
    turn_id = initial_state["turn_id"]

    # LangGraph config（thread_id 使用 turn_id 保证每次执行可追溯）
    config = {
        "configurable": {
            "thread_id": request.thread_id or turn_id,
            "session_id": session_id,
        }
    }

    async def event_generator():
        final_state = {}

        print(
            f"🚀 新任务开启 | 会话: {session_id} | Turn: {turn_id} | "
            f"模式: {request.search_mode} | 问题: {request.query[:50]}..."
        )

        try:
            async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
                app = create_graph(memory=memory)

                async for event in app.astream(initial_state, config=config):
                    for node_name, state_update in event.items():
                        # 合并最终状态
                        final_state.update(state_update)

                        # ─── 阶段二：节点级 Token 记录 ───
                        # Phase 1: 基于节点输出估算 Token
                        _record_node_token_estimate(
                            ledger, node_name, state_update
                        )

                        # 将节点名称和状态数据打包成 JSON（SSE 推送）
                        data = json.dumps(
                            {"step": node_name, "data": state_update},
                            ensure_ascii=False,
                        )
                        yield f"data: {data}\n\n"
                        await asyncio.sleep(0.1)

            # ─── 阶段三：会话层收尾 ───
            # 合并 initial_state（保留 session_id 等字段）
            full_state = {**initial_state, **final_state}
            turn_record = await assembler.finalize(full_state, ledger)

            # 推送会话信息给前端（首次返回 session_id）
            session_info = json.dumps(
                {
                    "step": "__session__",
                    "data": {
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "turn_number": turn_record.turn_number,
                        "token_usage": ledger.snapshot().__dict__,
                    },
                },
                ensure_ascii=False,
            )
            yield f"data: {session_info}\n\n"

        except Exception as e:
            import traceback
            print(f"❌ 任务执行失败: {e}")
            traceback.print_exc()
            error_data = json.dumps(
                {"step": "__error__", "data": {"message": str(e)}},
                ensure_ascii=False,
            )
            yield f"data: {error_data}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


# ─── 辅助函数 ───

def _record_node_token_estimate(
    ledger: BudgetLedger,
    node_name: str,
    state_update: dict,
) -> None:
    """
    基于节点输出估算 Token 用量。

    Phase 1: 粗略估算（字符数 / 4）。
    Phase 2: 替换为 tiktoken 精确计量 + API usage 回传。
    """
    from app.utils.token_counter import count_tokens

    # 估算节点产出的文本量
    output_text = ""
    for key in ("final_report", "plan", "search_results", "critique"):
        val = state_update.get(key)
        if isinstance(val, str):
            output_text += val
        elif isinstance(val, list):
            output_text += " ".join(str(v) for v in val)

    if output_text:
        estimated = count_tokens(output_text)
        ledger.record(
            node_name=node_name,
            estimated=estimated,
            actual_input=estimated,
            actual_output=0,
        )
