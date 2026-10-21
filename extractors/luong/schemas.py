from typing import Any, List, Optional
from pydantic import BaseModel, Field
from core.config import DocType
from core.schemas import ErrorItem, MetadataBase, PersonItemBase, ResultStatus, WarningItem


class LuongMetadata(MetadataBase):
    doc_type_detected: str = "LUONG"


class LuongDetail(BaseModel):
    raise_salary_reason: str = Field(..., description="Lý do nâng lương (VD: Nâng bậc lương thường xuyên)")
    position_wage: str = Field(..., description="Ngạch / Chức danh nghề nghiệp (VD: Giảng viên cao cấp (hạng I))")
    position_wage_code: Optional[str] = Field(None, description="Mã ngạch công chức (VD: V.07.01.01)")
    old_step: Optional[int] = Field(None, description="Bậc lương cũ trước khi nâng (VD: 3)")
    old_factor: Optional[float] = Field(None, description="Hệ số lương cũ trước khi nâng (VD: 6.92)")
    salary_step: Optional[int] = Field(None, description="Bậc lương mới được nâng lên (VD: 4)")
    salary_factor: Optional[float] = Field(None, description="Hệ số lương mới được nâng lên (VD: 7.28)")
    start_date: Optional[str] = Field(None, description="Mốc hưởng lương mới DD/MM/YYYY (VD: 01/06/2025)")
    review_date: Optional[str] = Field(None, description="Mốc tính nâng lương lần sau DD/MM/YYYY (VD: 01/06/2025)")
    percentage: Optional[float] = Field(None, description="Tỷ lệ hưởng nếu có (VD: vượt khung, tập sự)")


class LuongPerson(PersonItemBase):
    stt: int = 1
    group_index: Optional[int] = None
    code: Optional[str] = None
    is_collective: bool = False
    full_name: str
    position_name: Optional[str] = Field(None, description="Chức vụ tại đơn vị nếu có")
    work_organization_name: Optional[str] = Field(None, description="Đơn vị công tác (VD: Vụ Hợp tác quốc tế)")
    raw_text: str


class LuongResult(BaseModel):
    status: ResultStatus = ResultStatus.SUCCESS
    error: Optional[ErrorItem] = None
    doc_type: DocType = DocType.LUONG
    person_count_declared: int = 1
    tong_so_ca_nhan: int = 1
    metadata: LuongMetadata
    detail: LuongDetail
    groups: List[Any] = Field(default_factory=list)
    persons: List[LuongPerson]
    warnings: List[WarningItem] = Field(default_factory=list)
