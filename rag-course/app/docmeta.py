"""文档元数据登记：记录"谁上传的、权限标签"，替代硬编码 FILE_ACCESS（生产化第一步）。

存储：data/doc_registry.json（{文件名: {creator, access, created_at}}）。
为什么单独存：文档是文件系统里的文件，归属信息不能写进文件本身，需要一个登记表。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

META_FILE = Path(__file__).resolve().parent.parent / "data" / "doc_registry.json"

# 内置示例文档：标记为 system 创建（只有管理员能管理）
DEFAULT_DOCS = {
    "员工手册.md": "all",
    "员工手册.docx": "all",
    "差旅报销制度.md": "finance",
    "差旅报销制度.pdf": "finance",
}


def _load() -> dict:
    if not META_FILE.exists():
        return {}
    return json.loads(META_FILE.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    META_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def ensure_seeded() -> None:
    """把内置示例文档登记为 system 创建（首次运行时补登记）。"""
    data = _load()
    changed = False
    for name, access in DEFAULT_DOCS.items():
        if name not in data:
            data[name] = {
                "creator": "system",
                "access": access,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            changed = True
    if changed:
        _save(data)


def register(filename: str, creator: str, access: str = "all") -> None:
    """登记/更新一份文档的归属与权限。"""
    data = _load()
    data[filename] = {
        "creator": creator,
        "access": access,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(data)


def get(filename: str) -> dict | None:
    """查文档元数据（creator / access）。"""
    return _load().get(filename)


def remove(filename: str) -> None:
    """删除登记（文件本身由调用方处理）。"""
    data = _load()
    data.pop(filename, None)
    _save(data)
