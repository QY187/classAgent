"""事实保守呈现：可核对的完整原文句子，改写不自动获得引用认证。"""
import re


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def sentences(text):
    return [item.strip() for item in re.split(r"[。！？!?\n]|(?<!\d)\.(?!\d)", text) if item.strip()]


def verified_claims(claims, evidence):
    verified = []
    for claim in claims[:8]:
        ids = [key for key in dict.fromkeys(claim["source_ids"]) if key in evidence][:3]
        if not ids:
            continue
        units = []
        for key in ids:
            item = evidence[key]
            # 完整句子必须确实在本次读取的内容中；不利用未读到的截断尾部。
            units.extend((unit,key) for unit in sentences(item.full_content)
                         if unit in item.content and len(unit) <= 1100)
        claim_units = sentences(claim["text"])
        supported = {normalize(unit) for unit,_ in units}
        if claim_units and all(normalize(unit) in supported for unit in claim_units):
            for claim_unit in claim_units:
                supporting_ids = list(dict.fromkeys(key for unit,key in units if normalize(unit) == normalize(claim_unit)))
                verified.append({"text":claim["text"] if len(claim_units) == 1 else claim_unit,
                                 "source_ids":supporting_ids})
            continue
        # 引用编号真实不等于改写结论真实。回退为原文，不展示未核对的自由结论。
        selected, used = [], set()
        for unit,key in units:
            if normalize(unit) in used:
                continue
            selected.append({"text":"课堂原文：" + unit, "source_ids":[key]})
            used.add(normalize(unit))
            if len(selected) >= 3:
                break
        verified.extend(selected)
    return verified[:8]
