from functools import lru_cache

from app.repositories import MemoryRepository
from app.seed import build_seed_record


@lru_cache
def get_repository() -> MemoryRepository:
    return MemoryRepository([build_seed_record()])
