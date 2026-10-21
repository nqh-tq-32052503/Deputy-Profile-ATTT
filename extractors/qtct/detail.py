import asyncio
import logging
from typing import Optional

from extractors.qtct.schemas import QTCTDetail
from services.llm_service import (
    LLMService,
    arefine_position_and_organization,
    clean_text,
    refine_position_and_organization,
)

logger = logging.getLogger(__name__)

DETAIL_PROMPT = """Bạn là chuyên gia trích xuất văn bản hành chính Việt Nam.
Nhiệm vụ: Trích xuất thông tin chi tiết quá trình công tác (detail) của văn bản dưới dạng JSON với các trường:
- process_type: Loại quá trình công tác (ví dụ: Điều động và bổ nhiệm, Bổ nhiệm, Luân chuyển...)
- start_date: Ngày bắt đầu giữ chức vụ mới định dạng DD/MM/YYYY
- from_organization_name: Cơ quan/đơn vị công tác trước khi điều động
- work_organization_name: Cơ quan/đơn vị mới đến nhận công tác
- position_name: Chức vụ mới được bổ nhiệm ngắn gọn (ví dụ: Phó Giám đốc, Vụ trưởng, Chủ nhiệm...). Nếu có từ 2 chức vụ trở lên thì chỉ lấy chức vụ đầu tiên; tuyệt đối không ghép tên cơ quan vào position_name.
- position_detail: Chức vụ cụ thể kèm đơn vị mới (ví dụ: Phó Giám đốc Trung tâm Bồi dưỡng đại biểu dân cử)
- appointment_term_years: Thời hạn bổ nhiệm tính theo năm (số thực hoặc số nguyên, ví dụ: 5.0, nếu không quy định thì null)
- allowance_name: Tên khoản phụ cấp kèm theo nếu có (ví dụ: Phụ cấp chức vụ lãnh đạo, nếu không có thì null)
- allowance_factor: Mức hưởng hệ số phụ cấp kèm theo (số thực, ví dụ: 0.8, nếu không có thì null)
Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng:
{
  "process_type": "...",
  "start_date": "...",
  "from_organization_name": "...",
  "work_organization_name": "...",
  "position_name": "...",
  "position_detail": "...",
  "appointment_term_years": 5.0,
  "allowance_name": "...",
  "allowance_factor": 0.8
}"""


class QTCTDetailExtractor:
    """
    Class trích xuất thông tin chi tiết quá trình công tác (detail) cho loại văn bản QTCT.
    Gửi request tới LLM để trích xuất thông tin chi tiết dưới dạng JSON.
    """

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()

    async def aextract(self, content: str) -> QTCTDetail:
        """
        Trích xuất detail bất đồng bộ từ nội dung văn bản bằng LLM.
        """
        data = await self.llm_service.ask_json_async(DETAIL_PROMPT, content)

        appointment_term_years = data.get("appointment_term_years")
        if appointment_term_years is not None:
            try:
                appointment_term_years = float(str(appointment_term_years).replace(",", "."))
            except (ValueError, TypeError):
                appointment_term_years = None

        allowance_factor = data.get("allowance_factor")
        if allowance_factor is not None:
            try:
                # Xử lý chuỗi nếu LLM trả về dạng '0,8/tháng'
                factor_str = str(allowance_factor).split("/")[0].strip().replace(",", ".")
                allowance_factor = float(factor_str)
            except (ValueError, TypeError):
                allowance_factor = None

        pos_name, _ = await arefine_position_and_organization(
            data.get("position_name"),
            llm_service=self.llm_service,
        )
        position_name_val = pos_name or clean_text(data.get("position_name")) or ""

        return QTCTDetail(
            process_type=clean_text(data.get("process_type")) or "",
            start_date=clean_text(data.get("start_date")) or "",
            from_organization_name=clean_text(data.get("from_organization_name")) or "",
            work_organization_name=clean_text(data.get("work_organization_name")) or "",
            position_name=position_name_val,
            position_detail=clean_text(data.get("position_detail")),
            appointment_term_years=appointment_term_years,
            allowance_name=clean_text(data.get("allowance_name")),
            allowance_factor=allowance_factor,
        )

    def extract(self, content: str) -> QTCTDetail:
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
