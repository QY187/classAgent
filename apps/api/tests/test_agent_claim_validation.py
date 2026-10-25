import unittest
from types import SimpleNamespace
from app.modules.agent.claim_validation import verified_claims


class ClaimValidationTest(unittest.TestCase):
    def check(self,text,source,read=None):
        return verified_claims([{"text":text,"source_ids":["E1"]}],{"E1":SimpleNamespace(full_content=source,content=read or source)})

    def test_opposite_claim_is_replaced_by_original(self):
        result=self.check("叶子节点有两个孩子。","叶子节点是没有孩子的节点。二叉树每个节点最多有两个孩子。")
        self.assertTrue(result)
        self.assertNotIn("叶子节点有两个孩子",str(result))
        self.assertIn("没有孩子",str(result))

    def test_qualifier_cannot_be_removed(self):
        result=self.check("这个公式适用于所有树。","仅当树是满二叉树时，这个公式适用。")
        self.assertNotIn("适用于所有树",str(result))
        self.assertIn("仅当",str(result))

    def test_complete_sentence_allowed_but_cutoff_not_authenticated(self):
        self.assertEqual(self.check("叶子节点没有孩子。","叶子节点没有孩子。")[0]["text"],"叶子节点没有孩子。")
        self.assertEqual(self.check("叶子节点没有","叶子节点没有孩子。",read="叶子节点没有"),[])
        self.assertEqual(verified_claims([{"text":"伪造","source_ids":["E99"]}],{}),[])

    def test_case_sensitive_symbols_and_spacing_are_not_conflated(self):
        from types import SimpleNamespace
        from app.modules.agent.claim_validation import verified_claims
        for source,wrong in [("变量 X 与 x 不同。","变量 x 与 x 不同。"),("标识符 a b 与 ab 不同。","标识符 ab 与 ab 不同。")]:
            evidence={"E1":SimpleNamespace(full_content=source,content=source)}
            result=verified_claims([{"text":wrong,"source_ids":["E1"]}],evidence)
            self.assertTrue(result[0]["text"].startswith("课堂原文："))
            self.assertNotEqual(result[0]["text"],wrong)

    def test_each_sentence_keeps_only_its_supporting_sources(self):
        from types import SimpleNamespace
        from app.modules.agent.claim_validation import verified_claims
        evidence={"E1":SimpleNamespace(full_content="叶子没有孩子。",content="叶子没有孩子。"),
                  "E2":SimpleNamespace(full_content="导数为2x。",content="导数为2x。")}
        result=verified_claims([{"text":"导数为2x。","source_ids":["E1","E2"]}],evidence)
        self.assertEqual(result[0]["source_ids"],["E2"])
        result=verified_claims([{"text":"叶子没有孩子。导数为2x。","source_ids":["E1","E2"]}],evidence)
        self.assertEqual([r["source_ids"] for r in result],[["E1"],["E2"]])
