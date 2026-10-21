# DeputyProfiling AI Service — Trích xuất thông tin văn bản Hồ sơ Đại biểu (HSĐB)

**DeputyProfiling AI Service** là dịch vụ xử lý tài liệu hành chính ứng dụng AI, tiếp nhận các văn bản quyết định/nghị quyết dạng PDF (bao gồm bản scan mộc đỏ, chữ ký và chữ viết tay), thực hiện OCR làm giàu dữ liệu, phân loại văn bản và bóc tách thông tin có cấu trúc để phục vụ tính năng **tự động điền (auto-fill)** vào Hệ thống Hồ sơ Đại biểu (HSĐB).

---

## 1. Khởi chạy Nhanh với Docker Compose (Khuyến nghị)

Toàn bộ hệ thống được đóng gói và vận hành chính thức thông qua **Docker Compose**.

### Bước 1: Thiết lập file môi trường
```bash
cp .env.example .env
```
Chỉnh sửa cấu hình kết nối tới **OCR Service** và **LLM Host** trong `.env`:
- `OCR_SERVICE_URL`: Endpoint dịch vụ OCR (ví dụ: `http://<ocr-host>:<port>/v1/extract`)
- `LLM_API_BASE_URL`: Base URL của máy chủ LLM (ví dụ: `http://<llm-host>:<port>/v1`)
- `LLM_MODEL_NAME`: Tên model LLM (ví dụ: `Qwen2.5-72B-Instruct`)
- `APP_PORT`: Cổng dịch vụ lắng nghe (mặc định: `8000`)

### Bước 2: Build và Khởi chạy Container
```bash
# Tạo thư mục mount lưu trữ log
mkdir -p logs

# Khởi chạy dịch vụ ngầm (detached mode)
docker compose up -d --build
```

### Bước 3: Kiểm tra trạng thái hoạt động
```bash
# Kiểm tra Healthcheck
curl -i http://localhost:8000/health

# Xem log thời gian thực
docker compose logs -f
```

Giao diện tương tác Swagger UI: `http://localhost:8000/docs`.

---

## 2. Cấu trúc Thư mục Dự án

```text
DeputyProfiling/
├── API-trich-xuat-vbtl-hsdb-v5.md  # Tài liệu đặc tả nghiệp vụ & API gốc (v4.2.0)
├── Dockerfile                      # Dockerfile tối ưu hoá (Python 3.11-slim, non-root user)
├── docker-compose.yml              # Quản lý triển khai container, volumes, healthcheck
├── .dockerignore                   # Quy tắc loại trừ file build Docker
├── .env.example                    # Template biến môi trường
├── .env                            # Cấu hình môi trường thực tế (được gitignore bảo vệ)
├── app.py                          # Ứng dụng FastAPI chính (Endpoints & Background worker)
├── run.sh                          # Script khởi chạy phụ trợ uvicorn
├── requirements.txt                # Danh sách thư viện Python
├── README.md                       # Tài liệu hướng dẫn tổng quan dự án
│
├── docs/                           # TÀI LIỆU KỸ THUẬT CHI TIẾT
│   ├── architecture.md             # Kiến trúc hệ thống, luồng dữ liệu & sơ đồ Mermaid
│   ├── docker_deployment.md        # Hướng dẫn chi tiết vận hành & bảo trì Docker
│   ├── api_specification.md        # Đặc tả chi tiết các endpoint HTTP, mã lỗi & cảnh báo
│   └── document_types.md           # Quy tắc nghiệp vụ chi tiết cho 7 loại văn bản
│
├── core/                           # Các module nền tảng dùng chung
│   ├── config.py                   # Cấu hình hằng số, Enum DocType, giới hạn file, TTL
│   ├── schemas.py                  # Pydantic schemas chung (MetadataBase, Warning, Result...)
│   ├── cache.py                    # Quản lý bộ nhớ đệm theo mã băm SHA-256 (24h TTL)
│   ├── exceptions.py               # Hệ thống Exception phân cấp chuẩn hóa
│   └── logger.py                   # Cấu hình logging chuẩn hóa
│
├── services/                       # Các dịch vụ xử lý nền tảng
│   ├── ocr_service.py              # Xử lý OCR, phục dựng bảng & bù đắp header artifacts
│   ├── doc_classifier.py           # Phân loại tự động loại văn bản & cảnh báo bất đồng
│   └── llm_service.py              # Client LLM, lọc chức vụ Đảng & chuẩn hóa chức danh
│
├── extractors/                     # Các module bóc tách thông tin theo từng doc_type
│   ├── __init__.py                 # Quản lý EXTRACTOR_REGISTRY & factory get_extractor
│   ├── base.py                     # Interface BaseExtractor
│   ├── qtct/                       # 3.1. Quá trình công tác (1 cá nhân)
│   ├── luong/                      # 3.2. Nâng bậc lương (1 cá nhân)
│   ├── phu_cap/                    # 3.3. Quyết định phụ cấp
│   ├── thi_dua/                    # 3.4. Danh hiệu thi đua
│   ├── khen_thuong/                # 3.5. Khen thưởng (hỗ trợ danh sách dài nhiều trang)
│   ├── ky_niem_chuong/             # 3.6. Kỷ niệm chương
│   └── quy_hoach/                  # 3.7. Phê duyệt quy hoạch chức danh
├── launch_all.py                   # Công cụ CLI gửi hàng loạt file PDF và polling
├── test_cases/                     # Dữ liệu kịch bản kiểm thử mẫu
└── tests/                          # Bộ kiểm thử tự động (Unit test & Integration test)
```

---

## 3. Danh mục 7 Loại Văn bản Hỗ trợ (`doc_type`)

| Mã `doc_type` | Tên nghiệp vụ | Form đích tương ứng trên HSĐB | Đối tượng |
| :--- | :--- | :--- | :---: |
| **`QTCT`** | Quá trình công tác (Điều động, bổ nhiệm, luân chuyển...) | Thêm mới quá trình công tác | 1 cá nhân |
| **`LUONG`** | Nâng bậc lương (Thường xuyên / Trước hạn) | Thêm mới quá trình lương | 1 cá nhân |
| **`PHU_CAP`** | Quyết định phụ cấp (Chức vụ, kiêm nhiệm, trách nhiệm...) | Thêm mới quá trình phụ cấp | 1 cá nhân |
| **`THI_DUA`** | Công nhận danh hiệu thi đua (Cá nhân / Tập thể) | Thi đua – Khen thưởng (`type = 1`) | N đối tượng |
| **`KHEN_THUONG`** | Khen thưởng (Bằng khen, Huân chương, Huy chương...) | Thi đua – Khen thưởng (`type = 2`) | N đối tượng |
| **`KY_NIEM_CHUONG`** | Tặng Kỷ niệm chương "Vì sự nghiệp Quốc hội VN" | Quản lý kỷ niệm chương | N cá nhân |
| **`QUY_HOACH`** | Phê duyệt quy hoạch chức danh cán bộ | Thêm mới Quyết định Quy hoạch | N cá nhân |

---

## 4. Hướng dẫn Gọi API Cơ bản

Hệ thống hoạt động theo mô hình **bất đồng bộ (Polling Flow)**:

### Bước 1: Gửi yêu cầu trích xuất (`POST /hsdb/extract`)
```bash
curl -X POST "http://localhost:8000/hsdb/extract" \
  -F "doc_type=QTCT" \
  -F "files=@quyet_dinh_dieu_dong.pdf;type=application/pdf"
```

Phản hồi:
```json
{
  "request_id": "c7a812ef-29b1-4b16-9ef0-0a568b209d84",
  "status": "PROCESSING",
  "created_at": "2026-10-12T10:00:00Z"
}
```

*Lưu ý*: Nếu file đã từng trích xuất trong 24 giờ và không đặt `force_reprocess=true`, API sẽ trả kết quả ngay lập tức (`is_cached: true`).

### Bước 2: Kiểm tra trạng thái & Nhận kết quả (`GET /hsdb/extract/{request_id}`)
Client thực hiện polling định kỳ (mỗi 2-3 giây):
```bash
curl -X GET "http://localhost:8000/hsdb/extract/c7a812ef-29b1-4b16-9ef0-0a568b209d84"
```

Khi xử lý xong, hệ thống trả về `status: "FINISHED"` kèm theo toàn bộ đối tượng `result` (metadata, detail, danh sách cá nhân và các cảnh báo nghiệp vụ nếu có).

---

## 5. Tài liệu Kỹ thuật Chi tiết

Để tìm hiểu sâu hơn về từng phần của hệ thống, vui lòng tham khảo các tài liệu chuyên đề tại thư mục `docs/`:

- 🏗️ **[Kiến trúc Hệ thống (`docs/architecture.md`)](file:///home/hieunq10/X2-Project/DeputyProfiling-InformationRetrieval/docs/architecture.md)**: Sơ đồ luồng xử lý, cơ chế caching SHA-256, module hóa extractor và chiến lược xử lý lỗi.
- 🐳 **[Hướng dẫn Triển khai Docker (`docs/docker_deployment.md`)](file:///home/hieunq10/X2-Project/DeputyProfiling-InformationRetrieval/docs/docker_deployment.md)**: Hướng dẫn cấu hình chi tiết, tối ưu hoá image, quản lý volume và xử lý sự cố container.
- 📡 **[Đặc tả API (`docs/api_specification.md`)](file:///home/hieunq10/X2-Project/DeputyProfiling-InformationRetrieval/docs/api_specification.md)**: Đặc tả chi tiết các request/response, mã HTTP, mã lỗi nghiệp vụ và cảnh báo.
- 📋 **[Nghiệp vụ 7 Loại Văn bản (`docs/document_types.md`)](file:///home/hieunq10/X2-Project/DeputyProfiling-InformationRetrieval/docs/document_types.md)**: Chi tiết cấu trúc dữ liệu cho từng loại văn bản, quy tắc lọc danh xưng, tách chức vụ Đảng và xử lý danh sách kèm theo.
