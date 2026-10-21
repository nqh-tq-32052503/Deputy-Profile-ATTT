"""
Unit tests cho module phân loại loại văn bản (doc_classifier) và cảnh báo DOC_TYPE_MISMATCH.
Căn cứ theo Mục 1.1 và Mục 1.5.3 của tài liệu API-trich-xuat-vbtl-hsdb-v5.md.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest

from core.config import DocType
from core.schemas import ExtractionResult, MetadataBase, WarningItem
from services.doc_classifier import (
    DOC_CLASSIFIER_SYSTEM_PROMPT,
    DOC_TYPE_DESCRIPTIONS,
    DocClassificationResult,
    aclassify_and_verify_doc_type,
    aclassify_doc_type,
    apply_doc_type_verification,
    check_doc_type_mismatch,
    classify_and_verify_doc_type,
    classify_doc_type,
    extract_classification_context,
)
from tests.assertions import check


class TestDocTypeDefinitions:
    """Kiểm tra tính đầy đủ của định nghĩa 7 loại văn bản theo Mục 1.1."""

    def test_all_7_doc_types_defined(self):
        expected_types = {
            "QTCT",
            "LUONG",
            "PHU_CAP",
            "THI_DUA",
            "KHEN_THUONG",
            "KY_NIEM_CHUONG",
            "QUY_HOACH",
        }
        check(set(DOC_TYPE_DESCRIPTIONS.keys()) == expected_types)

    def test_required_metadata_in_each_definition(self):
        for doc_type, info in DOC_TYPE_DESCRIPTIONS.items():
            check("ten_nghiep_vu" in info)
            check("form_dich" in info)
            check("so_luong_doi_tuong" in info)
            check("ho_so_mau" in info)
            check("mo_ta" in info)
            check("dau_hieu" in info)
            check(len(info["dau_hieu"]) > 0)

    def test_system_prompt_contains_all_7_types(self):
        for doc_type in DOC_TYPE_DESCRIPTIONS.keys():
            check(doc_type in DOC_CLASSIFIER_SYSTEM_PROMPT)
        check("UNKNOWN" in DOC_CLASSIFIER_SYSTEM_PROMPT)
        check("doc_type" in DOC_CLASSIFIER_SYSTEM_PROMPT)
        check("confidence" in DOC_CLASSIFIER_SYSTEM_PROMPT)
        check("reason" in DOC_CLASSIFIER_SYSTEM_PROMPT)


class TestCheckDocTypeMismatch:
    """Kiểm tra hàm đối soát loại văn bản theo Mục 1.5.3."""

    def test_matching_types_return_none(self):
        check(check_doc_type_mismatch("QTCT", DocType.QTCT) is None)
        check(check_doc_type_mismatch("LUONG", "LUONG") is None)
        check(check_doc_type_mismatch("phu_cap", "PHU_CAP") is None)
        check(check_doc_type_mismatch("KHEN_THUONG", DocType.KHEN_THUONG) is None)

    def test_mismatch_returns_warning_item(self):
        warning = check_doc_type_mismatch("LUONG", DocType.QTCT)
        check(isinstance(warning, WarningItem))
        check(warning.code == "DOC_TYPE_MISMATCH")
        check("LUONG" in warning.message)
        check("QTCT" in warning.message)

    def test_unknown_detected_returns_warning(self):
        warning = check_doc_type_mismatch("UNKNOWN", DocType.KHEN_THUONG)
        check(warning is not None)
        check(warning.code == "DOC_TYPE_MISMATCH")
        check("UNKNOWN" in warning.message)


class TestClassificationContextExtraction:
    """Kiểm tra trích xuất ngữ cảnh văn bản cho phân loại."""

    def test_short_content_preserved(self):
        short = "QUYẾT ĐỊNH Về việc bổ nhiệm\nĐiều 1. Bổ nhiệm ông A..."
        check(extract_classification_context(short, max_chars=1000) == short)

    def test_long_content_truncated(self):
        long_text = "QUYẾT ĐỊNH\n" + "Nội dung văn bản rất dài " * 500
        result = extract_classification_context(long_text, max_chars=500)
        check(len(result) <= 600)


@pytest.mark.anyio
class TestAsyncClassifyDocType:
    """Kiểm tra hàm aclassify_doc_type với Mocked LLMService."""

    async def test_aclassify_success(self):
        mock_llm = MagicMock()
        mock_llm.ask_json_async = AsyncMock(
            return_value={
                "doc_type": "QTCT",
                "confidence": 0.98,
                "reason": "Văn bản quyết định điều động và bổ nhiệm cán bộ.",
            }
        )

        content = "QUYẾT ĐỊNH Về việc điều động và bổ nhiệm công chức\nĐiều 1. Điều động..."
        result = await aclassify_doc_type(content, llm_service=mock_llm)

        check(isinstance(result, DocClassificationResult))
        check(result.doc_type_detected == "QTCT")
        check(result.confidence == 0.98)
        check("điều động" in result.reason)
        mock_llm.ask_json_async.assert_called_once()

    async def test_aclassify_unknown_doc_type(self):
        mock_llm = MagicMock()
        mock_llm.ask_json_async = AsyncMock(
            return_value={
                "doc_type": "THONG_BAO_CHUNG",
                "confidence": 0.5,
                "reason": "Không thuộc 7 loại",
            }
        )

        result = await aclassify_doc_type("Thông báo họp thường niên", llm_service=mock_llm)
        check(result.doc_type_detected == "UNKNOWN")

    async def test_aclassify_llm_exception_handled_gracefully(self):
        mock_llm = MagicMock()
        mock_llm.ask_json_async = AsyncMock(side_effect=RuntimeError("Connection timeout"))

        result = await aclassify_doc_type("Nội dung", llm_service=mock_llm)
        check(result.doc_type_detected == "UNKNOWN")
        check(result.confidence == 0.0)
        check("Connection timeout" in (result.reason or ""))

    async def test_aclassify_and_verify_doc_type_mismatch(self):
        mock_llm = MagicMock()
        mock_llm.ask_json_async = AsyncMock(
            return_value={
                "doc_type": "LUONG",
                "confidence": 0.95,
                "reason": "Quyết định nâng bậc lương thường xuyên",
            }
        )

        content = "QUYẾT ĐỊNH Về việc nâng bậc lương thường xuyên\nĐiều 1. Nâng bậc lương..."
        # Tham số gửi lên form là QTCT nhưng AI phát hiện là LUONG
        result = await aclassify_and_verify_doc_type(
            content=content,
            param_doc_type=DocType.QTCT,
            llm_service=mock_llm,
        )

        check(result.doc_type_detected == "LUONG")
        check(result.is_match is False)
        check(result.warning is not None)
        check(result.warning.code == "DOC_TYPE_MISMATCH")
        check("LUONG" in result.warning.message)
        check("QTCT" in result.warning.message)

    async def test_aclassify_and_verify_doc_type_match(self):
        mock_llm = MagicMock()
        mock_llm.ask_json_async = AsyncMock(
            return_value={
                "doc_type": "QTCT",
                "confidence": 0.99,
                "reason": "Điều động bổ nhiệm",
            }
        )

        content = "QUYẾT ĐỊNH Về việc điều động cán bộ"
        result = await aclassify_and_verify_doc_type(
            content=content,
            param_doc_type=DocType.QTCT,
            llm_service=mock_llm,
        )

        check(result.doc_type_detected == "QTCT")
        check(result.is_match is True)
        check(result.warning is None)


class TestSyncClassifyDocType:
    """Kiểm tra phiên bản đồng bộ classify_doc_type và classify_and_verify_doc_type."""

    def test_sync_classify(self):
        mock_llm = MagicMock()
        mock_llm.ask_json = MagicMock(
            return_value={
                "doc_type": "KHEN_THUONG",
                "confidence": 0.92,
                "reason": "Tặng Bằng khen của Ủy ban Thường vụ Quốc hội",
            }
        )

        res = classify_doc_type("NGHỊ QUYẾT Tặng Bằng khen", llm_service=mock_llm)
        check(res.doc_type_detected == "KHEN_THUONG")
        check(res.confidence == 0.92)

    def test_sync_classify_and_verify_mismatch(self):
        mock_llm = MagicMock()
        mock_llm.ask_json = MagicMock(
            return_value={
                "doc_type": "KY_NIEM_CHUONG",
                "confidence": 0.99,
                "reason": "Tặng Kỷ niệm chương Vì sự nghiệp Quốc hội",
            }
        )

        res = classify_and_verify_doc_type(
            content="Tặng Kỷ niệm chương Vì sự nghiệp Quốc hội",
            param_doc_type=DocType.KHEN_THUONG,
            llm_service=mock_llm,
        )
        check(res.doc_type_detected == "KY_NIEM_CHUONG")
        check(res.is_match is False)
        check(res.warning is not None)
        check(res.warning.code == "DOC_TYPE_MISMATCH")


class TestApplyDocTypeVerification:
    """Kiểm tra hàm cập nhật metadata.doc_type_detected và warnings vào ExtractionResult."""

    def test_apply_to_pydantic_object_with_mismatch(self):
        extraction_res = ExtractionResult(
            doc_type=DocType.QTCT,
            metadata=MetadataBase(
                document_number="123",
                document_name="Test",
                doc_type_detected="QTCT",
            ),
            warnings=[],
        )

        warning = apply_doc_type_verification(
            extraction_result=extraction_res,
            detected_doc_type="LUONG",
            param_doc_type=DocType.QTCT,
        )

        check(warning is not None)
        check(extraction_res.metadata.doc_type_detected == "LUONG")
        check(len(extraction_res.warnings) == 1)
        check(extraction_res.warnings[0].code == "DOC_TYPE_MISMATCH")

    def test_apply_to_pydantic_object_with_match(self):
        extraction_res = ExtractionResult(
            doc_type=DocType.QTCT,
            metadata=MetadataBase(
                document_number="123",
                document_name="Test",
                doc_type_detected="QTCT",
            ),
            warnings=[],
        )

        warning = apply_doc_type_verification(
            extraction_result=extraction_res,
            detected_doc_type="QTCT",
            param_doc_type=DocType.QTCT,
        )

        check(warning is None)
        check(extraction_res.metadata.doc_type_detected == "QTCT")
        check(len(extraction_res.warnings) == 0)

    def test_apply_to_dict_with_mismatch(self):
        res_dict = {
            "doc_type": "QTCT",
            "metadata": {
                "document_number": "123",
                "doc_type_detected": "QTCT",
            },
            "warnings": [],
        }

        warning = apply_doc_type_verification(
            extraction_result=res_dict,
            detected_doc_type="PHU_CAP",
            param_doc_type="QTCT",
        )

        check(warning is not None)
        check(res_dict["metadata"]["doc_type_detected"] == "PHU_CAP")
        check(len(res_dict["warnings"]) == 1)
        check(res_dict["warnings"][0]["code"] == "DOC_TYPE_MISMATCH")

    def test_avoid_duplicate_warnings(self):
        extraction_res = ExtractionResult(
            doc_type=DocType.QTCT,
            metadata=MetadataBase(
                doc_type_detected="QTCT",
            ),
            warnings=[
                WarningItem(
                    code="DOC_TYPE_MISMATCH",
                    message="Cảnh báo trước đó",
                )
            ],
        )

        apply_doc_type_verification(
            extraction_result=extraction_res,
            detected_doc_type="LUONG",
            param_doc_type="QTCT",
        )

        # Không được nhân đôi cảnh báo
        check(len(extraction_res.warnings) == 1)
