import asyncio
import logging
from typing import List, Optional

from extractors.luong.schemas import LuongPerson
from services.llm_service import (
    LLMService,
    arefine_position_and_organization,
    clean_text,
    refine_position_and_organization,
)

logger = logging.getLogger(__name__)

PERSONS_PROMPT = """Bạn là chuyên gia trích xuất văn bản hành chính Việt Nam.
Nhiệm vụ: Trích xuất danh sách nhân sự được nâng bậc lương trong văn bản Nâng bậc lương (LUONG) dưới dạng JSON mảng danh sách cá nhân.
Mỗi cá nhân gồm các trường:
- stt: Số thứ tự (số nguyên, ví dụ: 1)
- full_name: Họ và tên cá nhân (loại bỏ hoàn toàn danh xưng Ông, Bà, Đồng chí, ví dụ: Hoàng Văn Nghĩa)
- position_name: Chức vụ lãnh đạo/quản lý tại đơn vị nếu có (ví dụ: Chủ tịch, Phó Chủ tịch, Trưởng ban, Phó Trưởng ban, Vụ trưởng, Phó Vụ trưởng, Trưởng phòng, Phó Trưởng phòng, Chủ nhiệm, Phó Chủ nhiệm...).
- work_organization_name: Đơn vị/cơ quan công tác trực tiếp của nhân sự.
- raw_text: Toàn văn câu hoặc đoạn văn trong Điều 1 chỉ định cá nhân được nâng bậc lương

QUY TẮC BÓC TÁCH CHỨC VỤ (position_name) VÀ CƠ QUAN CÔNG TÁC (work_organization_name) (BẮT BUỘC TUÂN THỦ):
1. Lựa chọn chức vụ chính:
   - TUYỆT ĐỐI KHÔNG đưa các chức danh Đảng vào position_name hoặc work_organization_name khi cá nhân có chức vụ chính quyền/Quốc hội/chuyên môn.
     * Dấu hiệu nhận biết các chức vụ Đảng là có từ khóa "đảng" ở trong tên chức vụ (hoặc "Bộ Chính trị", "Ban Bí thư", "Trung ương Đảng", "BCH Trung ương Đảng", "Cấp ủy", "Đảng ủy", "Đảng viên"...).
     * Ví dụ: "Ủy viên Ban Chấp hành Trung ương Đảng", "Ủy viên Trung ương Đảng", "Ủy viên Bộ Chính trị", "Ủy viên Ban Bí thư"... là các chức danh Đảng và BẮT BUỘC PHẢI BỎ QUA.
   - BỎ QUA các chức vụ kiêm nhiệm như "Ủy viên Ủy ban Thường vụ Quốc hội", "Ủy viên Hội đồng...", "Ủy viên Ủy ban... của Quốc hội", "đại biểu Quốc hội khóa...".
   - LỰA CHỌN chức vụ chính quyền / Quốc hội / chuyên môn cao nhất tại thời điểm ban hành.
   - Trường hợp cá nhân chỉ có duy nhất chức vụ thuộc tổ chức Đảng (ví dụ: Bí thư Thành ủy, Phó Bí thư Tỉnh ủy...) mà không có chức vụ chính quyền nào khác thì lấy chức vụ Đảng đó.
2. Phân tách position_name và work_organization_name từ chức vụ được chọn:
   - position_name: CHỈ là tên của chức danh/vị trí (ví dụ: Chủ tịch, Phó Chủ tịch, Trưởng ban, Phó Trưởng ban, Chủ nhiệm, Phó Chủ nhiệm, Vụ trưởng, Phó Vụ trưởng, Giám đốc, Phó Giám đốc, Trưởng phòng, Phó Trưởng phòng, Chuyên viên, Thư ký, Kế toán...). TUYỆT ĐỐI KHÔNG ghép tên cơ quan vào position_name, KHÔNG chứa dấu phẩy nối nhiều chức vụ. Nếu không có chức vụ lãnh đạo/quản lý cụ thể (chỉ có chức danh nghề nghiệp / ngạch lương như Giảng viên cao cấp, Chuyên viên chính...) thì position_name để null.
   - work_organization_name: Tên cơ quan, đơn vị công tác đi liền phía sau chức danh. Phải lấy tên cơ quan, đơn vị cấp nhỏ nhất (cụ thể và sát nhất với nhân sự tương ứng chức vụ, ví dụ: "Hội đồng nhân dân thành phố Hà Nội", "Ủy ban Văn hóa, Giáo dục", "Vụ Hợp tác quốc tế", không lấy cơ quan cấp trên chung chung). Nếu chức vụ đứng riêng không kèm tên cơ quan ngay sau (ví dụ: "Vụ trưởng"), lấy tên cơ quan công tác tương ứng được nêu trong văn bản (hoặc null nếu văn bản không nhắc đến).

Ví dụ minh họa:
- "(1) Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội" -> position_name: "Chủ tịch", work_organization_name: "Quốc hội" (bỏ chức danh Đảng "Ủy viên Bộ Chính trị").
- "(3) Ông Nguyễn Đức Hải, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội." -> position_name: "Phó Chủ tịch", work_organization_name: "Quốc hội" (bỏ chức danh Đảng "Ủy viên Ban Chấp hành Trung ương Đảng").
- "Chủ tịch Hội đồng nhân dân thành phố Hà Nội, Phó Trưởng Đoàn đại biểu Quốc hội thành phố Hà Nội" -> position_name: "Chủ tịch", work_organization_name: "Hội đồng nhân dân thành phố Hà Nội" (bỏ chức vụ kiêm nhiệm thứ 2).
- "Phó Chủ nhiệm Ủy ban Văn hóa, Giáo dục" -> position_name: "Phó Chủ nhiệm", work_organization_name: "Ủy ban Văn hóa, Giáo dục" (chỉ có 1 chức vụ thì mặc định lấy luôn chức vụ đó).
- "Vụ trưởng, Thư ký Chủ tịch Quốc hội" -> position_name: "Vụ trưởng", work_organization_name: tên cơ quan công tác nếu có (bỏ chức vụ kiêm nhiệm "Thư ký Chủ tịch Quốc hội").
- "Phó Trưởng phòng thuộc Vụ Hợp tác quốc tế" -> position_name: "Phó Trưởng phòng", work_organization_name: "Vụ Hợp tác quốc tế".

Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng mảng:
[
  {
    "stt": 1,
    "full_name": "...",
    "position_name": null,
    "work_organization_name": "...",
    "raw_text": "..."
  }
]"""


class LuongPersonsExtractor:
    """
    Class trích xuất danh sách nhân sự (persons) cho văn bản Nâng bậc lương (LUONG).
    Gửi request tới LLM để trích xuất danh sách nhân sự dưới dạng JSON.
    """

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()

    async def aextract(self, content: str) -> List[LuongPerson]:
        """
        Trích xuất danh sách nhân sự bất đồng bộ từ nội dung văn bản bằng LLM.
        """
        data = await self.llm_service.ask_json_async(PERSONS_PROMPT, content)
        if isinstance(data, dict):
            data = data.get("persons", [data])
        if not isinstance(data, list):
            data = [data]

        persons = []
        for idx, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            pos_name, work_org = await arefine_position_and_organization(
                clean_text(item.get("position_name")),
                clean_text(item.get("work_organization_name")),
                raw_text=clean_text(item.get("raw_text")),
                llm_service=self.llm_service,
            )
            person = LuongPerson(
                stt=item.get("stt") or idx,
                group_index=None,
                code=None,
                is_collective=False,
                full_name=clean_text(item.get("full_name")) or "",
                position_name=pos_name,
                work_organization_name=work_org,
                raw_text=clean_text(item.get("raw_text")) or "",
            )
            persons.append(person)

        return persons

    def extract(self, content: str) -> List[LuongPerson]:
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
