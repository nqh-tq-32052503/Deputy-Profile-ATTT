import os
from enum import Enum
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Tự động nạp cấu hình từ .env nếu tồn tại
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv(override=True)


class DocType(str, Enum):
    QTCT = "QTCT"                       # 3.1 Quá trình công tác
    LUONG = "LUONG"                     # 3.2 Nâng bậc lương
    PHU_CAP = "PHU_CAP"                 # 3.3 Quyết định phụ cấp
    THI_DUA = "THI_DUA"                 # 3.4 Công nhận danh hiệu thi đua
    KHEN_THUONG = "KHEN_THUONG"         # 3.5 Khen thưởng
    KY_NIEM_CHUONG = "KY_NIEM_CHUONG"   # 3.6 Kỷ niệm chương
    QUY_HOACH = "QUY_HOACH"             # 3.7 Phê duyệt quy hoạch chức danh


def _parse_bool(val: Optional[str], default: bool) -> bool:
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in ("true", "1", "t", "yes", "y")


def _parse_optional_bool(val: Optional[str], default: Optional[bool] = None) -> Optional[bool]:
    if val is None:
        return default
    v = val.strip().lower()
    if v == "" or v in ("none", "null"):
        return None
    if v in ("true", "1", "t", "yes", "y"):
        return True
    if v in ("false", "0", "f", "no", "n"):
        return False
    return default


# App & System
API_VERSION = "4.2.0"
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
APP_ENV = os.getenv("APP_ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# API Key Authentication (BUG-1113) - Đọc duy nhất từ file .env
API_KEY = os.getenv("API_KEY", "")
REQUIRE_API_KEY = _parse_bool(os.getenv("REQUIRE_API_KEY"), default=True)

# Files & Cache (BUG-1123)
MAX_FILES = 5
MIN_FILE_SIZE_BYTES = int(os.getenv("MIN_FILE_SIZE_BYTES", "100"))
MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_MB", "30")) * 1024 * 1024
ALLOWED_MIME_TYPES = {"application/pdf"}
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", str(24 * 3600)))


# OCR Service
OCR_SERVICE_URL = os.getenv("OCR_SERVICE_URL", "https://<ocr-service-host>:<port>/v1/extract")
OCR_API_KEY = os.getenv("OCR_API_KEY", "")
OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "60"))
OCR_RASTERIZE = _parse_bool(os.getenv("OCR_RASTERIZE", os.getenv("RASTERIZE")), default=True)
OCR_ENABLE_CORRECTION = _parse_bool(
    os.getenv("OCR_ENABLE_CORRECTION", os.getenv("ENABLE_CORRECTION")), default=True
)
OCR_PROCESS_TABLE = _parse_bool(
    os.getenv("OCR_PROCESS_TABLE", os.getenv("PROCESS_TABLE")), default=True
)
OCR_USE_CELERY = _parse_optional_bool(
    os.getenv("OCR_USE_CELERY", os.getenv("USE_CELERY")), default=False
)
OCR_USE_CACHE = _parse_optional_bool(
    os.getenv("OCR_USE_CACHE", os.getenv("USE_CACHE")), default=False
)

# LLM Service (Self-hosted model / OpenAI compatible)
LLM_API_BASE_URL = os.getenv("LLM_API_BASE_URL", "https://<llm-host>:<port>/v1")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "your_model_name_here")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))