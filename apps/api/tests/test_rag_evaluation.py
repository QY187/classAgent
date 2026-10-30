import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.modules.rag.evaluation import evaluate_cases
from app.modules.rag.service import _cross_encoder_rerank, _normalize_query, _rerank


class RagQualityTest(unittest.TestCase):
    def test_query_rewrite_removes_conversational_noise(self):
        self.assertEqual(_normalize_query("请帮我解释一下：这门课里面的前序遍历"), "前序遍历")

    def test_rerank_prefers_exact_phrase(self):
        rows = {
            "a": SimpleNamespace(content="前序遍历的访问顺序是根、左、右"),
            "b": SimpleNamespace(content="二叉树遍历需要递归")}
        result = _rerank("前序遍历", [("b", 0.02), ("a", 0.019)], rows, {"a": 0.5, "b": 0.1})
        self.assertEqual(result[0][0], "a")

    def test_offline_metrics(self):
        cases = [{"query": "a", "relevant_ids": ["x"], "k": 2}]
        metrics = evaluate_cases(cases, lambda _query, _k: ["x", "y"])
        self.assertEqual(metrics["recall_at_k"], 1.0)
        self.assertEqual(metrics["mrr"], 1.0)

    @patch("app.modules.rag.service.get_settings")
    @patch("app.modules.rag.service.httpx.post")
    def test_cross_encoder_rerank_uses_service_scores(self, post, settings):
        settings.return_value = SimpleNamespace(rerank_enabled=True, dashscope_api_key="key",
            rerank_base_url="https://rerank.test", rerank_model="gte-rerank-v2")
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"output": {"results": [
            {"index": 1, "relevance_score": 0.95}, {"index": 0, "relevance_score": 0.2}]}}
        rows = {"a": SimpleNamespace(content="不相关"), "b": SimpleNamespace(content="正确答案")}
        result = _cross_encoder_rerank("问题", [("a", 0.02), ("b", 0.01)], rows)
        self.assertEqual([item[0] for item in result], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
