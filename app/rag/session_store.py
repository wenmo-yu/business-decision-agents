"""会话级知识库路径，确保上传附件不会进入全局知识库。"""

import os
from pathlib import Path


def session_database_path(thread_id: str) -> Path:
    root = Path(os.getenv("RAG_DB_PATH", "app/data/knowledge.db")).resolve().parent / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{thread_id}.db"
