"""既有业务测试隔离新增的模型规划边界；不对新测试或真实评测生效。"""
from pathlib import Path
from unittest.mock import patch
import pytest

from semantic_fixtures import semantic_fixture


@pytest.fixture(autouse=True)
def isolate_legacy_tests_from_quota(request, monkeypatch):
    # 既有业务单测不连接全局额度库；新专项用真实账本开启配额并验证调用边界。
    if not Path(request.module.__file__).stem.startswith("test_token_quota"):
        from app.core.config import get_settings
        monkeypatch.setattr(get_settings(), "token_quota_enabled", False)


LEGACY_TOOL_TESTS = {
    "test_agent_adversarial", "test_agent_authorization_boundaries", "test_agent_combined_actions",
    "test_agent_combined_answers", "test_agent_create_course", "test_agent_create_lesson",
    "test_agent_create_semester", "test_agent_creation_followup", "test_agent_knowledge",
    "test_agent_knowledge_status", "test_agent_multi_target_status", "test_agent_practice",
    "test_agent_quiz", "test_agent_quiz_results", "test_agent_scoped_negation",
    "test_agent_status_verification", "test_agent_wrong_questions", "test_chat_agent_progress",
    "test_chat_archive", "test_chat_cancellation", "test_chat_course", "test_chat_global",
    "test_chat_sending", "test_chat_streaming", "test_course_agent", "test_course_agent_quiz",
}


@pytest.fixture(autouse=True)
def legacy_semantic_boundary(request):
    if Path(request.module.__file__).stem not in LEGACY_TOOL_TESTS:
        yield
        return
    with patch("app.modules.chat.sending.resolve_turn_intent", side_effect=semantic_fixture):
        yield
