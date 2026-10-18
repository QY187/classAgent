"""写请求的语言边界；只归一化明确请求，不把咨询或资料内容变成授权。"""
import re


def request_text(question):
    value = question.strip()
    # 只有带明确请托的句子才去掉礼貌问尾，能力询问仍保留并拒绝。
    if re.match(r"^(?:请|帮我|给我|麻烦你|麻烦|我想要|我希望)", value):
        value = re.sub(r"[，,\s]*(?:可以吗|可以么|好吗|好么|行吗|好不好)[？?。！!\s]*$", "", value)
    return value


def follows_clarification(question, history):
    if not history or len(question.strip()) > 200:
        return False
    last = history[-1] if isinstance(history[-1], dict) else {}
    return last.get("role") == "assistant" and isinstance(last.get("content"), str) and bool(re.search(r"[？?]\s*$", last["content"]))


def explicit_request(question):
    value = request_text(question)
    if re.search(r"不要|不需要|不用|取消|先不做|(?:^|[，,。；;\s]|请)别(?:帮|给|创建|新建|添加|新增|标记|生成|出)|原文(?:说|中|里)|老师(?:说|要求)|引用|资料(?:内容|里|中)|阅读.{0,8}(?:文字|内容|原文)", value):
        return False
    return not bool(re.search(r"怎么|如何|是否|能否|能不能|为什么|什么意思|(?:可以|能).*吗|[？?]", value))


def quiz_request(question):
    if not explicit_request(question):
        return False
    value = request_text(question)
    prefix = r"(?:请|帮我|给我|为我|麻烦你|麻烦|然后|再|我想要|我想|我希望|你|\s)*"
    for clause in re.split(r"[，,。；;\n]", value):
        # 根据/针对是资料范围，不能让普通讲解、已有题作答开启出题工具。
        candidate = re.sub(r"^" + prefix, "", clause.strip())
        candidate = re.sub(r"^(?:根据|基于|针对).{1,150}?(?=(?:给我|帮我|请)?(?:生成|出|创建|新建|做|来))", "", candidate)
        candidate = re.sub(r"^" + prefix, "", candidate)
        if re.match(r"^(?:生成|出(?!现|错|处)|创建|新建|来).{0,30}(?:小测|测验|测试|题)", candidate):
            return True
        if re.match(r"^做(?:一?[个组套份])?.{0,20}(?:小测|测验|测试)", candidate):
            return True
        if re.match(r"^(?:\d+|[一二三四五六七八九十几]+|一些)道(?:小测|练习|判断|单选|选择)?题", candidate) and re.search(r"给我|帮我|请|来", clause):
            return True
    return False
