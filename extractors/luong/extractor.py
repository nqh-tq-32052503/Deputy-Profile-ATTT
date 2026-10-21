from typing import Optional
from core.config import DocType
from core.schemas import WarningItem
from extractors.base import BaseExtractor
from extractors.luong.detail import LuongDetailExtractor
from extractors.luong.metadata import LuongMetadataExtractor
from extractors.luong.persons import LuongPersonsExtractor
from extractors.luong.schemas import LuongResult


class LuongExtractor(BaseExtractor):
    """
    Trình điều phối trích xuất thông tin văn bản Nâng bậc lương (LUONG).
    Kết hợp 3 sub-extractors:
    1. LuongMetadataExtractor (metadata)
    2. LuongDetailExtractor (detail)
    3. LuongPersonsExtractor (persons)
    """

    def __init__(
        self,
        metadata_extractor: Optional[LuongMetadataExtractor] = None,
        detail_extractor: Optional[LuongDetailExtractor] = None,
        persons_extractor: Optional[LuongPersonsExtractor] = None,
    ):
        self.metadata_extractor = metadata_extractor or LuongMetadataExtractor()
        self.detail_extractor = detail_extractor or LuongDetailExtractor()
        self.persons_extractor = persons_extractor or LuongPersonsExtractor()

    def extract(self, markdown_text: str, **kwargs) -> LuongResult:
        """
        Thực hiện trích xuất dữ liệu đồng bộ cho văn bản LUONG.
        """
        ocr_data = kwargs.get("ocr_data")
        metadata = self.metadata_extractor.extract(markdown_text, ocr_data=ocr_data)
        detail = self.detail_extractor.extract(markdown_text)
        persons = self.persons_extractor.extract(markdown_text)

        warnings = []
        if len(persons) != 1:
            warnings.append(
                WarningItem(
                    code="PERSON_COUNT_MISMATCH",
                    message=f"Số lượng cá nhân trích xuất ({len(persons)}) khác với số lượng văn bản lương (1)",
                )
            )

        return LuongResult(
            doc_type=DocType.LUONG,
            person_count_declared=1,
            tong_so_ca_nhan=len(persons),
            metadata=metadata,
            detail=detail,
            groups=[],
            persons=persons,
            warnings=warnings,
        )

    async def aextract(self, markdown_text: str, **kwargs) -> LuongResult:
        """Async extraction pipeline chạy đồng thời cả 3 sub-extractors."""
        import asyncio

        ocr_data = kwargs.get("ocr_data")
        metadata_task = self.metadata_extractor.aextract(markdown_text, ocr_data=ocr_data)
        detail_task = self.detail_extractor.aextract(markdown_text)
        persons_task = self.persons_extractor.aextract(markdown_text)

        metadata, detail, persons = await asyncio.gather(
            metadata_task, detail_task, persons_task
        )

        warnings = []
        if len(persons) != 1:
            warnings.append(
                WarningItem(
                    code="PERSON_COUNT_MISMATCH",
                    message=f"Số lượng cá nhân trích xuất ({len(persons)}) khác với số lượng văn bản lương (1)",
                )
            )

        return LuongResult(
            doc_type=DocType.LUONG,
            person_count_declared=1,
            tong_so_ca_nhan=len(persons),
            metadata=metadata,
            detail=detail,
            groups=[],
            persons=persons,
            warnings=warnings,
        )
