import asyncio
import logging
from typing import Any, Optional

from extractors.khen_thuong.schemas import KhenThuongDetail
from services.llm_service import LLMService, clean_text

logger = logging.getLogger(__name__)

DETAIL_PROMPT = """Bạn là chuyên gia trích xuất văn bản hành chính Việt Nam.
Nhiệm vụ: Trích xuất thông tin chi tiết khen thưởng (detail) của văn bản Khen thưởng (KHEN_THUONG) dưới dạng JSON với các trường:
- type: Cố định là số nguyên 2 (quy ước HSĐB: 2 = Khen thưởng).
- year: Năm khen thưởng (số nguyên 4 chữ số, ví dụ: 2024, lấy từ nội dung khen thưởng trong Điều 1 hoặc năm ban hành).
- reward_level: Cấp khen thưởng (ví dụ: "Bằng khen Ủy ban Thường vụ Quốc hội", "Bằng khen Thủ tướng Chính phủ").
- content: Nội dung khen thưởng chung trong Điều 1 (ví dụ: "Tặng Bằng khen của Ủy ban Thường vụ Quốc hội cho 17 cá nhân do có thành tích xuất sắc").

Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng:
{
  "type": 2,
  "year": 2024,
  "reward_level": "...",
  "content": "..."
}"""


def _parse_year(val: Any) -> int:
    """Trích xuất năm (4 chữ số) an toàn mà không dùng regex."""
    if val is not None:
        try:
            v_str = str(val).strip()
            if v_str.isdigit() and len(v_str) == 4:
                return int(v_str)
            for i in range(len(v_str) - 3):
                sub = v_str[i : i + 4]
                if sub.isdigit() and sub.startswith(("19", "20")):
                    return int(sub)
        except (ValueError, TypeError):
            pass
    return 2024


class KhenThuongDetailExtractor:
    """
    Class trích xuất thông tin chi tiết khen thưởng (detail) cho loại văn bản KHEN_THUONG.
    Gửi request tới LLM để trích xuất thông tin chi tiết dưới dạng JSON.
    """

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()

    async def aextract(self, content: str) -> KhenThuongDetail:
        """
        Trích xuất detail bất đồng bộ từ nội dung văn bản bằng LLM.
        """
        data = await self.llm_service.ask_json_async(DETAIL_PROMPT, content)

        year = _parse_year(data.get("year"))
        reward_level = clean_text(data.get("reward_level")) or ""
        content_text = clean_text(data.get("content")) or ""

        return KhenThuongDetail(
            type=2,
            year=year,
            reward_level=reward_level,
            content=content_text,
        )

    def extract(self, content: str) -> KhenThuongDetail:
        """Sync wrapper cho aextract."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(self.aextract(content))
            return loop.run_until_complete(self.aextract(content))
        except RuntimeError:
            return asyncio.run(self.aextract(content))
