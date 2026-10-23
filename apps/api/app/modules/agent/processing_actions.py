from .tools import check_lesson
from .actions import execute_action


def retry_transcription(db, context, args):
    check_lesson(db, context, args.lesson_id)
    return execute_action(db, context, "retry_transcription", args)
