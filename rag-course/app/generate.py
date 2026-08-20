"""阶段 4 + 升级④：生成 —— 检索资料 + 多轮历史 + 流式输出。"""
from __future__ import annotations

from collections.abc import Iterator

import ollama

LLM_MODEL = "qwen3:8b"
MAX_HISTORY_TURNS = 6  # 最多携带 6 轮历史，防止上下文爆炸

SYSTEM_PROMPT = """你是企业内部知识库助手。请严格遵循以下规则：
1. 只依据【资料】回答问题，禁止编造资料中没有的信息；
2. 回答中用 [1]、[2] 这样的编号标注信息来源，编号对应【资料】的条目编号；
3. 如果资料中没有答案，直接回答"资料中没有相关信息"，不要猜测；
4. 可以结合【对话历史】理解指代（如"那发票呢"），但答案仍以【资料】为准；
5. 用简洁、准确的中文回答。"""


def build_messages(
    question: str,
    chunks: list[dict],
    history: list[dict] | None = None,
) -> list[dict]:
    context = "\n\n".join(f"[{i + 1}] {chunk['text']}" for i, chunk in enumerate(chunks))
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    # 历史每轮占两条消息（user + assistant），取最后 MAX_HISTORY_TURNS 轮
    for msg in (history or [])[-MAX_HISTORY_TURNS * 2 :]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": f"【资料】\n{context}\n\n【问题】{question}"})
    return messages


def generate_answer(
    question: str,
    chunks: list[dict],
    history: list[dict] | None = None,
) -> str:
    """chunks 是 retrieve() 的返回结果，每项含 text / section / file_name。"""
    response = ollama.chat(model=LLM_MODEL, messages=build_messages(question, chunks, history))
    return response["message"]["content"]


def stream_answer(
    question: str,
    chunks: list[dict],
    history: list[dict] | None = None,
) -> Iterator[str]:
    """流式生成：逐个 token 产出（供 SSE 使用）。"""
    stream = ollama.chat(
        model=LLM_MODEL,
        messages=build_messages(question, chunks, history),
        stream=True,
    )
    for piece in stream:
        yield piece["message"]["content"]


def generate_suggestions(chunks: list[dict], count: int = 4) -> list[str]:
    """基于知识库内容片段，让模型生成员工可能会问的问题（首屏推荐用）。"""
    context = "\n".join(
        f"[{i + 1}] {chunk['text'][:200]}" for i, chunk in enumerate(chunks[:5])
    )
    user_prompt = (
        "以下是企业内部知识库的部分内容片段。请根据这些内容，生成"
        f"{count} 个员工可能会问的问题。要求：只输出问题，每行一个，不要编号，不要解释。\n\n"
        f"内容：\n{context}"
    )
    response = ollama.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": user_prompt}],
    )
    questions = [
        line.strip().lstrip("0123456789.、- ").strip()
        for line in response["message"]["content"].splitlines()
        if line.strip()
    ]
    return questions[:count]
