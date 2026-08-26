from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CareDelta API"
    frontend_origin: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CAREDELTA_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
