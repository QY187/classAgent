from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://classagent:classagent@localhost:5432/classagent"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "classagent-audio"
    s3_secure: bool = False
    storage_backend: str = "local"
    local_storage_path: str = "./data/local/uploads"
    transcription_provider: str = "mock"
    asr_model: str = "paraformer-v2"
    asr_poll_interval_seconds: float = 3.0
    asr_max_wait_seconds: int = 1800
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    summary_model: str = "deepseek-chat"
    summary_provider: str = "deepseek"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
