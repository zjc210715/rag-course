# 运维手册（OPS）

> 适用系统：rag-course 企业内部知识库 RAG（Docker Compose 部署）
> 值班原则：**先恢复服务，再排查根因；任何变更前先备份、留后路。**

## 1. 系统组成

| 容器 | 作用 | 端口 |
| --- | --- | --- |
| rag-nginx | HTTPS 终结 + 反向代理 + SSE | 80 / 443 |
| rag-backend | FastAPI 业务（问答/认证/审计） | 8000（仅本机） |
| rag-ollama | 模型服务（qwen3 8B + bge-m3） | 11434（仅内部网络） |

数据卷：`rag-course_app_data`（chroma + users.db + audit）、`rag-course_ollama_data`（模型）。

## 2. 日常巡检（每天约 5 分钟）

| 检查项 | 命令 | 正常表现 |
| --- | --- | --- |
| 服务状态 | `docker compose ps` | 三容器 `Up`，无 `Restarting` |
| 接口健康 | `curl -k https://<域名>/api/health` | `{"status":"ok"}` |
| 资源占用 | `docker stats --no-stream` | CPU/内存无异常飙升 |
| 安全日志 | `docker exec rag-backend python app/auth.py security-log` | 无连续失败/异常锁定 |
| 磁盘 | `df -h` | 使用率 < 80% |

## 3. 备份与恢复

```text
每日 03:00  自动备份（schtasks 定时任务 KB-Backup）
每周        跑恢复演练 scripts/restore-check.ps1（验完整性）
每月        真演练：测试机还原到全新环境，跑起来、问一句
```

备份文件：`backups/kb-<时间戳>.tar.gz`，自动轮转保留 7 份。

**恢复步骤（数据回滚）**：

```text
1. docker compose stop backend
2. 解压最新备份，确认内容
3. 替换数据卷内容（docker cp 回容器或挂载点）
4. docker compose start backend
5. 验证：health + 登录 + 提问
```

## 4. 更新与回滚

**标准流程**：备份 → `git pull` → 看变更 → `docker compose up -d --build` → 验证 → 出问题回滚。

| 更新类型 | 操作 | 注意 |
| --- | --- | --- |
| 代码 | `docker compose up -d --build` | 几十秒到几分钟 |
| 依赖 | 改 requirements.txt 后 rebuild | pip 全量重装，慢，挑低峰期 |
| 模型 | `docker exec rag-ollama ollama pull <模型>` 先单独验证 | 不要直接换正在用的模型 |

**改动 docker-compose.yml 后**：建议用 `docker compose up -d` 让 nginx 一起重建，而不是只 restart 单个容器——否则 nginx 缓存的是旧容器 IP，会 502（见第 5 节）。

**回滚**：

```text
代码回滚：git revert <提交> → docker compose up -d --build
数据回滚：按第 3 节恢复流程，从备份还原
```

## 5. 故障排查

排查三步：`docker compose ps`（谁没起来）→ `docker compose logs <服务> --tail 100`（报了什么）→ 按下表处理。

| 症状 | 常见原因 | 处理 |
| --- | --- | --- |
| nginx 502 | backend/ui 容器挂了或重启中 | 先看 `docker compose ps` + `docker compose logs backend --tail 100` / `logs ui`，查完 `docker compose restart backend` |
| nginx 502（backend/ui 日志都正常） | 容器重建后换了新 IP，nginx 还缓存旧 IP | `docker compose restart nginx` 让它重新解析服务名；仍不行则 `docker compose up -d --force-recreate` 全套重建 |
| 端口冲突 | 宿主机程序占端口 | `netstat -ano \| findstr <端口>` 找占用者 |
| 报"模型不存在" | ollama 容器没拉模型 | `docker exec rag-ollama ollama pull qwen3:8b` |
| 登录被集体锁 | 限流误伤（同 IP） | 等 15 分钟，或 `docker compose restart backend`（内存限流清零） |
| 磁盘满 | chroma/日志膨胀 | 清日志 → 加磁盘 → 补备份 |
| 回答质量变差 | 文档改了/索引过期 | 用 admin 账号调 rebuild 接口重建索引 |

**注意**：限流是内存版，重启 backend 会清零失败计数（逃生通道）；但多 worker 部署时限流失效，届时换 Redis。

## 6. 证书管理（最容易忘的坑）

- 证书位置：`certs/kb.crt` + `certs/kb.key`，有效期 **365 天**，过期后全公司无法访问；
- 每周自动检查：`scripts/check-cert.ps1`（定时任务 KB-CertCheck），剩余 <30 天会报警；
- **续签流程**（提前一个月做）：

```powershell
$env:OPENSSL_CONF = "D:\anaconda\Library\ssl\openssl.cnf"
# 重新生成服务器私钥 + 请求 + 用 CA 签名（-days 365），SAN 与原来一致
# 替换 certs/kb.crt 和 certs/kb.key
docker compose restart nginx
curl -k https://<域名>/api/health   # 验证
```

- CA 根证书（ca.crt）10 年有效，但 **ca.key 必须放仓库外安全位置**。

## 7. 周期性安全运维

| 周期 | 事项 |
| --- | --- |
| 每周 | 看 security-log 有无异常登录/爆破迹象 |
| 每月 | 恢复真演练一次；检查磁盘与备份大小 |
| 每季度 | `docker compose pull` + rebuild（基础镜像安全补丁）；检查密钥与账号 |
| 每年 | 证书续签；安全审计复盘 |

## 8. 容量规划信号

- 文档几百份：chroma 膨胀，监控磁盘；分块参数重跑评估实验；
- 并发几十人：qwen3 8B 单请求串行，看 `docker stats`；压力大加 worker/换机器（限流同步换 Redis）；
- 日志量大：audit/security_log 定保留期归档，避免无限膨胀。

## 9. 值班速查卡（出事故先看这）

```text
1. docker compose ps                    → 谁挂了
2. docker compose logs <服务> --tail 100 → 为什么挂
3. 是数据问题？→ 备份恢复（第 3 节）
4. 是代码问题？→ git revert + rebuild（第 4 节）
5. 先恢复服务，根因记录到值班日志，事后复盘
```
