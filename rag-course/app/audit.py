"""阶段 6a：审计日志 —— 每次问答留痕，可追溯。

被 main.py 的 /api/chat 调用。日志以 JSON Lines 格式追加写入
data/audit.jsonl（一行一条，方便程序读、人也看得懂）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

AUDIT_FILE = Path(__file__).resolve().parent.parent / "data" / "audit.jsonl"


def log_question(
    question: str,
    answer: str,
    citations: list[dict],
    *,
    user: str = "anonymous",
) -> None:
    """把一次问答追加写入审计日志。"""
    record = {
        "time": datetime.now().astimezone().isoformat(),  # 本地时间带时区
        "user": user,
        "question": question,
        "answer": answer,
        "citations": [
            {
                "section": c.get("section"),
                "file_name": c.get("file_name"),
                "score": round(c["score"], 4) if c.get("score") is not None else None,
                "text": c.get("text", "")[:200],  # 只留截断原文，防止日志膨胀
            }
            for c in citations
        ],
    }
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")