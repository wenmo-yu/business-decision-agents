"""会话工作区的严格路径边界。"""

from pathlib import Path


VIRTUAL_PREFIXES = ("/workspace", "/mnt/data", "/home/user")


def resolve_path(filename: str, session_dir: str) -> str:
    """只解析当前会话目录内的相对路径，越界路径一律拒绝。"""
    if not session_dir:
        raise ValueError("缺少当前会话工作目录。")
    raw = filename.strip().replace("\\", "/")
    if not raw:
        raise ValueError("文件路径不能为空。")
    for prefix in VIRTUAL_PREFIXES:
        if raw == prefix or raw.startswith(f"{prefix}/"):
            raw = raw[len(prefix) :].lstrip("/")
            break

    root = Path(session_dir).resolve()
    requested = Path(raw)
    candidate = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("拒绝访问会话工作目录之外的路径。") from error
    return str(candidate)
