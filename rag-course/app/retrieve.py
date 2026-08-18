"""阶段 3 + 6b：检索与重排 + 权限过滤。

两阶段漏斗：
1. 召回：向量检索取 top_k 候选，同时按用户权限过滤（Chroma where，数据库层过滤）；
2. 重排：语义分 + 关键词分(BM25) 混合，取最终 top_n。

用法（在 rag-course 目录下）：
    python app/retrieve.py "请假超过三天找谁审批"
    python app/retrieve.py "出差住宿标准是多少" --groups all
    python app/retrieve.py "出差住宿标准是多少" --groups all,finance
"""
from __future__ import annotations

import argparse
import math
import re
import sys

import chromadb

from store import CHROMA_DIR, COLLECTION_NAME, embed_texts

DENSE_WEIGHT = 0.7
LEXICAL_WEIGHT = 0.3
RECALL_K = 20
FINAL_N = 3


def tokenize(text: str) -> list[str]:
    """中文按相邻两字切（bigram），英文数字按单词切。"""
    tokens = [word.lower() for word in re.findall(r"[a-zA-Z0-9]+", text)]
    hanzi = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.extend("".join(pair) for pair in zip(hanzi, hanzi[1:]))
    return tokens


def bm25_score(query_tokens, doc_text, doc_freq, total_docs):
    """简化版 BM25：词频饱和 + IDF（稀有词权重更高）。"""
    score = 0.0
    for token in set(query_tokens):
        tf = doc_text.count(token)
        if tf == 0:
            continue
        idf = math.log(1 + (total_docs - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5))
        score += (tf / (tf + 1.0)) * idf
    return score


def retrieve(
    query: str,
    top_k: int = RECALL_K,
    final_n: int = FINAL_N,
    groups: list[str] | None = None,
) -> list[dict]:
    """检索 + 重排，返回最终命中的块列表。

    groups：当前用户拥有的权限组（如 ["all"] 或 ["all", "finance"]）。
    传 None 表示不限制（开发模式）；传入后只在有权访问的块里检索。
    """
    collection = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION_NAME)
    where = None
    if groups is not None:
        where = {"access": {"$in": groups}}  # 数据库层过滤：没权限的块根本不会被召回
    result = collection.query(
        query_embeddings=embed_texts([query]),
        n_results=top_k,
        where=where,
    )
    docs, metas, dists = result["documents"][0], result["metadatas"][0], result["distances"][0]

    # 语义分：L2 距离越小越相似，转成 0~1
    dense = [1.0 / (1.0 + d) for d in dists]

    # 关键词分：BM25，章节路径也纳入匹配文本（标题被移出了正文）
    query_tokens = tokenize(query)
    doc_freq: dict[str, int] = {}
    for doc, meta in zip(docs, metas):
        for token in set(tokenize((meta.get("section") or "") + doc)):
            doc_freq[token] = doc_freq.get(token, 0) + 1
    lexical_raw = [
        bm25_score(query_tokens, (meta.get("section") or "") + doc, doc_freq, len(docs))
        for doc, meta in zip(docs, metas)
    ]
    lexical_max = max(lexical_raw) or 1.0
    lexical = [s / lexical_max for s in lexical_raw]

    scored = sorted(
        zip(docs, metas, dense, lexical),
        key=lambda x: DENSE_WEIGHT * x[2] + LEXICAL_WEIGHT * x[3],
        reverse=True,
    )[:final_n]

    return [
        {
            "text": doc,
            "section": meta.get("section") or meta.get("file_name"),
            "file_name": meta.get("file_name"),
            "score": DENSE_WEIGHT * d + LEXICAL_WEIGHT * lex,
        }
        for doc, meta, d, lex in scored
    ]


def search(query: str, groups: list[str] | None = None) -> None:
    hits = retrieve(query, groups=groups)
    print(f"提问：{query}（权限组：{groups or '不限制'}）\n")
    for rank, hit in enumerate(hits, 1):
        print(f"#{rank} [综合 {hit['score']:.4f}] {hit['section']}")
        print(f"   {hit['text'][:80].replace(chr(10), ' ')}…\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="检索 + 重排（含权限过滤）")
    parser.add_argument("query", help="提问内容")
    parser.add_argument("--groups", type=str, default="", help="逗号分隔的权限组，如 all,finance；不传则不限制")
    args = parser.parse_args()
    groups = [g.strip() for g in args.groups.split(",") if g.strip()] if args.groups else None
    search(args.query, groups=groups)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    main()