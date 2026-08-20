# 域名 / IP 切换操作流程

> 现状：测试期用 IP（192.168.1.16），后续切换到正式域名（如 kb.internal.example.com）。
> 核心原则：**证书 SAN、nginx server_name、DNS 解析、浏览器访问地址，四者必须一致。**

## 阶段一：当前——统一用 IP（测试期）

1. **统一 nginx server_name**：`nginx.conf` 里 80 和 443 两个 server 块都写成 `192.168.1.50`（已完成）；
2. **确认证书认 IP**：`openssl x509 -in certs\kb.crt -noout -ext subjectAltName`，应含 `IP Address:192.168.1.16`（当前已含）；
3. **重启 nginx**：`docker compose restart nginx`；
4. **验证**：浏览器访问 `https://192.168.1.16` → 小锁、无警告、能登录。

## 阶段二：切换到域名（正式上线）

### 第 1 步：确定域名与 DNS

- 确定正式域名（如 kb.internal.example.com）；
- 确认解析方式：公司 DNS 加 A 记录（推荐，全公司生效），或临时用 hosts（每台机器手动加）；
- 验证解析：`ping kb.internal.example.com` 能返回 `192.168.1.16`。

### 第 2 步：重新签发证书（域名变了必须重签）

```powershell
$env:OPENSSL_CONF = "D:\anaconda\Library\ssl\openssl.cnf"

# ① 服务器私钥 + 证书请求（SAN 换成正式域名，可保留 IP 备用）
openssl req -newkey rsa:2048 -keyout kb.key -out kb.csr -nodes `
  -subj "/CN=kb.internal.example.com" -addext "subjectAltName=DNS:kb.internal.example.com,IP:192.168.1.16"

# ② 写 SAN 扩展文件
"subjectAltName=DNS:kb.internal.example.com,IP:192.168.1.16" | Out-File -Encoding ascii san.cnf

# ③ 用 CA 签名（有效期 1 年）
openssl x509 -req -in kb.csr -CA ca.crt -CAkey ca.key -CAcreateserial `
  -out kb.crt -days 365 -sha256 -extfile san.cnf

# ④ 确认 SAN
openssl x509 -in kb.crt -noout -subject -ext subjectAltName
```

- 替换 `certs/kb.crt` 和 `certs/kb.key`（替换前把旧证书备份一份）；
- `ca.crt` / `ca.key` 不变（CA 有效期 10 年）。

### 第 3 步：改 nginx

- `nginx.conf` 两处 `server_name` 都改成正式域名；
- `docker compose restart nginx`。

### 第 4 步：客户端信任

- 员工机器之前装过同一个 `ca.crt` → 不用动；
- 新机器 → 安装 `ca.crt` 到"受信任的根证书颁发机构"。

### 第 5 步：验证

1. `curl -k https://kb.internal.example.com/api/health` → `{"status":"ok"}`；
2. 浏览器访问 `https://kb.internal.example.com` → 小锁、无"名称不匹配"；
3. 登录 + 问答 + 上传重建走一遍；
4. 旧地址 `https://192.168.1.16` 若 SAN 保留了 IP 仍可用（可选保留）。

## 常见坑

| 坑 | 症状 | 解法 |
| --- | --- | --- |
| 证书 SAN 没写域名 | 浏览器"名称不匹配" | 重签证书（第 2 步） |
| DNS 没配 | 域名解析失败打不开 | 公司 DNS 加记录，或 hosts |
| 只改了一处 server_name | 80/443 行为不一致 | 两处都改 |
| 换了证书没重启 nginx | 用的还是旧证书 | `docker compose restart nginx` |
| CA 没装 | "连接不是私密连接" | 每台机器装 ca.crt |

## 切换时机建议

- 选低峰期（影响几分钟）；
- 切换前跑一次备份 `.\scripts\backup.ps1` 保险；
- 切换后把 OPS.md 里的访问地址同步更新；
- 在日历上记证书续签提醒（-days 365，OPS.md 第 6 节有自动检查脚本）。
