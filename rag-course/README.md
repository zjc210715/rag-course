# 企业内部知识库 RAG（rag-course）

从零手写的企业内网知识库问答系统：**纯 Python 实现 RAG（不依赖 LangChain）**，
Ollama 本地开源模型，支持多格式文档、登录认证、权限隔离、审计日志、限流、
评估、设计版前端与 Docker 部署。

## 技术栈

| 组件 | 选择 | 说明 |
| --- | --- | --- |
| LLM | Qwen3 8B（Ollama 本地） | 内网离线，中文强 |
| Embedding | bge-m3（Ollama 本地） | 中文检索效果好 |
| 向量库 | Chroma（本地持久化） | 零运维，数据在 data/chroma/ |
| 后端 | FastAPI | REST + SSE 流式 |
| 前端 | Streamlit | 内部工具快速出界面，含设计版主题 |
| 认证 | SQLite + pbkdf2 + 服务端 token | 密码加盐慢哈希，会话可即时吊销 |
| 限流 | 内存计数（IP+用户名） | 5 分钟 5 次失败锁定 15 分钟 |
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
│   ├── main.py          # FastAPI：问答 / 鉴权 / 审计 / 统计接口
│   ├── auth.py          # 登录：用户库 / 密码哈希 / 会话 token / 改密
│   ├── ratelimit.py     # 登录与改密限流（防暴力破解）
│   ├── audit.py         # 审计日志（JSONL）
│   ├── eval.py          # 检索评估 Hit@3
│   ├── eval_answer.py   # 答案评估（LLM 当裁判）
│   └── ui.py            # Streamlit 前端（登录门禁 + 流式聊天）
├── .streamlit/config.toml  # 前端主题（档案蓝 + 印章红，宋体标题）
├── assets/logo.svg      # 品牌标识
├── data/
│   ├── sample/          # 示例文档（员工手册、差旅报销制度，含 md/docx/pdf）
│   ├── chroma/          # 向量库数据（git 忽略）
│   ├── audit.jsonl      # 问答审计日志（git 忽略）
│   └── users.db         # 用户与会话库（git 忽略）
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 本地启动

```bash
python app/auth.py seed                 # 初始化用户库 + 默认账号（首次）
python app/store.py --chunk-size 150   # 首次建索引
python -m uvicorn app.main:app --reload   # 终端 1：后端
streamlit run app/ui.py                    # 终端 2：前端
```

默认账号：`zhangsan`（普通员工）/ `lisi`（财务），首次创建密码 `123456`，
**上线前务必修改**：`python app/auth.py change-password`，或登录后在侧边栏"修改密码"。

## Docker 部署

```bash
docker compose up -d --build
docker exec rag-ollama ollama pull bge-m3
docker exec rag-ollama ollama pull qwen3:8b
docker exec rag-backend python app/store.py --chunk-size 150
```

## 功能

- 多格式文档（Markdown / TXT / PDF / DOCX），PDF 记录页码
- 检索：向量召回 + BM25 混合重排；分块参数经对比实验确定（150 字）
- 生成：带引用标注、防幻觉 Prompt、多轮对话、SSE 流式输出
- 登录认证：pbkdf2 加盐慢哈希（60 万次迭代，登录时渐进重哈希）、
  服务端会话 token（30 分钟过期、可即时吊销）、登录后修改密码
- 权限：文档 access 标签 + Chroma where 数据库层过滤；默认拒绝未登录访问
- 管理员：groups 含 admin 的角色才能重建索引（/api/documents/rebuild）
- 限流：登录/改密按 IP+用户名 5 分钟 5 次失败锁定 15 分钟
- 审计：问答留痕（用户/时间/问题/答案/引用），用户名来自服务端验证
- 安全日志：登录成功/失败/锁定、登出、改密事件入库，可用
  `python app/auth.py security-log` 查询
- 评估：Hit@3 检索评估 + LLM 裁判答案评估（忠实度/相关性）
- 前端：档案蓝主题、指标卡、印章式引用卡、流式打字效果

## 当前评估结论

- 测试集：15 条（正文关键词），内容命中率 Hit@3 = 15/15
- 对比实验结论：chunk_size=150 最佳（引用标签准确）；权重 0.7/0.3、top_n=3 保持默认；
  语料扩大后需重跑实验

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/auth/login | 登录，返回 token（限流保护） |
| POST | /api/auth/logout | 登出，吊销 token |
| GET | /api/auth/me | 当前登录用户 |
| POST | /api/auth/change-password | 修改密码（需登录，改后踢出全部会话） |
| POST | /api/chat | 问答（需 Bearer token，支持 history） |
| POST | /api/chat/stream | SSE 流式问答（需 Bearer token） |
| POST | /api/documents/rebuild | 重建索引 |
| GET | /api/stats | 统计信息（文档数/向量块/用户数） |
| GET | /api/health | 健康检查 |

除 health/stats 外，接口均需请求头 `Authorization: Bearer <token>`。

## 已知简化与生产注意事项

- 多轮对话：历史帮助理解指代，但检索仍基于当前问题（查询改写是进阶）
- 扫描版 PDF 需 OCR；同内容多格式会产生重复检索结果（需去重）
- 限流为单进程内存实现，多 worker 需换 Redis
- 未接统一认证（SSO/AD），生产建议接 OIDC
- 生产必做：HTTPS、默认密码修改、安全日志保留策略与告警
- 运维备份：`powershell -File scripts/backup.ps1` 每日备份数据卷（含轮转），
  `powershell -File scripts/restore-check.ps1` 演练恢复；建议接计划任务/定时任务
