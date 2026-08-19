"""阶段 4b + 6a + 6b + 升级④ + ⑦：FastAPI 接口 + 审计 + 权限 + 多轮 + 流式 + 登录鉴权。

用法（在 rag-course 目录下）：
    python -m uvicorn app.main:app --reload
然后打开 http://127.0.0.1:8000/docs 测试接口
"""
from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 把本目录加入模块搜索路径：让 uvicorn 也能找到 rag.py / auth.py 等
APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import auth
import ratelimit
from audit import log_question
from rag import ask, ask_stream


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用启动时初始化用户库 + 默认用户（登录模块的数据地基）。"""
    auth.init_db()
    yield


class UTF8JSONResponse(JSONResponse):
    """显式声明 UTF-8：避免老客户端（如 PowerShell 5.1）按 ISO-8859-1 解码中文。"""

    media_type = "application/json; charset=utf-8"


app = FastAPI(title="企业内部知识库 RAG", default_response_class=UTF8JSONResponse, lifespan=lifespan)


def get_current_user(authorization: str = Header(default="")) -> dict:
    """鉴权依赖：从 Authorization 头解析用户。无 token 一律 401（默认拒绝）。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    user = auth.get_user_by_token(authorization[7:])
    if user is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user


class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []  # 多轮对话历史：[{"role": "user"/"assistant", "content": "..."}]


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    groups: list[str]


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/stats")
def stats() -> dict:
    """统计信息（供前端指标卡展示）。"""
    import chromadb
    from store import CHROMA_DIR, COLLECTION_NAME
    try:
        collection = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION_NAME)
        chunk_count = collection.count()
    except Exception:
        chunk_count = 0
    data_dir = Path(__file__).resolve().parent.parent / "data" / "sample"
    doc_count = sum(1 for p in data_dir.iterdir() if p.is_file())
    return {"documents": doc_count, "chunks": chunk_count, "users": auth.count_users()}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request) -> LoginResponse:
    """登录：限流 → 校验密码 → 签发 token。

    - 限流：同一 IP+用户名 5 分钟内失败 5 次则锁定 15 分钟（防暴力破解）；
    - 密码错误统一返回 401，不透露是用户名不存在还是密码错。
    """
    ip = request.client.host if request.client else "unknown"
    if ratelimit.is_locked(ip, req.username):
        raise HTTPException(status_code=429, detail="尝试次数过多，请 15 分钟后再试")
    token = auth.authenticate(req.username, req.password)
    if token is None:
        ratelimit.record_failure(ip, req.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    ratelimit.reset(ip, req.username)
    user = auth.get_user(req.username)
    return LoginResponse(token=token, username=req.username, groups=user["groups"])


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default="")) -> dict:
    """登出：服务端删掉会话，token 立即失效。"""
    if authorization.startswith("Bearer "):
        auth.logout(authorization[7:])
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    """返回当前登录用户（前端用来校验会话是否还有效）。"""
    return user


@app.post("/api/auth/change-password")
def change_password(
    req: ChangePasswordRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """修改密码：必须登录，且只能改自己的密码（身份来自 token，不由客户端指定）。

    改密后吊销该用户所有会话（包括当前这个），必须重新登录。
    """
    ip = request.client.host if request.client else "unknown"
    if ratelimit.is_locked(ip, user["username"]):
        raise HTTPException(status_code=429, detail="尝试次数过多，请 15 分钟后再试")
    if not auth.check_password(user["username"], req.old_password):
        ratelimit.record_failure(ip, user["username"])
        raise HTTPException(status_code=401, detail="旧密码不正确")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    if not auth.change_password(user["username"], req.new_password):
        raise HTTPException(status_code=404, detail="用户不存在")
    ratelimit.reset(ip, user["username"])
    return {"status": "ok", "message": "密码已修改，请重新登录"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, user: dict = Depends(get_current_user)) -> ChatResponse:
    result = ask(req.question, groups=user["groups"], history=req.history)
    # 审计：用户名来自服务端验证结果，客户端无法伪造
    log_question(req.question, result["answer"], result["citations"], user=user["username"])
    return ChatResponse(answer=result["answer"], citations=result["citations"])


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, user: dict = Depends(get_current_user)) -> StreamingResponse:
    """SSE 流式问答：先发 citations，再逐 token 发答案，最后 done。"""
    groups = user["groups"]

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
        log_question(req.question, "".join(answer_parts), citations, user=user["username"])

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/documents/rebuild")
def rebuild_index() -> dict:
    """重新扫描 data/sample 并重建向量索引（内部工具，生产需加鉴权 + 管理员校验）。"""
    from store import build_index
    collection = build_index(chunk_size=150)  # 150 是评估结论推荐的分块大小
    return {"status": "ok", "chunks": collection.count()}
