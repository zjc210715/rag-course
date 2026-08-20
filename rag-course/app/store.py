"""阶段 2 + 6b：向量化与入库 —— 把分块结果变成向量存进 Chroma，并打上权限标签。

用法（在 rag-course 目录下）：
    python app/store.py                          # 重建索引
    python app/store.py --query "发薪日是什么时候"   # 入库后顺手测一次检索
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import chromadb
import ollama

import docmeta
from ingest import SUPPORTED_SUFFIXES, Chunk, process_document

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
CHROMA_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma"
COLLECTION_NAME = "kb_rag"
EMBED_MODEL = "bge-m3"

# 文档访问权限标签：all=全员可见；finance=仅财务可见（阶段 6b 教学演示）
FILE_ACCESS = {
    "员工手册.md": "all",
    "员工手册.docx": "all",
    "差旅报销制度.md": "finance",
    "差旅报销制度.pdf": "finance",
}

def embed_texts(texts: list[str]) -> list[list[float]]:
    """用 bge-m3 把一批文本转成向量（入库和查询共用同一个模型）。"""
    response = ollama.embed(model=EMBED_MODEL, input=texts)
    return response["embeddings"]


def build_index(chunk_size: int = 500, overlap: int = 50) -> chromadb.Collection:
    """加载文档 → 分块 → 打权限标签 → 向量化 → 存入 Chroma（每次运行都重建索引）。"""
    docmeta.ensure_seeded()
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.get_or_create_collection(COLLECTION_NAME)

    chunks: list[Chunk] = []
    for path in sorted(DATA_DIR.iterdir()):
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            for chunk in process_document(path, chunk_size=chunk_size, overlap=overlap):
                # 权限标签优先读登记表（上传时指定），没有则回退硬编码默认
                meta = docmeta.get(path.name)
                chunk.metadata["access"] = meta["access"] if meta else FILE_ACCESS.get(path.name, "all")
                chunks.append(chunk)

    if not chunks:
        print("没有可入库的块，请检查 data/sample 目录")
        sys.exit(1)

    embeddings = embed_texts([c.text for c in chunks])
    ids = [f"{c.metadata['file_name']}::{c.metadata['chunk_index']}" for c in chunks]
    metadatas = [{k: v for k, v in c.metadata.items() if v is not None} for c in chunks]

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=[c.text for c in chunks],
        metadatas=metadatas,
    )
    print(f"已入库 {len(chunks)} 个块 → {CHROMA_DIR}（chunk_size={chunk_size}, overlap={overlap}）")
    return collection


def search(collection: chromadb.Collection, query: str, top_k: int = 3) -> None:
    """把一个提问转成向量去 Chroma 里找最相似的块。"""
    query_embeddings = embed_texts([query])
    result = collection.query(query_embeddings=query_embeddings, n_results=top_k)
    print(f"\n提问：{query}")
    for doc, meta, dist in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
        section = meta.get("section") or meta.get("file_name")
        print(f"\n  [距离 {dist:.4f}] {section}（access={meta.get('access')}）")
        print(f"  {doc[:70].replace(chr(10), ' ')}…")


def main() -> None:
    parser = argparse.ArgumentParser(description="向量化并入库（Chroma）")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--overlap", type=int, default=50)
    parser.add_argument("--query", type=str, default="", help="入库后测试一个提问")
    args = parser.parse_args()

    collection = build_index(chunk_size=args.chunk_size, overlap=args.overlap)
    if args.query:
        search(collection, args.query)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    main()
