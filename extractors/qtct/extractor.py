from typing import Optional
from core.config import DocType
from core.schemas import WarningItem
from extractors.base import BaseExtractor
from extractors.qtct.detail import QTCTDetailExtractor
from extractors.qtct.metadata import QTCTMetadataExtractor
from extractors.qtct.persons import QTCTPersonsExtractor
from extractors.qtct.schemas import QTCTResult


class QTCTExtractor(BaseExtractor):
    """
    Trình điều phối trích xuất thông tin văn bản Quá trình công tác (QTCT).
    Kết hợp 3 sub-extractors:
    1. QTCTMetadataExtractor (metadata)
    2. QTCTDetailExtractor (detail)
    3. QTCTPersonsExtractor (persons)
    """

    def __init__(
        self,
        metadata_extractor: Optional[QTCTMetadataExtractor] = None,
        detail_extractor: Optional[QTCTDetailExtractor] = None,
        persons_extractor: Optional[QTCTPersonsExtractor] = None,
    ):
        self.metadata_extractor = metadata_extractor or QTCTMetadataExtractor()
        self.detail_extractor = detail_extractor or QTCTDetailExtractor()
        self.persons_extractor = persons_extractor or QTCTPersonsExtractor()

    def extract(self, markdown_text: str, **kwargs) -> QTCTResult:
        """
        Thực hiện trích xuất dữ liệu hoàn chỉnh cho văn bản QTCT.
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
                    message=f"Số lượng cá nhân trích xuất ({len(persons)}) khác với số lượng văn bản công tác (1)",
                )
            )

        return QTCTResult(
            doc_type=DocType.QTCT,
            person_count_declared=1,
            tong_so_ca_nhan=len(persons),
            metadata=metadata,
            detail=detail,
            groups=[],
            persons=persons,
            warnings=warnings,
        )

    async def aextract(self, markdown_text: str, **kwargs) -> QTCTResult:
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
                    message=f"Số lượng cá nhân trích xuất ({len(persons)}) khác với số lượng văn bản công tác (1)",
                )
            )

        return QTCTResult(
            doc_type=DocType.QTCT,
            person_count_declared=1,
            tong_so_ca_nhan=len(persons),
            metadata=metadata,
            detail=detail,
            groups=[],
            persons=persons,
            warnings=warnings,
        )
