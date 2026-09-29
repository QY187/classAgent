import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.infrastructure.asr.paraformer import transcribe_file


class ParaformerTest(unittest.TestCase):
    def test_uploaded_file_result_becomes_timestamped_segments(self):
        calls = []

        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path.endswith("/services/audio/asr/transcription"):
                return httpx.Response(200, json={"output": {"task_id": "task-1"}})
            if request.url.path.endswith("/tasks/task-1"):
                return httpx.Response(200, json={"output": {
                    "task_status": "SUCCEEDED",
                    "results": [{
                        "subtask_status": "SUCCEEDED",
                        "transcription_url": "https://result.aliyuncs.com/transcript.json",
                    }],
                }})
            return httpx.Response(200, json={"transcripts": [{"sentences": [
                {"begin_time": 100, "end_time": 800, "speaker_id": 0, "text": "第一句。"},
                {"begin_time": 900, "end_time": 1500, "speaker_id": 1, "text": "第二句。"},
            ]}]})

        settings = SimpleNamespace(
            dashscope_api_key="test-key",
            asr_model="paraformer-v2",
            dashscope_base_url="https://dashscope.aliyuncs.com/api/v1",
            asr_max_wait_seconds=10,
            asr_poll_interval_seconds=0.2,
        )
        client = httpx.Client(transport=httpx.MockTransport(respond))
        with patch("app.infrastructure.asr.paraformer.get_settings", return_value=settings), patch(
            "app.infrastructure.asr.paraformer.OssUtils.upload",
            return_value=("oss://temporary/audio.webm", None),
        ), patch("app.infrastructure.asr.paraformer.httpx.Client", return_value=client), patch(
            "app.infrastructure.asr.paraformer.time.sleep"
        ):
            segments = transcribe_file(Path("audio.webm"))

        self.assertEqual(
            [(item.speaker, item.start_ms, item.end_ms, item.text) for item in segments],
            [("说话人 1", 100, 800, "第一句。"), ("说话人 2", 900, 1500, "第二句。")],
        )
        self.assertEqual(calls[0].headers["X-DashScope-OssResourceResolve"], "enable")
        self.assertEqual(calls[0].headers["X-DashScope-Async"], "enable")


if __name__ == "__main__":
    unittest.main()
