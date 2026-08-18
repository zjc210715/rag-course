# 企业内部知识库 RAG（rag-course）

从零手写的企业内网知识库问答系统：**纯 Python 实现 RAG（不依赖 LangChain）**，
Ollama 本地开源模型，支持多格式文档、权限隔离、审计日志、评估与 Docker 部署。

## 技术栈

| 组件 | 选择 | 说明 |
| --- | --- | --- |
| LLM | Qwen3 8B（Ollama 本地） | 内网离线，中文强 |
| Embedding | bge-m3（Ollama 本地） | 中文检索效果好 |
| 向量库 | Chroma（本地持久化） | 零运维，数据在 data/chroma/ |
| 后端 | FastAPI | REST + SSE 流式 |
| 前端 | Streamlit | 内部工具快速出界面 |
| 部署 | Docker Compose | backend + ollama 两容器 |

## 目录结构

```text
rag-course/
├── app/
│   ├── ingest.py        # 文档接入：加载(md/txt/pdf/docx) → 清洗 → 分块 → 元数据
│   ├── store.py         # 向量化(bge-m3) + 入库(Chroma) + 权限标签
│   ├── retrieve.py      # 检索 + 重排（向量 top20 → 语义+BM25 混合）+ 权限过滤
│   ├── generate.py      # 生成（Prompt 防幻觉 + 多轮历史 + 流式）
│   ├── rag.py           # 问答闭环 ask() / ask_stream()
│   ├── main.py          # FastAPI：/api/chat、/api/chat/stream、/api/documents/rebuild
│   ├── audit.py         # 审计日志（JSONL）
│   ├── eval.py          # 检索评估 Hit@3
│   ├── eval_answer.py   # 答案评估（LLM 当裁判：忠实度/相关性）
│   └── ui.py            # Streamlit 前端
├── data/
│   ├── sample/          # 示例文档（员工手册、差旅报销制度，含 md/docx/pdf）
│   ├── chroma/          # 向量库数据（git 忽略）
│   └── audit.jsonl      # 审计日志（git 忽略）
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 本地启动

```bash
python -m uvicorn app.main:app --reload   # 终端 1：后端
streamlit run app/ui.py                    # 终端 2：前端
```

首次使用先建索引：

```bash
python app/store.py --chunk-size 150
```

## Docker 部署

```bash
docker compose up -d --build
docker exec rag-ollama ollama pull bge-m3
docker exec rag-ollama ollama pull qwen3:8b
docker exec rag-backend python app/store.py --chunk-size 150
```

## 功能

- 多格式文档（Markdown / TXT / PDF / DOCX），PDF 记录页码
- 检索：向量召回 + BM25 混合重排
- 生成：带引用标注、防幻觉 Prompt、多轮对话、SSE 流式输出
- 权限：文档 access 标签 + Chroma where 数据库层过滤，服务端用户→权限组
- 审计：每次问答留痕（用户/时间/问题/答案/引用）
- 评估：Hit@3 检索评估 + LLM 裁判答案评估

## 当前评估结论

- 测试集：15 条（正文关键词），内容命中率 Hit@3 = 15/15
- 对比实验结论：chunk_size=150 最佳（引用标签准确）；权重 0.7/0.3、top_n=3 保持默认；
  语料扩大后需重跑实验

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/chat | 问答（支持 history 多轮） |
| POST | /api/chat/stream | SSE 流式问答 |
| POST | /api/documents/rebuild | 重建索引 |
| GET | /api/health | 健康检查 |

## 已知简化与后续方向

- 多轮对话：历史帮助模型理解指代，但检索仍基于当前问题（查询改写是进阶）
- 扫描版 PDF 需 OCR
- 同内容多格式会产生重复检索结果（生产需统一格式或去重）
- 权限映射是教学简化（USER_GROUPS），生产接 SSO/JWT 并默认拒绝
- 前端对话历史不持久化（刷新即失），生产可接会话存储
