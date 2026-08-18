"""阶段 5（下半场）：答案级评估 —— 用 LLM 当裁判，检查忠实度与相关性。

用法（在 rag-course 目录下）：
    python app/eval_answer.py
"""
from __future__ import annotations

import json
import re
import sys

import ollama

from eval import TEST_CASES
from generate import LLM_MODEL, generate_answer
from retrieve import retrieve

JUDGE_PROMPT = """你是严格的 RAG 质量评审员。请根据【资料】评估【答案】的质量。

评分标准（每项 1~5 分）：
1. 忠实度（faithfulness）：答案中的每个论断是否都能在【资料】中找到依据，有没有编造或推测资料中不存在的内容。
2. 相关性（relevance）：答案是否直接回答了【问题】，没有答非所问。

输出要求：只输出一个 JSON 对象，不要输出其他内容：
{"faithfulness": 分数, "faithfulness_reason": "一句话理由", "relevance": 分数, "relevance_reason": "一句话理由"}
"""


def judge(question: str, chunks: list[dict], answer: str) -> dict:
    context = "\n\n".join(f"[{i + 1}] {chunk['text']}" for i, chunk in enumerate(chunks))
    user_prompt = f"【资料】\n{context}\n\n【问题】{question}\n\n【答案】\n{answer}"
    response = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    text = response["message"]["content"]
    # 容忍裁判在 JSON 前后多说几句：先找扁平 JSON，再退回贪婪匹配
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL) or re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"裁判没有输出 JSON：{text[:200]}")
    return json.loads(match.group(0))


def main() -> None:
    total_faith = 0.0
    total_rel = 0.0
    for case in TEST_CASES:
        question = case["question"]
        chunks = retrieve(question)
        answer = generate_answer(question, chunks)
        scores = judge(question, chunks, answer)
        total_faith += scores["faithfulness"]
        total_rel += scores["relevance"]
        print(f"【{question}】")
        print(f"  答案：{answer[:100].replace(chr(10), ' ')}…")
        print(f"  忠实度 {scores['faithfulness']}/5：{scores['faithfulness_reason']}")
        print(f"  相关性 {scores['relevance']}/5：{scores['relevance_reason']}")
        print()
    count = len(TEST_CASES)
    print(f"平均忠实度：{total_faith / count:.2f} / 5")
    print(f"平均相关性：{total_rel / count:.2f} / 5")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    main()