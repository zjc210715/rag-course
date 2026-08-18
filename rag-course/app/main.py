"""阶段 4b + 6a + 6b + 升级④：FastAPI 接口 + 审计 + 权限 + 多轮记忆 + 流式输出。

用法（在 rag-course 目录下）：
    python -m uvicorn app.main:app --reload
然后打开 http://127.0.0.1:8000/docs 测试接口
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 把本目录加入模块搜索路径：让 uvicorn 也能找到 rag.py / audit.py 等
APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from audit import log_question
from rag import ask, ask_stream

# 用户 → 权限组（权限在服务端判定，客户端只能报身份，不能自己声明权限）
USER_GROUPS = {
    "anonymous": ["all"],
    "zhangsan": ["all"],          # 普通员工
    "lisi": ["all", "finance"],   # 财务
}


class UTF8JSONResponse(JSONResponse):
    """显式声明 UTF-8：避免老客户端（如 PowerShell 5.1）按 ISO-8859-1 解码中文。"""

    media_type = "application/json; charset=utf-8"


app = FastAPI(title="企业内部知识库 RAG", default_response_class=UTF8JSONResponse)


class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []  # 多轮对话历史：[{"role": "user"/"assistant", "content": "..."}]


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict]


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_user_id: str = Header(default="anonymous")) -> ChatResponse:
    groups = USER_GROUPS.get(x_user_id, ["all"])
    result = ask(req.question, groups=groups, history=req.history)
    # 审计：谁、何时、问了什么、答了什么、引用了哪些文档
    log_question(req.question, result["answer"], result["citations"], user=x_user_id)
    return ChatResponse(answer=result["answer"], citations=result["citations"])


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, x_user_id: str = Header(default="anonymous")) -> StreamingResponse:
    """SSE 流式问答：先发 citations，再逐 token 发答案，最后 done。"""
    groups = USER_GROUPS.get(x_user_id, ["all"])

    def event_stream():
        answer_parts: list[str] = []
        citations: list[dict] = []
        for event in ask_stream(req.question, groups=groups, history=req.history):
            if event["type"] == "citations":
                citations = event["citations"]
            elif event["type"] == "token":
                answer_parts.append(event["content"])
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        # 审计：流结束后记录完整问答
        log_question(req.question, "".join(answer_parts), citations, user=x_user_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/documents/rebuild")
def rebuild_index() -> dict:
    """重新扫描 data/sample 并重建向量索引（内部工具，生产需加鉴权）。"""
    from store import build_index
    collection = build_index(chunk_size=150)  # 150 是评估结论推荐的分块大小
    return {"status": "ok", "chunks": collection.count()}
