"""阶段 4b + 6a + 6b + 升级④ + ⑦：FastAPI 接口 + 审计 + 权限 + 多轮 + 流式 + 登录鉴权。

用法（在 rag-course 目录下）：
    python -m uvicorn app.main:app --reload
然后打开 http://127.0.0.1:8000/docs 测试接口
"""
from __future__ import annotations

import json
import ipaddress
import sys
import base64
from contextlib import asynccontextmanager
from pathlib import Path

# 把本目录加入模块搜索路径：让 uvicorn 也能找到 rag.py / auth.py 等
APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import auth
import docmeta
import ratelimit
from audit import log_question
from generate import generate_suggestions
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


# ---------- 真实客户端 IP（nginx 反代后的限流依赖它） ----------

# 可信代理：本机 + docker 内网网段。只有这些来源的 X-Forwarded-For 才被信任，
# 防止客户端绕过 nginx 直连后端时伪造 IP。
TRUSTED_PROXIES = ["127.0.0.1", "::1", "172.16.0.0/12", "10.0.0.0/8"]


def _is_trusted(peer: str) -> bool:
    """判断对端 IP 是否属于可信代理网段。"""
    try:
        ip = ipaddress.ip_address(peer)
        return any(ip in ipaddress.ip_network(net) for net in TRUSTED_PROXIES)
    except ValueError:
        return False


def get_client_ip(request: Request) -> str:
    """取真实客户端 IP：只有可信代理转发的请求才信任 X-Forwarded-For。"""
    peer = request.client.host if request.client else "unknown"
    if _is_trusted(peer):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()  # 最左边 = 原始客户端
    return peer


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


class UploadRequest(BaseModel):
    filename: str
    content_b64: str          # base64 编码的文件内容（小文件教学方案；生产可换 multipart）
    access: str = "all"       # 权限标签：all / finance / dept_xxx / executive


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
    ip = get_client_ip(request)
    if ratelimit.is_locked(ip, req.username):
        auth.log_security_event("login_locked", req.username, ip, "触发限流锁定")
        raise HTTPException(status_code=429, detail="尝试次数过多，请 15 分钟后再试")
    token = auth.authenticate(req.username, req.password)
    if token is None:
        ratelimit.record_failure(ip, req.username)
        auth.log_security_event("login_failure", req.username, ip, "密码错误或用户不存在")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    ratelimit.reset(ip, req.username)
    auth.log_security_event("login_success", req.username, ip)
    user = auth.get_user(req.username)
    return LoginResponse(token=token, username=req.username, groups=user["groups"])


@app.post("/api/auth/logout")
def logout(request: Request, authorization: str = Header(default="")) -> dict:
    """登出：服务端删掉会话，token 立即失效。"""
    ip = get_client_ip(request)
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        user = auth.get_user_by_token(token)
        if user is not None:
            auth.log_security_event("logout", user["username"], ip)
        auth.logout(token)
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
    ip = get_client_ip(request)
    if ratelimit.is_locked(ip, user["username"]):
        auth.log_security_event("change_password_locked", user["username"], ip, "触发限流锁定")
        raise HTTPException(status_code=429, detail="尝试次数过多，请 15 分钟后再试")
    if not auth.check_password(user["username"], req.old_password):
        ratelimit.record_failure(ip, user["username"])
        auth.log_security_event("change_password_failure", user["username"], ip, "旧密码错误")
        raise HTTPException(status_code=401, detail="旧密码不正确")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    if not auth.change_password(user["username"], req.new_password):
        raise HTTPException(status_code=404, detail="用户不存在")
    ratelimit.reset(ip, user["username"])
    auth.log_security_event("change_password", user["username"], ip, "密码已修改")
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


# 首屏推荐问题缓存（10 分钟），避免每次刷新都调模型
_suggestions_cache: dict = {"ts": 0.0, "items": []}


@app.get("/api/chat/suggestions")
def chat_suggestions(user: dict = Depends(get_current_user)) -> dict:
    """基于知识库内容生成推荐问题（首屏用，带缓存）。"""
    import time

    now = time.time()
    if now - _suggestions_cache["ts"] < 600 and _suggestions_cache["items"]:
        return {"questions": _suggestions_cache["items"]}

    import chromadb
    from store import CHROMA_DIR, COLLECTION_NAME

    collection = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION_NAME)
    sample = collection.get(limit=5)
    if not sample or not sample.get("documents"):
        return {"questions": []}

    chunks = [
        {"text": text, "section": meta.get("section") or "", "file_name": meta.get("file_name")}
        for text, meta in zip(sample["documents"], sample["metadatas"])
    ]
    questions = generate_suggestions(chunks)
    _suggestions_cache.update(ts=now, items=questions)
    return {"questions": questions}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """管理员依赖：权限组里必须含 admin，否则 403（有资格问题，不是身份问题）。"""
    if "admin" not in user["groups"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@app.post("/api/documents/rebuild")
def rebuild_index(admin: dict = Depends(require_admin)) -> dict:
    """重建索引（仅管理员可调）。"""
    from store import build_index
    collection = build_index(chunk_size=150)  # 150 是评估结论推荐的分块大小
    return {"status": "ok", "chunks": collection.count()}


@app.post("/api/documents/upload")
def upload_document(req: UploadRequest, user: dict = Depends(get_current_user)) -> dict:
    """上传文档：保存 + 登记归属 + 重建索引。

    任何登录用户都可以上传（相当于 contributor），归属记录到登记表；
    删除/管理走归属守卫（见 DELETE 接口）。
    """
    # 防路径穿越：只允许纯文件名
    if Path(req.filename).name != req.filename:
        raise HTTPException(status_code=400, detail="文件名不合法")
    if Path(req.filename).suffix.lower() not in {".md", ".markdown", ".txt", ".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="不支持的格式")
    try:
        content = base64.b64decode(req.content_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="文件内容编码错误")

    data_dir = Path(__file__).resolve().parent.parent / "data" / "sample"
    (data_dir / req.filename).write_bytes(content)
    docmeta.register(req.filename, user["username"], req.access)
    auth.log_security_event("doc_upload", user["username"], "api", f"{req.filename} access={req.access}")

    from store import build_index
    collection = build_index(chunk_size=150)
    return {"status": "ok", "chunks": collection.count()}


@app.delete("/api/documents/{filename}")
def delete_document(filename: str, user: dict = Depends(get_current_user)) -> dict:
    """删除文档：只有上传者本人或管理员可以（归属守卫 OwnedDocOrAdmin）。"""
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="文件名不合法")
    meta = docmeta.get(filename)
    if meta is None:
        raise HTTPException(status_code=404, detail="文档不存在或未登记")
    if user["username"] != meta["creator"] and "admin" not in user["groups"]:
        raise HTTPException(status_code=403, detail="只有上传者或管理员可以删除")

    data_dir = Path(__file__).resolve().parent.parent / "data" / "sample"
    target = data_dir / filename
    if target.exists():
        target.unlink()
    docmeta.remove(filename)
    auth.log_security_event("doc_delete", user["username"], "api", filename)

    from store import build_index
    collection = build_index(chunk_size=150)
    return {"status": "ok", "chunks": collection.count()}
