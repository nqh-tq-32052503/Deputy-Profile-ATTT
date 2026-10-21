# Đặc tả Giao diện Lập trình (API Specification) — v4.2.0

Tài liệu này đặc tả chi tiết các endpoint HTTP của **DeputyProfiling AI Service** dành cho đội ngũ phát triển Hệ thống Hồ sơ Đại biểu (HSĐB).

---

## 1. Quy chuẩn Dữ liệu Chung

- **Chuẩn mã hóa**: JSON UTF-8 (Unicode NFC).
- **Định dạng Ngày tháng**: `DD/MM/YYYY` (Ví dụ: `06/08/2018`, `26/12/2024`). Nếu văn bản chỉ có tháng/năm thì trả về `MM/YYYY`, chỉ có năm trả về `YYYY`; không xác định trả `null`.
- **Định dạng Số**:
  - Hệ số lương, hệ số phụ cấp: Số thực dấu chấm thập phân `.` (Ví dụ: `6.92`, `7.28`, `0.8`).
  - Tiền thưởng: Số nguyên VNĐ (Ví dụ: `1872000`).
  - Bậc lương, số thứ tự: Số nguyên thuần.
- **Giá trị khuyết thiếu**: Trả `null` khi không tìm thấy thông tin trên văn bản. Tuyệt đối không tự suy đoán.
- **Mô hình Tương tác**: Bất đồng bộ (Asynchronous Polling qua `request_id`) kết hợp Caching SHA-256.

---

## 2. Luồng Tích hợp Bất đồng bộ (Polling Flow)

```text
[Hệ thống HSĐB]                                    [AI Service]
      |                                                 |
      |--- 1. POST /hsdb/extract (form-data) ---------->|
      |    (doc_type, files=[...], force_reprocess)     |
      |                                                 |
      |<-- 2. Trả về request_id, status: PROCESSING ---|
      |    (Hoặc status: FINISHED nếu trùng Cache)      |
      |                                                 |
      |=== VÒNG LẶP POLLING (Mỗi 2-3 giây) =============|
      |--- 3. GET /hsdb/extract/{request_id} ---------->|
      |<-- 4. status: PROCESSING -----------------------|
      |                                                 |
      |--- 5. GET /hsdb/extract/{request_id} ---------->|
      |<-- 6. status: FINISHED + result JSON -----------|
      |=================================================|
      |                                                 |
      |--- 7. Tự động điền dữ liệu lên form ------------|
```

---

## 3. Chi tiết các Endpoints

### 3.1. Health Check: `GET /health`

Kiểm tra tình trạng sẵn sàng của service.

- **URL**: `/health`
- **Method**: `GET`
- **Response (HTTP 200)**:
  ```json
  {
    "status": "ok",
    "version": "4.2.0"
  }
  ```

---

### 3.2. Khởi tạo Tiến trình Trích xuất: `POST /hsdb/extract`

Tiếp nhận tệp PDF (1 đến 5 tệp), kiểm tra cache hoặc chuyển giao cho background worker xử lý.

- **URL**: `/hsdb/extract`
- **Method**: `POST`
- **Content-Type**: `multipart/form-data`

#### Tham số Request (Form Data)
| Tên tham số | Kiểu dữ liệu | Bắt buộc | Mô tả |
| :--- | :--- | :---: | :--- |
| `doc_type` | `string` | **Có** | Một trong 7 mã: `QTCT`, `LUONG`, `PHU_CAP`, `THI_DUA`, `KHEN_THUONG`, `KY_NIEM_CHUONG`, `QUY_HOACH` |
| `files` | `file[]` (PDF) | **Có** | Danh sách từ 1 đến 5 file PDF (tối đa 30MB/file). Nếu tải từ 2 file trở lên, hệ thống tự động ghép lại theo thứ tự. |
| `force_reprocess` | `boolean` | Không | Mặc định `false`. Nếu là `true`, bỏ qua cache và ép xử lý lại từ đầu. |

#### Lệnh cURL mẫu
```bash
curl -X POST "http://localhost:8000/hsdb/extract" \
  -F "doc_type=QTCT" \
  -F "files=@quyet_dinh_dieu_dong.pdf;type=application/pdf" \
  -F "force_reprocess=false"
```

#### Cấu trúc Response

**Trường hợp A: Khởi tạo tiến trình nền mới (HTTP 200)**
```json
{
  "request_id": "8f7e2c94-1a3b-4c5d-9e6f-7a8b9c0d1e2f",
  "status": "PROCESSING",
  "created_at": "2026-10-12T09:30:00Z"
}
```

**Trường hợp B: Trả về kết quả ngay do Trùng Cache (HTTP 200)**
```json
{
  "request_id": "8f7e2c94-1a3b-4c5d-9e6f-7a8b9c0d1e2f",
  "status": "FINISHED",
  "is_cached": true,
  "result": {
    "status": "success",
    "error": null,
    "doc_type": "QTCT",
    "person_count_declared": 1,
    "tong_so_ca_nhan": 1,
    "metadata": { ... },
    "detail": { ... },
    "groups": [],
    "persons": [ ... ],
    "warnings": []
  }
}
```

---

### 3.3. Kiểm tra Trạng thái & Nhận Kết quả: `GET /hsdb/extract/{request_id}`

Thực hiện polling để lấy trạng thái tiến trình và dữ liệu kết quả bóc tách.

- **URL**: `/hsdb/extract/{request_id}`
- **Method**: `GET`

#### Tham số Path
| Tham số | Kiểu dữ liệu | Mô tả |
| :--- | :--- | :--- |
| `request_id` | `string` (UUID) | Mã định danh tiến trình nhận được từ endpoint POST |

#### Lệnh cURL mẫu
```bash
curl -X GET "http://localhost:8000/hsdb/extract/8f7e2c94-1a3b-4c5d-9e6f-7a8b9c0d1e2f"
```

#### Cấu trúc Response theo Trạng thái

**1. Tiến trình đang xử lý (`status = "PROCESSING"`)**
```json
{
  "request_id": "8f7e2c94-1a3b-4c5d-9e6f-7a8b9c0d1e2f",
  "status": "PROCESSING",
  "result": null,
  "error": null
}
```

**2. Tiến trình hoàn tất thành công (`status = "FINISHED"`)**
```json
{
  "request_id": "8f7e2c94-1a3b-4c5d-9e6f-7a8b9c0d1e2f",
  "status": "FINISHED",
  "result": {
    "status": "success",
    "error": null,
    "doc_type": "QTCT",
    "person_count_declared": 1,
    "tong_so_ca_nhan": 1,
    "metadata": {
      "document_number": "1122/QĐ-VPQH",
      "document_name": "Về việc điều động và bổ nhiệm công chức",
      "issue_date": "06/08/2018",
      "issue_unit": "Văn phòng Quốc hội",
      "signer": "Nguyễn Hạnh Phúc",
      "content": "Điều 1. Điều động ông Nguyễn Hải Long, Phó Vụ trưởng Vụ Công tác đại biểu...",
      "doc_type_detected": "QTCT"
    },
    "detail": {
      "process_type": "Điều động và bổ nhiệm",
      "start_date": "10/08/2018",
      "from_organization_name": "Vụ Công tác đại biểu, Văn phòng Quốc hội",
      "work_organization_name": "Trung tâm Bồi dưỡng đại biểu dân cử, Văn phòng Quốc hội",
      "position_name": "Phó Giám đốc",
      "position_detail": "Phó Giám đốc Trung tâm Bồi dưỡng đại biểu dân cử",
      "appointment_term_years": 5.0,
      "allowance_name": "Phụ cấp chức vụ lãnh đạo",
      "allowance_factor": 0.8
    },
    "groups": [],
    "persons": [
      {
        "stt": 1,
        "group_index": null,
        "code": null,
        "is_collective": false,
        "full_name": "Nguyễn Hải Long",
        "position_name": "Phó Vụ trưởng",
        "work_organization_name": "Vụ Công tác đại biểu, Văn phòng Quốc hội",
        "raw_text": "Điều 1. Điều động ông Nguyễn Hải Long, Phó Vụ trưởng Vụ Công tác đại biểu..."
      }
    ],
    "warnings": [
      {
        "code": "HANDWRITTEN_FIELD",
        "message": "Số quyết định và ngày ký có dấu hiệu viết tay trên bản in: metadata.document_number, metadata.issue_date"
      }
    ]
  },
  "error": null
}
```

**3. Tiến trình thất bại (`status = "FAILED"`)**
```json
{
  "request_id": "8f7e2c94-1a3b-4c5d-9e6f-7a8b9c0d1e2f",
  "status": "FAILED",
  "result": null,
  "error": {
    "code": "UNREADABLE_CONTENT",
    "message": "Bản scan quá mờ, rỗng hoặc không thể nhận dạng ký tự"
  }
}
```



## 4. Danh mục Mã lỗi & Mã Cảnh báo

### 4.1. Mã trạng thái HTTP
| Mã HTTP | Tên mã | Ý nghĩa |
| :---: | :--- | :--- |
| `200` | OK | Xử lý yêu cầu thành công, kiểm tra trường `status`. |
| `400` | Bad Request | Tham số không hợp lệ (sai `doc_type`, thiếu file hoặc quá 5 file). |
| `404` | Not Found | Không tìm thấy `request_id` (chưa tạo hoặc đã quá hạn TTL). |
| `413` | Payload Too Large | Dung lượng file PDF vượt quá giới hạn 30MB/file. |
| `415` | Unsupported Media Type | File gửi lên không phải định dạng PDF hợp lệ. |
| `502` | Bad Gateway | Lỗi kết nối đến dịch vụ OCR hoặc LLM backend. |
| `504` | Gateway Timeout | Dịch vụ OCR hoặc LLM phản hồi quá thời gian quy định (timeout). |

### 4.2. Mã lỗi nghiệp vụ (`result.error.code`)
| Mã lỗi | Mô tả |
| :--- | :--- |
| `UNREADABLE_CONTENT` | Bản scan quá mờ, trang trắng, rỗng hoặc có mật khẩu không thể giải mã. |
| `UNSUPPORTED_DOCUMENT` | Nội dung văn bản không thuộc phạm vi 7 loại quyết định được hỗ trợ. |
| `FILE_CORRUPTED` | File PDF bị hỏng luồng byte dữ liệu. |
| `INTERNAL_PROCESSING_ERROR` | Lỗi phát sinh ngoài dự kiến trong quá trình xử lý nội bộ. |

### 4.3. Mã cảnh báo nghiệp vụ (`result.warnings[].code`)
| Mã cảnh báo | Ý nghĩa & Khuyến nghị hành động |
| :--- | :--- |
| `HANDWRITTEN_FIELD` | Số quyết định, ngày ký hoặc ngày hiệu lực có dấu hiệu viết tay trên bản in. Người dùng cần rà soát kỹ lại trường này. |
| `PERSON_COUNT_MISMATCH` | Số cá nhân trích xuất thực tế (`tong_so_ca_nhan`) khác với số lượng ghi trong Điều 1 (`person_count_declared`). |
| `DOC_TYPE_MISMATCH` | Loại văn bản do AI nhận diện khác với tham số `doc_type` form gửi lên. |
| `MISSING_ATTACHMENT` | Văn bản ghi "Có danh sách kèm theo" nhưng yêu cầu chỉ gửi quyết định chính mà thiếu file danh sách đính kèm. |
