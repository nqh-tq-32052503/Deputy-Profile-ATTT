from core.config import DocType
from core.schemas import ExtractionResult, MetadataBase
from extractors.base import BaseExtractor


class PhuCapExtractor(BaseExtractor):
    """
    Trích xuất thông tin quyết định phụ cấp (PHU_CAP) - Mục 3.3.
    """

    def extract(self, markdown_text: str, **kwargs) -> ExtractionResult:
        # Placeholder
        return ExtractionResult(
            doc_type=DocType.PHU_CAP,
            person_count_declared=1,
            tong_so_ca_nhan=1,
            metadata=MetadataBase(
                document_number="852/QĐ-VPQH",
                document_name="Về việc chi trả phụ cấp trách nhiệm công tác",
                issue_date="15/01/2025",
                issue_unit="Văn phòng Quốc hội",
                signer="Bùi Văn Cường",
                content="Điều 1. Chi trả phụ cấp trách nhiệm công tác đối với ông Nguyễn Văn A...",
                doc_type_detected="PHU_CAP",
            ),
            detail={
                "allowance_type": "Phụ cấp trách nhiệm công việc",
                "allowance_name": "Phụ cấp trách nhiệm cán bộ chuyên môn",
                "allowance_factor": 0.5,
                "amount": None,
                "percentage": None,
                "effective_from": "01/01/2025",
                "effective_to": None,
            },
            groups=[],
            persons=[
                {
                    "stt": 1,
                    "group_index": None,
                    "code": None,
                    "is_collective": False,
                    "full_name": "Nguyễn Văn A",
                    "position_name": "Chuyên viên chính",
                    "work_organization_name": "Vụ Dân nguyện thuộc Văn phòng Quốc hội",
                    "raw_text": "Điều 1. Chi trả phụ cấp trách nhiệm công tác đối với ông Nguyễn Văn A...",
                }
            ],
            warnings=[],
        )
