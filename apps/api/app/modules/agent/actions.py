"""模型只提供业务参数，动作权限及真实回执来自后端。"""
from fastapi import HTTPException


def execute_action(db, context, name, args):
    action = context.actions.get(name)
    if action is None:
        raise HTTPException(403, "当前问题没有明确授权该操作")
    return action(args)


class ActionStore:
    def __init__(self):
        self.results = {}

    def collect(self, context, name, result):
        if name not in context.actions or not result["ok"]:
            return
        self.results[name] = result["data"]

    def answer(self):
        # 只使用动作执行器的真实回执，不采纳模型对写入结果的描述。
        return "\n\n".join(row["message"] for row in self.results.values())
