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
