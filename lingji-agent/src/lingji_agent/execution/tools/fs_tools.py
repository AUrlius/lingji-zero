"""内置工具：文件系统操作"""

import os
import shutil
from pathlib import Path

from lingji_agent.execution.registry import RiskLevel, registry
from lingji_agent.execution.sandbox import validate_path


@registry.register(
    name="list_directory",
    description="列出指定目录下的文件和子目录，支持按类型过滤",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径，如 /home/user/Documents"},
        },
        "required": ["path"],
    },
    risk=RiskLevel.SAFE,
)
async def list_directory(path: str) -> dict:
    """列出目录内容"""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"error": f"路径不存在: {path}"}
        if not p.is_dir():
            return {"error": f"不是目录: {path}"}

        entries = []
        for entry in sorted(p.iterdir()):
            entry_type = "dir" if entry.is_dir() else "file"
            size = entry.stat().st_size if entry.is_file() else 0
            entries.append({
                "name": entry.name,
                "type": entry_type,
                "size": size,
            })
        return {"path": str(p), "entries": entries, "count": len(entries)}
    except PermissionError:
        return {"error": f"权限不足: {path}"}
    except Exception as e:
        return {"error": str(e)}


@registry.register(
    name="read_file",
    description="读取文件内容（限制 10KB），适合查看文本/配置/日志文件",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "max_lines": {"type": "integer", "description": "最大读取行数，默认 100"},
        },
        "required": ["path"],
    },
    risk=RiskLevel.SAFE,
)
async def read_file(path: str, max_lines: int = 100) -> dict:
    """读取文件内容"""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"error": f"文件不存在: {path}"}
        if not p.is_file():
            return {"error": f"不是文件: {path}"}
        if p.stat().st_size > 100 * 1024:
            return {"error": f"文件过大 ({p.stat().st_size} bytes)，限制 100KB"}

        with open(p, errors="replace") as f:
            lines = [line.rstrip() for line in f.readlines()[:max_lines]]
        return {"path": str(p), "lines": lines, "line_count": len(lines), "total_size": p.stat().st_size}
    except Exception as e:
        return {"error": str(e)}


@registry.register(
    name="move_file",
    description="移动或重命名文件/目录",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "源路径"},
            "destination": {"type": "string", "description": "目标路径"},
        },
        "required": ["source", "destination"],
    },
    risk=RiskLevel.WARN,
)
async def move_file(source: str, destination: str) -> dict:
    """移动/重命名文件"""
    try:
        src = Path(source).expanduser().resolve()
        dst = Path(destination).expanduser().resolve()
        if not validate_path(str(src)):
            return {"error": f"源路径不在允许范围: {source}"}
        if not validate_path(str(dst)):
            return {"error": f"目标路径不在允许范围: {destination}"}
        if not src.exists():
            return {"error": f"源文件不存在: {source}"}
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return {"status": "ok", "source": str(src), "destination": str(dst)}
    except Exception as e:
        return {"error": str(e)}


@registry.register(
    name="delete_file",
    description="删除文件或空目录。⚠️ 此操作不可逆",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要删除的文件路径"},
        },
        "required": ["path"],
    },
    risk=RiskLevel.CRITICAL,
)
async def delete_file(path: str) -> dict:
    """删除文件（CRITICAL 级别，触发 HITL）"""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"error": f"文件不存在: {path}"}
        if p.is_dir():
            if any(p.iterdir()):
                return {"error": f"目录非空，拒绝删除: {path}"}
            p.rmdir()
        else:
            p.unlink()
        return {"status": "ok", "deleted": str(p)}
    except Exception as e:
        return {"error": str(e)}


@registry.register(
    name="search_files",
    description="按文件名模式搜索文件（支持通配符）",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "文件名模式，如 *.py 或 config*"},
            "directory": {"type": "string", "description": "搜索起始目录，默认当前"},
            "max_depth": {"type": "integer", "description": "最大深度，默认 3"},
        },
        "required": ["pattern"],
    },
    risk=RiskLevel.SAFE,
)
async def search_files_tool(pattern: str, directory: str = ".", max_depth: int = 3) -> dict:
    """搜索文件"""
    try:
        import fnmatch
        root = Path(directory).expanduser().resolve()
        if not root.exists():
            return {"error": f"目录不存在: {directory}"}

        matches = []
        for current_depth, (dirpath, dirnames, filenames) in enumerate(os.walk(root)):
            if current_depth > max_depth:
                dirnames.clear()
                continue
            for fname in filenames:
                if fnmatch.fnmatch(fname, pattern):
                    matches.append(str(Path(dirpath) / fname))

        return {
            "pattern": pattern,
            "directory": str(root),
            "matches": matches[:50],
            "count": len(matches),
        }
    except Exception as e:
        return {"error": str(e)}
