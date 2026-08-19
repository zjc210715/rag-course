"""阶段 ③ + 升级④ + 设计版 + ⑦：登录模块前端。

- 未登录：主区显示登录卡片（用户名/密码 + 匿名进入），聊天不可用；
- 登录后：token 存 st.session_state，请求带 Authorization 头；
- 退出：调 /api/auth/logout 吊销 token 并清空会话与对话历史。
"""
from __future__ import annotations

import json
from pathlib import Path

import requests
import streamlit as st

API = "http://127.0.0.1:8000"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
MAX_HISTORY_TURNS = 6

USERS = [
    {"id": "zhangsan", "role": "普通员工", "icon": ":material/person:"},
    {"id": "lisi", "role": "财务", "icon": ":material/account_balance_wallet:"},
]

SUGGESTIONS = [
    "发薪日是什么时候",
    "请假超过三天找谁审批",
    "出差住宿标准是多少",
    "公司有哪些福利",
]

st.set_page_config(
    page_title="企业知识库",
    page_icon=":material/menu_book:",
    layout="centered",
)
st.logo("assets/logo.svg")

# 唯一的动效：顶部开场的"升起"
st.html("""
<style>
@keyframes rise {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
.st-key-hero { animation: rise 0.55s ease-out both; }
@media (prefers-reduced-motion: reduce) {
  .st-key-hero { animation: none; }
}
</style>
""")


def auth_headers() -> dict:
    """把登录 token 转成请求头；匿名访客返回空字典（后端自动视为匿名）。"""
    auth = st.session_state.get("auth")
    if auth and auth.get("token"):
        return {"Authorization": f"Bearer {auth['token']}"}
    return {}


def user_icon(username: str) -> str:
    """按用户名选头像图标。"""
    return next((u["icon"] for u in USERS if u["id"] == username), ":material/person:")


def render_citations(citations: list[dict]) -> None:
    """把引用渲染成盖章式出处卡。"""
    for i, cite in enumerate(citations, 1):
        with st.container(border=True):
            cols = st.columns([2, 10], vertical_alignment="center")
            cols[0].badge(str(i), color="red")
            with cols[1]:
                st.markdown(f"**{cite['section']}**")
                st.caption(f"{cite['file_name']} · 相关度 `{cite['score']:.3f}`")


# ---------- 登录门禁 ----------
if "auth" not in st.session_state:
    st.session_state.auth = None

if st.session_state.auth is None:
    with st.container(key="hero", horizontal_alignment="center"):
        st.caption("内部制度知识库")
        st.title("问制度 · 答有出处", anchor=False)
        st.caption("登录后即可查询，回答都带出处")
    st.space("medium")
    with st.container(border=True):
        with st.form("login_form"):
            username = st.text_input("用户名", placeholder="zhangsan")
            password = st.text_input("密码", type="password", placeholder="输入密码")
            submitted = st.form_submit_button("登录", type="primary")
        if submitted:
            with st.spinner("正在验证…"):
                resp = requests.post(
                    f"{API}/api/auth/login",
                    json={"username": username, "password": password},
                    timeout=10,
                )
            if resp.status_code == 200:
                st.session_state.auth = resp.json()  # {token, username, groups}
                st.rerun()
            elif resp.status_code == 429:
                st.error("尝试次数过多，请 15 分钟后再试", icon=":material/lock:")
            else:
                st.error("用户名或密码错误", icon=":material/error:")
    st.stop()

auth_state = st.session_state.auth
username = auth_state["username"]

# ---------- 顶部：一句话主张 + 档案摘要 ----------
with st.container(key="hero", horizontal_alignment="center"):
    st.caption("内部制度知识库")
    st.title("问制度 · 答有出处", anchor=False)
    st.caption(f"当前登录：`{username}` · 回答只依据库内文档生成，并标注来源章节与文件")
st.space("medium")

try:
    stats = requests.get(f"{API}/api/stats", timeout=5).json()
except Exception:
    stats = {}
with st.container(horizontal=True):
    st.metric("库内文档", stats.get("documents", "—"), border=True)
    st.metric("向量块", stats.get("chunks", "—"), border=True)
    st.metric("可用身份", stats.get("users", "—"), border=True)
st.space("small")

# ---------- 侧边栏 ----------
with st.sidebar:
    st.subheader("当前身份")
    st.caption(f"{user_icon(username)} `{username}` · 权限组 {auth_state.get('groups')}")
    st.space("medium")

    try:
        online = requests.get(f"{API}/api/health", timeout=3).status_code == 200
    except Exception:
        online = False
    st.badge(
        "服务在线" if online else "服务离线",
        icon=":material/check_circle:" if online else ":material/error:",
        color="green" if online else "red",
    )
    st.space("small")

    with st.container(border=True):
        st.markdown("**管理文档**")
        uploaded = st.file_uploader(
            "上传文档", type=["md", "txt", "pdf", "docx"], label_visibility="collapsed"
        )
        if uploaded is not None:
            target = DATA_DIR / uploaded.name
            target.write_bytes(uploaded.getvalue())
            st.toast(f"已保存：{uploaded.name}", icon=":material/check_circle:")
        if st.button("重建索引", type="primary", icon=":material/sync:"):
            with st.spinner("正在向量化并入库…"):
                response = requests.post(f"{API}/api/documents/rebuild", timeout=300)
            if response.status_code == 200:
                st.toast(f"已入库 {response.json()['chunks']} 个块", icon=":material/database:")
            else:
                st.error(f"重建失败：{response.text[:200]}", icon=":material/error:")

    st.space("medium")
    with st.expander("修改密码", icon=":material/password:"):
        with st.form("change_pw_form"):
            cp_old = st.text_input("旧密码", type="password")
            cp_new = st.text_input("新密码（至少 8 位）", type="password")
            cp_new2 = st.text_input("再次输入新密码", type="password")
            cp_submit = st.form_submit_button("修改密码", type="primary")
        if cp_submit:
            if cp_new != cp_new2:
                st.error("两次输入的新密码不一致", icon=":material/error:")
            elif len(cp_new) < 8:
                st.error("新密码至少 8 位", icon=":material/error:")
            else:
                with st.spinner("正在修改…"):
                    resp = requests.post(
                        f"{API}/api/auth/change-password",
                        json={"old_password": cp_old, "new_password": cp_new},
                        headers=auth_headers(),
                        timeout=10,
                    )
                if resp.status_code == 200:
                    st.success("密码已修改，请重新登录", icon=":material/check_circle:")
                    st.session_state.auth = None
                    st.rerun()
                elif resp.status_code == 401:
                    st.error("旧密码不正确或登录已失效", icon=":material/error:")
                else:
                    st.error(resp.json().get("detail", "修改失败"), icon=":material/error:")

    st.space("large")
    if st.button("退出登录", icon=":material/logout:"):
        if auth_state.get("token"):
            try:
                requests.post(f"{API}/api/auth/logout", headers=auth_headers(), timeout=5)
            except requests.exceptions.RequestException:
                pass
        st.session_state.auth = None
        st.session_state.messages = []  # 清空对话，防止下一个人的历史串台
        st.rerun()
    st.caption("v1.3 · 内部使用")

# ---------- 聊天 ----------
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.container(gap="large"):
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            icon = user_icon(msg.get("user_id", "anonymous"))
        else:
            icon = ":material/psychology:"
        with st.chat_message(msg["role"], avatar=icon):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("citations"):
                st.space("small")
                render_citations(msg["citations"])

    if not st.session_state.messages:
        st.space("medium")
        st.caption("试试从这几个问题开始，或直接输入")
        selected = st.pills("建议问题", SUGGESTIONS, label_visibility="collapsed")
    else:
        selected = None

if not st.session_state.messages:
    prompt = selected if selected else st.chat_input("输入问题，比如：请假超过三天找谁审批")
else:
    prompt = st.chat_input("输入问题，比如：请假超过三天找谁审批")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt, "user_id": username})
    with st.container(gap="large"):
        with st.chat_message("user", avatar=user_icon(username)):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar=":material/psychology:"):
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages[:-1]
            ][-MAX_HISTORY_TURNS * 2 :]
            try:
                with requests.post(
                    f"{API}/api/chat/stream",
                    json={"question": prompt, "history": history},
                    headers=auth_headers(),
                    stream=True,
                    timeout=300,
                ) as response:
                    if response.status_code == 401:
                        st.session_state.auth = None
                        st.rerun()  # 登录失效 → 回到登录页
                    elif response.status_code != 200:
                        st.error(f"请求失败：{response.status_code} {response.text[:200]}")
                        st.session_state.messages.pop()
                    else:
                        result: dict = {}

                        def token_gen():
                            for line in response.iter_lines():
                                if not line or not line.startswith(b"data: "):
                                    continue
                                event = json.loads(line[6:].decode("utf-8"))
                                if event["type"] == "token":
                                    yield event["content"]
                                else:
                                    result.update(event)

                        answer = st.write_stream(token_gen())
                        citations = result.get("citations", [])
                        if citations:
                            st.space("small")
                            render_citations(citations)
                        st.session_state.messages.append(
                            {"role": "assistant", "content": answer, "citations": citations}
                        )
            except requests.exceptions.RequestException as exc:
                st.error(f"连接后端失败：{exc}")
                st.session_state.messages.pop()
