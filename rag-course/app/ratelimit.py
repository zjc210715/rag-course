"""阶段 P1：登录/改密限流 —— 防暴力破解。

为什么需要：
- pbkdf2 慢哈希只是让"每次尝试变贵"，但攻击者可以无限次尝试；
- 限流 = 固定时间内限制失败次数，超过就锁定，把暴力破解挡在门外。

策略（教学版，生产可换 Redis）：
- 按「IP + 用户名」计数：5 分钟内失败 ≥5 次 → 锁定 15 分钟；
- 锁定期间直接返回 429，不再做密码校验（省 CPU 也挡攻击）；
- 登录/改密成功 → 清零该键的失败记录。

注意：
- 内存版只对本进程生效；多 worker 部署需换 Redis 或 SQLite；
- 键是 IP+用户名：同一 IP 换不同用户名爆破不会被拦，
  若需防这种场景，再加一个"纯 IP"的计数键即可。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

WINDOW_SECONDS = 300   # 统计窗口：5 分钟
MAX_FAILURES = 5       # 窗口内允许的最大失败次数
LOCK_SECONDS = 900     # 锁定时长：15 分钟

_lock = threading.Lock()
_failures: dict[str, deque[float]] = defaultdict(deque)
_locked_until: dict[str, float] = {}


def _key(ip: str, username: str) -> str:
    return f"{ip}|{username}"


def is_locked(ip: str, username: str) -> bool:
    """是否处于锁定状态（锁定期间直接拒绝，不做密码校验）。"""
    with _lock:
        return _locked_until.get(_key(ip, username), 0) > time.time()


def record_failure(ip: str, username: str) -> bool:
    """记一次失败；若窗口内失败次数达到上限，触发锁定并返回 True。"""
    key = _key(ip, username)
    now = time.time()
    with _lock:
        queue = _failures[key]
        # 只保留窗口内的失败记录，防止表无限膨胀
        while queue and queue[0] < now - WINDOW_SECONDS:
            queue.popleft()
        queue.append(now)
        if len(queue) >= MAX_FAILURES:
            _locked_until[key] = now + LOCK_SECONDS
            queue.clear()
            return True
    return False


def reset(ip: str, username: str) -> None:
    """登录/改密成功后清零失败记录与锁定。"""
    key = _key(ip, username)
    with _lock:
        _failures.pop(key, None)
        _locked_until.pop(key, None)
