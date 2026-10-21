import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from core.schemas import ExtractionResult, WarningItem


class BaseExtractor(ABC):
    """
    Interface cơ sở cho các bộ trích xuất thông tin văn bản theo từng doc_type.
    """

    @abstractmethod
    def extract(self, markdown_text: str, **kwargs) -> ExtractionResult:
        """
        Trích xuất thông tin có cấu trúc từ văn bản Markdown.
        """
        pass

    async def aextract(self, markdown_text: str, **kwargs) -> ExtractionResult:
        """
        Bản async của hàm trích xuất.
        """
        await asyncio.sleep(0)
        return self.extract(markdown_text, **kwargs)
