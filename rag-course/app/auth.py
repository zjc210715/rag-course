"""阶段 ⑦：登录模块 —— 用户存储（SQLite）+ 密码哈希（pbkdf2）+ 服务端会话 token。

为什么这么设计（三步各解决一个问题）：
1. 密码哈希：绝不存明文。pbkdf2 加盐 + 10 万次迭代，暴力破解成本高；
2. 服务端 token：登录后签发随机令牌存库，登出/改密可即时吊销（JWT 做不到）；
3. hmac.compare_digest：恒定时间比较，防止"时序攻击"（靠响应快慢猜密码）。

命令行（在 rag-course 目录下）：
    python app/auth.py seed        # 初始化数据库 + 默认用户（zhangsan/lisi，密码 123456）
    python app/auth.py add-user    # 交互式添加用户
    python app/auth.py list        # 查看用户
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import secrets
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "users.db"
SESSION_TTL = timedelta(hours=0.5)  # token 有效期：30分钟
PBKDF2_ITERATIONS = 600_000        # 当前目标迭代次数（OWASP 建议量级）
LEGACY_ITERATIONS = 100_000        # 老哈希用的迭代次数（兼容迁移前的账号）

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    iterations INTEGER NOT NULL DEFAULT 600000,  -- 该哈希使用的迭代次数
    groups TEXT NOT NULL,           -- JSON 数组，如 ["all", "finance"]
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS security_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    event TEXT NOT NULL,            -- login_success / login_failure / login_locked / logout / change_password ...
    username TEXT NOT NULL,
    ip TEXT NOT NULL,
    detail TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """建表 + 迁移（老库补 iterations 列）+ 播种默认用户。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect()) as conn:
        conn.executescript(_SCHEMA)
        # 迁移：老库没有 iterations 列时补上（老哈希按 LEGACY_ITERATIONS 校验）
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "iterations" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN iterations INTEGER")
        conn.commit()
    for username, groups in (("zhangsan", ["all"]), ("lisi", ["all", "finance"])):
        if get_user(username) is None:
            create_user(username, "123456", groups)
            print(f"[auth] 已创建默认用户 {username}（密码 123456，请尽快修改）")


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> tuple[str, str, int]:
    """返回 (salt, hash, iterations)。salt 每次随机，同一密码两次哈希结果不同。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    )
    return salt, digest.hex(), iterations


def verify_password(
    password: str,
    salt: str,
    expected_hash: str,
    iterations: int = PBKDF2_ITERATIONS,
) -> bool:
    """校验密码。compare_digest 保证耗时恒定，不泄露"差几个字符"。"""
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    )
    return hmac.compare_digest(digest.hex(), expected_hash)


def create_user(username: str, password: str, groups: list[str]) -> None:
    salt, digest, iterations = hash_password(password)
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, iterations, groups, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                username,
                digest,
                salt,
                iterations,
                json.dumps(groups),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_user(username: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        return None
    return {"username": row["username"], "groups": json.loads(row["groups"])}


def change_password(username: str, new_password: str) -> bool:
    """修改密码：重新加盐哈希，并吊销该用户所有旧会话。

    为什么必须做这两件事：
    1. 重新生成随机盐：盐不能复用旧的，否则两次改密后的哈希可被对比；
    2. 删除该用户全部 sessions：否则改完密码，别人手里的旧 token
       在 24 小时过期前仍然有效——"改密码"必须立刻踢掉旧登录态。
    """
    if get_user(username) is None:
        return False
    salt, digest, iterations = hash_password(new_password)
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, salt = ?, iterations = ? WHERE username = ?",
            (digest, salt, iterations, username),
        )
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
        conn.commit()
    return True


def check_password(username: str, password: str) -> bool:
    """只校验密码是否正确（不签发会话），供"修改密码"前验证旧密码。"""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        return False
    iterations = row["iterations"] or LEGACY_ITERATIONS
    return verify_password(password, row["salt"], row["password_hash"], iterations)


def authenticate(username: str, password: str) -> str | None:
    """校验用户名密码；成功则签发 token 并入库，失败返回 None。"""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        return None
    iterations = row["iterations"] or LEGACY_ITERATIONS
    if not verify_password(password, row["salt"], row["password_hash"], iterations):
        return None
    # 渐进重哈希：老参数（低迭代）的哈希在登录成功时自动升级到当前目标，
    # 用户无感知，不用强制所有人改密码
    if iterations < PBKDF2_ITERATIONS:
        salt, digest, _ = hash_password(password)
        with closing(_connect()) as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ?, iterations = ? WHERE username = ?",
                (digest, salt, PBKDF2_ITERATIONS, username),
            )
            conn.commit()
    # 顺手清理过期会话，防止 sessions 表无限膨胀
    with closing(_connect()) as conn:
        conn.execute(
            "DELETE FROM sessions WHERE expires_at < ?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + SESSION_TTL
        conn.execute(
            "INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)",
            (token, username, expires_at.isoformat()),
        )
        conn.commit()
    return token


def get_user_by_token(token: str) -> dict | None:
    """按 token 查用户；会话不存在或已过期返回 None（前端会收到 401）。"""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    if row is None:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        return None
    return get_user(row["username"])


def logout(token: str) -> None:
    """删除会话：token 立即失效（服务端 token 的核心优势）。"""
    with closing(_connect()) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def count_users() -> int:
    with closing(_connect()) as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def log_security_event(
    event: str,
    username: str,
    ip: str,
    detail: str | None = None,
) -> None:
    """记录安全事件（登录/登出/改密），与问答审计 audit.jsonl 分开存放。"""
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO security_log (time, event, username, ip, detail) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), event, username, ip, detail),
        )
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="用户管理")
    parser.add_argument(
        "command",
        choices=["seed", "add-user", "change-password", "list", "security-log"],
    )
    args = parser.parse_args()

    if args.command == "seed":
        init_db()
    elif args.command == "add-user":
        init_db()
        username = input("用户名：")
        groups_input = input("权限组（逗号分隔，如 all,finance）：")
        password = getpass.getpass("密码：")
        groups = [g.strip() for g in groups_input.split(",") if g.strip()]
        create_user(username, password, groups)
        print(f"已创建用户 {username}，权限组 {groups}")
    elif args.command == "change-password":
        init_db()
        username = input("用户名：")
        if get_user(username) is None:
            print(f"用户 {username} 不存在")
            sys.exit(1)
        password = getpass.getpass("新密码：")
        confirm = getpass.getpass("再次输入新密码：")
        if password != confirm:
            print("两次输入不一致，未做任何修改")
            sys.exit(1)
        if change_password(username, password):
            print(f"已修改 {username} 的密码，其所有登录会话已失效")
    elif args.command == "list":
        init_db()
        with closing(_connect()) as conn:
            rows = conn.execute("SELECT username, groups FROM users").fetchall()
        for row in rows:
            print(f"{row['username']}  {row['groups']}")
    elif args.command == "security-log":
        init_db()
        with closing(_connect()) as conn:
            rows = conn.execute(
                "SELECT time, event, username, ip, detail FROM security_log "
                "ORDER BY id DESC LIMIT 20"
            ).fetchall()
        if not rows:
            print("暂无安全事件")
        for row in rows:
            detail = f"  {row['detail']}" if row["detail"] else ""
            print(f"{row['time']}  {row['event']}  {row['username']}  {row['ip']}{detail}")


if __name__ == "__main__":
    main()
