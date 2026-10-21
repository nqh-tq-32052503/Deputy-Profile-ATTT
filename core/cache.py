import hashlib
import time
from typing import Dict, List, Optional, Tuple
from core.config import CACHE_TTL_SECONDS
from core.schemas import ExtractionResult


class CacheManager:
    """
    Quản lý bộ nhớ đệm (Cache) theo mã băm SHA-256 của:
    Cache Key = SHA256(doc_type + nội dung tất cả các file)
    Thời gian lưu cache mặc định là 24 giờ.
    """

    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        # key -> (timestamp, ExtractionResult)
        self._cache_store: Dict[str, Tuple[float, ExtractionResult]] = {}

    @staticmethod
    def compute_key(doc_type: str, file_bytes_list: List[bytes]) -> str:
        hasher = hashlib.sha256()
        hasher.update(doc_type.encode("utf-8"))
        for content in file_bytes_list:
            hasher.update(content)
        return hasher.hexdigest()

    def get(self, key: str) -> Optional[ExtractionResult]:
        if key not in self._cache_store:
            return None
        created_time, result = self._cache_store[key]
        if time.time() - created_time > self.ttl_seconds:
            # Expired
            del self._cache_store[key]
            return None
        return result

    def set(self, key: str, result: ExtractionResult) -> None:
        self._cache_store[key] = (time.time(), result)

    def clear(self) -> None:
        self._cache_store.clear()


# Global cache instance
cache_manager = CacheManager()
