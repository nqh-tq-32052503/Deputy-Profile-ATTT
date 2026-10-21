import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from core.config import DocType
from core.exceptions import (
    DeputyProfilingException,
    ExtractorNotFoundError,
    LLMConnectionError,
    LLMHTTPError,
    LLMResponseParseError,
    LLMServiceException,
    LLMTimeoutError,
    OCRConnectionError,
    OCRHTTPError,
    OCRResponseParseError,
    OCRServiceException,
    OCRTimeoutError,
    OCRUnreadableContentError,
)
from services.llm_service import LLMService, parse_json_from_llm
from services.ocr_service import OCRService
import app
from tests.assertions import check


class TestExceptionsHierarchy:
    def test_base_exception(self):
        exc = DeputyProfilingException("Lỗi hệ thống", code="SYS_ERR", status_code=500, details={"foo": "bar"})
        check(str(exc) == "[SYS_ERR] Lỗi hệ thống | Details: {'foo': 'bar'}")
        check(exc.code == "SYS_ERR")
        check(exc.status_code == 500)
        check(exc.details == {"foo": "bar"})

    def test_ocr_exceptions(self):
        err = OCRTimeoutError("OCR time out sau 60s")
        check(isinstance(err, OCRServiceException))
        check(isinstance(err, DeputyProfilingException))
        check(err.code == "OCR_TIMEOUT_ERROR")
        check(err.status_code == 504)

        conn_err = OCRConnectionError("Connection refused")
        check(conn_err.code == "OCR_CONNECTION_ERROR")
        check(conn_err.status_code == 503)

        http_err = OCRHTTPError("Internal Server Error", http_status=500)
        check(http_err.code == "OCR_HTTP_ERROR")
        check(http_err.status_code == 500)

        parse_err = OCRResponseParseError("Bad JSON")
        check(parse_err.code == "OCR_PARSE_ERROR")

        unreadable = OCRUnreadableContentError("File rỗng")
        check(unreadable.code == "UNREADABLE_CONTENT")

    def test_llm_exceptions(self):
        timeout = LLMTimeoutError("LLM timed out")
        check(isinstance(timeout, LLMServiceException))
        check(timeout.code == "LLM_TIMEOUT_ERROR")

        conn = LLMConnectionError("Cannot connect")
        check(conn.code == "LLM_CONNECTION_ERROR")

        http = LLMHTTPError("Rate limited", http_status=429)
        check(http.code == "LLM_HTTP_ERROR")
        check(http.status_code == 429)

        parse = LLMResponseParseError("Invalid JSON", raw_text="not a json")
        check(parse.code == "LLM_PARSE_ERROR")
        check(parse.details["raw_text"] == "not a json")


class TestOCRServiceLoggingAndExceptions:
    def test_ocr_timeout_logs_and_raises(self, caplog):
        async def run():
            ocr = OCRService(endpoint_url="http://test-ocr.local/v1/extract", timeout=5)
            with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Read timed out")):
                with caplog.at_level(logging.ERROR):
                    with pytest.raises(OCRTimeoutError) as exc_info:
                        await ocr.aextract_full(b"%PDF-mock", file_name="sample.pdf")

                    check(exc_info.value.code == "OCR_TIMEOUT_ERROR")
                    check("OCR_TIMEOUT_ERROR" in caplog.text)
                    check("sample.pdf" in caplog.text)

        asyncio.run(run())

    def test_ocr_connect_error_logs_and_raises(self, caplog):
        async def run():
            ocr = OCRService(endpoint_url="http://test-ocr.local/v1/extract")
            with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
                with caplog.at_level(logging.ERROR):
                    with pytest.raises(OCRConnectionError) as exc_info:
                        await ocr.aextract_full(b"%PDF-mock", file_name="sample.pdf")

                    check(exc_info.value.code == "OCR_CONNECTION_ERROR")
                    check("OCR_CONNECTION_ERROR" in caplog.text)

        asyncio.run(run())

    def test_ocr_http_error_logs_and_raises(self, caplog):
        async def run():
            ocr = OCRService(endpoint_url="http://test-ocr.local/v1/extract")
            req = httpx.Request("POST", "http://test-ocr.local/v1/extract")
            resp = httpx.Response(500, request=req, text="Internal OCR Failure")
            with patch("httpx.AsyncClient.post", side_effect=httpx.HTTPStatusError("500 Error", request=req, response=resp)):
                with caplog.at_level(logging.ERROR):
                    with pytest.raises(OCRHTTPError) as exc_info:
                        await ocr.aextract_full(b"%PDF-mock", file_name="sample.pdf")

                    check(exc_info.value.code == "OCR_HTTP_ERROR")
                    check(exc_info.value.status_code == 500)
                    check("OCR_HTTP_ERROR" in caplog.text)

        asyncio.run(run())

    def test_ocr_unreadable_empty_content_logs_and_raises(self, caplog):
        async def run():
            ocr = OCRService(endpoint_url="http://test-ocr.local/v1/extract")
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"content": "   ", "page_artifacts": {}}
            mock_resp.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient.post", return_value=mock_resp):
                with caplog.at_level(logging.ERROR):
                    with pytest.raises(OCRUnreadableContentError) as exc_info:
                        await ocr.aextract_full(b"%PDF-mock", file_name="blank.pdf")

                    check(exc_info.value.code == "UNREADABLE_CONTENT")
                    check("UNREADABLE_CONTENT" in caplog.text)

        asyncio.run(run())


class TestLLMServiceLoggingAndExceptions:
    def test_llm_timeout_logs_and_raises(self, caplog):
        async def run():
            llm = LLMService(api_base_url="http://test-llm.local/v1", model_name="test-model", timeout=10)
            with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("LLM timed out")):
                with caplog.at_level(logging.ERROR):
                    with pytest.raises(LLMTimeoutError) as exc_info:
                        await llm.ask_async("system prompt", "content")

                    check(exc_info.value.code == "LLM_TIMEOUT_ERROR")
                    check("LLM_TIMEOUT_ERROR" in caplog.text)

        asyncio.run(run())

    def test_llm_connect_error_logs_and_raises(self, caplog):
        async def run():
            llm = LLMService(api_base_url="http://test-llm.local/v1", model_name="test-model")
            with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Host unreachable")):
                with caplog.at_level(logging.ERROR):
                    with pytest.raises(LLMConnectionError) as exc_info:
                        await llm.ask_async("system prompt", "content")

                    check(exc_info.value.code == "LLM_CONNECTION_ERROR")
                    check("LLM_CONNECTION_ERROR" in caplog.text)

        asyncio.run(run())

    def test_llm_json_parse_error_logs_and_raises(self, caplog):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(LLMResponseParseError) as exc_info:
                parse_json_from_llm("Đây là phản hồi văn bản không có JSON nào cả {broken json")

            check(exc_info.value.code == "LLM_PARSE_ERROR")
            check("LLM_PARSE_ERROR" in caplog.text)


class TestAppTaskExceptionHandling:
    def test_app_task_catches_ocr_exception(self, caplog):
        async def run():
            req_id = "test-req-ocr-err"
            app.tasks_store[req_id] = {"status": "PROCESSING"}

            with patch.object(
                app.ocr_service,
                "aextract_full",
                side_effect=OCRTimeoutError("Timeout khi OCR file", details={"timeout": 60}),
            ):
                with caplog.at_level(logging.ERROR):
                    await app.process_document_task(
                        request_id=req_id,
                        doc_type_enum=DocType.QTCT,
                        files_data=[("test.pdf", b"pdfcontent")],
                        cache_key="fake-cache-key",
                    )

            check(app.tasks_store[req_id]["status"] == app.ProcessStatus.FAILED)
            check(app.tasks_store[req_id]["error"]["code"] == "OCR_TIMEOUT_ERROR")
            check("TIẾN TRÌNH THẤT BẠI" in caplog.text)
            check("OCR_TIMEOUT_ERROR" in caplog.text)

        asyncio.run(run())

    def test_read_and_validate_upload_files_empty(self):
        from fastapi import HTTPException

        async def run():
            with pytest.raises(HTTPException) as exc_info:
                await app._read_and_validate_upload_files([])
            check(exc_info.value.status_code == 400)

        asyncio.run(run())
