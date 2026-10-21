"""
Module phân loại loại văn bản (doc_type) bằng LLM cho Hệ thống Hồ sơ Đại biểu (HSĐB).

Căn cứ theo tài liệu đặc tả API v5.0 (API-trich-xuat-vbtl-hsdb-v5.md):
- Mục 1.1: Phạm vi định nghĩa 7 loại văn bản nghiệp vụ (QTCT, LUONG, PHU_CAP, THI_DUA, KHEN_THUONG, KY_NIEM_CHUONG, QUY_HOACH).
- Mục 1.5.3: Mã cảnh báo nghiệp vụ DOC_TYPE_MISMATCH nếu loại văn bản AI tự động nhận diện
  (`metadata.doc_type_detected`) khác với tham số `doc_type` gửi lên từ form.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from core.config import DocType
from core.schemas import ExtractionResult, WarningItem
from services.llm_service import LLMService

logger = logging.getLogger(__name__)

TARGET_ONE_PERSON = "1 cá nhân"

# Bảng mô tả chi tiết 7 loại văn bản theo Mục 1.1 và Phần 3 của tài liệu API
DOC_TYPE_DESCRIPTIONS: Dict[str, Dict[str, Any]] = {
    "QTCT": {
        "ten_nghiep_vu": "Quá trình công tác (Điều động, bổ nhiệm, luân chuyển...)",
        "form_dich": "Thêm mới quá trình công tác",
        "so_luong_doi_tuong": TARGET_ONE_PERSON,
        "ho_so_mau": "1. QTCT_danh_dau.pdf (QĐ 1122/QĐ-VPQH)",
        "mo_ta": (
            "Quyết định điều động, bổ nhiệm, luân chuyển, từ chức hoặc thôi giữ chức vụ cho 01 cá nhân. "
            "Nội dung Điều 1 chỉ định đích danh 01 cá nhân chuyển từ đơn vị/chức vụ cũ sang giữ chức vụ/đơn vị mới, "
            "thời hạn bổ nhiệm (nếu có)."
        ),
        "dau_hieu": [
            "điều động và bổ nhiệm",
            "luân chuyển cán bộ",
            "thôi giữ chức vụ",
            "bổ nhiệm lại",
            "tiếp nhận và bổ nhiệm",
            "từ chức",
            "miễn nhiệm",
        ],
    },
    "LUONG": {
        "ten_nghiep_vu": "Nâng bậc lương (Thường xuyên / Trước hạn)",
        "form_dich": "Thêm mới quá trình lương",
        "so_luong_doi_tuong": TARGET_ONE_PERSON,
        "ho_so_mau": "2. LUONG_danh_dau.pdf (QĐ 3110-QĐ/HVCTQG)",
        "mo_ta": (
            "Quyết định nâng bậc lương thường xuyên hoặc nâng bậc lương trước thời hạn cho 01 cá nhân. "
            "Nội dung Điều 1 nâng ngạch/bậc/hệ số lương cho 01 cá nhân, ghi rõ chức danh nghề nghiệp/mã ngạch, "
            "từ bậc/hệ số cũ lên bậc/hệ số mới, ngày hưởng và mốc tính nâng lương lần sau, tỷ lệ vượt khung (nếu có)."
        ),
        "dau_hieu": [
            "nâng bậc lương",
            "nâng bậc lương thường xuyên",
            "nâng bậc lương trước thời hạn",
            "bậc lương",
            "hệ số lương",
            "ngạch công chức/viên chức",
        ],
    },
    "PHU_CAP": {
        "ten_nghiep_vu": "Quyết định phụ cấp (Chức vụ, kiêm nhiệm, trách nhiệm...)",
        "form_dich": "Thêm mới quá trình phụ cấp",
        "so_luong_doi_tuong": TARGET_ONE_PERSON,
        "ho_so_mau": "Mẫu nghiệp vụ chuẩn",
        "mo_ta": (
            "Quyết định hưởng hoặc chi trả chế độ phụ cấp (phụ cấp chức vụ lãnh đạo, phụ cấp trách nhiệm công tác, "
            "phụ cấp kiêm nhiệm, phụ cấp đặc thù nghề, phụ cấp độc hại, phụ cấp khu vực...) cho 01 cá nhân. "
            "Xác định mức hưởng bằng hệ số phụ cấp (vd 0.5, 0.8), số tiền hoặc tỷ lệ %. Khác với LUONG (nâng bậc ngạch lương)."
        ),
        "dau_hieu": [
            "phụ cấp chức vụ",
            "phụ cấp trách nhiệm công tác",
            "phụ cấp kiêm nhiệm",
            "hệ số phụ cấp",
            "chi trả phụ cấp",
            "hưởng phụ cấp",
        ],
    },
    "THI_DUA": {
        "ten_nghiep_vu": "Công nhận danh hiệu thi đua (Cá nhân / Tập thể)",
        "form_dich": "Thi đua – Khen thưởng (type = 1)",
        "so_luong_doi_tuong": "N đối tượng (cá nhân và/hoặc tập thể)",
        "ho_so_mau": "Mẫu nghiệp vụ chuẩn",
        "mo_ta": (
            "Quyết định công nhận danh hiệu thi đua cho nhiều cá nhân và/hoặc tập thể theo Luật Thi đua, khen thưởng. "
            "Các danh hiệu thi đua tiêu biểu gồm: Chiến sĩ thi đua toàn quốc, Chiến sĩ thi đua cấp Bộ/ngành, "
            "Chiến sĩ thi đua cơ sở, Cờ thi đua, Tập thể lao động xuất sắc, Tập thể lao động tiên tiến."
        ),
        "dau_hieu": [
            "công nhận danh hiệu thi đua",
            "chiến sĩ thi đua toàn quốc",
            "chiến sĩ thi đua cơ sở",
            "cờ thi đua",
            "tập thể lao động xuất sắc",
            "lao động tiên tiến",
        ],
    },
    "KHEN_THUONG": {
        "ten_nghiep_vu": "Khen thưởng (Bằng khen, Huân chương, Huy chương...)",
        "form_dich": "Thi đua – Khen thưởng (type = 2)",
        "so_luong_doi_tuong": "N đối tượng (cá nhân và/hoặc tập thể)",
        "ho_so_mau": "5. KHEN_THUONG_NQ1330_danh_dau.pdf",
        "mo_ta": (
            "Nghị quyết hoặc Quyết định tặng thưởng hình thức khen thưởng (Bằng khen của Ủy ban Thường vụ Quốc hội, "
            "Bằng khen Thủ tướng Chính phủ, Huân chương, Huy chương, Giấy khen...) cho nhiều cá nhân và/hoặc tập thể vì thành tích xuất sắc. "
            "Danh sách thường phân chia theo nhóm hình thức khen thưởng hoặc đợt/giai đoạn thành tích. "
            "(Lưu ý: Nếu tặng riêng Kỷ niệm chương Vì sự nghiệp Quốc hội VN thì xếp vào KY_NIEM_CHUONG)."
        ),
        "dau_hieu": [
            "tặng bằng khen",
            "bằng khen của ủy ban thường vụ quốc hội",
            "bằng khen của thủ tướng",
            "huân chương",
            "huy chương",
            "thành tích xuất sắc trong công tác",
        ],
    },
    "KY_NIEM_CHUONG": {
        "ten_nghiep_vu": "Tặng Kỷ niệm chương \"Vì sự nghiệp Quốc hội VN\"",
        "form_dich": "Quản lý kỷ niệm chương",
        "so_luong_doi_tuong": "N cá nhân",
        "ho_so_mau": "6. KY_NIEM_CHUONG_NQ1783_danh_dau.pdf + DS kèm",
        "mo_ta": (
            "Nghị quyết tặng Kỷ niệm chương \"Vì sự nghiệp Quốc hội Việt Nam\" (do Ủy ban Thường vụ Quốc hội "
            "hoặc Văn phòng Quốc hội ban hành) cho nhiều cá nhân đã có đóng góp vào quá trình phát triển của Quốc hội. "
            "Văn bản thường kèm danh sách chia theo 3 khối: Khối I (Đại biểu Quốc hội), Khối II (Lãnh đạo Tỉnh/Thành phố), "
            "Khối III (Công chức/người lao động Văn phòng Đoàn ĐBQH & HĐND)."
        ),
        "dau_hieu": [
            "kỷ niệm chương vì sự nghiệp quốc hội việt nam",
            "vì sự nghiệp quốc hội",
            "đóng góp vào quá trình phát triển của quốc hội",
        ],
    },
    "QUY_HOACH": {
        "ten_nghiep_vu": "Phê duyệt quy hoạch chức danh cán bộ",
        "form_dich": "Thêm mới Quyết định Quy hoạch",
        "so_luong_doi_tuong": "N cá nhân",
        "ho_so_mau": "7. QUY_HOACH_danh_dau.pdf (QĐ 2031-QĐ/BTCTW)",
        "mo_ta": (
            "Quyết định phê duyệt hoặc rà soát, bổ sung quy hoạch cán bộ vào các chức danh lãnh đạo, quản lý "
            "(Chủ tịch Hội đồng Dân tộc, Chủ nhiệm các Ủy ban của Quốc hội, Thứ trưởng...) theo nhiệm kỳ cụ thể "
            "(vd nhiệm kỳ 2026-2031). Danh sách ghi rõ thông tin nhân thân: giới tính, dân tộc, ngày tháng năm sinh, "
            "chức vụ đơn vị công tác hiện tại."
        ),
        "dau_hieu": [
            "phê duyệt quy hoạch",
            "rà soát, bổ sung quy hoạch",
            "quy hoạch các chức danh",
            "nhiệm kỳ",
            "dân tộc",
            "ngày tháng năm sinh",
        ],
    },
}


def build_classification_system_prompt() -> str:
    """
    Xây dựng system prompt chi tiết dựa trên mô tả của từng loại văn bản (7 loại)
    ở Mục 1.1 và Phần 3 của tài liệu API-trich-xuat-vbtl-hsdb-v5.md.
    """
    lines = [
        "Bạn là chuyên gia phân loại văn bản hành chính Việt Nam cho Hệ thống Hồ sơ Đại biểu (HSĐB).",
        "Nhiệm vụ của bạn là đọc và phân tích nội dung văn bản (đặc biệt là tiêu đề, trích yếu, cơ quan ban hành, căn cứ pháp lý và nội dung Điều 1) để xác định chính xác văn bản thuộc loại nào trong 7 loại văn bản nghiệp vụ sau:\n",
    ]

    for idx, (code, info) in enumerate(DOC_TYPE_DESCRIPTIONS.items(), 1):
        lines.append(f"{idx}. `{code}` — {info['ten_nghiep_vu']}:")
        lines.append(f"   - Form đích trên HSĐB: {info['form_dich']}")
        lines.append(f"   - Số lượng đối tượng: {info['so_luong_doi_tuong']}")
        lines.append(f"   - Hồ sơ mẫu đính kèm: {info['ho_so_mau']}")
        lines.append(f"   - Mô tả nghiệp vụ & Quy tắc: {info['mo_ta']}")
        lines.append(f"   - Dấu hiệu đặc trưng: {', '.join(info['dau_hieu'])}\n")

    lines.append(
        "8. `UNKNOWN` — Không xác định:\n"
        "   - Áp dụng khi nội dung văn bản không thuộc bất kỳ loại nào trong 7 loại trên "
        "(ví dụ: công văn trao đổi thông thường, tờ trình, thông báo họp, quyết định kỷ luật, hợp đồng kinh tế...).\n"
    )

    lines.append(
        "QUY TẮC PHÂN LOẠI QUAN TRỌNG ĐỂ TRÁNH NHẦM LẪN:\n"
        "- `LUONG` vs `PHU_CAP`: `LUONG` thay đổi bậc/hệ số ngạch lương chính; `PHU_CAP` là quyết định hưởng chế độ phụ cấp (chức vụ, trách nhiệm, kiêm nhiệm) tính bằng hệ số riêng hoặc số tiền.\n"
        "- `THI_DUA` vs `KHEN_THUONG`: `THI_DUA` công nhận 'Danh hiệu thi đua' (Chiến sĩ thi đua, Cờ thi đua, Tập thể lao động xuất sắc...); `KHEN_THUONG` là tặng thưởng 'Hình thức khen thưởng' (Bằng khen, Huân chương, Huy chương, Giấy khen...).\n"
        "- `KHEN_THUONG` vs `KY_NIEM_CHUONG`: Nếu văn bản tặng riêng Kỷ niệm chương \"Vì sự nghiệp Quốc hội Việt Nam\" thì PHẢI phân loại vào `KY_NIEM_CHUONG`, không chọn `KHEN_THUONG`.\n"
        "- `QTCT` vs `QUY_HOACH`: `QTCT` là quyết định điều động/bổ nhiệm giữ chức vụ có hiệu lực ngay cho 01 người; `QUY_HOACH` là phê duyệt dự nguồn cán bộ cho nhiệm kỳ tương lai (vd 2026-2031) cho nhiều người, có ghi ngày sinh/dân tộc.\n"
    )

    lines.append(
        "YÊU CẦU ĐẦU RA:\n"
        "Chỉ trả về DUY NHẤT một chuỗi JSON hợp lệ với định dạng sau, không kèm bất kỳ giải thích nào bên ngoài JSON:\n"
        "{\n"
        '  "doc_type": "QTCT" | "LUONG" | "PHU_CAP" | "THI_DUA" | "KHEN_THUONG" | "KY_NIEM_CHUONG" | "QUY_HOACH" | "UNKNOWN",\n'
        '  "confidence": <float từ 0.0 đến 1.0>,\n'
        '  "reason": "<Giải thích ngắn gọn 1-2 câu căn cứ vào trích yếu và nội dung Điều 1>"\n'
        "}"
    )

    return "\n".join(lines)


DOC_CLASSIFIER_SYSTEM_PROMPT = build_classification_system_prompt()


class DocClassificationResult(BaseModel):
    """Kết quả phân loại văn bản và đối soát với tham số doc_type."""
    doc_type_detected: str = Field(
        ...,
        description="Loại văn bản detect được (QTCT, LUONG, PHU_CAP, THI_DUA, KHEN_THUONG, KY_NIEM_CHUONG, QUY_HOACH hoặc UNKNOWN)",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Độ tin cậy của kết quả phân loại (0.0 đến 1.0)",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Lý do phân loại từ LLM",
    )
    is_match: Optional[bool] = Field(
        default=None,
        description="True nếu doc_type_detected khớp với param doc_type, False nếu khác",
    )
    warning: Optional[WarningItem] = Field(
        default=None,
        description="Cảnh báo DOC_TYPE_MISMATCH theo mục 1.5.3 nếu khác loại",
    )


def extract_classification_context(content: str, max_chars: int = 4000) -> str:
    """
    Trích xuất phần nội dung quan trọng nhất của văn bản (tiêu đề, trích yếu,
    căn cứ ban hành và các điều khoản đầu tiên như Điều 1, Điều 2) để gửi tới LLM.
    Giúp tối ưu hóa tốc độ và tiết kiệm chi phí token cho các văn bản dài hàng chục trang.
    """
    if not content:
        return ""
    text = content.strip()
    if len(text) <= max_chars:
        return text

    # Cố gắng cắt tại hết Điều 2 hoặc Điều 3 nếu nằm trong phạm vi cho phép
    for marker in ["Điều 3.", "Điều 3:", "Điều 2.", "Điều 2:", "Nơi nhận:"]:
        idx = text.find(marker)
        if idx != -1 and 500 <= idx <= max_chars + 1000:
            return text[: idx + len(marker) + 200].strip()

    return text[:max_chars].strip()


def check_doc_type_mismatch(
    detected_doc_type: str,
    param_doc_type: Union[DocType, str],
) -> Optional[WarningItem]:
    """
    Đối chiếu kết quả phân loại với param doc_type của API.
    Nếu khác nhau, trả về WarningItem với mã DOC_TYPE_MISMATCH theo mục 1.5.3:
    `- DOC_TYPE_MISMATCH: Loại văn bản AI tự động nhận diện (metadata.doc_type_detected) khác với tham số doc_type gửi lên từ form.`

    Nếu trùng khớp, trả về None.
    """
    param_val = param_doc_type.value if hasattr(param_doc_type, "value") else str(param_doc_type)
    detected_norm = (detected_doc_type or "").strip().upper()
    param_norm = (param_val or "").strip().upper()

    if detected_norm != param_norm:
        logger.warning(
            f"[DOC_TYPE_MISMATCH] Phát hiện loại văn bản không khớp: "
            f"AI nhận diện='{detected_norm}', tham số API='{param_norm}'."
        )
        return WarningItem(
            code="DOC_TYPE_MISMATCH",
            message=(
                f"Loại văn bản AI tự động nhận diện ({detected_norm}) "
                f"khác với tham số doc_type ({param_norm}) gửi lên từ form."
            ),
        )
    return None


async def aclassify_doc_type(
    content: str,
    llm_service: Optional[LLMService] = None,
    max_chars: int = 4000,
) -> DocClassificationResult:
    """
    Hàm bất đồng bộ (async) sử dụng LLM để phân loại nội dung văn bản thành 1 trong 7 loại
    (hoặc UNKNOWN) dựa trên system prompt mô tả chi tiết của từng loại văn bản.

    :param content: Nội dung văn bản (markdown hoặc plain text trích xuất từ OCR).
    :param llm_service: Instance LLMService (nếu None sẽ tự tạo instance mặc định).
    :param max_chars: Số ký tự tối đa đưa vào LLM để phân loại (mặc định 4000 ký tự đầu).
    :return: DocClassificationResult chứa doc_type_detected, confidence, reason.
    """
    service = llm_service or LLMService()
    trimmed_content = extract_classification_context(content, max_chars=max_chars)

    try:
        data = await service.ask_json_async(
            system_prompt=DOC_CLASSIFIER_SYSTEM_PROMPT,
            content=trimmed_content,
        )
    except Exception as e:
        logger.exception(f"Lỗi khi gọi LLM phân loại văn bản: {e}")
        return DocClassificationResult(
            doc_type_detected="UNKNOWN",
            confidence=0.0,
            reason=f"Lỗi giao tiếp LLM: {str(e)}",
        )

    if not isinstance(data, dict):
        logger.warning(f"Phản hồi từ LLM không phải dictionary: {data}")
        return DocClassificationResult(
            doc_type_detected="UNKNOWN",
            confidence=0.0,
            reason="Phản hồi LLM không đúng định dạng JSON object",
        )

    raw_doc_type = str(data.get("doc_type", "")).strip().upper()
    valid_doc_types = {e.value for e in DocType}

    # Chuẩn hóa nếu LLM trả về có khoảng trắng hoặc ký tự đặc biệt
    matched_type = "UNKNOWN"
    if raw_doc_type in valid_doc_types:
        matched_type = raw_doc_type
    else:
        for v in valid_doc_types:
            if v in raw_doc_type:
                matched_type = v
                break

    confidence = data.get("confidence", 1.0)
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = 1.0

    reason = data.get("reason")
    if reason:
        reason = str(reason).strip()

    logger.info(
        f"Phân loại văn bản thành công: doc_type='{matched_type}', "
        f"confidence={confidence:.2f}, reason='{reason}'"
    )

    return DocClassificationResult(
        doc_type_detected=matched_type,
        confidence=confidence,
        reason=reason,
    )


def classify_doc_type(
    content: str,
    llm_service: Optional[LLMService] = None,
    max_chars: int = 4000,
) -> DocClassificationResult:
    """
    Bản đồng bộ (sync) của hàm aclassify_doc_type.
    """
    service = llm_service or LLMService()
    trimmed_content = extract_classification_context(content, max_chars=max_chars)

    try:
        data = service.ask_json(
            system_prompt=DOC_CLASSIFIER_SYSTEM_PROMPT,
            content=trimmed_content,
        )
    except Exception as e:
        logger.exception(f"Lỗi khi gọi sync LLM phân loại văn bản: {e}")
        return DocClassificationResult(
            doc_type_detected="UNKNOWN",
            confidence=0.0,
            reason=f"Lỗi giao tiếp LLM: {str(e)}",
        )

    if not isinstance(data, dict):
        return DocClassificationResult(
            doc_type_detected="UNKNOWN",
            confidence=0.0,
            reason="Phản hồi LLM không đúng định dạng JSON object",
        )

    raw_doc_type = str(data.get("doc_type", "")).strip().upper()
    valid_doc_types = {e.value for e in DocType}

    matched_type = "UNKNOWN"
    if raw_doc_type in valid_doc_types:
        matched_type = raw_doc_type
    else:
        for v in valid_doc_types:
            if v in raw_doc_type:
                matched_type = v
                break

    confidence = data.get("confidence", 1.0)
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = 1.0

    reason = data.get("reason")
    if reason:
        reason = str(reason).strip()

    return DocClassificationResult(
        doc_type_detected=matched_type,
        confidence=confidence,
        reason=reason,
    )


async def aclassify_and_verify_doc_type(
    content: str,
    param_doc_type: Union[DocType, str],
    llm_service: Optional[LLMService] = None,
    max_chars: int = 4000,
) -> DocClassificationResult:
    """
    Hàm tổng hợp:
    1. Sử dụng LLM phân loại nội dung văn bản.
    2. Đối chiếu kết quả phân loại với tham số doc_type từ API param.
    3. Nếu khác nhau, tự động bổ sung cảnh báo DOC_TYPE_MISMATCH theo mục 1.5.3.
    """
    result = await aclassify_doc_type(content, llm_service=llm_service, max_chars=max_chars)
    warning = check_doc_type_mismatch(result.doc_type_detected, param_doc_type)
    result.is_match = (warning is None)
    result.warning = warning
    return result


def classify_and_verify_doc_type(
    content: str,
    param_doc_type: Union[DocType, str],
    llm_service: Optional[LLMService] = None,
    max_chars: int = 4000,
) -> DocClassificationResult:
    """
    Bản đồng bộ (sync) của hàm aclassify_and_verify_doc_type.
    """
    result = classify_doc_type(content, llm_service=llm_service, max_chars=max_chars)
    warning = check_doc_type_mismatch(result.doc_type_detected, param_doc_type)
    result.is_match = (warning is None)
    result.warning = warning
    return result


def _update_result_metadata_doc_type(extraction_result: Any, detected_doc_type: str) -> None:
    """Cập nhật doc_type_detected vào metadata của extraction_result."""
    if hasattr(extraction_result, "metadata"):
        metadata = getattr(extraction_result, "metadata")
        if hasattr(metadata, "doc_type_detected"):
            metadata.doc_type_detected = detected_doc_type
        elif isinstance(metadata, dict):
            metadata["doc_type_detected"] = detected_doc_type
    elif isinstance(extraction_result, dict):
        metadata = extraction_result.get("metadata")
        if isinstance(metadata, dict):
            metadata["doc_type_detected"] = detected_doc_type


def _has_doc_type_mismatch(warnings: list) -> bool:
    for w in warnings:
        code = w.get("code") if isinstance(w, dict) else getattr(w, "code", None)
        if code == "DOC_TYPE_MISMATCH":
            return True
    return False


def _dump_warning(warning: WarningItem) -> Any:
    if hasattr(warning, "model_dump"):
        return warning.model_dump()
    if hasattr(warning, "dict"):
        return warning.dict()
    return warning


def _append_doc_type_mismatch_warning(extraction_result: Any, warning: WarningItem) -> None:
    """Bổ sung warning DOC_TYPE_MISMATCH vào danh sách warnings nếu chưa tồn tại."""
    if hasattr(extraction_result, "warnings") and isinstance(extraction_result.warnings, list):
        if not _has_doc_type_mismatch(extraction_result.warnings):
            extraction_result.warnings.append(warning)
        return

    if isinstance(extraction_result, dict):
        warnings_list = extraction_result.get("warnings")
        if isinstance(warnings_list, list) and not _has_doc_type_mismatch(warnings_list):
            warnings_list.append(_dump_warning(warning))


def apply_doc_type_verification(
    extraction_result: Union[ExtractionResult, Dict[str, Any], Any],
    detected_doc_type: str,
    param_doc_type: Union[DocType, str],
) -> Optional[WarningItem]:
    """
    Gắn kết quả phân loại vào extraction_result:
    1. Cập nhật `metadata.doc_type_detected = detected_doc_type`.
    2. Nếu `detected_doc_type != param_doc_type`, bổ sung WarningItem (DOC_TYPE_MISMATCH)
       vào danh sách `warnings` của `extraction_result`.

    Hỗ trợ cả object Pydantic (ExtractionResult) và dictionary.
    """
    warning = check_doc_type_mismatch(detected_doc_type, param_doc_type)
    _update_result_metadata_doc_type(extraction_result, detected_doc_type)
    if warning:
        _append_doc_type_mismatch_warning(extraction_result, warning)
    return warning
