import asyncio
import logging
import re
from typing import Any, Optional

from extractors.luong.schemas import LuongDetail
from services.llm_service import LLMService, clean_text

logger = logging.getLogger(__name__)

DETAIL_PROMPT = """Bạn là chuyên gia trích xuất văn bản hành chính Việt Nam.
Nhiệm vụ: Trích xuất thông tin chi tiết quá trình nâng bậc lương (detail) của văn bản Nâng bậc lương (LUONG) dưới dạng JSON với các trường sau:

1. raise_salary_reason: Lý do nâng lương (ví dụ: "Nâng bậc lương thường xuyên", "Nâng bậc lương trước thời hạn").
2. position_wage: Ngạch / Chức danh nghề nghiệp (ví dụ: "Giảng viên cao cấp (hạng I)", "Chuyên viên chính").
3. position_wage_code: Mã ngạch / mã số chức danh nghề nghiệp (ví dụ: "V.07.01.01", nếu không có thì null).
4. old_step: Bậc lương cũ trước khi nâng (số nguyên, ví dụ: 3, nếu không có thì null).
5. old_factor: Hệ số lương cũ trước khi nâng (số thực dùng dấu chấm, ví dụ: 6.92, nếu không có thì null).
6. salary_step: Bậc lương mới được nâng lên (số nguyên, ví dụ: 4, nếu không tìm thấy thông tin thì bắt buộc trả về null, tuyệt đối không điền 0).
7. salary_factor: Hệ số lương mới được nâng lên (số thực dùng dấu chấm, ví dụ: 7.28, nếu không tìm thấy thông tin thì bắt buộc trả về null, tuyệt đối không điền 0).
8. start_date: Mốc hưởng lương mới bắt buộc chuẩn hóa theo định dạng DD/MM/YYYY (ví dụ: từ "ngày 01/6/2025" -> "01/06/2025").
9. review_date: Mốc tính nâng lương lần sau bắt buộc chuẩn hóa theo định dạng DD/MM/YYYY (ví dụ: từ "ngày 01/6/2025" -> "01/06/2025", nếu không quy định thì null). Thông thường mốc này trùng với start_date.
10. percentage: Tỷ lệ hưởng lương nếu có (số thực ví dụ: vượt khung, tập sự, nếu không có thì null).

LƯU Ý QUAN TRỌNG:
- NẾU KHÔNG TÌM THẤY THÔNG TIN VỀ BẤT KỲ TRƯỜNG NÀO (đặc biệt là salary_step, salary_factor, old_step, old_factor), BẮT BUỘC PHẢI TRẢ VỀ null, TUYỆT ĐỐI KHÔNG TỰ Ý ĐIỀN 0 HOẶC BẤT KỲ GIÁ TRỊ NÀO KHÁC.
- Phân biệt rõ giữa bậc cũ / hệ số cũ (old_step, old_factor) và bậc mới / hệ số mới (salary_step, salary_factor).
- Các trường số thực phải dùng dấu chấm thập phân, không dùng dấu phẩy (ví dụ: 6.92 thay vì 6,92).
- Các trường ngày tháng bắt buộc đủ 2 chữ số ngày, 2 chữ số tháng, 4 chữ số năm: DD/MM/YYYY.

Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng:
{
  "raise_salary_reason": "...",
  "position_wage": "...",
  "position_wage_code": "...",
  "old_step": 3,
  "old_factor": 6.92,
  "salary_step": 4,
  "salary_factor": 7.28,
  "start_date": "...",
  "review_date": "...",
  "percentage": null
}"""


def _parse_int(val: Any) -> Optional[int]:
    """Chuyển đổi an toàn sang số nguyên."""
    if val is None:
        return None
    try:
        if isinstance(val, int):
            return val
        cleaned = str(val).strip()
        match = re.search(r"\d+", cleaned)
        if match:
            return int(match.group())
        return None
    except (ValueError, TypeError):
        return None


def _parse_float(val: Any) -> Optional[float]:
    """Chuyển đổi an toàn sang số thực, hỗ trợ cả dấu phẩy."""
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            return float(val)
        cleaned = str(val).strip().replace(",", ".")
        match = re.search(r"\d+(\.\d+)?", cleaned)
        if match:
            return float(match.group())
        return None
    except (ValueError, TypeError):
        return None


def _normalize_date(val: Optional[str]) -> Optional[str]:
    """Chuẩn hóa ngày sang định dạng DD/MM/YYYY nếu có dạng D/M/YYYY."""
    if not val:
        return None
    cleaned = val.strip()
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", cleaned)
    if match:
        day, month, year = match.groups()
        return f"{int(day):02d}/{int(month):02d}/{year}"
    return cleaned


class LuongDetailExtractor:
    """
    Class trích xuất thông tin chi tiết quá trình nâng lương (detail) cho loại văn bản LUONG.
    Gửi request tới LLM để trích xuất thông tin chi tiết dưới dạng JSON.
    """

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()

    async def aextract(self, content: str) -> LuongDetail:
        """
        Trích xuất detail bất đồng bộ từ nội dung văn bản bằng LLM.
        """
        data = await self.llm_service.ask_json_async(DETAIL_PROMPT, content)

        old_step = _parse_int(data.get("old_step"))
        old_factor = _parse_float(data.get("old_factor"))
        salary_step = _parse_int(data.get("salary_step"))
        salary_factor = _parse_float(data.get("salary_factor"))
        percentage = _parse_float(data.get("percentage"))

        # Nếu không có thông tin hoặc bằng 0 thì chuyển thành None (null trong JSON)
        if salary_step == 0:
            salary_step = None
        if salary_factor is not None and abs(salary_factor) < 1e-6:
            salary_factor = None
        if old_step == 0:
            old_step = None
        if old_factor is not None and abs(old_factor) < 1e-6:
            old_factor = None

        start_date = clean_text(data.get("start_date")) or ""
        start_date = _normalize_date(start_date) or start_date

        review_date = clean_text(data.get("review_date"))
        if review_date:
            review_date = _normalize_date(review_date)

        return LuongDetail(
            raise_salary_reason=clean_text(data.get("raise_salary_reason")) or "",
            position_wage=clean_text(data.get("position_wage")) or "",
            position_wage_code=clean_text(data.get("position_wage_code")),
            old_step=old_step,
            old_factor=old_factor,
            salary_step=salary_step,
            salary_factor=salary_factor,
            start_date=start_date,
            review_date=review_date,
            percentage=percentage,
        )

    def extract(self, content: str) -> LuongDetail:
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
