import io
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

import app
from core.config import DocType
from core.schemas import ProcessStatus
from tests.assertions import check


def _create_sample_pdf(num_pages: int = 1) -> bytes:
    """Tạo file PDF giả lập trong bộ nhớ với số trang chỉ định."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestPdfConcatenationUtils:
    def test_concatenate_pdf_bytes_single_file(self):
        pdf_bytes = _create_sample_pdf(num_pages=2)
        result = app.concatenate_pdf_bytes([pdf_bytes])
        check(result == pdf_bytes)

    def test_concatenate_pdf_bytes_empty_list_raises(self):
        with pytest.raises(ValueError):
            app.concatenate_pdf_bytes([])

    def test_concatenate_pdf_bytes_multiple_files(self):
        pdf1 = _create_sample_pdf(num_pages=2)
        pdf2 = _create_sample_pdf(num_pages=3)
        pdf3 = _create_sample_pdf(num_pages=1)

        merged = app.concatenate_pdf_bytes([pdf1, pdf2, pdf3])
        reader = PdfReader(io.BytesIO(merged))
        check(len(reader.pages) == 6)

    def test_concatenate_pdf_files_single_file(self):
        pdf_bytes = _create_sample_pdf(num_pages=1)
        original_data = [("document.pdf", pdf_bytes)]
        result = app.concatenate_pdf_files(original_data)
        check(result == original_data)

    def test_concatenate_pdf_files_multiple_files(self):
        pdf1 = _create_sample_pdf(num_pages=2)
        pdf2 = _create_sample_pdf(num_pages=3)
        original_data = [
            ("quyet_dinh_part1.pdf", pdf1),
            ("quyet_dinh_part2.pdf", pdf2),
        ]

        result = app.concatenate_pdf_files(original_data)
        check(len(result) == 1)
        merged_filename, merged_bytes = result[0]
        check(merged_filename == "quyet_dinh_part1_merged.pdf")
        reader = PdfReader(io.BytesIO(merged_bytes))
        check(len(reader.pages) == 5)

    def test_concatenate_pdf_files_corrupted_file_raises_bad_request(self):
        corrupted_bytes = b"not-a-valid-pdf"
        with pytest.raises(HTTPException):
            app.concatenate_pdf_files([("f1.pdf", corrupted_bytes), ("f2.pdf", corrupted_bytes)])


class TestPipelineWithPdfConcatenation:
    @pytest.fixture
    def client(self):
        return TestClient(app.app)

    def test_extract_endpoint_single_file_passes_single(self, client):
        pdf1 = _create_sample_pdf(num_pages=1)

        with patch("app.process_document_task") as mock_task:
            response = client.post(
                "/hsdb/extract",
                data={"doc_type": DocType.QTCT.value, "force_reprocess": True},
                files=[
                    ("files", ("test_doc.pdf", pdf1, "application/pdf")),
                ],
            )
            check(response.status_code == 200)
            data = response.json()
            check(data["status"] == "PROCESSING")

            # Kiểm tra arguments truyền vào background task
            mock_task.assert_called_once()
            _, kwargs = mock_task.call_args
            files_data = kwargs["files_data"]
            check(len(files_data) == 1)
            check(files_data[0][0] == "test_doc.pdf")

    def test_extract_endpoint_multiple_files_concatenates(self, client):
        pdf1 = _create_sample_pdf(num_pages=2)
        pdf2 = _create_sample_pdf(num_pages=3)

        with patch("app.process_document_task") as mock_task:
            response = client.post(
                "/hsdb/extract",
                data={"doc_type": DocType.QTCT.value, "force_reprocess": True},
                files=[
                    ("files", ("ho_so_p1.pdf", pdf1, "application/pdf")),
                    ("files", ("ho_so_p2.pdf", pdf2, "application/pdf")),
                ],
            )
            check(response.status_code == 200)
            data = response.json()
            check(data["status"] == "PROCESSING")

            # Kiểm tra task được gọi với đúng 1 file duy nhất đã ghép
            mock_task.assert_called_once()
            _, kwargs = mock_task.call_args
            files_data = kwargs["files_data"]
            check(len(files_data) == 1)
            merged_name, merged_bytes = files_data[0]
            check(merged_name == "ho_so_p1_merged.pdf")
            reader = PdfReader(io.BytesIO(merged_bytes))
            check(len(reader.pages) == 5)

    def test_process_document_task_concatenates_if_multiple(self):
        import asyncio

        async def run():
            pdf1 = _create_sample_pdf(num_pages=1)
            pdf2 = _create_sample_pdf(num_pages=2)

            mock_ocr_result = ("# Sample Markdown", {"document": {"page_count": 3}})
            mock_extractor = MagicMock()
            mock_extractor.aextract = AsyncMock(return_value=MagicMock(model_dump=lambda: {"tong_so_ca_nhan": 1, "warnings": []}))

            req_id = "test-req-multi-pdf"
            app.tasks_store[req_id] = {"status": "PROCESSING"}

            with patch.object(app.ocr_service, "aextract_full", AsyncMock(return_value=mock_ocr_result)) as mock_ocr:
                with patch("app.get_extractor", return_value=mock_extractor):
                    await app.process_document_task(
                        request_id=req_id,
                        doc_type_enum=DocType.QTCT,
                        files_data=[("part1.pdf", pdf1), ("part2.pdf", pdf2)],
                        cache_key="test-cache-key-multi",
                    )

                    # Đảm bảo OCR chỉ được gọi đúng 1 lần với file đã ghép 3 trang
                    check(mock_ocr.call_count == 1)
                    called_bytes = mock_ocr.call_args[0][0]
                    reader = PdfReader(io.BytesIO(called_bytes))
                    check(len(reader.pages) == 3)
                    check(mock_ocr.call_args[1]["file_name"] == "part1_merged.pdf")

            check(app.tasks_store[req_id]["status"] == ProcessStatus.FINISHED)

        asyncio.run(run())

