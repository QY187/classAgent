from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dashscope.audio.asr import Transcription
from dashscope.utils.oss_utils import OssUtils

from ...core.config import get_settings


@dataclass(frozen=True)
class TranscriptResult:
    speaker: str
    start_ms: int
    end_ms: int
    text: str


def transcribe_file(file_path: Path) -> list[TranscriptResult]:
    """Upload one local audio file and wait for Paraformer file transcription."""
    settings = get_settings()
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法调用 Paraformer ASR")
    if not file_path.is_file():
        raise FileNotFoundError(f"找不到音频文件: {file_path}")

    file_url, _ = OssUtils.upload(
        model=settings.asr_model,
        file_path=str(file_path),
        api_key=settings.dashscope_api_key,
    )
    submitted = Transcription.async_call(
        model=settings.asr_model,
        file_urls=[file_url],
        api_key=settings.dashscope_api_key,
        language_hints=["zh"],
        diarization_enabled=True,
        timestamp_alignment_enabled=True,
    )
    if submitted.status_code != 200 or submitted.output is None:
        raise RuntimeError(_response_error(submitted, "提交 Paraformer 转写任务失败"))

    task_id = submitted.output.get("task_id")
    if not task_id:
        raise RuntimeError("Paraformer 未返回转写任务 ID")

    deadline = time.monotonic() + settings.asr_max_wait_seconds
    while time.monotonic() < deadline:
        time.sleep(max(0.2, settings.asr_poll_interval_seconds))
        response = Transcription.fetch(
            task_id,
            api_key=settings.dashscope_api_key,
        )
        output = response.output or {}
        task_status = str(output.get("task_status", "")).upper()
        if task_status in {"FAILED", "CANCELED", "CANCELLED"}:
            raise RuntimeError(_response_error(response, "Paraformer 转写失败"))
        if task_status not in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
            continue
        return _parse_output(output)

    raise TimeoutError(f"Paraformer 转写超过 {settings.asr_max_wait_seconds} 秒仍未完成")


def _parse_output(output: dict[str, Any]) -> list[TranscriptResult]:
    """Parse SDK output and the optional result JSON returned by Paraformer."""
    payloads: list[Any] = [output]
    for item in _walk_dicts(output):
        for key in ("transcription_url", "result_url", "url"):
            value = item.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                try:
                    response = httpx.get(value, timeout=60)
                    response.raise_for_status()
                    payloads.append(response.json())
                except (httpx.HTTPError, ValueError) as exc:
                    raise RuntimeError(f"读取 Paraformer 转写结果失败: {exc}") from exc

    segments: list[TranscriptResult] = []
    seen: set[tuple[int, int, str, str]] = set()
    for payload in payloads:
        for segment in _extract_segments(payload):
            marker = (segment.start_ms, segment.end_ms, segment.speaker, segment.text)
            if marker not in seen:
                seen.add(marker)
                segments.append(segment)
    segments.sort(key=lambda item: (item.start_ms, item.end_ms))
    if not segments:
        raise RuntimeError("Paraformer 已完成，但没有返回可保存的文字片段")
    return segments


def _extract_segments(value: Any, speaker: str = "说话人 1") -> list[TranscriptResult]:
    if isinstance(value, list):
        segments: list[TranscriptResult] = []
        for item in value:
            segments.extend(_extract_segments(item, speaker))
        return segments
    if not isinstance(value, dict):
        return []

    current_speaker = _speaker_name(value, speaker)
    segments: list[TranscriptResult] = []
    # Paraformer returns sentences in this shape for timestamped output.
    sentences = value.get("sentences")
    if isinstance(sentences, list):
        for sentence in sentences:
            segments.extend(_extract_segments(sentence, current_speaker))
    text = value.get("text")
    start = _first_number(value, "begin_time", "start_time", "start_ms")
    end = _first_number(value, "end_time", "stop_time", "end_ms")
    if isinstance(text, str) and text.strip() and start is not None and end is not None:
        segments.append(
            TranscriptResult(
                speaker=current_speaker,
                start_ms=max(0, int(start)),
                end_ms=max(int(start), int(end)),
                text=text.strip(),
            )
        )

    for key, child in value.items():
        if key in {"sentences", "text", "begin_time", "start_time", "start_ms", "end_time", "stop_time", "end_ms"}:
            continue
        child_speaker = _speaker_name(value, current_speaker) if key in {"results", "transcripts", "channels"} else current_speaker
        segments.extend(_extract_segments(child, child_speaker))
    return segments


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _speaker_name(value: dict[str, Any], fallback: str) -> str:
    speaker = value.get("speaker_id", value.get("speaker"))
    if speaker is None:
        return fallback
    return f"说话人 {speaker}"


def _first_number(value: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, (int, float)):
            return candidate
        if isinstance(candidate, str):
            try:
                return float(candidate)
            except ValueError:
                continue
    return None


def _response_error(response: Any, prefix: str) -> str:
    output = getattr(response, "output", None) or {}
    code = getattr(response, "code", None) or output.get("code")
    message = getattr(response, "message", None) or output.get("message") or output.get("task_status")
    detail = ": ".join(str(item) for item in (code, message) if item)
    return f"{prefix}{(': ' + detail) if detail else ''}"
