from functools import lru_cache

from pymongo import MongoClient

from app.config import get_settings
from app.repositories import MongoRepository
from app.seed import build_seed_record
from app.services.ai_ingest import DeepSeekAdapter, LLMAdapter


@lru_cache
def get_mongo_client() -> MongoClient:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError(
            "MONGODB_URI is required when starting the CareDelta application"
        )
    return MongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=5_000,
        tz_aware=True,
    )


@lru_cache
def get_repository() -> MongoRepository:
    settings = get_settings()
    collection = get_mongo_client()[settings.mongodb_database]["patient_records"]
    return MongoRepository(collection)


@lru_cache
def get_llm_adapter() -> LLMAdapter | None:
    settings = get_settings()
    if not settings.deepseek_api_key:
        return None
    return DeepSeekAdapter(
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        timeout=settings.deepseek_timeout_seconds,
        max_tokens=settings.deepseek_max_tokens,
    )


def initialize_repository() -> None:
    get_repository().initialize(build_seed_record())


def close_repository() -> None:
    if get_mongo_client.cache_info().currsize:
        get_mongo_client().close()
    get_repository.cache_clear()
    get_mongo_client.cache_clear()
    get_llm_adapter.cache_clear()
