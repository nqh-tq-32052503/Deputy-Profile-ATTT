from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.config import DocType


class ProcessStatus(str, Enum):
    PROCESSING = "PROCESSING"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


class ResultStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class WarningItem(BaseModel):
    code: str
    message: str


class ErrorItem(BaseModel):
    code: str
    message: str


class MetadataBase(BaseModel):
    document_number: Optional[str] = Field(None, description="Số/ký hiệu văn bản")
    document_name: Optional[str] = Field(None, description="Trích yếu văn bản")
    issue_date: Optional[str] = Field(None, description="Ngày ký ban hành DD/MM/YYYY")
    issue_unit: Optional[str] = Field(None, description="Cơ quan ban hành")
    signer: Optional[str] = Field(None, description="Người ký văn bản")
    content: Optional[str] = Field(None, description="Toàn văn nội dung Điều 1")
    doc_type_detected: Optional[str] = Field(None, description="Loại văn bản nhận diện tự động")


class PersonItemBase(BaseModel):
    stt: int = Field(..., description="Số thứ tự danh sách")
    group_index: Optional[int] = Field(None, description="Chỉ số nhóm liên kết")
    code: Optional[str] = Field(None, description="Số thứ tự gốc")
    is_collective: bool = Field(False, description="True nếu là tập thể, False nếu là cá nhân")
    full_name: str = Field(..., description="Họ và tên hoặc tên tập thể")
    position_name: Optional[str] = Field(None, description="Chức vụ")
    work_organization_name: Optional[str] = Field(None, description="Đơn vị công tác")
    raw_text: str = Field(..., description="Đoạn văn đối chiếu nguyên văn")


class GroupItemBase(BaseModel):
    group_index: int
    title: str
    person_count_declared: Optional[int] = None


class ExtractionResult(BaseModel):
    status: ResultStatus = ResultStatus.SUCCESS
    error: Optional[ErrorItem] = None
    doc_type: DocType
    person_count_declared: Optional[int] = None
    tong_so_ca_nhan: int = 0
    metadata: MetadataBase
    detail: Dict[str, Any] = Field(default_factory=dict)
    groups: List[Any] = Field(default_factory=list)
    persons: List[Any] = Field(default_factory=list)
    warnings: List[WarningItem] = Field(default_factory=list)


# API Responses
class ExtractInitResponse(BaseModel):
    request_id: str
    status: ProcessStatus
    created_at: Optional[str] = None
    is_cached: Optional[bool] = None
    result: Optional[ExtractionResult] = None


class ExtractPollResponse(BaseModel):
    request_id: str
    status: ProcessStatus
    result: Optional[ExtractionResult] = None
    error: Optional[ErrorItem] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
