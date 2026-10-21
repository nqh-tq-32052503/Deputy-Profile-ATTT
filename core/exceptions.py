from typing import Any, Optional


class DeputyProfilingException(Exception):
    """
    Exception cơ sở cho toàn bộ hệ thống Deputy Profiling AI Service.
    Mọi exception tùy biến đều kế thừa từ class này.
    """

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"[{self.code}] {self.message} | Details: {self.details}"
        return f"[{self.code}] {self.message}"


# ==============================================================================
# OCR SERVICE EXCEPTIONS
# ==============================================================================


class OCRServiceException(DeputyProfilingException):
    """Lỗi chung phát sinh từ dịch vụ OCR."""

    def __init__(
        self,
        message: str,
        code: str = "OCR_SERVICE_ERROR",
        status_code: int = 502,
        details: Optional[Any] = None,
    ):
        super().__init__(message, code=code, status_code=status_code, details=details)


class OCRConnectionError(OCRServiceException):
    """Không thể kết nối đến máy chủ dịch vụ OCR (Connection refused, DNS error, network unreachable)."""

    def __init__(
        self,
        message: str = "Không thể kết nối đến dịch vụ OCR",
        details: Optional[Any] = None,
    ):
        super().__init__(message, code="OCR_CONNECTION_ERROR", status_code=503, details=details)


class OCRTimeoutError(OCRServiceException):
    """Quá thời gian chờ phản hồi từ dịch vụ OCR (Request timeout)."""

    def __init__(
        self,
        message: str = "Quá thời gian chờ phản hồi từ dịch vụ OCR",
        details: Optional[Any] = None,
    ):
        super().__init__(message, code="OCR_TIMEOUT_ERROR", status_code=504, details=details)


class OCRHTTPError(OCRServiceException):
    """Dịch vụ OCR phản hồi với mã lỗi HTTP không thành công (4xx/5xx)."""

    def __init__(
        self,
        message: str,
        http_status: int = 500,
        details: Optional[Any] = None,
    ):
        super().__init__(message, code="OCR_HTTP_ERROR", status_code=http_status, details=details)


class OCRResponseParseError(OCRServiceException):
    """Không thể phân tích cú pháp dữ liệu JSON từ dịch vụ OCR."""

    def __init__(
        self,
        message: str = "Phản hồi từ OCR Service không phải là định dạng JSON hợp lệ",
        details: Optional[Any] = None,
    ):
        super().__init__(message, code="OCR_PARSE_ERROR", status_code=502, details=details)


class OCRUnreadableContentError(OCRServiceException):
    """Bản scan quá mờ, trang trắng hoặc rỗng không thể đọc được nội dung (UNREADABLE_CONTENT)."""

    def __init__(
        self,
        message: str = "Bản scan quá mờ, rỗng hoặc không thể nhận dạng ký tự",
        details: Optional[Any] = None,
    ):
        super().__init__(message, code="UNREADABLE_CONTENT", status_code=422, details=details)


# ==============================================================================
# LLM SERVICE EXCEPTIONS
# ==============================================================================


class LLMServiceException(DeputyProfilingException):
    """Lỗi chung phát sinh từ dịch vụ LLM."""

    def __init__(
        self,
        message: str,
        code: str = "LLM_SERVICE_ERROR",
        status_code: int = 502,
        details: Optional[Any] = None,
    ):
        super().__init__(message, code=code, status_code=status_code, details=details)


class LLMConnectionError(LLMServiceException):
    """Không thể kết nối đến máy chủ mô hình ngôn ngữ lớn (LLM Host/Gateway)."""

    def __init__(
        self,
        message: str = "Không thể kết nối đến dịch vụ LLM",
        details: Optional[Any] = None,
    ):
        super().__init__(message, code="LLM_CONNECTION_ERROR", status_code=503, details=details)


class LLMTimeoutError(LLMServiceException):
    """Quá thời gian chờ phản hồi từ dịch vụ LLM."""

    def __init__(
        self,
        message: str = "Quá thời gian chờ phản hồi từ dịch vụ LLM",
        details: Optional[Any] = None,
    ):
        super().__init__(message, code="LLM_TIMEOUT_ERROR", status_code=504, details=details)


class LLMHTTPError(LLMServiceException):
    """Dịch vụ LLM phản hồi với mã lỗi HTTP không thành công (4xx/5xx)."""

    def __init__(
        self,
        message: str,
        http_status: int = 500,
        details: Optional[Any] = None,
    ):
        super().__init__(message, code="LLM_HTTP_ERROR", status_code=http_status, details=details)


class LLMResponseParseError(LLMServiceException):
    """Không thể trích xuất hoặc phân tích cấu trúc JSON từ câu trả lời của LLM."""

    def __init__(
        self,
        message: str = "Không thể phân tích cú pháp JSON từ kết quả trả về của LLM",
        raw_text: Optional[str] = None,
        details: Optional[Any] = None,
    ):
        info = {"raw_text": raw_text} if raw_text else {}
        if details and isinstance(details, dict):
            info.update(details)
        super().__init__(message, code="LLM_PARSE_ERROR", status_code=502, details=info)


# ==============================================================================
# EXTRACTION EXCEPTIONS
# ==============================================================================


class ExtractionException(DeputyProfilingException):
    """Lỗi phát sinh trong quá trình trích xuất thông tin văn bản."""

    def __init__(
        self,
        message: str,
        code: str = "EXTRACTION_ERROR",
        status_code: int = 400,
        details: Optional[Any] = None,
    ):
        super().__init__(message, code=code, status_code=status_code, details=details)


class UnsupportedDocumentError(ExtractionException):
    """Văn bản không thuộc phạm vi 7 loại văn bản được hỗ trợ."""

    def __init__(
        self,
        message: str = "Văn bản không thuộc phạm vi 7 loại quyết định/nghị quyết được hỗ trợ",
        details: Optional[Any] = None,
    ):
        super().__init__(message, code="UNSUPPORTED_DOCUMENT", status_code=400, details=details)


class ExtractorNotFoundError(ExtractionException):
    """Không tìm thấy bộ trích xuất tương ứng với mã doc_type."""

    def __init__(self, doc_type: str):
        super().__init__(
            f"Không hỗ trợ hoặc chưa đăng ký bộ trích xuất cho doc_type: '{doc_type}'",
            code="EXTRACTOR_NOT_FOUND",
            status_code=400,
        )
