"""请求内的工具进展观察；仅阻止重复无变化读取，不缓存授权或写入回执。"""
import json
from hashlib import sha256

from .executor import failure
from .registry import TOOLS


class ExecutionState:
    def __init__(self):
        self.reads = {}

    def identity(self, name, arguments):
        tool = TOOLS.get(name)
        if tool is None or tool.writes:
            return None
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
            # 同义默认参数、字段顺序不构成新策略；无效参数仍交给原执行器校验。
            args = tool.arguments.model_validate(args).model_dump()
            return name, json.dumps(args, sort_keys=True, ensure_ascii=False)
        except (ValueError, TypeError):
            return None

    def before(self, name, arguments):
        key = self.identity(name, arguments)
        if key is not None and self.reads.get(key, (None, 0))[1] >= 2:
            return failure(name, "no_progress", "相同参数已读取两次且结果未变化。请调整查询词、来源或分页；无法继续时返回已核验结果并说明不足。")
        return None

    def observe(self, name, arguments, result):
        tool = TOOLS.get(name)
        if tool and tool.writes:
            if result["ok"]:
                self.reads.clear()  # 状态改变后允许重新读取，不复用旧数据或权限。
            return None
        key = self.identity(name, arguments)
        if key is not None and result.get("error", {}).get("code") != "no_progress":
            digest = sha256(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
            old, count = self.reads.get(key, (None, 0))
            self.reads[key] = (digest, count + 1 if old == digest else 1)
        if not result["ok"]:
            return "读取失败：根据错误修正参数或改用其他授权来源；不要重复相同失败，也不能将失败当成空数据。"
        data = result.get("data")
        if not isinstance(data, dict):
            return None
        if data.get("items") == []:
            return "本次条件无匹配：只说明这一查询为空；可调整检索词或资料来源，不代表全部课堂资料都不存在。"
        if data.get("next_offset") is not None or data.get("has_more"):
            return "结果未读完：若用户要求完整列表或尚缺依据，继续分页；已足够回答时停止，不把本页统计当成全部。"
        if key is not None and self.reads.get(key, (None, 0))[1] >= 2:
            return "相同读取未增加信息：利用已读依据回答，或换查询方式，勿继续重复相同参数。"
        return None
