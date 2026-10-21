import asyncio
import logging
from typing import Dict, List, Optional

from extractors.qtct.schemas import QTCTMetadata
from services.llm_service import LLMService, clean_text

logger = logging.getLogger(__name__)

METADATA_PROMPT = """Bạn là chuyên gia trích xuất thông tin văn bản hành chính Việt Nam.
Nhiệm vụ: Trích xuất thông tin chung (metadata) của văn bản Quá trình công tác (QTCT) và trả về định dạng JSON theo đúng các quy tắc bóc tách sau:

1. document_number: Số và ký hiệu quyết định (kể cả số viết tay, ví dụ: 1122/QĐ-VPQH, M22/QĐ-VPQH).
   - QUY TẮC BẮT BUỘC: Phần lớn số hiệu là chữ viết tay trên văn bản, bạn phải trích xuất đúng các ký tự nhận diện được từ văn bản, TUYỆT ĐỐI KHÔNG được tự ý sửa hay suy đoán sang số khác (ví dụ: không được phép tự ý sửa "M22" thành "1122", phải coi "M22" là một document number hợp lệ). Chuẩn hóa khoảng trắng thừa nếu có.
2. document_name: Trích yếu văn bản (ví dụ: "Về việc điều động và bổ nhiệm công chức"). Loại bỏ phần tên loại văn bản (như "QUYẾT ĐỊNH") ở phía trước, chỉ lấy trích yếu nội dung.
3. issue_date: Ngày ký ban hành văn bản, chuẩn hóa bắt buộc theo định dạng DD/MM/YYYY (ví dụ: "ngày 06 tháng 8 năm 2018" -> "06/08/2018").
4. issue_unit: Cơ quan ban hành quyết định (ví dụ: "Văn phòng Quốc hội"). Chuẩn hóa viết hoa theo quy tắc chính tả tên cơ quan, tổ chức (không để toàn bộ in hoa như "VĂN PHÒNG QUỐC HỘI").
5. signer: Họ và tên người ký quyết định (ví dụ: "Nguyễn Hạnh Phúc"). Chỉ lấy họ tên cá nhân, loại bỏ chức vụ/danh xưng nếu có.
6. content: Toàn văn nội dung Điều 1 của quyết định.

Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng:
{
  "document_number": "...",
  "document_name": "...",
  "issue_date": "...",
  "issue_unit": "...",
  "signer": "...",
  "content": "..."
}"""


class QTCTMetadataExtractor:
    """
    Class trích xuất thông tin chung (metadata) cho văn bản Quá trình công tác (QTCT).
    Gửi request tới LLM để trích xuất thông tin theo cấu trúc JSON.
    """

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()

    @staticmethod
    def _prepend_artifact_headers(
        content: str, ocr_data: Optional[Dict] = None
    ) -> str:
        """
        Bổ sung text từ page_artifacts.headers vào đầu content nếu chưa xuất hiện,
        đảm bảo LLM nhận đầy đủ Quốc hiệu, Tiêu ngữ, Số hiệu, Ngày tháng, Cơ quan ban hành.
        """
        if not ocr_data:
            return content

        page_artifacts = ocr_data.get("page_artifacts", {})
        headers: List[Dict] = page_artifacts.get("headers", [])
        if not headers:
            return content

        # Sắp xếp headers theo reading_order để giữ đúng thứ tự hiển thị trên trang
        def _reading_order(h: Dict) -> int:
            locs = h.get("locations", [])
            if locs:
                return locs[0].get("reading_order", 0)
            return 0

        sorted_headers = sorted(headers, key=_reading_order)

        # Thu thập các header text chưa có trong content
        # So sánh theo dòng riêng biệt (line-level) thay vì substring
        # để tránh false-positive khi header là chuỗi con của dòng khác
        content_lines = {line.strip() for line in content.splitlines() if line.strip()}

        missing_headers: List[str] = []
        for h in sorted_headers:
            htext = h.get("text", "").strip()
            if htext and htext not in content_lines:
                missing_headers.append(htext)

        if missing_headers:
            header_block = "\n".join(missing_headers)
            content = f"{header_block}\n\n{content}"

        return content

    async def aextract(self, content: str, ocr_data: Optional[Dict] = None) -> QTCTMetadata:
        """
        Trích xuất metadata bất đồng bộ từ nội dung văn bản bằng LLM.
        Nếu ocr_data được cung cấp, tự động bổ sung page_artifacts headers.
        """
        content = self._prepend_artifact_headers(content, ocr_data)
        data = await self.llm_service.ask_json_async(METADATA_PROMPT, content)
        return QTCTMetadata(
            document_number=clean_text(data.get("document_number")) or "",
            document_name=clean_text(data.get("document_name")) or "",
            issue_date=clean_text(data.get("issue_date")) or "",
            issue_unit=clean_text(data.get("issue_unit")) or "",
            signer=clean_text(data.get("signer")) or "",
            content=clean_text(data.get("content")) or "",
            doc_type_detected="QTCT",
        )

    def extract(self, content: str, ocr_data: Optional[Dict] = None) -> QTCTMetadata:
        """Sync wrapper cho aextract."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(self.aextract(content, ocr_data))
            return loop.run_until_complete(self.aextract(content, ocr_data))
        except RuntimeError:
            return asyncio.run(self.aextract(content, ocr_data))

