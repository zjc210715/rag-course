# 企业内部知识库 RAG —— 项目总结

> 从零手写、可内网部署的企业知识库问答系统。纯 Python RAG（不依赖 LangChain），
> 全流程覆盖：文档接入 → 向量检索 → 生成问答 → 权限/审计/登录 → 评估 → 部署。

## 里程碑

| 提交 | 内容 |
| --- | --- |
| b23c343 | 从零搭建：RAG 全流程 + Docker + 评估 |
| 04b6ccc | 生产加固：登录认证 + 限流 + 设计版前端 |
| 本次 | 安全日志 + 管理员权限 + HTTPS 反代 + 备份脚本 |

## 技术栈

| 组件 | 选择 |
| --- | --- |
| LLM | Qwen3 8B（Ollama 本地） |
| Embedding | bge-m3（Ollama 本地） |
| 向量库 | Chroma（持久化） |
| 后端 | FastAPI（REST + SSE） |
| 前端 | Streamlit（登录门禁 + 流式聊天） |
| 认证 | SQLite + pbkdf2 + 服务端 token |
| 部署 | Docker Compose（nginx + backend + ollama） |

## 架构

```mermaid
flowchart LR
    U[员工浏览器] -->|HTTPS 443| N[nginx<br/>TLS + 反代 + SSE]
    N -->|/api| B[backend<br/>FastAPI]
    B --> O[ollama<br/>qwen3 + bge-m3]
    B <--> V1[(app_data 卷<br/>chroma + users.db + audit)]
    O <--> V2[(ollama_data 卷<br/>模型文件)]
    S[备份脚本] -.每日备份.-> V1
```

## 功能模块

- 文档接入：md/txt/pdf/docx，PDF 页码，清洗 + 分块（150 字，经评估确定）
- 检索：向量召回 top20 + 语义/BM25 混合重排 + 权限过滤
- 问答：防幻觉 Prompt、引用标注、多轮历史、SSE 流式
- 认证：登录/登出/改密、pbkdf2 渐进重哈希、服务端 token（30 分钟）
- 权限：文档 access 标签 + 数据库层过滤；admin 角色
- 审计：问答审计（JSONL）+ 安全事件日志（SQLite）
- 限流：登录/改密按 IP+用户名，5 次/5 分钟锁 15 分钟
- 评估：Hit@3（15/15）+ LLM 裁判（忠实度/相关性）
- 运维：备份脚本 + 恢复演练 + 轮转保留 7 份

## 安全体系（分层）

1. 传输：HTTPS（nginx TLS 终结，内部 CA）
2. 身份：登录 token（30 分钟过期、可即时吊销）
3. 权限：默认拒绝 + access 标签过滤 + admin 校验
4. 行为：问答审计 + 安全事件日志
5. 对抗：限流 + 慢哈希 + XFF 防伪造

## 部署

```bash
docker compose up -d --build
# 首次：容器内拉模型
docker exec rag-ollama ollama pull bge-m3
docker exec rag-ollama ollama pull qwen3:8b
```

## 评估结论

- Hit@3 = 15/15（15 条正文关键词测试集）
- chunk_size=150、权重 0.7/0.3、top_n=3（对比实验确定）
- 语料扩大后需重跑实验

## 剩余事项

- SSO/OIDC（视公司是否有 IdP）
- Streamlit 前端纳入 Docker + nginx（当前本地跑）
- Cookie 会话（可缓）
- 上线清单：改默认密码、安全日志保留策略、备份接定时任务
