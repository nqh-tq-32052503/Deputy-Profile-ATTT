from typing import Any, List, Optional, Union
from pydantic import BaseModel, Field
from core.config import DocType
from core.schemas import ErrorItem, MetadataBase, PersonItemBase, ResultStatus, WarningItem


class QTCTMetadata(MetadataBase):
    doc_type_detected: str = "QTCT"


class QTCTDetail(BaseModel):
    process_type: str = Field(..., description="Loại quá trình công tác (VD: Điều động và bổ nhiệm)")
    start_date: str = Field(..., description="Thời gian bắt đầu giữ chức vụ mới DD/MM/YYYY")
    from_organization_name: str = Field(..., description="Đơn vị công tác trước khi điều động")
    work_organization_name: str = Field(..., description="Đơn vị mới đến công tác")
    position_name: str = Field(..., description="Chức danh/Chức vụ mới được bổ nhiệm")
    position_detail: Optional[str] = Field(None, description="Tên đầy đủ chức vụ + cơ quan mới bổ nhiệm")
    appointment_term_years: Optional[Union[int, float]] = Field(None, description="Thời hạn bổ nhiệm tính theo năm")
    allowance_name: Optional[str] = Field(None, description="Tên khoản phụ cấp kèm theo")
    allowance_factor: Optional[float] = Field(None, description="Hệ số phụ cấp kèm theo")


class QTCTPerson(PersonItemBase):
    stt: int = 1
    group_index: Optional[int] = None
    code: Optional[str] = None
    is_collective: bool = False
    full_name: str
    position_name: Optional[str] = Field(None, description="Chức vụ trước khi chuyển công tác")
    work_organization_name: Optional[str] = Field(None, description="Đơn vị trước khi chuyển công tác")
    raw_text: str


class QTCTResult(BaseModel):
    status: ResultStatus = ResultStatus.SUCCESS
    error: Optional[ErrorItem] = None
    doc_type: DocType = DocType.QTCT
    person_count_declared: int = 1
    tong_so_ca_nhan: int = 1
    metadata: QTCTMetadata
    detail: QTCTDetail
    groups: List[Any] = Field(default_factory=list)
    persons: List[QTCTPerson]
    warnings: List[WarningItem] = Field(default_factory=list)
