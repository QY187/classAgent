from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


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
    asr_model: str = "paraformer-v2"
    asr_poll_interval_seconds: float = 3.0
    asr_max_wait_seconds: int = 1800
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v2"
    embedding_dim: int = 1536
    rerank_enabled: bool = True
    rerank_base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank"
    rerank_model: str = "gte-rerank-v2"
    deepseek_api_key: str = ""
    summary_model: str = "deepseek-chat"
    summary_provider: str = "deepseek"
    agent_provider: Literal["deepseek", "dashscope", "openai_compatible"] = "deepseek"
    agent_base_url: str = ""
    agent_api_key: str = Field(default="", repr=False)
    agent_model: str = ""
    token_quota_enabled: bool = True
    daily_token_limit: int = Field(default=100000, ge=0, le=1000000000)
    secret_key: str = "dev-secret-change-me"
    admin_username: str = "root"
    admin_password: str = "123456"
    allow_registration: bool = True
    access_token_expire_minutes: int = 1440
    refresh_token_expire_minutes: int = 43200

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore", hide_input_in_errors=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
