from core.config import DocType
from core.schemas import ExtractionResult, MetadataBase
from extractors.base import BaseExtractor


class ThiDuaExtractor(BaseExtractor):
    """
    Trích xuất thông tin danh hiệu thi đua (THI_DUA) - Mục 3.4.
    """

    def extract(self, markdown_text: str, **kwargs) -> ExtractionResult:
        # Placeholder
        return ExtractionResult(
            doc_type=DocType.THI_DUA,
            person_count_declared=3,
            tong_so_ca_nhan=3,
            metadata=MetadataBase(
                document_number="45/QĐ-VPQH",
                document_name="Về việc công nhận danh hiệu Chiến sĩ thi đua cơ sở năm 2024",
                issue_date="10/01/2025",
                issue_unit="Văn phòng Quốc hội",
                signer="Bùi Văn Cường",
                content="Điều 1. Công nhận danh hiệu “Chiến sĩ thi đua cơ sở” năm 2024 cho 03 cá nhân...",
                doc_type_detected="THI_DUA",
            ),
            detail={
                "type": 1,
                "year": 2024,
                "reward_level": "Chiến sĩ thi đua cấp cơ sở",
                "content": "Công nhận danh hiệu Chiến sĩ thi đua cơ sở năm 2024 cho 03 cá nhân",
            },
            groups=[
                {
                    "group_index": 1,
                    "title": "Danh hiệu Chiến sĩ thi đua cơ sở cho các cá nhân thuộc Vụ Công tác đại biểu:",
                    "person_count_declared": 3,
                    "reward_type": "Chiến sĩ thi đua cơ sở",
                    "accomplishment": "Đã có thành tích xuất sắc trong phong trào thi đua năm 2024",
                }
            ],
            persons=[
                {
                    "stt": 1,
                    "group_index": 1,
                    "code": "1",
                    "is_collective": False,
                    "full_name": "Phạm Văn Long",
                    "position_name": "Vụ trưởng",
                    "work_organization_name": "Vụ Công tác đại biểu",
                    "award_type": "TANG",
                    "raw_text": "(1) Ông Phạm Văn Long, Vụ trưởng Vụ Công tác đại biểu.",
                }
            ],
            warnings=[],
        )
