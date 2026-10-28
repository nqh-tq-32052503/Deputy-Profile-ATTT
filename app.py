import asyncio
import io
from datetime import datetime, timezone
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

import filetype
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Security,
    UploadFile,
    status,
)
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pypdf import PdfReader

from core.cache import CacheManager, cache_manager
from core.config import (
    ALLOWED_MIME_TYPES,
    API_KEY,
    API_VERSION,
    MAX_FILE_SIZE_BYTES,
    MAX_FILES,
    MIN_FILE_SIZE_BYTES,
    REQUIRE_API_KEY,
    DocType,
)
from core.exceptions import DeputyProfilingException
from core.logger import setup_logger
from core.schemas import (
    ErrorItem,
    ExtractInitResponse,
    ExtractionResult,
    ExtractPollResponse,
    HealthResponse,
    ProcessStatus,
)
from extractors import get_extractor
from services.doc_classifier import aclassify_doc_type, apply_doc_type_verification
from services.ocr_service import OCRService

# Cấu hình logging chuẩn
logger = setup_logger("app")

# BUG-1122: Vô hiệu hóa tài liệu API trên production theo mặc định.
# Chỉ bật khi chủ động khai báo API_DOCS_ENABLED=true (ví dụ môi trường development).
API_DOCS_ENABLED = os.getenv("API_DOCS_ENABLED", "false").strip().lower() == "true"

app = FastAPI(
    title="Deputy Profiling AI Service",
    description="Dịch vụ AI trích xuất thông tin văn bản Hồ sơ Đại biểu (HSĐB)",
    version=API_VERSION,
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
)


def _patch_openapi_schema(schema: Any) -> None:
    """Tùy biến schema để Swagger UI hiển thị format: binary cho file upload."""
    if isinstance(schema, dict):
        if schema.get("contentMediaType") == "application/octet-stream":
            schema.pop("contentMediaType", None)
            schema["format"] = "binary"
        for v in schema.values():
            _patch_openapi_schema(v)
    elif isinstance(schema, list):
        for item in schema:
            _patch_openapi_schema(item)


def _patch_doc_type_dropdown(schemas: dict, schema_key: str) -> None:
    """Cung cấp dropdown enum doc_type cho request body schema trên Swagger UI."""
    body_schema = schemas.get(schema_key)
    if body_schema and "properties" in body_schema and "doc_type" in body_schema["properties"]:
        body_schema["properties"]["doc_type"]["enum"] = [e.value for e in DocType]
        body_schema["properties"]["doc_type"]["default"] = DocType.QTCT.value


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    _patch_openapi_schema(openapi_schema)
    schemas = openapi_schema.get("components", {}).get("schemas", {})
    _patch_doc_type_dropdown(schemas, "Body_extract_document_hsdb_extract_post")

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# In-memory store for async task tracking: request_id -> dict
tasks_store: Dict[str, dict] = {}
ocr_service = OCRService()

DOC_TYPE_FORM_DESC = "Một trong 7 mã văn bản được hỗ trợ"
FILES_FORM_DESC = "Từ 1 đến 5 file PDF (tối đa 30MB/file)"
FORCE_REPROCESS_FORM_DESC = "Bỏ qua cache nếu đặt True"


def concatenate_pdf_bytes(pdf_bytes_list: List[bytes]) -> bytes:
    """
    Ghép (concatenate) danh sách bytes của nhiều file PDF thành 1 file PDF bytes duy nhất bằng pypdf (BSD-3-Clause).
    Nếu chỉ có 1 file, trả về nguyên bản không qua xử lý.
    """
    if not pdf_bytes_list:
        raise ValueError("Danh sách bytes file PDF rỗng.")
    if len(pdf_bytes_list) == 1:
        return pdf_bytes_list[0]

    try:
        from pypdf import PdfWriter
        writer = PdfWriter()
        for b in pdf_bytes_list:
            writer.append(io.BytesIO(b))
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception as err:
        raise RuntimeError(f"Lỗi khi ghép các file PDF: {err}") from err


def concatenate_pdf_files(files_data: List[Tuple[str, bytes]]) -> List[Tuple[str, bytes]]:
    """
    Nếu người dùng upload lên 2 hoặc nhiều file PDF một lúc, hàm này sẽ ghép (concatenate)
    chúng thành 1 file PDF duy nhất trước khi đưa vào pipeline xử lý.

    Args:
        files_data: Danh sách các tuple (filename, file_bytes).

    Returns:
        Danh sách chứa đúng 1 tuple (merged_filename, merged_bytes) nếu len(files_data) >= 2,
        hoặc giữ nguyên danh sách files_data ban đầu nếu len(files_data) <= 1.
    """
    if not files_data or len(files_data) <= 1:
        return files_data

    logger.info(
        f"Phát hiện {len(files_data)} file PDF được tải lên. "
        f"Tiến hành ghép (concatenate) thành 1 file duy nhất trước khi đưa vào pipeline..."
    )
    first_filename = files_data[0][0]
    base_name = os.path.splitext(first_filename)[0]
    merged_filename = f"{base_name}_merged.pdf"

    pdf_bytes_list = [content for _, content in files_data]
    try:
        merged_bytes = concatenate_pdf_bytes(pdf_bytes_list)
        logger.info(
            f"Ghép thành công {len(files_data)} file PDF thành '{merged_filename}' ({len(merged_bytes):,} bytes)."
        )
        return [(merged_filename, merged_bytes)]
    except Exception as e:
        logger.exception(f"Lỗi khi ghép các file PDF: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lỗi khi ghép các file PDF đã tải lên. Vui lòng kiểm tra lại tính toàn vẹn của tệp.",
        )


# Alias để thuận tiện khi gọi
concatenate_pdfs = concatenate_pdf_files


async def process_document_task(
    request_id: str,
    doc_type_enum: DocType,
    files_data: List[tuple],  # List of (filename, bytes)
    cache_key: str,
):
    """
    Background worker thực hiện OCR và bóc tách thông tin.
    """
    task_start_time = time.time()
    logger.info(
        f"[{request_id}] === BẮT ĐẦU XỬ LÝ TIẾN TRÌNH: doc_type='{doc_type_enum.value}', "
        f"số lượng file: {len(files_data)} ==="
    )

    try:
        # Nếu có từ 2 file PDF trở lên, đảm bảo ghép thành 1 file duy nhất trước khi đưa vào OCR
        if len(files_data) > 1:
            files_data = concatenate_pdf_files(files_data)

        # 1. Thực hiện OCR từng file PDF thành Markdown và lấy full OCR data
        logger.info(f"[{request_id}] [Bước 1/3] Bắt đầu OCR cho {len(files_data)} file PDF...")
        markdown_chunks = []
        ocr_data_list = []
        for file_idx, (filename, file_bytes) in enumerate(files_data, start=1):
            logger.info(
                f"[{request_id}] Đang thực hiện OCR file ({file_idx}/{len(files_data)}): "
                f"'{filename}' ({len(file_bytes):,} bytes)..."
            )
            md_chunk, ocr_json = await ocr_service.aextract_full(file_bytes, file_name=filename)
            markdown_chunks.append(md_chunk)
            ocr_data_list.append(ocr_json)

        combined_markdown = "\n\n---\n\n".join(markdown_chunks)
        logger.info(
            f"[{request_id}] [Bước 1/3] OCR hoàn tất thành công. Tổng chiều dài markdown: "
            f"{len(combined_markdown):,} ký tự."
        )

        # 2. Lấy bộ trích xuất tương ứng theo doc_type
        logger.info(f"[{request_id}] [Bước 2/3] Khởi tạo extractor cho doc_type='{doc_type_enum.value}'...")
        extractor = get_extractor(doc_type_enum)

        # 3. Trích xuất thông tin & Phân loại doc_type bằng LLM
        logger.info(f"[{request_id}] [Bước 3/3] Bắt đầu bóc tách dữ liệu có cấu trúc và nhận diện doc_type với LLM...")

        async def _safe_classify():
            try:
                return await aclassify_doc_type(combined_markdown)
            except Exception as ex:
                logger.warning(f"[{request_id}] Phân loại doc_type gặp lỗi: {ex}")
                return None

        classification_task = asyncio.create_task(_safe_classify())
        extraction_result = await extractor.aextract(
            combined_markdown,
            ocr_data=ocr_data_list[0] if ocr_data_list else None,
            ocr_data_list=ocr_data_list,
        )
        classification = await classification_task

        # Đối soát và bổ sung cảnh báo DOC_TYPE_MISMATCH nếu AI detect khác param
        if classification and classification.doc_type_detected not in ("UNKNOWN", ""):
            apply_doc_type_verification(
                extraction_result,
                classification.doc_type_detected,
                doc_type_enum,
            )

        # Chuyển đổi sang ExtractionResult / dict nếu cần
        if hasattr(extraction_result, "model_dump"):
            result_dict = extraction_result.model_dump()
        else:
            result_dict = extraction_result.dict()

        # 4. Lưu Cache
        cache_manager.set(cache_key, result_dict)
        logger.info(f"[{request_id}] Đã lưu kết quả trích xuất vào Cache (key: {cache_key[:16]}...).")

        # 5. Cập nhật task status
        tasks_store[request_id] = {
            "status": ProcessStatus.FINISHED,
            "result": result_dict,
            "error": None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        total_elapsed = time.time() - task_start_time
        logger.info(
            f"[{request_id}] === TIẾN TRÌNH HOÀN THÀNH THÀNH CÔNG trong {total_elapsed:.2f}s "
            f"(Tổng số cá nhân: {result_dict.get('tong_so_ca_nhan', 0)}, "
            f"Số cảnh báo: {len(result_dict.get('warnings', []))}) ==="
        )

    except DeputyProfilingException as e:
        total_elapsed = time.time() - task_start_time
        logger.exception(
            f"[{request_id}] === TIẾN TRÌNH THẤT BẠI sau {total_elapsed:.2f}s "
            f"[{e.code}]: {e.message} ==="
        )
        tasks_store[request_id] = {
            "status": ProcessStatus.FAILED,
            "result": None,
            "error": {
                "code": e.code,
                "message": e.message,
            },
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        total_elapsed = time.time() - task_start_time
        logger.exception(
            f"[{request_id}] === TIẾN TRÌNH THẤT BẠI DO LỖI HỆ THỐNG KHÔNG XÁC ĐỊNH "
            f"sau {total_elapsed:.2f}s: {e} ==="
        )
        tasks_store[request_id] = {
            "status": ProcessStatus.FAILED,
            "result": None,
            "error": {
                "code": "INTERNAL_PROCESSING_ERROR",
                "message": "Đã xảy ra lỗi nội bộ trong quá trình xử lý tài liệu.",
            },
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }


# Cấu hình xác thực API Key qua header X-API-Key (BUG-1113)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
) -> Optional[str]:
    """
    Xác thực API Key qua header X-API-Key cho các endpoint bóc tách (BUG-1113).
    API Key chỉ được cấu hình và nạp từ file .env.
    """
    if not REQUIRE_API_KEY:
        return x_api_key

    if not API_KEY:
        logger.error("Hệ thống chưa được thiết lập API_KEY trong file .env.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dịch vụ chưa được cấu hình API Key bảo mật trong file .env.",
        )

    if not x_api_key:
        logger.warning("Từ chối truy cập: Thiếu header 'X-API-Key'.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu API Key xác thực. Vui lòng cung cấp header 'X-API-Key'.",
        )

    if not secrets.compare_digest(x_api_key, API_KEY):
        logger.warning("Từ chối truy cập: 'X-API-Key' không chính xác.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key không hợp lệ.",
        )

    return x_api_key


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Bắt mọi exception chưa được xử lý để ngăn chặn lộ chuỗi exception ra client (BUG-1120).
    Ghi chi tiết traceback vào logger server, chỉ trả message thông báo chung an toàn cho client.
    """
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    logger.exception(f"Unhandled exception tại {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Đã xảy ra lỗi máy chủ nội bộ. Vui lòng thử lại sau."},
    )


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    2.3. Health Check endpoint
    """
    return HealthResponse(status="ok", version=API_VERSION)


async def _read_and_validate_upload_files(
    files: List[UploadFile],
) -> Tuple[List[tuple], List[bytes]]:
    """
    Validate số lượng, phần mở rộng, dung lượng, Magic Bytes và tính hợp lệ của cấu trúc PDF (BUG-1123).
    """
    if not files or len(files) == 0:
        logger.warning("Từ chối yêu cầu: Không có file PDF nào được gửi lên.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yêu cầu tối thiểu 1 file PDF.",
        )
    if len(files) > MAX_FILES:
        logger.warning(f"Từ chối yêu cầu: Số lượng file ({len(files)}) vượt quá giới hạn ({MAX_FILES}).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Số lượng file vượt quá giới hạn cho phép ({MAX_FILES} files).",
        )

    files_data: List[tuple] = []
    file_bytes_list: List[bytes] = []

    for upload_file in files:
        filename = upload_file.filename or "unknown.pdf"

        # 1.1. Kiểm tra phần mở rộng đuôi file (.pdf)
        if not filename.lower().endswith(".pdf"):
            logger.warning(f"Từ chối yêu cầu: File '{filename}' không có phần mở rộng .pdf hợp lệ.")
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"File '{filename}' không phải là định dạng PDF hợp lệ (yêu cầu đuôi file .pdf).",
            )

        content = await upload_file.read()

        # 1.2. Kiểm tra kích thước tối thiểu và tối đa
        if len(content) < MIN_FILE_SIZE_BYTES:
            logger.warning(
                f"Từ chối yêu cầu: File '{filename}' có dung lượng ({len(content)} bytes) "
                f"nhỏ hơn kích thước tối thiểu ({MIN_FILE_SIZE_BYTES} bytes)."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{filename}' rỗng hoặc dung lượng quá nhỏ ({len(content)} bytes), không phải là file PDF hợp lệ.",
            )

        if len(content) > MAX_FILE_SIZE_BYTES:
            logger.warning(
                f"Từ chối yêu cầu: File '{filename}' dung lượng {len(content):,} bytes "
                f"vượt quá giới hạn {MAX_FILE_SIZE_BYTES:,} bytes."
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File '{filename}' có dung lượng vượt quá giới hạn 30MB.",
            )

        # 2. Kiểm tra Magic Bytes bằng thư viện filetype
        kind = filetype.guess(content)
        if kind is None or kind.mime != "application/pdf":
            detected_type = kind.mime if kind else "Không xác định"
            logger.warning(
                f"Từ chối yêu cầu: File '{filename}' có Magic bytes không khớp với PDF "
                f"(nhận diện: {detected_type})."
            )
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Nội dung file '{filename}' không phải là định dạng PDF hợp lệ (Magic bytes không khớp).",
            )

        # 3. Đọc thử file PDF bằng thư viện pypdf
        try:
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) == 0:
                raise ValueError("File PDF rỗng, không chứa trang tài liệu nào.")
        except Exception as e:
            logger.warning(f"Từ chối yêu cầu: File '{filename}' bị lỗi cấu trúc PDF khi đọc bằng pypdf: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{filename}' bị hỏng cấu trúc hoặc không thể phân tích cú pháp PDF.",
            )

        files_data.append((filename, content))
        file_bytes_list.append(content)

    if len(files_data) > 1:
        files_data = concatenate_pdf_files(files_data)
        file_bytes_list = [content for _, content in files_data]

    return files_data, file_bytes_list


@app.post(
    "/hsdb/extract",
    response_model=ExtractInitResponse,
    status_code=status.HTTP_200_OK,
    tags=["Extraction"],
    dependencies=[Depends(verify_api_key)],
)
async def extract_document(
    background_tasks: BackgroundTasks,
    doc_type: str = Form(..., description=DOC_TYPE_FORM_DESC),
    files: List[UploadFile] = File(..., description=FILES_FORM_DESC),
    force_reprocess: bool = Form(False, description=FORCE_REPROCESS_FORM_DESC),
):
    """
    2.1. Upload File & Khởi tạo tiến trình trích xuất văn bản.
    """
    logger.info(
        f"Nhận yêu cầu trích xuất: doc_type='{doc_type}', files={len(files)} file(s), "
        f"force_reprocess={force_reprocess}"
    )

    # 1. Validate doc_type
    try:
        doc_type_enum = DocType(doc_type.strip())
    except ValueError:
        logger.warning(f"Từ chối yêu cầu: doc_type '{doc_type}' không hợp lệ.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"doc_type '{doc_type}' không hợp lệ. Phải là một trong: {[e.value for e in DocType]}",
        )

    # 2 & 3. Validate và đọc files
    files_data, file_bytes_list = await _read_and_validate_upload_files(files)

    # 4. Kiểm tra Cache
    cache_key = CacheManager.compute_key(doc_type_enum.value, file_bytes_list)
    if not force_reprocess:
        cached_result = cache_manager.get(cache_key)
        if cached_result is not None:
            req_id = str(uuid.uuid4())
            logger.info(
                f"Cache HIT [key: {cache_key[:16]}...]. Trả ngay kết quả đã lưu cho request_id={req_id}."
            )
            return ExtractInitResponse(
                request_id=req_id,
                status=ProcessStatus.FINISHED,
                is_cached=True,
                result=cached_result,
            )

    # 5. Khởi tạo tiến trình xử lý nền
    request_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    tasks_store[request_id] = {
        "status": ProcessStatus.PROCESSING,
        "result": None,
        "error": None,
        "created_at": created_at,
    }

    logger.info(
        f"Khởi tạo background task [request_id={request_id}] cho doc_type='{doc_type_enum.value}' "
        f"với {len(files_data)} file(s)."
    )

    background_tasks.add_task(
        process_document_task,
        request_id=request_id,
        doc_type_enum=doc_type_enum,
        files_data=files_data,
        cache_key=cache_key,
    )

    return ExtractInitResponse(
        request_id=request_id,
        status=ProcessStatus.PROCESSING,
        created_at=created_at,
    )


@app.get(
    "/hsdb/extract/{request_id}",
    response_model=ExtractPollResponse,
    tags=["Extraction"],
    dependencies=[Depends(verify_api_key)],
)
async def get_extraction_status(request_id: str):
    """
    2.2. Kiểm tra trạng thái & Lấy kết quả bóc tách.
    """
    task = tasks_store.get(request_id)
    if not task:
        logger.warning(f"Polling không tìm thấy tiến trình: request_id='{request_id}'")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tiến trình với request_id '{request_id}' hoặc đã quá hạn.",
        )

    logger.debug(f"Polling kiểm tra trạng thái [request_id={request_id}]: status={task['status']}")
    return ExtractPollResponse(
        request_id=request_id,
        status=task["status"],
        result=task.get("result"),
        error=task.get("error"),
    )


if __name__ == "__main__":
    import uvicorn
    from core.config import APP_HOST, APP_PORT

    uvicorn.run("app:app", host=APP_HOST, port=APP_PORT, reload=False)
