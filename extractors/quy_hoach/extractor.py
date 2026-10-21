from core.config import DocType
from core.schemas import ExtractionResult, MetadataBase
from extractors.base import BaseExtractor


class QuyHoachExtractor(BaseExtractor):
    """
    Trích xuất thông tin quyết định quy hoạch cán bộ (QUY_HOACH) - Mục 3.7.
    """

    def extract(self, markdown_text: str, **kwargs) -> ExtractionResult:
        # Placeholder
        return ExtractionResult(
            doc_type=DocType.QUY_HOACH,
            person_count_declared=1,
            tong_so_ca_nhan=1,
            metadata=MetadataBase(
                document_number="2031-QĐ/BTCTW",
                document_name="Phê duyệt quy hoạch các chức danh cán bộ diện Trung ương quản lý...",
                issue_date="20/07/2023",
                issue_unit="Ban Tổ chức Trung ương",
                signer="Nguyễn Quang Dương",
                content="Điều 1. Phê duyệt quy hoạch các chức danh cán bộ...",
                doc_type_detected="QUY_HOACH",
            ),
            detail={
                "approval_agency": "Ban Tổ chức Trung ương",
                "na_term": "XVI",
                "period_from": 2026,
                "period_to": 2031,
            },
            groups=[
                {
                    "group_index": 1,
                    "title": "1- Quy hoạch chức danh Chủ tịch Hội đồng Dân tộc của Quốc hội",
                    "planned_unit": "Hội đồng Dân tộc của Quốc hội",
                    "planned_position": "Chủ tịch",
                    "person_count_declared": 1,
                }
            ],
            persons=[
                {
                    "stt": 1,
                    "group_index": 1,
                    "code": "1",
                    "is_collective": False,
                    "full_name": "Trần Thị Hoa Ry",
                    "gender": "Nữ",
                    "ethnicity": "Khmer",
                    "date_of_birth": "11/04/1976",
                    "current_position": "Phó Chủ tịch Hội đồng Dân tộc của Quốc hội khóa XV",
                    "position_name": "Phó Chủ tịch",
                    "work_organization_name": "Hội đồng Dân tộc của Quốc hội",
                    "raw_text": "Đồng chí Trần Thị Hoa Ry; (nữ, dân tộc: Khmer), sinh ngày 11/4/1976...",
                }
            ],
            warnings=[],
        )
