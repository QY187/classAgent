"""既有工具/存储用例的显式语义桩。不是生产解析器，不用正则或业务实现推导答案。

只有列出的旧测试使用此边界；未知文本直接失败，新增能力必须定义预期计划。
真实解析协议由 test_agent_semantic_turns 和独立真实模型评测覆盖。
"""
from copy import deepcopy
from app.modules.chat.intent_schema import IntentPayload, TurnDecision, missing_information


READS = {
    "这门课有哪些知识点？", "这门课哪些知识点需要复习", "我还有哪些错题没掌握", "查询课程",
    "继续提问", "后续问题", "新问题", "课堂问题", "整门课程讲了什么", "我有哪些课程",
    "二叉树定义", "其他对话", "另一个问题", "能举个例子吗", "当前对话的课程有哪些",
    "有哪些课堂内容", "有哪些课次", "查看其他课程以及当前课程的课堂内容", "课堂内容是什么",
    "这门课程讲了什么", "有哪些知识点", "不要生成小测", "如何生成小测",
}
PLANS = {text: {} for text in READS}
PLANS.update({
    "创建课程": {"create_course": {}},
    "创建网络课程": {"create_course": {"name": "网络"}},
    "帮我创建网络课程": {"create_course": {"name": "网络"}},
    "创建数据结构课程": {"create_course": {"name": "数据结构"}},
    "创建线性代数课程": {"create_course": {"name": "线性代数"}},
    "创建网络课程，学期为2026秋。": {"create_course": {"name": "网络", "semester": "2026秋"}},
    "创建操作系统课程，学期为2026秋，学期为2027春。": {"issue": "请明确唯一的学期名称？"},
    "创建课程，再添加第三讲。": {"create_course": {}, "create_lesson": {"title": "第三讲"}},
    "帮我创建网络课程，再添加第三讲": {"create_course": {"name": "网络"}, "create_lesson": {"course": "网络", "title": "第三讲"}},
    "创建数据结构课程，再添加第三讲": {"create_course": {"name": "数据结构"}, "create_lesson": {"course": "数据结构", "title": "第三讲"}},
    "添加课次": {"create_lesson": {}},
    "添加第三讲": {"create_lesson": {"title": "第三讲"}},
    "添加课次标题为二叉树": {"create_lesson": {"title": "二叉树"}},
    "在数据结构课程下添加第三讲": {"create_lesson": {"course": "数据结构", "title": "第三讲"}},
    "在数据结构课程下添加第三讲，日期为2026-10-03": {"create_lesson": {"course": "数据结构", "title": "第三讲", "lesson_date": "2026-10-03"}},
    "在数据结构课程添加课次，日期为2026-10-05。": {"create_lesson": {"course": "数据结构", "lesson_date": "2026-10-05"}},
    "把前序遍历标记为": {"knowledge": {"title": "前序遍历"}},
    "把前序遍历标记为已掌握": {"knowledge": {"title": "前序遍历", "status": "mastered"}},
    "把前序遍历和中序遍历标记为已掌握": {"knowledge": {"title": "前序遍历和中序遍历", "status": "mastered"}},
    "把当前课程的递归和迭代的区别标记为已掌握": {"knowledge": {"title": "递归和迭代的区别", "status": "mastered"}},
    "把数据结构课程第三讲的前序遍历标记为已掌握": {"knowledge": {"title": "数据结构课程的第三讲的前序遍历", "status": "mastered"}},
    "不要修改叶子节点，把前序遍历标记为已掌握。": {"knowledge": {"title": "前序遍历", "status": "mastered"}},
    "把叶子节点标记为已掌握，再把前序遍历标记为未学习。": {"issue": "每次只能修改一个知识点，请明确选择其中一个。"},
    "取消，把前序遍历标记为未学习": {"issue": "指令包含取消和冲突，请明确是否修改？"},
    "刚才修改成功了吗？": {"verify": {"target": "前序遍历"}},
    "把前序遍历标记为已掌握，同时列出还没做的小测": {"knowledge": {"title": "前序遍历", "status": "mastered"}, "queries": ["workflow"]},
    "把前序遍历标记为已掌握，同时查询课程进度和未作答小测。": {"knowledge": {"title": "前序遍历", "status": "mastered"}, "queries": ["progress", "workflow"]},
    "把数据结构课程的前序遍历标记为已掌握，同时列出所有课程。": {"knowledge": {"title": "数据结构课程的前序遍历", "status": "mastered"}, "queries": ["catalog"], "catalog": ["list_courses"]},
    "查课程进度和最近一次小测成绩": {"queries": ["progress", "quiz_results"]},
    "看看最近一次小测成绩、选项和错题": {"queries": ["quiz_results", "learning"]},
})
for text in ("根据薄弱点生成3道题", "根据错题生成3道判断题", "根据需要复习的知识点生成3道判断题", "根据需要复习的知识点生成3道题"):
    PLANS[text] = {"quiz": {"mode": "practice", "count": 3}}
for text in ("根据错题生成3道判断题", "根据需要复习的知识点生成3道判断题"):
    PLANS[text]["quiz"]["question_type"] = "true_false"
for text in ("生成3道小测题", "请生成3道小测题", "生成3道判断题", "给我生成3道判断题", "生成3道单选题"):
    PLANS[text] = {"quiz": {"mode": "quiz", "count": 3}}
PLANS["给我生成5道小测题"] = {"quiz": {"mode": "quiz", "count": 5}}
for text in ("生成3道判断题", "给我生成3道判断题"):
    PLANS[text]["quiz"]["question_type"] = "true_false"
PLANS["生成3道单选题"]["quiz"]["question_type"] = "single_choice"
PLANS["根据二叉树这节课生成3道判断题"] = {"quiz": {"mode": "quiz", "count": 3, "question_type": "true_false", "lessons": ["二叉树"]}}
PLANS["请根据二叉树课次生成3道选择题"] = {"quiz": {"mode": "quiz", "count": 3, "question_type": "single_choice", "lessons": ["二叉树"]}}


def semantic_fixture(question, history=None, *, pending=None, bound_course=None, **kwargs):
    if question == "先别做":
        return TurnDecision(relation="cancel", intent=IntentPayload())
    supplements = {"网络", "线性代数", "第三讲", "第三讲？", "已掌握", "二叉树这节课"}
    relation, task_id = "new", None
    if question in supplements:
        value = deepcopy(pending["intent"]) if pending else {}
        if pending:
            relation, task_id = "continue", pending["id"]
            if question in {"网络", "线性代数"} and value.get("create_course") is not None:
                value["create_course"]["name"] = question
                if value.get("create_lesson") is not None: value["create_lesson"]["course"] = question
            elif question in {"第三讲", "第三讲？"} and value.get("create_lesson") is not None:
                value["create_lesson"]["title"] = "第三讲"
            elif question == "已掌握" and value.get("knowledge") is not None:
                value["knowledge"]["status"] = "mastered"
            elif question == "二叉树这节课" and value.get("quiz") is not None:
                value["quiz"]["lessons"] = ["二叉树"]
    else:
        if question not in PLANS:
            raise AssertionError(f"请为现有工具测试补充明确的语义桩：{question}")
        value = deepcopy(PLANS[question])
    intent = IntentPayload.model_validate(value)
    # 旧工具测试允许 Agent 通过真实目录查询定位课程，不在本桩提前决定范围。
    # 新语义入口对缺失范围的提前澄清有独立测试。
    clarification = missing_information(intent, bound_course or ("由工具查询" if intent.quiz else None))
    return TurnDecision(relation=relation, task_id=task_id, intent=intent, clarification=clarification)
