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
    def _embedding_model() -> str:
        return os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-v4")

    def _validate_embedding_contract(self, dimension: int) -> None:
        """拒绝将不同模型或不同维度的向量混在同一个索引中。"""
        with closing(self._connect()) as connection, connection:
            values = dict(connection.execute("SELECT key, value FROM rag_meta WHERE key IN ('embedding_model', 'embedding_dimension')"))
            has_chunks = connection.execute("SELECT EXISTS(SELECT 1 FROM chunks)").fetchone()[0]
            model = self._embedding_model()
            previous_dimension = values.get("embedding_dimension")
            if has_chunks and values and (values.get("embedding_model") != model or previous_dimension != str(dimension)):
                raise ValueError("Embedding 模型或向量维度已变化；请删除旧索引后重新构建知识库。")
            connection.execute("INSERT INTO rag_meta(key, value) VALUES ('embedding_model', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (model,))
            connection.execute("INSERT INTO rag_meta(key, value) VALUES ('embedding_dimension', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(dimension),))

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

    def index_paths(self, paths: Iterable[Path], source_names: dict[Path, str] | None = None) -> dict[str, int]:
        documents = []
        indexed_sources: set[str] = set()
        for path in paths:
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            source = (source_names or {}).get(path, str(path).replace("\\", "/"))
            indexed_sources.add(source)
            content = self.read_document(path)
            for index, chunk in enumerate(self._chunks(content)):
                documents.append((source, index, chunk))
        if not indexed_sources:
            return {"documents": 0, "chunks": 0}

        vectors = self._embedder().embed_documents([item[2] for item in documents]) if documents else []
        if vectors:
            self._validate_embedding_contract(len(vectors[0]))
        with closing(self._connect()) as connection, connection:
            # 即使文件为空也先清理旧分块，避免旧证据继续被召回。
            for source in indexed_sources:
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
        return {"documents": len(indexed_sources), "chunks": len(documents)}

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
        return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0

    def search(self, query: str, limit: int = 5) -> list[dict]:
        query_vector = self._embedder().embed_query(query)
        self._validate_embedding_contract(len(query_vector))
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
        ranked = sorted(results, key=lambda item: item["rrf_score"], reverse=True)
        if not ranked:
            return []
        # RRF 是排序分数而不是置信度。无词法命中且最优语义相似度偏低时拒答。
        if not any(item["lexical_rank"] for item in ranked) and (ranked[0]["semantic_score"] or 0) < float(os.getenv("RAG_MIN_SEMANTIC_SCORE", "0.35")):
            return []
        return ranked[:limit]
