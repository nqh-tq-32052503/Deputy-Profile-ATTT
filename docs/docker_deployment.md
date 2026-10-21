# Hướng dẫn Triển khai với Docker & Docker Compose

Tài liệu này cung cấp hướng dẫn toàn diện để triển khai, vận hành và bảo trì **DeputyProfiling AI Service** trong môi trường Docker sử dụng Docker Compose.

---

## 1. Yêu cầu hệ thống (Prerequisites)

- **Hệ điều hành**: Linux (Ubuntu 20.04/22.04/24.04, Debian 11/12, CentOS/RHEL 8/9) hoặc macOS/Windows có Docker Desktop.
- **Docker Engine**: Phiên bản `>= 24.0.0`
- **Docker Compose**: Phiên bản `>= 2.20.0` (tích hợp sẵn qua lệnh `docker compose`)
- **Tài nguyên tối thiểu**:
  - CPU: 2 Cores
  - RAM: 4 GB
  - Dung lượng ổ đĩa: Tối thiểu 5 GB trống (chứa Docker image và lưu trữ logs)
- **Mạng (Network)**: Kết nối được tới:
  - Dịch vụ OCR backend (`OCR_SERVICE_URL`)
  - Máy chủ mô hình LLM (`LLM_API_BASE_URL`)

Kiểm tra phiên bản trước khi chạy:
```bash
docker --version
docker compose version
```

---

## 2. Cấu trúc Triển khai Docker

```text
DeputyProfiling/
├── Dockerfile              # Dockerfile tối ưu hóa (multi-layer, non-root user appuser)
├── docker-compose.yml      # Cấu hình dịch vụ, container name, volume, healthcheck
├── .dockerignore           # Bỏ qua các file tạm, test binaries, git logs
├── .env.example            # Template cấu hình mẫu
├── .env                    # File cấu hình thực tế (được mount vào container)
└── logs/                   # Thư mục host được mount để lưu trữ log hệ thống
```

### 2.1. Thiết kế an toàn trong `Dockerfile`
- **Base image**: `python:3.11-slim` giảm thiểu kích thước và bề mặt tấn công.
- **Bảo mật Non-root User**: Container chạy dưới tài khoản `appuser` (thuộc `appgroup`), không chạy với quyền `root`.
- **Healthcheck tích hợp**: Tự động gọi định kỳ `curl -f http://localhost:8000/health` mỗi 30 giây để Docker daemon theo dõi trạng thái sống sót của container.
- **Layer caching**: Cài đặt `requirements.txt` trước khi copy mã nguồn giúp tận dụng tối đa cache của Docker khi rebuild.

### 2.2. Thiết kế trong `docker-compose.yml`
- **Container Name**: `deputy-profiling-ai`
- **Port Mapping**: `${APP_PORT:-8000}:${APP_PORT:-8000}`
- **Volume Mount**: `./logs:/app/logs` — Đảm bảo toàn bộ log và các tệp bảng đối soát CSV không bị mất khi container bị hủy hoặc cập nhật.
- **Restart Policy**: `restart: unless-stopped` — Tự động khởi động lại container khi hệ thống reboot hoặc service gặp sự cố.

---

## 3. Các bước Triển khai Chi tiết

### Bước 1: Chuẩn bị file cấu hình môi trường `.env`

Tạo file `.env` từ file mẫu:
```bash
cp .env.example .env
```

Mở `.env` và chỉnh sửa các tham số thực tế:

```ini
# ==============================================================================
# CẤU HÌNH DỊCH VỤ ỨNG DỤNG
# ==============================================================================
APP_HOST=0.0.0.0
APP_PORT=8000
APP_ENV=production
LOG_LEVEL=INFO

# Giới hạn dung lượng file PDF tải lên (MB) và thời gian sống Cache (giây)
MAX_FILE_SIZE_MB=30
CACHE_TTL_SECONDS=86400

# ==============================================================================
# CẤU HÌNH DỊCH VỤ OCR BACKEND
# ==============================================================================
OCR_SERVICE_URL=http://10.x.x.x:8085/v1/extract
OCR_API_KEY=your_ocr_api_key_if_any
OCR_TIMEOUT_SECONDS=60
OCR_RASTERIZE=true
OCR_ENABLE_CORRECTION=true
OCR_PROCESS_TABLE=true
OCR_USE_CELERY=false
OCR_USE_CACHE=false

# ==============================================================================
# CẤU HÌNH DỊCH VỤ MÔ HÌNH LLM
# ==============================================================================
LLM_API_BASE_URL=http://10.x.x.x:8000/v1
LLM_MODEL_NAME=Qwen2.5-72B-Instruct
LLM_API_KEY=EMPTY
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=4096
LLM_TIMEOUT_SECONDS=120
```

### Bước 2: Tạo thư mục lưu trữ logs trên máy chủ

Đảm bảo thư mục `logs/` tồn tại trên host trước khi khởi chạy:
```bash
mkdir -p logs
```

### Bước 3: Khởi chạy dịch vụ với Docker Compose

Thực hiện build image và chạy ở chế độ chạy ngầm (detached mode):
```bash
docker compose up -d --build
```

Kiểm tra trạng thái container:
```bash
docker compose ps
```

Kết quả mong đợi:
```text
NAME                   IMAGE                         COMMAND                  SERVICE                STATUS                    PORTS
deputy-profiling-ai    deputy-profiling-ai:latest    "sh -c 'uvicorn app:…"   deputy-profiling-ai    Up (healthy)              0.0.0.0:8000->8000/tcp
```

### Bước 4: Kiểm tra trạng thái hoạt động (Healthcheck & Swagger UI)

Kiểm tra endpoint Healthcheck:
```bash
curl -i http://localhost:8000/health
```

Phản hồi thành công:
```json
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","version":"4.2.0"}
```

Mở trình duyệt truy cập tài liệu Swagger UI:
```text
http://<server-ip>:8000/docs
```

---

## 4. Quản trị & Vận hành Thường nhật

### 4.1. Xem log thời gian thực (Real-time logs)
```bash
# Xem log tổng hợp
docker compose logs -f

# Xem 100 dòng log gần nhất
docker compose logs --tail=100 -f deputy-profiling-ai
```

### 4.2. Khởi động lại dịch vụ (Restart)
```bash
docker compose restart deputy-profiling-ai
```

### 4.3. Dừng dịch vụ (Stop)
```bash
# Dừng container (giữ nguyên container và network)
docker compose stop

# Dừng và gỡ bỏ container, network (dữ liệu logs/ vẫn được giữ nguyên)
docker compose down
```

### 4.4. Cập nhật mã nguồn mới (Rebuild & Update)
Khi có phiên bản mã nguồn mới:
```bash
# 1. Kéo code mới từ git
git pull origin main

# 2. Build lại image và cập nhật container không làm gián đoạn volume
docker compose up -d --build
```

### 4.5. Kiểm tra tài nguyên tiêu thụ
```bash
docker stats deputy-profiling-ai --no-stream
```

---

## 5. Xử lý sự cố thường gặp (Troubleshooting)

### 5.1. Container có trạng thái `unhealthy`
- **Nguyên nhân**: Port trong container không khớp với cổng Uvicorn lắng nghe, hoặc dịch vụ chưa khởi động kịp trong 10 giây đầu.
- **Cách khắc phục**:
  - Kiểm tra log chi tiết: `docker compose logs deputy-profiling-ai`.
  - Đảm bảo biến `APP_PORT` trong `.env` khớp với port định cấu hình.

### 5.2. Lỗi `OCRConnectionError` hoặc `LLMConnectionError`
- **Hiện tượng**: API trả lỗi mã 502/503 khi upload file.
- **Nguyên nhân**: Container Docker không kết nối được tới IP máy chủ OCR hoặc LLM (thường do firewall hoặc IP `127.0.0.1` của máy chủ host).
- **Lưu ý**: Nếu OCR hoặc LLM chạy trên cùng máy host với Docker, không thể dùng `localhost` hay `127.0.0.1` bên trong `.env`. Hãy cấu hình IP mạng LAN thực tế của máy chủ hoặc dùng `host.docker.internal`.

### 5.3. Lỗi quyền ghi thư mục `logs/`
- **Hiện tượng**: `PermissionError: [Errno 13] Permission denied: '/app/logs/...'`
- **Nguyên nhân**: Thư mục `logs/` trên host được tạo bởi root và tài khoản non-root `appuser` (UID 999/1000) trong container không có quyền ghi.
- **Cách khắc phục**:
  ```bash
  chmod -R 777 logs
  ```
