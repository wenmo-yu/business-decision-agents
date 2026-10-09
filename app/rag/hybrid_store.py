"""SQLite FTS5 + 向量语义召回的轻量 Hybrid RAG 实现。"""

import json
import math
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable

from langchain_openai import OpenAIEmbeddings


SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}
RRF_K = 60
LEXICAL_SCHEMA_VERSION = "2"


class HybridKnowledgeBase:
    """自维护分块、向量、倒排索引和引用信息的知识库。"""

    def __init__(self, database_path: str | None = None) -> None:
        self.database_path = Path(
            database_path or os.getenv("RAG_DB_PATH", "app/data/knowledge.db")
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    UNIQUE(source, chunk_index)
                )
                """
            )
            connection.execute("CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            version = connection.execute("SELECT value FROM rag_meta WHERE key = 'lexical_schema_version'").fetchone()
            if version is None or version["value"] != LEXICAL_SCHEMA_VERSION:
                connection.execute("DROP TABLE IF EXISTS chunks_fts")
                connection.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(content, source, tokenize='unicode61')")
                for row in connection.execute("SELECT id, content, source FROM chunks"):
                    connection.execute(
                        "INSERT INTO chunks_fts(rowid, content, source) VALUES (?, ?, ?)",
                        (row["id"], self._lexical_text(row["content"]), row["source"]),
                    )
                connection.execute(
                    "INSERT INTO rag_meta(key, value) VALUES ('lexical_schema_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (LEXICAL_SCHEMA_VERSION,),
                )

    def _embedder(self) -> OpenAIEmbeddings:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("未配置 OPENAI_API_KEY，无法为内部知识库生成向量。")
        return OpenAIEmbeddings(
            model=os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-v4"),
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL"),
        )

    @staticmethod
    def _chunks(text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
        normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not normalized:
            return []
        result, start = [], 0
        while start < len(normalized):
            end = min(start + chunk_size, len(normalized))
            if end < len(normalized):
                boundary = max(normalized.rfind("\n", start, end), normalized.rfind("。", start, end))
                if boundary > start + chunk_size // 2:
                    end = boundary + 1
            result.append(normalized[start:end])
            if end >= len(normalized):
                break
            start = end - overlap
        return result

    @staticmethod
    def _lexical_tokens(text: str) -> list[str]:
        """统一处理中英文：中文使用字/双字 n-gram，英文保留完整词。"""
        tokens: list[str] = []
        for chinese_run, latin_word in re.findall(r"([\u4e00-\u9fff]+)|([A-Za-z0-9_]+)", text.lower()):
            if chinese_run:
                tokens.extend(chinese_run)
                tokens.extend(chinese_run[index : index + 2] for index in range(len(chinese_run) - 1))
            elif latin_word:
                tokens.append(latin_word)
        return tokens

    @classmethod
    def _lexical_text(cls, text: str) -> str:
        return " ".join(cls._lexical_tokens(text))

    @classmethod
    def _fts_query(cls, text: str) -> str:
        # 使用 OR 扩大中文 n-gram 召回面；RRF 在候选集合上再融合并排序。
        tokens = list(dict.fromkeys(cls._lexical_tokens(text)))[:32]
        return " OR ".join(f'"{token}"' for token in tokens)

    @staticmethod
    def read_document(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            from pypdf import PdfReader
            return "\n".join(f"[第 {index + 1} 页]\n{page.extract_text() or ''}" for index, page in enumerate(PdfReader(path).pages))
        if suffix == ".docx":
            import docx
            return "\n".join(paragraph.text for paragraph in docx.Document(path).paragraphs)
        raise ValueError(f"不支持的文档格式：{path.suffix}")

    def index_paths(self, paths: Iterable[Path]) -> dict[str, int]:
        documents = []
        for path in paths:
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            content = self.read_document(path)
            for index, chunk in enumerate(self._chunks(content)):
                documents.append((str(path).replace("\\", "/"), index, chunk))
        if not documents:
            return {"documents": 0, "chunks": 0}

        vectors = self._embedder().embed_documents([item[2] for item in documents])
        with closing(self._connect()) as connection, connection:
            # 同一文件重新索引时先清除旧分块，避免文档缩短后遗留过期证据。
            for source in {item[0] for item in documents}:
                existing = connection.execute("SELECT id FROM chunks WHERE source = ?", (source,)).fetchall()
                for row in existing:
                    connection.execute("DELETE FROM chunks_fts WHERE rowid = ?", (row["id"],))
                connection.execute("DELETE FROM chunks WHERE source = ?", (source,))
            for (source, chunk_index, content), vector in zip(documents, vectors, strict=True):
                cursor = connection.execute(
                    "INSERT INTO chunks(source, chunk_index, content, embedding, metadata) VALUES (?, ?, ?, ?, ?)",
                    (source, chunk_index, content, json.dumps(vector), json.dumps({"source": source, "chunk_index": chunk_index})),
                )
                chunk_id = cursor.lastrowid
                connection.execute(
                    "INSERT INTO chunks_fts(rowid, content, source) VALUES (?, ?, ?)",
                    (chunk_id, self._lexical_text(content), source),
                )
        return {"documents": len({item[0] for item in documents}), "chunks": len(documents)}

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
        return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0

    def search(self, query: str, limit: int = 5) -> list[dict]:
        query_vector = self._embedder().embed_query(query)
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM chunks").fetchall()
            fts_query = self._fts_query(query)
            lexical_rows = connection.execute(
                """SELECT rowid, bm25(chunks_fts) AS bm25_score
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY bm25_score ASC
                LIMIT ?""",
                (fts_query, 50),
            ).fetchall() if fts_query else []

        semantic_ranked = sorted(
            ((row["id"], self._cosine(query_vector, json.loads(row["embedding"]))) for row in rows),
            key=lambda item: item[1],
            reverse=True,
        )[:50]
        semantic_ranks = {chunk_id: rank for rank, (chunk_id, _) in enumerate(semantic_ranked, start=1)}
        semantic_scores = dict(semantic_ranked)
        lexical_ranks = {row["rowid"]: rank for rank, row in enumerate(lexical_rows, start=1)}
        candidates = set(semantic_ranks) | set(lexical_ranks)
        rows_by_id = {row["id"]: row for row in rows}
        results = []
        for chunk_id in candidates:
            row = rows_by_id[chunk_id]
            semantic_rank = semantic_ranks.get(chunk_id)
            lexical_rank = lexical_ranks.get(chunk_id)
            rrf_score = (1 / (RRF_K + semantic_rank) if semantic_rank else 0) + (1 / (RRF_K + lexical_rank) if lexical_rank else 0)
            results.append({"source": row["source"], "chunk_index": row["chunk_index"], "content": row["content"], "rrf_score": round(rrf_score, 6), "semantic_rank": semantic_rank, "lexical_rank": lexical_rank, "semantic_score": round(semantic_scores.get(chunk_id, 0.0), 4) if semantic_rank else None})
        return sorted(results, key=lambda item: item["rrf_score"], reverse=True)[:limit]
