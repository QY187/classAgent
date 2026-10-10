from datetime import timedelta, timezone
from ...shared.models import ChatConversation, now_utc

GENERATION_LEASE = timedelta(minutes=5)


class GenerationStopped(Exception):
    """该请求的生成占用已经释放，旧生成任务不能再写入。"""


def is_generating(conversation: ChatConversation) -> bool:
    started = conversation.generating_at
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return bool(conversation.generation_token and started and started + GENERATION_LEASE > now_utc())
