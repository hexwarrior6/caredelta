import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CareDelta API"
    frontend_origin: str = "http://localhost:3000"
    frontend_origin_regex: str | None = None
    mongodb_uri: str | None = Field(default=None, validation_alias="MONGODB_URI")
    mongodb_database: str = Field(
        default="caredelta_development", validation_alias="MONGODB_DATABASE"
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com", validation_alias="DEEPSEEK_BASE_URL"
    )
    deepseek_model: str = Field(
        default="deepseek-v4-flash", validation_alias="DEEPSEEK_MODEL"
    )
    deepseek_api_key: str | None = Field(
        default=None, validation_alias="DEEPSEEK_API_KEY"
    )
    deepseek_timeout_seconds: float = Field(
        default=30.0, validation_alias="DEEPSEEK_TIMEOUT_SECONDS", gt=0, le=60
    )
    deepseek_max_tokens: int = Field(
        default=1_200, validation_alias="DEEPSEEK_MAX_TOKENS", ge=200, le=8_000
    )
    demo_auth_secret: str = Field(validation_alias="DEMO_AUTH_SECRET", min_length=32)
    allow_legacy_auth_headers: bool = Field(
        default=False, validation_alias="ALLOW_LEGACY_AUTH_HEADERS"
    )

    model_config = SettingsConfigDict(
        env_file=os.getenv("CAREDELTA_ENV_FILE", ".env.local"),
        env_prefix="CAREDELTA_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
