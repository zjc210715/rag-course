"""阶段 ③ + 升级④：前端界面 —— Streamlit 内部问答页面（流式 + 多轮历史）。

聊天走 FastAPI（权限与审计在服务端），文档上传 + 重建索引也通过后端接口，
前端不直接碰向量库，避免多进程同时访问 Chroma。

用法（在 rag-course 目录下）：
    1. 先启动后端：python -m uvicorn app.main:app --reload
    2. 再启动界面：streamlit run app/ui.py
"""
from __future__ import annotations

import json
from pathlib import Path

import requests
import streamlit as st

API = "http://127.0.0.1:8000"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
MAX_HISTORY_TURNS = 6

USERS = {
    "张三四（普通员工）": "zhangsan",
    "李四（财务）": "lisi",
    "匿名用户": "anonymous",
}

SUGGESTIONS = [
    "发薪日是什么时候",
    "请假超过三天找谁审批",
    "出差住宿标准是多少",
    "公司有哪些福利",
]

st.set_page_config(page_title="企业内部知识库", page_icon="📚")
st.title("📚 企业内部知识库问答")

# ---------- 侧边栏：身份 + 文档管理 ----------
user_label = st.sidebar.selectbox("当前用户", list(USERS))
user_id = USERS[user_label]
st.sidebar.caption(f"身份：`{user_id}`（权限由服务端判定）")

with st.sidebar.expander("文档管理"):
    uploaded = st.file_uploader("上传文档", type=["md", "txt", "pdf", "docx"])
    if uploaded is not None:
        target = DATA_DIR / uploaded.name
        target.write_bytes(uploaded.getvalue())
        st.success(f"已保存：{uploaded.name}")
    if st.button("重建索引"):
        with st.spinner("正在向量化并入库，请稍候…"):
            response = requests.post(f"{API}/api/documents/rebuild", timeout=300)
        if response.status_code == 200:
            st.success(f"已入库 {response.json()['chunks']} 个块")
        else:
            st.error(f"重建失败：{response.text[:200]}")

# ---------- 聊天 ----------
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("citations"):
            with st.expander(f"引用来源（{len(msg['citations'])} 条）"):
                for i, cite in enumerate(msg["citations"], 1):
                    st.markdown(
                        f"**[{i}] {cite['section']}** — {cite['file_name']}（分数 {cite['score']:.3f}）"
                    )
                    st.text(cite["text"])

# 首条消息前显示建议问题，发过消息后消失
if not st.session_state.messages:
    selected = st.pills("试试问：", SUGGESTIONS, label_visibility="collapsed")
    if selected:
        prompt = selected
    else:
        prompt = st.chat_input("问点什么？")
else:
    prompt = st.chat_input("问点什么？")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # 发送最近 MAX_HISTORY_TURNS 轮历史（去掉刚追加的当前问题）
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]
        ][-MAX_HISTORY_TURNS * 2 :]
        try:
            with requests.post(
                f"{API}/api/chat/stream",
                json={"question": prompt, "history": history},
                headers={"X-User-Id": user_id},
                stream=True,
                timeout=300,
            ) as response:
                if response.status_code != 200:
                    st.error(f"请求失败：{response.status_code} {response.text[:200]}")
                    st.session_state.messages.pop()
                else:
                    result: dict = {}

                    def token_gen():
                        """把 SSE 事件里的 token 逐个吐给 st.write_stream。"""
                        for line in response.iter_lines():
                            if not line or not line.startswith(b"data: "):
                                continue
                            event = json.loads(line[6:].decode("utf-8"))
                            if event["type"] == "token":
                                yield event["content"]
                            else:
                                result.update(event)  # citations / done

                    answer = st.write_stream(token_gen())
                    citations = result.get("citations", [])
                    if citations:
                        with st.expander(f"引用来源（{len(citations)} 条）"):
                            for i, cite in enumerate(citations, 1):
                                st.markdown(
                                    f"**[{i}] {cite['section']}** — {cite['file_name']}（分数 {cite['score']:.3f}）"
                                )
                                st.text(cite["text"])
                    st.session_state.messages.append(
                        {"role": "assistant", "content": answer, "citations": citations}
                    )
        except requests.exceptions.RequestException as exc:
            st.error(f"连接后端失败：{exc}")
            st.session_state.messages.pop()
