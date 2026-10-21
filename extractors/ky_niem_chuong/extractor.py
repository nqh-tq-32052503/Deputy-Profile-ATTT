from core.config import DocType
from core.schemas import ExtractionResult, MetadataBase
from extractors.base import BaseExtractor


class KyNiemChuongExtractor(BaseExtractor):
    """
    Trích xuất thông tin kỷ niệm chương (KY_NIEM_CHUONG) - Mục 3.6.
    """

    def extract(self, markdown_text: str, **kwargs) -> ExtractionResult:
        # Placeholder
        return ExtractionResult(
            doc_type=DocType.KY_NIEM_CHUONG,
            person_count_declared=47,
            tong_so_ca_nhan=47,
            metadata=MetadataBase(
                document_number="1783/NQ-UBTVQH15",
                document_name="Về việc tặng Kỷ niệm chương “Vì sự nghiệp Quốc hội Việt Nam”",
                issue_date="06/08/2025",
                issue_unit="Ủy ban Thường vụ Quốc hội",
                signer="Trần Thanh Mẫn",
                content="Điều 1. Tặng Kỷ niệm chương “Vì sự nghiệp Quốc hội Việt Nam” cho 47 cá nhân...",
                doc_type_detected="KY_NIEM_CHUONG",
            ),
            detail={
                "award_year": 2025,
                "medal_name": "Vì sự nghiệp Quốc hội Việt Nam",
            },
            groups=[
                {
                    "group_index": 1,
                    "title": "I. Tặng Kỷ niệm chương... cho 37 cá nhân là đại biểu Quốc hội...",
                    "person_count_declared": 37,
                }
            ],
            persons=[
                {
                    "stt": 1,
                    "group_index": 1,
                    "code": "1",
                    "is_collective": False,
                    "full_name": "Nguyễn Tân Cương",
                    "position_name": "Tổng Tham mưu trưởng Quân đội nhân dân Việt Nam, Thứ trưởng",
                    "work_organization_name": "Bộ Quốc phòng",
                    "na_term": "XV",
                    "delegation": "Thành phố Hồ Chí Minh",
                    "raw_text": "(1) Đồng chí Đại tướng Nguyễn Tân Cương...",
                }
            ],
            warnings=[],
        )
