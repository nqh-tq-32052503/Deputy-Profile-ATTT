import json
import logging
from pathlib import Path
import time
from typing import Any, BinaryIO, Optional, Tuple, Union

import httpx

from core.config import (
    OCR_API_KEY,
    OCR_ENABLE_CORRECTION,
    OCR_PROCESS_TABLE,
    OCR_RASTERIZE,
    OCR_SERVICE_URL,
    OCR_TIMEOUT_SECONDS,
    OCR_USE_CACHE,
    OCR_USE_CELERY,
)
from core.exceptions import (
    OCRConnectionError,
    OCRHTTPError,
    OCRResponseParseError,
    OCRServiceException,
    OCRTimeoutError,
    OCRUnreadableContentError,
)

logger = logging.getLogger(__name__)


class OCRService:
    """
    Dịch vụ OCR chuyển đổi văn bản PDF (scan/điện tử) thành nội dung Markdown
    thông qua việc gửi request tới OCR Service URL được cấu hình.
    """

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
        rasterize: Optional[bool] = None,
        enable_correction: Optional[bool] = None,
        process_table: Optional[bool] = None,
        use_celery: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ):
        self.endpoint_url = endpoint_url or OCR_SERVICE_URL
        self.api_key = api_key or OCR_API_KEY
        self.timeout = timeout or OCR_TIMEOUT_SECONDS
        self.rasterize = OCR_RASTERIZE if rasterize is None else rasterize
        self.enable_correction = (
            OCR_ENABLE_CORRECTION if enable_correction is None else enable_correction
        )
        self.process_table = (
            OCR_PROCESS_TABLE if process_table is None else process_table
        )
        self.use_celery = OCR_USE_CELERY if use_celery is None else use_celery
        self.use_cache = OCR_USE_CACHE if use_cache is None else use_cache

    def _read_pdf_bytes(self, pdf_input: Union[str, Path, bytes, BinaryIO]) -> bytes:
        if isinstance(pdf_input, bytes):
            return pdf_input
        elif isinstance(pdf_input, (str, Path)):
            with open(pdf_input, "rb") as f:
                return f.read()
        elif hasattr(pdf_input, "read"):
            content = pdf_input.read()
            if isinstance(content, str):
                return content.encode("utf-8")
            return content
        else:
            raise ValueError(f"Đầu vào PDF không hợp lệ: {type(pdf_input)}")

    def _build_data_payload(
        self,
        rasterize: Optional[bool] = None,
        enable_correction: Optional[bool] = None,
        process_table: Optional[bool] = None,
        use_celery: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> dict:
        flags = {
            "rasterize": self.rasterize if rasterize is None else rasterize,
            "enable_correction": self.enable_correction if enable_correction is None else enable_correction,
            "process_table": self.process_table if process_table is None else process_table,
            "use_celery": self.use_celery if use_celery is None else use_celery,
            "use_cache": self.use_cache if use_cache is None else use_cache,
        }
        return {k: ("true" if v else "false") for k, v in flags.items() if v is not None}

    @staticmethod
    def _enrich_markdown_with_artifacts(resp_data: dict) -> str:
        """
        Bổ sung các text node bị OCR xếp vào page_artifacts (headers) nhưng chưa có
        trong content markdown để LLM không bị thiếu phần Quốc hiệu, Số hiệu, Ngày tháng.
        """
        content = resp_data.get("content") or ""
        page_artifacts = resp_data.get("page_artifacts", {})
        headers = page_artifacts.get("headers", [])

        missing_headers = []
        for h in headers:
            htext = h.get("text", "").strip()
            if htext and htext not in content:
                missing_headers.append(htext)

        if missing_headers:
            header_block = "\n".join(missing_headers)
            content = f"{header_block}\n\n{content}"

        return content

    @staticmethod
    def _table_cells_to_md(cells: list) -> str:
        """Chuyển đổi danh sách cells thành bảng Markdown."""
        if not cells:
            return ""
        rows = {}
        for c in cells:
            rows.setdefault(c.get("row_index", 0), []).append(c)
        md_lines = []
        for r_idx in sorted(rows.keys()):
            r_cells = sorted(rows[r_idx], key=lambda x: x.get("column_index", 0))
            cells_text = [c.get("text", "").replace("\n", " ").strip() for c in r_cells]
            line = "| " + " | ".join(cells_text) + " |"
            md_lines.append(line)
            if r_idx == 0:
                md_lines.append("| " + " | ".join(["---"] * len(cells_text)) + " |")
        return "\n".join(md_lines)

    @classmethod
    def _table_obj_to_md(cls, t_obj: dict) -> str:
        """Trích xuất markdown từ table object hoặc dựng lại từ cells."""
        rep = t_obj.get("representations", {})
        if rep.get("markdown"):
            return rep["markdown"].strip()
        return cls._table_cells_to_md(t_obj.get("cells", []))

    @staticmethod
    def _collect_sorted_tables(tables: Any) -> list:
        """Thu thập và sắp xếp các bảng theo thứ tự đọc và trang."""
        table_items = []
        if isinstance(tables, dict):
            for t_id, t_obj in tables.items():
                locs = t_obj.get("locations", [])
                page = locs[0].get("page_number", 0) if locs else 0
                ro = locs[0].get("reading_order", 0) if locs else 0
                table_items.append((page, ro, t_id, t_obj))
            table_items.sort(key=lambda x: (x[0], x[1], x[2]))
        elif isinstance(tables, list):
            for idx, t_obj in enumerate(tables):
                table_items.append((0, idx, str(idx), t_obj))
        return table_items

    @classmethod
    def _enrich_markdown_with_tables(cls, content: str, resp_data: dict) -> str:
        """
        Bổ sung dữ liệu bảng (tables) từ phản hồi OCR vào nội dung Markdown nếu có
        và chưa xuất hiện trong content, đảm bảo các bảng danh sách phụ lục được đưa vào bóc tách.
        """
        tables = resp_data.get("tables")
        if not tables:
            return content

        table_items = cls._collect_sorted_tables(tables)
        tables_md_blocks = []
        for item in table_items:
            t_md = cls._table_obj_to_md(item[3])
            if not t_md:
                continue
            first_row = t_md.splitlines()[0] if t_md.splitlines() else ""
            if first_row and first_row in content:
                continue
            tables_md_blocks.append(t_md)

        if not tables_md_blocks:
            return content

        tables_combined = "\n\n".join(tables_md_blocks)
        if content.strip():
            return f"{content.strip()}\n\n{tables_combined}"
        return tables_combined

    def _handle_response(self, resp: httpx.Response, file_name: str, elapsed: float) -> Tuple[str, dict]:
        """
        Kiểm tra và xử lý phản hồi từ OCR HTTP response.
        """
        try:
            resp_data = resp.json()
        except json.JSONDecodeError as e:
            err_msg = f"Phản hồi từ OCR Service không phải là định dạng JSON hợp lệ: {resp.text[:300]}"
            logger.exception(f"[OCR_PARSE_ERROR] {err_msg}")
            raise OCRResponseParseError(err_msg, details={"file_name": file_name, "raw_response": resp.text[:500]}) from e

        content = self._enrich_markdown_with_artifacts(resp_data)
        content = self._enrich_markdown_with_tables(content, resp_data)
        page_count = resp_data.get("document", {}).get("page_count", "N/A")

        if not content.strip():
            err_msg = f"File '{file_name}' không chứa nội dung văn bản nào sau khi OCR (bản scan quá mờ hoặc rỗng)."
            logger.error(f"[UNREADABLE_CONTENT] {err_msg}")
            raise OCRUnreadableContentError(err_msg, details={"file_name": file_name, "page_count": page_count})

        logger.info(
            f"OCR thành công cho file '{file_name}' trong {elapsed:.2f}s "
            f"(độ dài: {len(content)} ký tự, số trang: {page_count})."
        )
        return content, resp_data

    def extract_full(
        self,
        pdf_input: Union[str, Path, bytes, BinaryIO],
        file_name: Optional[str] = None,
        rasterize: Optional[bool] = None,
        enable_correction: Optional[bool] = None,
        process_table: Optional[bool] = None,
        use_celery: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> Tuple[str, dict]:
        """
        Thực hiện gọi service OCR để chuyển đổi file PDF thành định dạng Text/Markdown
        và trả về cả full response JSON của OCR.
        """
        actual_name = file_name or "document.pdf"
        pdf_bytes = self._read_pdf_bytes(pdf_input)
        headers = {}
        if self.api_key and self.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self.api_key}"

        files = {"file": (actual_name, pdf_bytes, "application/pdf")}
        data = self._build_data_payload(
            rasterize=rasterize,
            enable_correction=enable_correction,
            process_table=process_table,
            use_celery=use_celery,
            use_cache=use_cache,
        )

        logger.info(
            f"Bắt đầu gửi request tới OCR Service [{self.endpoint_url}] cho file '{actual_name}' "
            f"({len(pdf_bytes):,} bytes, timeout={self.timeout}s)..."
        )
        start_time = time.time()

        try:
            with httpx.Client(timeout=float(self.timeout)) as client:
                resp = client.post(
                    self.endpoint_url,
                    files=files,
                    data=data if data else None,
                    headers=headers,
                )
                resp.raise_for_status()
                elapsed = time.time() - start_time
                return self._handle_response(resp, actual_name, elapsed)

        except httpx.TimeoutException as e:
            elapsed = time.time() - start_time
            err_msg = f"Quá thời gian chờ phản hồi ({self.timeout}s) từ OCR Service cho file '{actual_name}' (sau {elapsed:.2f}s)"
            logger.exception(f"[OCR_TIMEOUT_ERROR] {err_msg}")
            raise OCRTimeoutError(err_msg, details={"file_name": actual_name, "timeout": self.timeout, "elapsed": elapsed}) from e

        except httpx.ConnectError as e:
            err_msg = f"Không thể kết nối đến OCR Service tại {self.endpoint_url}: {e}"
            logger.exception(f"[OCR_CONNECTION_ERROR] {err_msg}")
            raise OCRConnectionError(err_msg, details={"file_name": actual_name, "endpoint_url": self.endpoint_url}) from e

        except httpx.HTTPStatusError as e:
            elapsed = time.time() - start_time
            response_text = e.response.text[:500] if e.response else ""
            err_msg = f"OCR Service trả về mã lỗi HTTP {e.response.status_code}: {response_text}"
            logger.exception(f"[OCR_HTTP_ERROR] {err_msg}")
            raise OCRHTTPError(
                err_msg,
                http_status=e.response.status_code,
                details={"file_name": actual_name, "status_code": e.response.status_code, "response": response_text},
            ) from e

        except httpx.RequestError as e:
            err_msg = f"Lỗi giao tiếp với OCR Service khi xử lý file '{actual_name}': {e}"
            logger.exception(f"[OCR_SERVICE_ERROR] {err_msg}")
            raise OCRServiceException(err_msg, details={"file_name": actual_name, "error": str(e)}) from e

    def extract_markdown(
        self,
        pdf_input: Union[str, Path, bytes, BinaryIO],
        file_name: Optional[str] = None,
        rasterize: Optional[bool] = None,
        enable_correction: Optional[bool] = None,
        process_table: Optional[bool] = None,
        use_celery: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> str:
        """
        Thực hiện gọi service OCR để chuyển đổi file PDF thành định dạng Text/Markdown.
        """
        content, _ = self.extract_full(
            pdf_input=pdf_input,
            file_name=file_name,
            rasterize=rasterize,
            enable_correction=enable_correction,
            process_table=process_table,
            use_celery=use_celery,
            use_cache=use_cache,
        )
        return content

    async def aextract_full(
        self,
        pdf_input: Union[str, Path, bytes, BinaryIO],
        file_name: Optional[str] = None,
        rasterize: Optional[bool] = None,
        enable_correction: Optional[bool] = None,
        process_table: Optional[bool] = None,
        use_celery: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> Tuple[str, dict]:
        """
        Bản async của extract_full phục vụ luồng bất đồng bộ FastAPI.
        """
        actual_name = file_name or "document.pdf"
        pdf_bytes = self._read_pdf_bytes(pdf_input)
        headers = {}
        if self.api_key and self.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self.api_key}"

        files = {"file": (actual_name, pdf_bytes, "application/pdf")}
        data = self._build_data_payload(
            rasterize=rasterize,
            enable_correction=enable_correction,
            process_table=process_table,
            use_celery=use_celery,
            use_cache=use_cache,
        )

        logger.info(
            f"Bắt đầu gửi async request tới OCR Service [{self.endpoint_url}] cho file '{actual_name}' "
            f"({len(pdf_bytes):,} bytes, timeout={self.timeout}s)..."
        )
        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                resp = await client.post(
                    self.endpoint_url,
                    files=files,
                    data=data if data else None,
                    headers=headers,
                )
                resp.raise_for_status()
                elapsed = time.time() - start_time
                return self._handle_response(resp, actual_name, elapsed)

        except httpx.TimeoutException as e:
            elapsed = time.time() - start_time
            err_msg = f"Quá thời gian chờ phản hồi ({self.timeout}s) từ OCR Service cho file '{actual_name}' (sau {elapsed:.2f}s)"
            logger.exception(f"[OCR_TIMEOUT_ERROR] {err_msg}")
            raise OCRTimeoutError(err_msg, details={"file_name": actual_name, "timeout": self.timeout, "elapsed": elapsed}) from e

        except httpx.ConnectError as e:
            err_msg = f"Không thể kết nối đến OCR Service tại {self.endpoint_url}: {e}"
            logger.exception(f"[OCR_CONNECTION_ERROR] {err_msg}")
            raise OCRConnectionError(err_msg, details={"file_name": actual_name, "endpoint_url": self.endpoint_url}) from e

        except httpx.HTTPStatusError as e:
            elapsed = time.time() - start_time
            response_text = e.response.text[:500] if e.response else ""
            err_msg = f"OCR Service trả về mã lỗi HTTP {e.response.status_code}: {response_text}"
            logger.exception(f"[OCR_HTTP_ERROR] {err_msg}")
            raise OCRHTTPError(
                err_msg,
                http_status=e.response.status_code,
                details={"file_name": actual_name, "status_code": e.response.status_code, "response": response_text},
            ) from e

        except httpx.RequestError as e:
            err_msg = f"Lỗi giao tiếp với OCR Service khi xử lý file '{actual_name}': {e}"
            logger.exception(f"[OCR_SERVICE_ERROR] {err_msg}")
            raise OCRServiceException(err_msg, details={"file_name": actual_name, "error": str(e)}) from e

    async def aextract_markdown(
        self,
        pdf_input: Union[str, Path, bytes, BinaryIO],
        file_name: Optional[str] = None,
        rasterize: Optional[bool] = None,
        enable_correction: Optional[bool] = None,
        process_table: Optional[bool] = None,
        use_celery: Optional[bool] = None,
        use_cache: Optional[bool] = None,
    ) -> str:
        """
        Bản async của extract_markdown phục vụ luồng bất đồng bộ FastAPI.
        """
        content, _ = await self.aextract_full(
            pdf_input=pdf_input,
            file_name=file_name,
            rasterize=rasterize,
            enable_correction=enable_correction,
            process_table=process_table,
            use_celery=use_celery,
            use_cache=use_cache,
        )
        return content
