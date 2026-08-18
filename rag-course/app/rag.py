"""阶段 4 + 6b + 升级④：RAG 问答闭环 —— 检索 → 拼上下文 → 生成带引用的答案。

支持多轮历史（history）与流式输出（ask_stream）。

用法（在 rag-course 目录下）：
    python app/rag.py "发薪日是什么时候"
"""
from __future__ import annotations

import sys
from collections.abc import Iterator

from generate import generate_answer, stream_answer
from retrieve import retrieve


def ask(
    question: str,
    groups: list[str] | None = None,
    history: list[dict] | None = None,
) -> dict:
    chunks = retrieve(question, groups=groups)
    answer = generate_answer(question, chunks, history=history)
    return {"answer": answer, "citations": chunks}


def ask_stream(
    question: str,
    groups: list[str] | None = None,
    history: list[dict] | None = None,
) -> Iterator[dict]:
    """流式问答：先发 citations（前端可先展示来源），再逐个 token，最后 done。"""
    chunks = retrieve(question, groups=groups)
    yield {"type": "citations", "citations": chunks}
    answer_parts: list[str] = []
    for token in stream_answer(question, chunks, history=history):
        answer_parts.append(token)
        yield {"type": "token", "content": token}
    yield {"type": "done", "answer": "".join(answer_parts)}


def main() -> None:
    question = " ".join(sys.argv[1:]) or "发薪日是什么时候"
    result = ask(question)
    print(f"问题：{question}\n")
    print(result["answer"])
    print("\n--- 引用来源 ---")
    for i, chunk in enumerate(result["citations"], 1):
        print(f"[{i}] {chunk['section']}（{chunk['file_name']}）")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    main()
