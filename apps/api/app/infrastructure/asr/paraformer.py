from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
import dashscope
from dashscope.utils.oss_utils import OssUtils

from ...core.config import get_settings


@dataclass(frozen=True)
class TranscriptResult:
    speaker: str
    start_ms: int
    end_ms: int
    text: str


def transcribe_file(file_path: Path) -> list[TranscriptResult]:
    settings = get_settings()
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法转写上传的音频")

    base_url = settings.dashscope_base_url.rstrip("/")
    dashscope.base_http_api_url = base_url
    temporary_url, _ = OssUtils.upload(
        model=settings.asr_model,
        file_path=str(file_path),
        api_key=settings.dashscope_api_key,
    )
    if not temporary_url:
        raise RuntimeError("上传音频到百炼临时存储失败")

    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "X-DashScope-OssResourceResolve": "enable",
    }
    parameters: dict[str, object] = {
        "diarization_enabled": True,
        "timestamp_alignment_enabled": True,
    }
    if settings.asr_model == "paraformer-v2":
        parameters["language_hints"] = ["zh", "en"]

    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{base_url}/services/audio/asr/transcription",
            headers={**headers, "X-DashScope-Async": "enable"},
            json={
                "model": settings.asr_model,
                "input": {"file_urls": [temporary_url]},
                "parameters": parameters,
            },
        )
        task = _output(response, "提交录音文件转写任务失败")
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("百炼未返回转写任务 ID")

        deadline = time.monotonic() + settings.asr_max_wait_seconds
        while time.monotonic() < deadline:
            time.sleep(max(0.2, settings.asr_poll_interval_seconds))
            response = client.get(f"{base_url}/tasks/{task_id}", headers=headers)
            result = _output(response, "查询录音文件转写任务失败")
            status = result.get("task_status")
            if status == "FAILED":
                raise RuntimeError(f"录音文件转写失败：{_result_error(result)}")
            if status != "SUCCEEDED":
                continue
            files = result.get("results") or []
            if not files or files[0].get("subtask_status") != "SUCCEEDED":
                raise RuntimeError(f"录音文件转写失败：{_result_error(result)}")
            result_url = files[0].get("transcription_url")
            parsed = urlparse(result_url or "")
            if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".aliyuncs.com"):
                raise RuntimeError("百炼返回了无效的转写结果地址")
            transcript_response = client.get(result_url)
            transcript_response.raise_for_status()
            return _parse_transcript(transcript_response.json())

    raise TimeoutError(f"录音文件转写超过 {settings.asr_max_wait_seconds} 秒仍未完成")


def _output(response: httpx.Response, fallback: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{fallback}：服务返回了非 JSON 内容") from exc
    if not isinstance(payload, dict) or response.status_code >= 400 or not isinstance(payload.get("output"), dict):
        message = payload.get("message") or payload.get("code") or response.status_code
        raise RuntimeError(f"{fallback}：{message}")
    return payload["output"]


def _result_error(result: dict) -> str:
    files = result.get("results") or []
    detail = files[0] if files else result
    return str(detail.get("message") or detail.get("code") or result.get("task_status") or "未知错误")


def _parse_transcript(payload: dict) -> list[TranscriptResult]:
    segments: list[TranscriptResult] = []
    for transcript in payload.get("transcripts", []):
        sentences = transcript.get("sentences") or []
        if not sentences and transcript.get("text"):
            sentences = [{
                "begin_time": 0,
                "end_time": transcript.get("content_duration_in_milliseconds", 0),
                "text": transcript["text"],
            }]
        for sentence in sentences:
            text = str(sentence.get("text") or "").strip()
            if not text:
                continue
            start_ms = max(0, int(sentence.get("begin_time") or 0))
            end_ms = max(start_ms, int(sentence.get("end_time") or start_ms))
            speaker_id = sentence.get("speaker_id")
            segments.append(TranscriptResult(
                speaker=f"说话人 {int(speaker_id) + 1}" if speaker_id is not None else "说话人 1",
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
            ))
    segments.sort(key=lambda segment: (segment.start_ms, segment.end_ms))
    if not segments:
        raise RuntimeError("录音文件转写完成，但没有识别到文字")
    return segments
