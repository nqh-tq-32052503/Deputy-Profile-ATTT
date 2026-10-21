# Kiến trúc Hệ thống — DeputyProfiling AI Service

## 1. Tổng quan hệ thống

**DeputyProfiling AI Service** là hệ thống microservice chuyên biệt nhằm tự động hóa quy trình số hóa và trích xuất thông tin có cấu trúc từ các văn bản quyết định, nghị quyết hành chính phục vụ công tác quản lý **Hồ sơ Đại biểu (HSĐB)**.

Hệ thống được thiết kế theo mô hình **bất đồng bộ (Asynchronous Polling)** kết hợp **caching thông minh**, tiếp nhận các tệp PDF scan (có mộc đỏ, chữ ký, chữ viết tay, bảng biểu danh sách nhiều trang), đưa qua đường ống OCR, làm giàu dữ liệu và sử dụng Large Language Model (LLM) để trích xuất dữ liệu JSON chuẩn mực.

---

## 2. Sơ đồ kiến trúc tổng thể (Architecture Diagram)

```mermaid
flowchart TD
    subgraph Client["Phía Client & Hệ thống nghiệp vụ"]
        HSDB["Hệ thống Hồ sơ Đại biểu (HSĐB)"]
        User["Chuyên viên nghiệp vụ"]
    end

    subgraph Service["DeputyProfiling AI Service Container"]
        API["FastAPI Web Server (app.py)"]
        Cache["Cache Manager (SHA-256 / 24h TTL)"]
        Worker["Background Task Worker"]
        
        subgraph ServicesLayer["Tầng Services (services/)"]
            OCRClient["OCR Service Client (services/ocr_service.py)"]
            DocClassifier["Doc Type Classifier (services/doc_classifier.py)"]
            LLMClient["LLM Service Client (services/llm_service.py)"]
        end

        subgraph ExtractorsLayer["Tầng Trích xuất (extractors/)"]
            Factory["Extractor Factory (get_extractor)"]
            QTCT["QTCT Extractor"]
            LUONG["Luong Extractor"]
            KHENTHUONG["Khen Thuong Extractor"]
            OTHERS["Phu Cap / Thi Dua / Ky Niem Chuong / Quy Hoach"]
        end
    end

    subgraph External["Hạ tầng & Dịch vụ ngoài"]
        OCREngine["Hệ thống OCR Service (/v1/extract)"]
        LLMHost["LLM Gateway / vLLM / OpenAI Compatible"]
    end

    User -->|Tải file PDF| HSDB
    HSDB -->|1. POST /hsdb/extract| API
    API -->|Kiểm tra Cache| Cache
    API -->|Khởi tạo Task ID| Worker
    API -.->|Trả request_id, PROCESSING| HSDB
    HSDB -->|2. Polling GET /hsdb/extract/{id}| API

    Worker -->|OCR PDF sang Markdown + Tree| OCRClient
    OCRClient <-->|HTTP POST| OCREngine
    Worker -->|Nhận diện loại văn bản| DocClassifier
    DocClassifier <-->|LLM Chat| LLMHost

    Worker -->|Lựa chọn bộ bóc tách| Factory
    Factory --> QTCT & LUONG & KHENTHUONG & OTHERS
    QTCT & LUONG & KHENTHUONG & OTHERS <-->|Trích xuất cấu trúc| LLMClient
    LLMClient <-->|LLM Chat| LLMHost

    Worker -->|Lưu kết quả| Cache
    API -->|Trả status FINISHED + JSON| HSDB
```

---

## 3. Các thành phần chính (Components)

### 3.1. Tầng Giao diện Lập trình (API Layer - `app.py`)
- **FastAPI Framework**: Cung cấp các endpoint RESTful với validation tự động theo chuẩn OpenAPI 3.0.
- **Ghép PDF tự động (`concatenate_pdf_files`)**: Khi người dùng tải lên từ 2 đến 5 file (ví dụ: Quyết định chính kèm theo các file danh sách phụ lục), hệ thống tự động ghép thành 1 file PDF duy nhất trước khi đưa vào pipeline OCR.
- **Background Worker**: Xử lý các tác vụ bóc tách tốn thời gian mà không làm nghẽn luồng HTTP request.
- **Swagger UI Patching**: Tự động tùy biến OpenAPI schema để hiển thị dropdown `doc_type` và hỗ trợ nút upload file binary chuẩn trên Swagger UI.

### 3.2. Bộ nhớ đệm (Caching System - `core/cache.py`)
- **Khóa Cache**: `Cache Key = SHA256(doc_type + nội dung binary của tất cả các file)`.
- **Cơ chế hoạt động**:
  - Khi nhận file, hệ thống băm SHA-256 toàn bộ nội dung. Nếu phát hiện file đã được trích xuất thành công trong 24 giờ, hệ thống trả về kết quả ngay lập tức (`is_cached: true`, `status: FINISHED`).
  - Cho phép người dùng bỏ qua cache bằng cờ `force_reprocess=true`.

### 3.3. Dịch vụ OCR & Làm giàu dữ liệu (`services/ocr_service.py`)
- Chuyển đổi PDF (scan/ảnh/văn bản số) sang định dạng Markdown cấu trúc.
- **Enrichment với Page Artifacts**: Tự động phục hồi các phần text bị OCR phân loại nhầm vào header/footer như Quốc hiệu, Tiêu ngữ, Số ký hiệu, Ngày ký.
- **Enrichment với Tables**: Tự động phân tích các mảng dữ liệu bảng (`tables`), phục dựng lại định dạng bảng Markdown để đảm bảo LLM không bỏ sót dữ liệu danh sách dạng cột.

### 3.4. Bộ phân loại văn bản (`services/doc_classifier.py`)
- Chạy song song bất đồng bộ (`asyncio.create_task`) cùng lúc với quá trình bóc tách.
- Nhận diện loại văn bản thực tế trong 7 nhóm nghiệp vụ.
- Đối soát giữa `doc_type` người dùng chọn và văn bản thực tế, tự động sinh cảnh báo nghiệp vụ `DOC_TYPE_MISMATCH` nếu phát hiện sai lệch.

### 3.5. Dịch vụ LLM & Chuẩn hóa dữ liệu (`services/llm_service.py`)
- Kết nối tới backend LLM theo chuẩn OpenAI API qua `httpx.AsyncClient` và `httpx.Client`.
- Phân tích cú pháp JSON linh hoạt (`parse_json_from_llm`) chống lỗi parse khi LLM trả về markdown code block hoặc văn bản kèm theo.
- **Chuẩn hóa Chức vụ & Đơn vị công tác (`arefine_position_and_organization`)**:
  - Tra cứu theo từ điển chuẩn chức danh hành chính `POSITION_TITLES`.
  - **Quy tắc cốt lõi**: Tách bỏ và loại trừ các chức danh thuộc Đảng (ví dụ: *Ủy viên Bộ Chính trị, Ủy viên Ban Chấp hành Trung ương Đảng, Bí thư Đảng ủy...*) và chức vụ kiêm nhiệm ĐBQH khi cá nhân có chức vụ chính quyền / chuyên môn tương ứng.
  - Tự động kích hoạt prompt LLM fallback chuyên sâu khi gặp chức vụ mới hoặc phức tạp.

### 3.6. Tầng Extractor Registry (`extractors/`)
Áp dụng Factory Pattern qua interface [`BaseExtractor`](file:///home/hieunq10/X2-Project/DeputyProfiling-InformationRetrieval/extractors/base.py) với 7 module độc lập:
1. **`QTCTExtractor`** (`extractors/qtct/`): Trích xuất thông tin điều động, bổ nhiệm cho đúng 01 cá nhân.
2. **`LuongExtractor`** (`extractors/luong/`): Trích xuất quá trình nâng bậc lương, ngạch, bậc, hệ số và mốc thời gian.
3. **`KhenThuongExtractor`** (`extractors/khen_thuong/`): 
   - Hỗ trợ văn bản danh sách dài nhiều trang.
   - Phân tích cây cấu trúc OCR (`ocr_parser.py`), bóc tách từng mục cá nhân theo mô hình **1 request / 1 cá nhân (Parallel Chunking)** để tối ưu chất lượng và tốc độ.
4. **`PhuCapExtractor`**, **`ThiDuaExtractor`**, **`KyNiemChuongExtractor`**, **`QuyHoachExtractor`**: Đã chuẩn hóa khung Pydantic schema và khung thực thi theo chuẩn v5.

---

## 4. Cơ chế Xử lý lỗi & Cảnh báo (Error & Warning Strategy)

Hệ thống phân biệt rõ ràng giữa **Lỗi hệ thống (System Error)**, **Lỗi nghiệp vụ (Business Error)** và **Cảnh báo nghiệp vụ (Warning)**:

### 4.1. Lỗi HTTP & Lỗi nghiệp vụ
- Nếu file hỏng hoặc mờ hoàn toàn: Trả mã lỗi `UNREADABLE_CONTENT` (HTTP 422).
- Nếu văn bản nằm ngoài 7 nhóm hỗ trợ: Trả `UNSUPPORTED_DOCUMENT` (HTTP 400).
- Nếu kết nối OCR/LLM gián đoạn: Trả `OCR_CONNECTION_ERROR` / `LLM_TIMEOUT_ERROR` (HTTP 502/503/504).

### 4.2. Cảnh báo nghiệp vụ (`warnings[]`)
Khi văn bản vẫn được trích xuất thành công (`status = success`), nhưng có yếu tố cần người dùng lưu ý kiểm tra lại:
- `HANDWRITTEN_FIELD`: Số quyết định hoặc ngày ký có dấu vết viết tay trên bản scan.
- `PERSON_COUNT_MISMATCH`: Số lượng cá nhân thực tế bóc tách được khác với số lượng ghi trong Điều 1.
- `DOC_TYPE_MISMATCH`: Loại văn bản phát hiện khác với tham số người dùng truyền vào.
- `MISSING_ATTACHMENT`: Văn bản ghi có danh sách kèm theo nhưng thiếu file danh sách đính kèm.
