"""ASR provider adapters used by the background audio worker."""

from .paraformer import TranscriptResult, transcribe_file

__all__ = ["TranscriptResult", "transcribe_file"]
