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

# ─── 上下文工程（Phase 2）───
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
    search_mode: str = "hybrid"
    thread_id: Optional[str] = None
    session_id: Optional[str] = None
    pinned_turn_ids: Optional[List[str]] = None  # Phase 2: 用户引用的历史 Turn


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


class HistoryResponse(BaseModel):
    session_id: str
    turns_count: int
    total_budget: int
    window_k: int
    window_stats: dict
    episodic: List[dict] = []
    semantic: List[dict] = []
    memory_context: str = ""


class TurnDetailResponse(BaseModel):
    session_id: str
    turn_id: str = ""
    turn_number: int = 0
    query: str = ""
    plan: List[str] = []
    search_results: List[str] = []
    final_report: str = ""
    critique: str = ""
    review_status: str = ""
    search_mode: str = "hybrid"
    token_usage: dict = {}
    timestamp: float = 0
    full_data: dict = {}


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


# ─── 会话管理端点 ───

@router.post("/sessions")
async def create_session():
    """创建新会话。"""
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
    """获取会话详情（含窗口统计）。"""
    assembler = await get_assembler()
    info = await assembler.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return info


# ─── 历史浏览端点（Phase 2 新增）───

@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str, limit: int = 20):
    """
    获取会话的完整历史，含分层记忆视图。

    返回 episosic (完整保留的最近 Turn) 和 semantic (压缩的早期 Turn)。
    前端可据此渲染"历史研究脉络"面板。
    """
    assembler = await get_assembler()
    history = await assembler.get_session_history(session_id, limit)
    if history is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return history


@router.get("/sessions/{session_id}/turns/{turn_id}")
async def get_turn_detail(session_id: str, turn_id: str):
    """
    获取单个 Turn 的完整详情（含完整 report、search_results 等大字段）。
    用于前端点击历史记录时展示完整内容。
    """
    assembler = await get_assembler()
    detail = await assembler.get_turn_detail(session_id, turn_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Turn 不存在")
    return detail


# ─── 聊天端点（核心）───

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    多轮研究聊天端点。

    Phase 2 更新:
    - 集成 SlidingWindowManager：装配 Episodic/Semantic 分层记忆
    - memory_context 注入到各节点 Prompt（Planner/Writer 可利用历史脉络）
    - 支持 pinned_turn_ids（用户引用历史 Turn）
    """
    assembler = await get_assembler()

    # ─── 阶段一：会话层准备 ───
    initial_state, ledger, memory = await assembler.prepare(
        query=request.query,
        search_mode=request.search_mode,
        session_id=request.session_id,
        pinned_turn_ids=request.pinned_turn_ids,
    )

    session_id = initial_state["session_id"]
    turn_id = initial_state["turn_id"]

    # LangGraph config
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
            f"模式: {request.search_mode} | 窗口K: {memory.window_k} | "
            f"Episodic: {len(memory.episodic_memory)} | Semantic: {len(memory.semantic_memory)} | "
            f"问题: {request.query[:50]}..."
        )

        try:
            async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory_saver:
                app = create_graph(memory=memory_saver)

                async for event in app.astream(initial_state, config=config):
                    for node_name, state_update in event.items():
                        # 合并最终状态
                        final_state.update(state_update)

                        # ─── 阶段二：节点级 Token 记录 ───
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
            full_state = {**initial_state, **final_state}
            turn_record = await assembler.finalize(full_state, ledger)

            # 获取更新后的窗口统计
            window_stats = assembler.window_mgr.get_window_stats(
                initial_state.get("episodic_memory", []) +
                initial_state.get("semantic_memory", [])
            )

            # 推送会话信息给前端
            session_info = json.dumps(
                {
                    "step": "__session__",
                    "data": {
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "turn_number": turn_record.turn_number,
                        "token_usage": ledger.snapshot().__dict__,
                        "window_stats": window_stats,
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
    """基于节点输出估算 Token 用量。"""
    from app.utils.token_counter import count_tokens

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
