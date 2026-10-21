import asyncio
import logging
from typing import Any, Dict, List, Optional

from core.config import DocType
from core.schemas import WarningItem
from extractors.base import BaseExtractor
from extractors.khen_thuong.detail import KhenThuongDetailExtractor
from extractors.khen_thuong.groups import KhenThuongGroupsExtractor
from extractors.khen_thuong.metadata import KhenThuongMetadataExtractor
from extractors.khen_thuong.ocr_parser import (
    GroupChunk,
    adetect_has_attachment,
    aparse_individual_group_chunks,
    detect_has_attachment,
    parse_individual_group_chunks,
)
from extractors.khen_thuong.persons import KhenThuongPersonsExtractor
from extractors.khen_thuong.schemas import KhenThuongGroup, KhenThuongPerson, KhenThuongResult

logger = logging.getLogger(__name__)


class KhenThuongExtractor(BaseExtractor):
    """
    Trình điều phối trích xuất thông tin văn bản Khen thưởng (KHEN_THUONG).

    Hỗ trợ hai luồng:

    **Luồng A – Văn bản không có danh sách kèm theo (1 trang):**
      Chạy song song 4 sub-extractors theo kiểu cũ (metadata, detail, groups, persons
      đều nhận toàn bộ markdown text).

    **Luồng B – Văn bản có danh sách kèm theo (nhiều trang):**
      1. Phát hiện "Có danh sách kèm theo" trong Điều 1 bằng LLM/regex.
      2. Trích xuất số lượng cá nhân tuyên bố (N) từ Điều 1.
      3. Phân tích OCR tree để tìm phần DANH SÁCH kèm theo.
      4. Lọc phần Cá nhân, bỏ qua phần Tập thể.
      5. Xây dựng groups trực tiếp từ cấu trúc OCR (không cần LLM).
      6. Gửi async LLM requests song song cho từng list_item (cá nhân),
         trích xuất thông tin từng người.
      Metadata và detail vẫn chạy song song với bước phân tích danh sách.
    """

    def __init__(
        self,
        metadata_extractor: Optional[KhenThuongMetadataExtractor] = None,
        detail_extractor: Optional[KhenThuongDetailExtractor] = None,
        groups_extractor: Optional[KhenThuongGroupsExtractor] = None,
        persons_extractor: Optional[KhenThuongPersonsExtractor] = None,
    ):
        self.metadata_extractor = metadata_extractor or KhenThuongMetadataExtractor()
        self.detail_extractor = detail_extractor or KhenThuongDetailExtractor()
        self.groups_extractor = groups_extractor or KhenThuongGroupsExtractor()
        self.persons_extractor = persons_extractor or KhenThuongPersonsExtractor()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_dieu1_text(markdown_text: str) -> str:
        """
        Trích xuất nguyên văn nội dung Điều 1 từ markdown text.
        Tìm đoạn bắt đầu bằng "Điều 1" và kết thúc trước "Điều 2".
        """
        lower = markdown_text.lower()
        start_markers = ["điều 1.", "điều 1:", "điều 1 ", "điều 1\n", "điều 1-"]
        end_markers = ["điều 2.", "điều 2:", "điều 2 ", "điều 2\n", "điều 3.", "điều 4."]

        start_idx = -1
        for marker in start_markers:
            idx = lower.find(marker)
            if idx != -1:
                start_idx = idx
                break

        if start_idx == -1:
            return ""

        end_idx = len(markdown_text)
        for marker in end_markers:
            idx = lower.find(marker, start_idx + 1)
            if idx != -1 and idx < end_idx:
                end_idx = idx

        return markdown_text[start_idx:end_idx].strip()

    @staticmethod
    def _extract_danh_sach_text(markdown_text: str) -> str:
        """
        Trích xuất phần văn bản từ tiêu đề "DANH SÁCH" trở về sau mà không dùng regex.
        """
        lines = markdown_text.split("\n")
        for idx, line in enumerate(lines):
            stripped = line.strip().lstrip("#").strip().upper()
            if stripped.startswith(("DANH SÁCH", "DANH SACH")):
                return "\n".join(lines[idx:]).strip()
        return markdown_text

    @staticmethod
    def _build_warnings(
        person_count_declared: int,
        tong_so_ca_nhan: int,
        has_attachment: bool,
        use_ocr_flow: bool,
    ) -> List[WarningItem]:
        warnings = []

        if person_count_declared != tong_so_ca_nhan:
            warnings.append(
                WarningItem(
                    code="PERSON_COUNT_MISMATCH",
                    message=(
                        f"Số lượng cá nhân trích xuất ({tong_so_ca_nhan}) "
                        f"khác với số lượng tuyên bố ({person_count_declared})"
                    ),
                )
            )

        if has_attachment and tong_so_ca_nhan == 0:
            warnings.append(
                WarningItem(
                    code="MISSING_ATTACHMENT",
                    message=(
                        "Văn bản ghi chú có danh sách kèm theo nhưng không "
                        "trích xuất được danh sách cá nhân"
                    ),
                )
            )

        return warnings

    # ------------------------------------------------------------------
    # Luồng B: xử lý văn bản có danh sách kèm theo
    # ------------------------------------------------------------------

    async def _aextract_with_attachment(
        self,
        markdown_text: str,
        ocr_data: Any,
        person_count_from_dieu1: int,
    ) -> KhenThuongResult:
        """
        Luồng B (async): Xử lý văn bản có danh sách kèm theo.

        - Metadata và detail chạy song song với nhau.
        - OCR parser phân tích tree để lấy GroupChunk.
        - Groups được xây dựng trực tiếp từ GroupChunk (không cần LLM).
        - Persons được xử lý song song qua từng list_item (1 request / 1 cá nhân).
        - Nếu OCR parsing thất bại, fallback bóc tách từng cá nhân từ phần DANH SÁCH.
        """
        # Bước 1: Chạy metadata và detail song song
        ocr_for_meta = ocr_data[0] if isinstance(ocr_data, list) and ocr_data else ocr_data
        metadata_task = self.metadata_extractor.aextract(
            markdown_text, ocr_data=ocr_for_meta if isinstance(ocr_for_meta, dict) else None
        )
        detail_task = self.detail_extractor.aextract(markdown_text)
        metadata, detail = await asyncio.gather(metadata_task, detail_task)

        # Bước 2: Phân tích OCR tree lấy GroupChunk (bất đồng bộ)
        group_chunks: Optional[List[GroupChunk]] = (
            await aparse_individual_group_chunks(ocr_data, llm_service=self.groups_extractor.llm_service)
            if ocr_data
            else None
        )

        if not group_chunks:
            logger.warning(
                "[KHEN_THUONG] Luồng B: Không phân tích được GroupChunk từ OCR tree. "
                "Fallback sang trích xuất từng người từ phần DANH SÁCH (1 người / 1 LLM request)."
            )
            danh_sach_text = self._extract_danh_sach_text(markdown_text)
            groups_task = self.groups_extractor.aextract(danh_sach_text)
            persons_task = self.persons_extractor.aextract(danh_sach_text)
            groups, persons = await asyncio.gather(groups_task, persons_task)
        else:
            logger.info(
                f"[KHEN_THUONG] Luồng B: Phân tích OCR thành công. "
                f"Tìm thấy {len(group_chunks)} nhóm cá nhân, "
                f"tổng {sum(len(c.item_texts) for c in group_chunks)} items."
            )
            # Bước 3: Xây dựng groups từ chunks (không cần LLM)
            groups: List[KhenThuongGroup] = self.groups_extractor.build_from_chunks(
                group_chunks
            )
            # Bước 4: Trích xuất persons song song (1 LLM call / list_item)
            persons: List[KhenThuongPerson] = (
                await self.persons_extractor.aextract_from_group_chunks(group_chunks)
            )

        # Tính toán số lượng
        declared_sum = sum(g.person_count_declared for g in groups if g.person_count_declared)
        person_count_declared = (
            person_count_from_dieu1
            or (declared_sum if declared_sum > 0 else len(persons))
        )
        tong_so_ca_nhan = len(persons)

        warnings = self._build_warnings(
            person_count_declared=person_count_declared,
            tong_so_ca_nhan=tong_so_ca_nhan,
            has_attachment=True,
            use_ocr_flow=True,
        )

        return KhenThuongResult(
            doc_type=DocType.KHEN_THUONG,
            person_count_declared=person_count_declared,
            tong_so_ca_nhan=tong_so_ca_nhan,
            metadata=metadata,
            detail=detail,
            groups=groups,
            persons=persons,
            warnings=warnings,
        )


    # ------------------------------------------------------------------
    # Luồng A: văn bản không có danh sách kèm theo
    # ------------------------------------------------------------------

    async def _aextract_simple(
        self,
        markdown_text: str,
        ocr_data: Optional[Dict],
    ) -> KhenThuongResult:
        """
        Luồng A (async): Văn bản 1 trang hoặc không phát hiện danh sách kèm theo.
        Chạy song song tất cả 4 sub-extractors như luồng cũ.
        """
        metadata_task = self.metadata_extractor.aextract(
            markdown_text, ocr_data=ocr_data
        )
        detail_task = self.detail_extractor.aextract(markdown_text)
        groups_task = self.groups_extractor.aextract(markdown_text)
        persons_task = self.persons_extractor.aextract(markdown_text)

        metadata, detail, groups, persons = await asyncio.gather(
            metadata_task, detail_task, groups_task, persons_task
        )

        declared_sum = sum(g.person_count_declared for g in groups if g.person_count_declared)
        person_count_declared = declared_sum if declared_sum > 0 else len(persons)
        tong_so_ca_nhan = len(persons)

        warnings = self._build_warnings(
            person_count_declared=person_count_declared,
            tong_so_ca_nhan=tong_so_ca_nhan,
            has_attachment=False,
            use_ocr_flow=False,
        )

        return KhenThuongResult(
            doc_type=DocType.KHEN_THUONG,
            person_count_declared=person_count_declared,
            tong_so_ca_nhan=tong_so_ca_nhan,
            metadata=metadata,
            detail=detail,
            groups=groups,
            persons=persons,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def aextract(self, markdown_text: str, **kwargs) -> KhenThuongResult:
        """
        Async extraction pipeline chính.

        Bước 1: Đọc Điều 1, kiểm tra xem có 'Có danh sách kèm theo' không.
        Bước 2: Nếu có → Luồng B (OCR-aware, per-item async LLM).
                Nếu không → Luồng A (đơn giản, toàn bộ text 1 lần).
        """
        ocr_data: Optional[Any] = kwargs.get("ocr_data")
        ocr_data_list: Optional[List[Dict]] = kwargs.get("ocr_data_list")

        active_ocr = ocr_data_list if ocr_data_list else ocr_data

        dieu1_text = self._get_dieu1_text(markdown_text)
        has_attachment, person_count_from_dieu1 = await adetect_has_attachment(
            dieu1_text, full_text=markdown_text, llm_service=self.metadata_extractor.llm_service
        )

        logger.info(
            f"[KHEN_THUONG] has_attachment={has_attachment}, "
            f"person_count_from_dieu1={person_count_from_dieu1}"
        )

        if has_attachment:
            return await self._aextract_with_attachment(
                markdown_text=markdown_text,
                ocr_data=active_ocr,
                person_count_from_dieu1=person_count_from_dieu1,
            )

        if isinstance(ocr_data, dict):
            simple_ocr_data = ocr_data
        elif ocr_data_list:
            simple_ocr_data = ocr_data_list[0]
        else:
            simple_ocr_data = None
        return await self._aextract_simple(
            markdown_text=markdown_text,
            ocr_data=simple_ocr_data,
        )

    def extract(self, markdown_text: str, **kwargs) -> KhenThuongResult:
        """Sync wrapper cho aextract."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(self.aextract(markdown_text, **kwargs))
            return loop.run_until_complete(self.aextract(markdown_text, **kwargs))
        except RuntimeError:
            return asyncio.run(self.aextract(markdown_text, **kwargs))
