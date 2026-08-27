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

    model_config = SettingsConfigDict(
        env_file=os.getenv("CAREDELTA_ENV_FILE", ".env.local"),
        env_prefix="CAREDELTA_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
