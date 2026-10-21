from typing import Any, List, Optional
from pydantic import BaseModel, Field
from core.config import DocType
from core.schemas import ErrorItem, GroupItemBase, MetadataBase, PersonItemBase, ResultStatus, WarningItem


class KhenThuongMetadata(MetadataBase):
    doc_type_detected: str = "KHEN_THUONG"


class KhenThuongDetail(BaseModel):
    type: int = Field(2, description="Phân loại: 2 = Khen thưởng")
    year: int = Field(..., description="Năm khen thưởng")
    reward_level: str = Field(..., description="Cấp khen thưởng (VD: Bằng khen Ủy ban Thường vụ Quốc hội)")
    content: str = Field(..., description="Nội dung khen thưởng chung Điều 1")


class KhenThuongGroup(GroupItemBase):
    group_index: int = Field(..., description="STT nhóm, bắt đầu từ 1")
    title: str = Field(..., description="Nguyên văn tiêu đề mục nhóm")
    person_count_declared: int = Field(..., description="Số lượng cá nhân tuyên bố trong tiêu đề mục")
    reward_type: str = Field(..., description="Hình thức khen thưởng")
    accomplishment: str = Field(..., description="Thành tích đạt được")


class KhenThuongPerson(PersonItemBase):
    stt: int = Field(..., description="STT toàn bộ danh sách tăng dần từ 1")
    group_index: int = Field(..., description="Thuộc nhóm nào trong mảng groups")
    code: Optional[str] = Field(None, description="Số thứ tự gốc ghi trong dấu ngoặc đơn")
    is_collective: bool = Field(False, description="false nếu là cá nhân, true nếu là tập thể")
    full_name: str = Field(..., description="Họ tên cá nhân (đã lọc danh xưng, cấp hàm)")
    position_name: Optional[str] = Field(None, description="Chức vụ chính quyền/Quốc hội")
    work_organization_name: Optional[str] = Field(None, description="Cơ quan/đơn vị công tác chính tương ứng chức vụ")
    award_type: str = Field("TANG", description="Loại hình thức: TANG hoặc TRUY_TANG")
    raw_text: str = Field(..., description="Nguyên văn dòng cá nhân trên văn bản")


class KhenThuongResult(BaseModel):
    status: ResultStatus = ResultStatus.SUCCESS
    error: Optional[ErrorItem] = None
    doc_type: DocType = DocType.KHEN_THUONG
    person_count_declared: int = 0
    tong_so_ca_nhan: int = 0
    metadata: KhenThuongMetadata
    detail: KhenThuongDetail
    groups: List[KhenThuongGroup] = Field(default_factory=list)
    persons: List[KhenThuongPerson] = Field(default_factory=list)
    warnings: List[WarningItem] = Field(default_factory=list)
