import io
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import app, tasks_store
from core.cache import CacheManager, cache_manager
from core.config import API_KEY, API_VERSION, DocType, MIN_FILE_SIZE_BYTES
from core.exceptions import (
    LLMTimeoutError,
    OCRConnectionError,
    OCRUnreadableContentError,
)
from core.schemas import ExtractionResult, MetadataBase, ProcessStatus, ResultStatus
from tests.assertions import check


def make_dummy_pdf() -> bytes:
    """Tạo file PDF hợp lệ tối thiểu bằng pypdf."""
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def client():
    """FastAPI TestClient fixture có kèm header X-API-Key hợp lệ."""
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    with TestClient(app, headers=headers) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state():
    """Tự động dọn dẹp tasks_store và cache_manager trước mỗi test."""
    tasks_store.clear()
    cache_manager.clear()
    yield
    tasks_store.clear()
    cache_manager.clear()


# ==============================================================================
# 1. TEST SYSTEM HEALTH & OPENAPI DOCS
# ==============================================================================


class TestSystemEndpoints:
    def test_health_check(self, client):
        """GET /health phải trả về HTTP 200, status 'ok' và đúng API version."""
        response = client.get("/health")
        check(response.status_code == 200)
        data = response.json()
        check(data["status"] == "ok")
        check(data["version"] == API_VERSION)

    def test_openapi_schema(self, client):
        """GET /openapi.json phải trả về schema OpenAPI hợp lệ."""
        response = client.get("/openapi.json")
        check(response.status_code == 200)
        schema = response.json()
        check("paths" in schema)
        check("/health" in schema["paths"])
        check("/hsdb/extract" in schema["paths"])
        check("/hsdb/extract/{request_id}" in schema["paths"])

    def test_swagger_ui(self, client):
        """GET /docs phải hiển thị giao diện Swagger UI thành công."""
        response = client.get("/docs")
        check(response.status_code == 200)
        check("text/html" in response.headers.get("content-type", ""))


# ==============================================================================
# 2. TEST REQUEST VALIDATION (POST /hsdb/extract)
# ==============================================================================


class TestExtractValidation:
    def test_invalid_doc_type(self, client):
        """doc_type không thuộc 7 loại hợp lệ phải trả về HTTP 400."""
        pdf_bytes = make_dummy_pdf()
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": "INVALID_DOCTYPE"},
            files=[("files", ("test.pdf", pdf_bytes, "application/pdf"))],
        )
        check(response.status_code == 400)
        check("không hợp lệ" in response.json()["detail"])

    def test_missing_files(self, client):
        """Không gửi file nào phải trả về HTTP 400 hoặc 422."""
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.QTCT.value},
            files=[],
        )
        check(response.status_code in (400, 422))

    def test_exceed_max_files(self, client):
        """Gửi vượt quá 5 files phải bị từ chối với HTTP 400."""
        pdf_bytes = make_dummy_pdf()
        files = [
            ("files", (f"test_{i}.pdf", pdf_bytes, "application/pdf"))
            for i in range(6)
        ]
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.QTCT.value},
            files=files,
        )
        check(response.status_code == 400)
        check("vượt quá giới hạn cho phép" in response.json()["detail"])

    def test_invalid_file_extension(self, client):
        """Gửi file không phải định dạng PDF phải trả về HTTP 415."""
        text_content = b"Day khong phai la file PDF"
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.QTCT.value},
            files=[("files", ("document.txt", text_content, "text/plain"))],
        )
        check(response.status_code == 415)
        check("không phải là định dạng PDF hợp lệ" in response.json()["detail"])

    def test_exceed_file_size_limit(self, client):
        """File vượt quá dung lượng tối đa 30MB phải trả về HTTP 413."""
        # Mock kiểm tra độ dài file bằng cách patch MAX_FILE_SIZE_BYTES
        with patch("app.MAX_FILE_SIZE_BYTES", 100):  # Giới hạn giả lập 100 bytes
            pdf_bytes = make_dummy_pdf()  # > 100 bytes
            response = client.post(
                "/hsdb/extract",
                data={"doc_type": DocType.QTCT.value},
                files=[("files", ("large.pdf", pdf_bytes, "application/pdf"))],
            )
            check(response.status_code == 413)
            check("dung lượng vượt quá giới hạn" in response.json()["detail"])

    def test_file_size_below_minimum(self, client):
        """File có dung lượng nhỏ hơn MIN_FILE_SIZE_BYTES phải bị từ chối với HTTP 400 (BUG-1123)."""
        tiny_bytes = b"%PDF"  # chỉ có 4 bytes
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.QTCT.value},
            files=[("files", ("tiny.pdf", tiny_bytes, "application/pdf"))],
        )
        check(response.status_code == 400)
        check("quá nhỏ" in response.json()["detail"])

    def test_fake_pdf_magic_bytes_invalid(self, client):
        """File có đuôi .pdf nhưng nội dung text giả mạo phải bị phát hiện qua Magic Bytes HTTP 415 (BUG-1123)."""
        fake_content = b"This is plain text pretending to be a pdf file." * 5  # > 100 bytes
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.QTCT.value},
            files=[("files", ("fake.pdf", fake_content, "application/pdf"))],
        )
        check(response.status_code == 415)
        check("Magic bytes không khớp" in response.json()["detail"])

    def test_corrupt_pdf_structure(self, client):
        """File có Magic Bytes %PDF- nhưng cấu trúc hỏng không đọc được bằng pypdf phải trả về HTTP 400 (BUG-1123)."""
        corrupt_content = b"%PDF-1.4\n" + b"Corrupted invalid PDF body stream without xref or pages" * 5
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.QTCT.value},
            files=[("files", ("corrupted.pdf", corrupt_content, "application/pdf"))],
        )
        check(response.status_code == 400)
        check("bị hỏng cấu trúc" in response.json()["detail"] or "không thể phân tích cú pháp" in response.json()["detail"])


# ==============================================================================
# TEST API KEY AUTHENTICATION (BUG-1113)
# ==============================================================================


class TestApiKeyAuthentication:
    def test_extract_without_api_key_returns_401(self):
        """Gọi POST /hsdb/extract không có header X-API-Key phải trả về HTTP 401."""
        raw_client = TestClient(app)
        pdf_bytes = make_dummy_pdf()
        response = raw_client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.QTCT.value},
            files=[("files", ("test.pdf", pdf_bytes, "application/pdf"))],
        )
        check(response.status_code == 401)
        check("Thiếu API Key xác thực" in response.json()["detail"])

    def test_extract_with_invalid_api_key_returns_401(self):
        """Gọi POST /hsdb/extract với X-API-Key sai phải trả về HTTP 401."""
        raw_client = TestClient(app, headers={"X-API-Key": "wrong-key"})
        pdf_bytes = make_dummy_pdf()
        response = raw_client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.QTCT.value},
            files=[("files", ("test.pdf", pdf_bytes, "application/pdf"))],
        )
        check(response.status_code == 401)
        check("API Key không hợp lệ" in response.json()["detail"])

    def test_poll_without_api_key_returns_401(self):
        """Gọi GET /hsdb/extract/{request_id} không có header X-API-Key phải trả về HTTP 401."""
        raw_client = TestClient(app)
        response = raw_client.get("/hsdb/extract/some-request-id")
        check(response.status_code == 401)

    def test_health_check_does_not_require_api_key(self):
        """GET /health không yêu cầu API Key."""
        raw_client = TestClient(app)
        response = raw_client.get("/health")
        check(response.status_code == 200)


# ==============================================================================
# 3. TEST PROCESS INITIALIZATION & CACHING
# ==============================================================================


class TestExtractInitAndCache:
    def test_extract_init_success(self, client):
        """Khởi tạo tiến trình thành công với 1 file PDF hợp lệ."""
        pdf_bytes = make_dummy_pdf()
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.QTCT.value, "force_reprocess": "false"},
            files=[("files", ("qd_dieu_dong.pdf", pdf_bytes, "application/pdf"))],
        )
        check(response.status_code == 200)
        data = response.json()
        check("request_id" in data)
        check(data["status"] == ProcessStatus.PROCESSING.value)
        check("created_at" in data)
        # Kiểm tra task được ghi nhận trong memory store
        check(data["request_id"] in tasks_store)

    def test_multi_file_concatenation_init(self, client):
        """Gửi 2 file PDF hợp lệ phải kích hoạt hàm ghép PDF và trả về HTTP 200."""
        pdf1 = make_dummy_pdf()
        pdf2 = make_dummy_pdf()
        files = [
            ("files", ("qd_chinh.pdf", pdf1, "application/pdf")),
            ("files", ("danh_sach.pdf", pdf2, "application/pdf")),
        ]
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.KHEN_THUONG.value},
            files=files,
        )
        check(response.status_code == 200)
        data = response.json()
        check(data["status"] == ProcessStatus.PROCESSING.value)
        check(data["request_id"] in tasks_store)

    def test_caching_hit_returns_immediately(self, client):
        """
        Khi file đã được xử lý và lưu trong cache, request tiếp theo
        (với force_reprocess=False) phải trả kết quả ngay lập tức (is_cached: True).
        """
        pdf_bytes = make_dummy_pdf()
        cache_key = CacheManager.compute_key(DocType.LUONG.value, [pdf_bytes])

        mock_cached_result = {
            "status": "success",
            "error": None,
            "doc_type": DocType.LUONG.value,
            "person_count_declared": 1,
            "tong_so_ca_nhan": 1,
            "metadata": {
                "document_number": "123/QĐ-VPQH",
                "document_name": "Về việc nâng bậc lương",
                "issue_date": "01/01/2025",
                "issue_unit": "Văn phòng Quốc hội",
                "signer": "Nguyễn Văn A",
                "content": "Điều 1...",
                "doc_type_detected": "LUONG",
            },
            "detail": {
                "raise_salary_reason": "Nâng bậc lương thường xuyên",
                "position_wage": "Chuyên viên chính",
                "position_wage_code": "01.002",
                "old_step": 3,
                "old_factor": 5.08,
                "salary_step": 4,
                "salary_factor": 5.42,
                "start_date": "01/01/2025",
                "review_date": "01/01/2028",
                "percentage": None,
            },
            "groups": [],
            "persons": [
                {
                    "stt": 1,
                    "group_index": None,
                    "code": None,
                    "is_collective": False,
                    "full_name": "Nguyễn Văn B",
                    "position_name": "Chuyên viên",
                    "work_organization_name": "Văn phòng Quốc hội",
                    "raw_text": "Điều 1...",
                }
            ],
            "warnings": [],
        }

        # Lưu sẵn vào cache
        cache_manager.set(cache_key, mock_cached_result)

        # Gửi request với file trùng
        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.LUONG.value, "force_reprocess": "false"},
            files=[("files", ("nang_luong.pdf", pdf_bytes, "application/pdf"))],
        )

        check(response.status_code == 200)
        data = response.json()
        check(data["status"] == ProcessStatus.FINISHED.value)
        check(data["is_cached"] is True)
        check(data["result"] is not None)
        check(data["result"]["metadata"]["document_number"] == "123/QĐ-VPQH")

    def test_force_reprocess_bypasses_cache(self, client):
        """
        Khi bật force_reprocess=True, hệ thống phải bỏ qua cache và tạo tiến trình mới.
        """
        pdf_bytes = make_dummy_pdf()
        cache_key = CacheManager.compute_key(DocType.LUONG.value, [pdf_bytes])
        cache_manager.set(cache_key, {"cached": "data"})

        response = client.post(
            "/hsdb/extract",
            data={"doc_type": DocType.LUONG.value, "force_reprocess": "true"},
            files=[("files", ("nang_luong.pdf", pdf_bytes, "application/pdf"))],
        )

        check(response.status_code == 200)
        data = response.json()
        check(data["status"] == ProcessStatus.PROCESSING.value)
        check(data.get("is_cached") is not True)


# ==============================================================================
# 4. TEST POLLING ENDPOINT (GET /hsdb/extract/{request_id})
# ==============================================================================


class TestPollStatusEndpoint:
    def test_poll_not_found(self, client):
        """request_id không tồn tại phải trả về HTTP 404."""
        random_id = str(uuid.uuid4())
        response = client.get(f"/hsdb/extract/{random_id}")
        check(response.status_code == 404)
        check("Không tìm thấy tiến trình" in response.json()["detail"])

    def test_poll_processing_status(self, client):
        """request_id đang xử lý phải trả về status PROCESSING và result null."""
        req_id = "test-processing-id"
        tasks_store[req_id] = {
            "status": ProcessStatus.PROCESSING,
            "result": None,
            "error": None,
            "created_at": "2026-10-14T00:00:00Z",
        }

        response = client.get(f"/hsdb/extract/{req_id}")
        check(response.status_code == 200)
        data = response.json()
        check(data["request_id"] == req_id)
        check(data["status"] == ProcessStatus.PROCESSING.value)
        check(data["result"] is None)
        check(data["error"] is None)

    def test_poll_finished_status(self, client):
        """request_id đã hoàn thành phải trả về status FINISHED và kết quả đầy đủ."""
        req_id = "test-finished-id"
        expected_result = {
            "status": "success",
            "error": None,
            "doc_type": DocType.QTCT.value,
            "person_count_declared": 1,
            "tong_so_ca_nhan": 1,
            "metadata": {
                "document_number": "1122/QĐ-VPQH",
                "document_name": "Về việc điều động và bổ nhiệm",
                "issue_date": "06/08/2018",
                "issue_unit": "Văn phòng Quốc hội",
                "signer": "Nguyễn Hạnh Phúc",
                "content": "Điều 1...",
                "doc_type_detected": "QTCT",
            },
            "detail": {
                "process_type": "Điều động và bổ nhiệm",
                "start_date": "10/08/2018",
                "from_organization_name": "Vụ Công tác đại biểu",
                "work_organization_name": "Trung tâm Bồi dưỡng đại biểu dân cử",
                "position_name": "Phó Giám đốc",
                "position_detail": "Phó Giám đốc Trung tâm Bồi dưỡng",
                "appointment_term_years": 5.0,
                "allowance_name": "Phụ cấp chức vụ lãnh đạo",
                "allowance_factor": 0.8,
            },
            "groups": [],
            "persons": [
                {
                    "stt": 1,
                    "group_index": None,
                    "code": None,
                    "is_collective": False,
                    "full_name": "Nguyễn Hải Long",
                    "position_name": "Phó Vụ trưởng",
                    "work_organization_name": "Vụ Công tác đại biểu",
                    "raw_text": "Điều 1...",
                }
            ],
            "warnings": [],
        }

        tasks_store[req_id] = {
            "status": ProcessStatus.FINISHED,
            "result": expected_result,
            "error": None,
        }

        response = client.get(f"/hsdb/extract/{req_id}")
        check(response.status_code == 200)
        data = response.json()
        check(data["status"] == ProcessStatus.FINISHED.value)
        check(data["result"]["doc_type"] == DocType.QTCT.value)
        check(data["result"]["metadata"]["document_number"] == "1122/QĐ-VPQH")
        check(len(data["result"]["persons"]) == 1)

    def test_poll_failed_status(self, client):
        """request_id thất bại phải trả về status FAILED kèm error object."""
        req_id = "test-failed-id"
        tasks_store[req_id] = {
            "status": ProcessStatus.FAILED,
            "result": None,
            "error": {
                "code": "UNREADABLE_CONTENT",
                "message": "Bản scan quá mờ, rỗng hoặc không thể nhận dạng ký tự",
            },
        }

        response = client.get(f"/hsdb/extract/{req_id}")
        check(response.status_code == 200)
        data = response.json()
        check(data["status"] == ProcessStatus.FAILED.value)
        check(data["result"] is None)
        check(data["error"]["code"] == "UNREADABLE_CONTENT")


# ==============================================================================
# 5. TEST END-TO-END BACKGROUND PIPELINE (process_document_task)
# ==============================================================================


class TestBackgroundProcessingPipeline:
    @pytest.mark.anyio
    async def test_pipeline_qtct_execution(self):
        """Kiểm tra pipeline xử lý trọn gói cho tài liệu QTCT."""
        from app import process_document_task

        req_id = "pipeline-test-qtct"
        pdf_bytes = make_dummy_pdf()
        files_data = [("qtct_doc.pdf", pdf_bytes)]
        cache_key = "test_key_qtct"

        # Mock OCR trả về text
        sample_ocr_md = """VĂN PHÒNG QUỐC HỘI
Số: 1122/QĐ-VPQH
Hà Nội, ngày 06 tháng 8 năm 2018
QUYẾT ĐỊNH
Về việc điều động và bổ nhiệm công chức lãnh đạo, quản lý
Điều 1. Điều động ông Nguyễn Hải Long, Phó Vụ trưởng Vụ Công tác đại biểu đến nhận công tác và bổ nhiệm giữ chức vụ Phó Giám đốc Trung tâm Bồi dưỡng đại biểu dân cử từ ngày 10/8/2018. Thời hạn bổ nhiệm là 05 năm. Phụ cấp chức vụ lãnh đạo hệ số 0,8.
Điều 2. Quyết định này có hiệu lực kể từ ngày ký.
CHỦ NHIỆM: Nguyễn Hạnh Phúc
"""
        sample_ocr_json = {"content": sample_ocr_md}

        async def mock_llm_dispatch(*args, **kwargs):
            prompt = kwargs.get("system_prompt") or (args[0] if len(args) > 0 else "")
            p_low = str(prompt).lower()
            if "metadata" in p_low or "trích yếu" in p_low:
                return {
                    "document_number": "1122/QĐ-VPQH",
                    "document_name": "Về việc điều động và bổ nhiệm công chức lãnh đạo, quản lý",
                    "issue_date": "06/08/2018",
                    "issue_unit": "Văn phòng Quốc hội",
                    "signer": "Nguyễn Hạnh Phúc",
                    "content": "Điều 1...",
                }
            elif "chi tiết" in p_low or "process_type" in p_low or "loại quá trình" in p_low:
                return {
                    "process_type": "Điều động và bổ nhiệm",
                    "start_date": "10/08/2018",
                    "from_organization_name": "Vụ Công tác đại biểu",
                    "work_organization_name": "Trung tâm Bồi dưỡng đại biểu dân cử",
                    "position_name": "Phó Giám đốc",
                    "position_detail": "Phó Giám đốc Trung tâm Bồi dưỡng đại biểu dân cử",
                    "appointment_term_years": 5.0,
                    "allowance_name": "Phụ cấp chức vụ lãnh đạo",
                    "allowance_factor": 0.8,
                }
            elif "danh sách" in p_low or "cá nhân" in p_low:
                return [
                    {
                        "stt": 1,
                        "full_name": "Nguyễn Hải Long",
                        "position_name": "Phó Vụ trưởng",
                        "work_organization_name": "Vụ Công tác đại biểu",
                        "raw_text": "Điều 1...",
                    }
                ]
            return {}

        with patch("app.ocr_service.aextract_full", new=AsyncMock(return_value=(sample_ocr_md, sample_ocr_json))):
            with patch(
                "app.aclassify_doc_type",
                new=AsyncMock(
                    return_value=MagicMock(doc_type_detected="QTCT", confidence=0.99)
                ),
            ):
                with patch("services.llm_service.LLMService.ask_json_async", new=AsyncMock(side_effect=mock_llm_dispatch)):
                    await process_document_task(
                        request_id=req_id,
                        doc_type_enum=DocType.QTCT,
                        files_data=files_data,
                        cache_key=cache_key,
                    )

        task = tasks_store.get(req_id)
        check(task is not None)
        check(task["status"] == ProcessStatus.FINISHED)
        result = task["result"]
        check(result["doc_type"] == DocType.QTCT.value)
        check(result["tong_so_ca_nhan"] == 1)
        check(result["detail"]["process_type"] == "Điều động và bổ nhiệm")
        check(result["detail"]["position_name"] == "Phó Giám đốc")
        check(len(result["persons"]) == 1)
        check(result["persons"][0]["full_name"] == "Nguyễn Hải Long")

    @pytest.mark.anyio
    async def test_pipeline_doc_type_mismatch_warning(self):
        """
        Khi client gửi doc_type=QTCT nhưng AI nhận diện thực tế là LUONG,
        hệ thống phải tự động bổ sung warning DOC_TYPE_MISMATCH.
        """
        from app import process_document_task

        req_id = "test-doc-type-mismatch"
        pdf_bytes = make_dummy_pdf()
        files_data = [("doc.pdf", pdf_bytes)]
        cache_key = "test_key_mismatch"

        sample_md = "Quyết định nâng bậc lương..."
        sample_json = {"content": sample_md}

        async def mock_mismatch_dispatch(*args, **kwargs):
            prompt = kwargs.get("system_prompt") or (args[0] if len(args) > 0 else "")
            p_low = str(prompt).lower()
            if "metadata" in p_low or "trích yếu" in p_low:
                return {
                    "document_number": "3110-QĐ",
                    "document_name": "Nâng bậc lương",
                    "issue_date": "01/01/2025",
                    "issue_unit": "HVCTQG",
                    "signer": "Nguyễn Văn A",
                    "content": "Điều 1...",
                }
            elif "chi tiết" in p_low or "process_type" in p_low:
                return {
                    "process_type": "Nâng bậc lương",
                    "start_date": "01/01/2025",
                    "from_organization_name": "A",
                    "work_organization_name": "B",
                    "position_name": "Chuyên viên",
                }
            elif "danh sách" in p_low or "cá nhân" in p_low:
                return [{"stt": 1, "full_name": "Trần Văn A", "raw_text": "Điều 1..."}]
            return {}

        with patch("app.ocr_service.aextract_full", new=AsyncMock(return_value=(sample_md, sample_json))):
            with patch(
                "app.aclassify_doc_type",
                new=AsyncMock(
                    return_value=MagicMock(doc_type_detected="LUONG", confidence=0.95)
                ),
            ):
                with patch("services.llm_service.LLMService.ask_json_async", new=AsyncMock(side_effect=mock_mismatch_dispatch)):
                    await process_document_task(
                        request_id=req_id,
                        doc_type_enum=DocType.QTCT,  # Gửi QTCT
                        files_data=files_data,
                        cache_key=cache_key,
                    )

        task = tasks_store.get(req_id)
        check(task["status"] == ProcessStatus.FINISHED)
        result = task["result"]
        warning_codes = [w["code"] for w in result["warnings"]]
        check("DOC_TYPE_MISMATCH" in warning_codes)

    @pytest.mark.anyio
    async def test_pipeline_ocr_unreadable_error(self):
        """
        Khi OCR báo file mờ hoặc rỗng (OCRUnreadableContentError),
        task phải ghi nhận trạng thái FAILED với mã UNREADABLE_CONTENT.
        """
        from app import process_document_task

        req_id = "test-ocr-unreadable"
        pdf_bytes = make_dummy_pdf()
        files_data = [("empty.pdf", pdf_bytes)]
        cache_key = "test_key_unreadable"

        with patch(
            "app.ocr_service.aextract_full",
            new=AsyncMock(side_effect=OCRUnreadableContentError("File quá mờ không thể nhận diện")),
        ):
            await process_document_task(
                request_id=req_id,
                doc_type_enum=DocType.QTCT,
                files_data=files_data,
                cache_key=cache_key,
            )

        task = tasks_store.get(req_id)
        check(task["status"] == ProcessStatus.FAILED)
        check(task["error"]["code"] == "UNREADABLE_CONTENT")

    @pytest.mark.anyio
    async def test_pipeline_llm_timeout_error(self):
        """
        Khi LLM bị timeout, task phải ghi nhận trạng thái FAILED với mã LLM_TIMEOUT_ERROR.
        """
        from app import process_document_task

        req_id = "test-llm-timeout"
        pdf_bytes = make_dummy_pdf()
        files_data = [("test.pdf", pdf_bytes)]
        cache_key = "test_key_timeout"

        sample_md = "Nội dung văn bản..."
        sample_json = {"content": sample_md}

        with patch("app.ocr_service.aextract_full", new=AsyncMock(return_value=(sample_md, sample_json))):
            with patch(
                "services.llm_service.LLMService.ask_json_async",
                new=AsyncMock(side_effect=LLMTimeoutError("Quá thời gian chờ phản hồi từ LLM")),
            ):
                await process_document_task(
                    request_id=req_id,
                    doc_type_enum=DocType.QTCT,
                    files_data=files_data,
                    cache_key=cache_key,
                )

        task = tasks_store.get(req_id)
        check(task["status"] == ProcessStatus.FAILED)
        check(task["error"]["code"] == "LLM_TIMEOUT_ERROR")

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "doc_type",
        [
            DocType.PHU_CAP,
            DocType.THI_DUA,
            DocType.KY_NIEM_CHUONG,
            DocType.QUY_HOACH,
        ],
    )
    async def test_pipeline_placeholder_doc_types(self, doc_type):
        """
        Kiểm tra 4 loại văn bản còn lại (PHU_CAP, THI_DUA, KY_NIEM_CHUONG, QUY_HOACH)
        hoạt động an toàn qua background task.
        """
        from app import process_document_task

        req_id = f"test-placeholder-{doc_type.value}"
        pdf_bytes = make_dummy_pdf()
        files_data = [(f"{doc_type.value}.pdf", pdf_bytes)]
        cache_key = f"key_{doc_type.value}"

        sample_md = f"Quyết định mẫu cho {doc_type.value}"
        sample_json = {"content": sample_md}

        with patch("app.ocr_service.aextract_full", new=AsyncMock(return_value=(sample_md, sample_json))):
            with patch(
                "services.doc_classifier.aclassify_doc_type",
                new=AsyncMock(return_value=MagicMock(doc_type_detected=doc_type.value)),
            ):
                await process_document_task(
                    request_id=req_id,
                    doc_type_enum=doc_type,
                    files_data=files_data,
                    cache_key=cache_key,
                )

        task = tasks_store.get(req_id)
        check(task["status"] == ProcessStatus.FINISHED)
        check(task["result"]["doc_type"] == doc_type.value)
