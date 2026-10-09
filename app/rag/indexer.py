"""命令行索引入口：uv run python -m app.rag.indexer docs/knowledge_base"""

import argparse
from pathlib import Path

from app.rag.hybrid_store import HybridKnowledgeBase, SUPPORTED_SUFFIXES


def main() -> None:
    parser = argparse.ArgumentParser(description="为内置 Hybrid RAG 建立知识库索引")
    parser.add_argument("path", type=Path, help="待索引的文档或目录")
    args = parser.parse_args()
    paths = [args.path] if args.path.is_file() else [item for item in args.path.rglob("*") if item.suffix.lower() in SUPPORTED_SUFFIXES]
    result = HybridKnowledgeBase().index_paths(paths)
    print(f"已索引 {result['documents']} 个文档、{result['chunks']} 个分块。")


if __name__ == "__main__":
    main()
