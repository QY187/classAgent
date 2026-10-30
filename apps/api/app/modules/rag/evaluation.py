"""离线召回评测，不依赖数据库或外部模型。"""


def evaluate_cases(cases: list[dict], retrieve) -> dict:
    """评估 Recall@K、MRR 和 NDCG；retrieve(query, k) 返回文档 ID 列表。"""
    if not cases:
        return {"cases": 0, "recall_at_k": 0.0, "mrr": 0.0, "ndcg": 0.0}
    recall = mrr = ndcg = 0.0
    for case in cases:
        expected = set(case.get("relevant_ids", []))
        result = list(retrieve(case["query"], int(case.get("k", 5))))
        if not expected:
            continue
        seen_relevant = set()
        hits = []
        for index, identity in enumerate(result, 1):
            if identity in expected and identity not in seen_relevant:
                hits.append(index)
                seen_relevant.add(identity)
        recall += 1.0 if hits else 0.0
        mrr += 1.0 / hits[0] if hits else 0.0
        dcg = sum(1.0 / __import__("math").log2(index + 1) for index in hits)
        ideal_hits = min(len(expected), int(case.get("k", 5)))
        idcg = sum(1.0 / __import__("math").log2(index + 1) for index in range(1, ideal_hits + 1))
        ndcg += dcg / idcg if idcg else 0.0
    total = len(cases)
    return {"cases": total, "recall_at_k": round(recall / total, 4),
            "mrr": round(mrr / total, 4), "ndcg": round(ndcg / total, 4)}
