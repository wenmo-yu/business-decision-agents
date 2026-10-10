import tempfile
import unittest
from pathlib import Path

from app.rag.hybrid_store import HybridKnowledgeBase
from app.tools.commerce_analytics_tool import _bounded, _consume_sse
from app.tools.evidence_tools import evaluate_evidence
from app.utils.path_utils import resolve_path


class FakeEmbedder:
    def embed_documents(self, values):
        return [[1.0, 0.0] for _ in values]

    def embed_query(self, _value):
        return [1.0, 0.0]


class PlatformSafetyTests(unittest.TestCase):
    def test_session_path_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(Path(resolve_path("report.md", str(root))).parent, root)
            with self.assertRaises(ValueError):
                resolve_path("../other-session/secret.md", str(root))

    def test_empty_reindex_removes_stale_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "strategy.md"
            source.write_text("促销活动的最低毛利率要求。", encoding="utf-8")
            knowledge_base = HybridKnowledgeBase(str(root / "knowledge.db"))
            knowledge_base._embedder = lambda: FakeEmbedder()
            knowledge_base.index_paths([source])
            self.assertTrue(knowledge_base.search("毛利率"))
            source.write_text("", encoding="utf-8")
            knowledge_base.index_paths([source])
            self.assertEqual(knowledge_base.search("毛利率"), [])

    def test_bounded_payload_remains_structured(self):
        payload, truncated = _bounded({"data": ["x" * 3_000]})
        self.assertTrue(truncated)
        self.assertEqual(len(payload["data"][0]), 2_000)

    def test_sse_error_is_not_reported_as_success(self):
        response = type("Response", (), {"iter_lines": lambda self, decode_unicode: iter(['data: {\"type\": \"error\", \"message\": \"blocked\"}'])})()
        self.assertEqual(_consume_sse(response)["execution_status"], "failed")

    def test_internal_citation_requires_retrieval_fields(self):
        result = evaluate_evidence.invoke({"claims_json": '[{"claim":"结论","sources":[{"type":"内部材料"}]}]'})
        self.assertIn("needs_evidence", result)
        self.assertIn("来源文件", result)


if __name__ == "__main__":
    unittest.main()
