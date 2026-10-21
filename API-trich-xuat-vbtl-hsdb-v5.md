# TÀI LIỆU NGHIỆP VỤ & ĐẶC TẢ API TRÍCH XUẤT VĂN BẢN — HỆ THỐNG HỒ SƠ ĐẠI BIỂU (HSĐB)

- **Document Version**: `4.2.0` (17/09/2026)  
- **Base URL**: `https://<ai-service-host>/`  
- **Tiêu chuẩn dữ liệu**: JSON UTF-8 (Unicode NFC), Ngày tháng `DD/MM/YYYY`, Số thập phân dấu chấm (`.`).  
- **Phương thức giao tiếp**: Bất đồng bộ (Polling qua Request ID) + Caching theo mã băm nội dung file (SHA-256).

---

# PHẦN 1: TỔNG QUAN & CƠ CHẾ TÍCH HỢP

## 1.1. Bài toán nghiệp vụ & Phạm vi 7 loại văn bản (`doc_type`)

Mỗi biến động trong hồ sơ đại biểu (quá trình công tác, lương, phụ cấp, thi đua, khen thưởng, kỷ niệm chương, quy hoạch) đều căn cứ vào một **quyết định / nghị quyết** (dưới định dạng PDF, phần lớn là **bản scan có dấu mộc và chữ ký/số hiệu viết tay**). Trước đây cán bộ nghiệp vụ phải nhập thủ công toàn bộ thông tin; đối với các văn bản khen thưởng hoặc kỷ niệm chương tập thể, số lượng cá nhân có thể lên tới **hàng chục đến hàng trăm người**, gây tốn thời gian và dễ xảy ra sai sót.

Hệ thống AI Service cung cấp khả năng tiếp nhận file PDF, nhận diện và trích xuất thông tin có cấu trúc để hệ thống HSĐB **tự động điền (auto-fill)** vào các form thêm mới tương ứng.

| `doc_type` | Tên nghiệp vụ | Form đích tương ứng trên HSĐB | Số lượng cá nhân | Hồ sơ mẫu đính kèm |
| :--- | :--- | :--- | :---: | :--- |
| `QTCT` | Quá trình công tác (Điều động, bổ nhiệm, luân chuyển...) | Thêm mới quá trình công tác | 1 cá nhân | `1. QTCT_danh_dau.pdf` (QĐ 1122/QĐ-VPQH) |
| `LUONG` | Nâng bậc lương (Thường xuyên / Trước hạn) | Thêm mới quá trình lương | 1 cá nhân | `2. LUONG_danh_dau.pdf` (QĐ 3110-QĐ/HVCTQG) |
| `PHU_CAP` | Quyết định phụ cấp (Chức vụ, kiêm nhiệm, trách nhiệm...) | Thêm mới quá trình phụ cấp | 1 cá nhân | Mẫu nghiệp vụ chuẩn |
| `THI_DUA` | Công nhận danh hiệu thi đua (Cá nhân / Tập thể) | Thi đua – Khen thưởng (`type = 1`) | N đối tượng | Mẫu nghiệp vụ chuẩn |
| `KHEN_THUONG` | Khen thưởng (Bằng khen, Huân chương, Huy chương...) | Thi đua – Khen thưởng (`type = 2`) | N đối tượng | `5. KHEN_THUONG_NQ1330_danh_dau.pdf` |
| `KY_NIEM_CHUONG` | Tặng Kỷ niệm chương "Vì sự nghiệp Quốc hội VN" | Quản lý kỷ niệm chương | N cá nhân | `6. KY_NIEM_CHUONG_NQ1783_danh_dau.pdf` + DS kèm |
| `QUY_HOACH` | Phê duyệt quy hoạch chức danh cán bộ | Thêm mới Quyết định Quy hoạch | N cá nhân | `7. QUY_HOACH_danh_dau.pdf` (QĐ 2031-QĐ/BTCTW) |

> **Giới hạn trách nhiệm (Out of Scope):**
> 1. AI Service không ghi trực tiếp vào CSDL HSĐB; kết quả trả về là dữ liệu gợi ý để HSĐB đưa lên giao diện cho người dùng rà soát và bấm "Lưu".
> 2. AI Service không thực hiện khớp nối ID đại biểu (HSĐB tự đối soát dựa trên `full_name`, ngày sinh, cơ quan).
> 3. AI Service trả về dữ liệu dạng chuỗi (text), HSĐB chịu trách nhiệm ánh xạ với các danh mục mã (dropdown code) nội bộ.

---

## 1.2. Luồng tích hợp bất đồng bộ (Asynchronous Polling Flow)

Do các văn bản scan có thể dài nhiều trang và cần thời gian OCR/LLM xử lý (15s – 120s), hệ thống áp dụng giao tiếp bất đồng bộ qua cơ chế Polling:

```
[Người dùng]                 [Hệ thống HSĐB]                          [AI Service]
     |                              |                                      |
     |--- 1. Chọn file & Trích xuất ->|                                      |
     |                              |--- 2. POST /hsdb/extract (form-data)->|
     |                              |    (doc_type, files=[...])           |
     |                              |<-- 3. Trả về request_id, PROCESSING --|
     |                              |                                      |
     |                              |=== VÒNG LẶP POLLING (Mỗi 2-3 giây) ==|
     |                              |--- 4. GET /hsdb/extract/{request_id}->|
     |                              |<-- 5. status = PROCESSING -----------|
     |                              |                                      |
     |                              |--- 6. GET /hsdb/extract/{request_id}->|
     |                              |<-- 7. status = FINISHED + result ----|
     |                              |======================================|
     |                              |                                      |
     |<-- 8. Tự điền form + cảnh báo -|                                      |
     |--- 9. Rà soát & Bấm Lưu ---->|                                      |
```

### Nguyên tắc nghiệp vụ chính (Business Rules)
- **BR-01**: Dữ liệu AI trả về chỉ mang tính chất gợi ý, cho phép người dùng sửa đổi tất cả các trường trước khi lưu CSDL.
- **BR-02**: Không tìm thấy thông tin trên văn bản thì trả `null`. Tuyệt đối không tự suy đoán thông tin.
- **BR-03 (Kế thừa nhóm)**: Đối với văn bản tập thể chia nhóm, thông tin chung của nhóm (hình thức khen thưởng, thành tích, chức danh quy hoạch) được kế thừa xuống từng cá nhân thuộc nhóm đó thông qua liên kết `group_index`.
- **BR-04 (Fallback nhập tay)**: Nếu AI Service gặp sự cố hoặc timeout, người dùng vẫn thực hiện nhập liệu thủ công bình thường.

---

## 1.3. Cơ chế Caching & Xử lý trùng lặp

- **Khóa Cache**: `Cache Key = SHA256(doc_type + nội dung tất cả các file)`.
- **Hành vi**: Nếu file đã được trích xuất thành công trước đó trong vòng 24 giờ, khi gọi `POST /hsdb/extract`, hệ thống trả ngay trạng thái `status = FINISHED` cùng `result` mà không cần đợi chạy lại.
- **Bỏ qua Cache**: Truyền tham số `force_reprocess=true` trong form-data khi người dùng muốn ép hệ thống nhận dạng lại từ đầu.

---

## 1.4. Quy chuẩn dữ liệu & Chuẩn hóa

1. **Định dạng ngày tháng**: Toàn bộ các trường ngày tháng được chuẩn hóa về định dạng `DD/MM/YYYY` (ví dụ: `26/12/2024`, `06/08/2018`). Nếu văn bản chỉ có tháng/năm hoặc năm thì trả về `MM/YYYY` hoặc `YYYY`; nếu không rõ thì trả `null`.
2. **Số và tiền tệ**:
   - Hệ số lương, phụ cấp: Định dạng số thập phân dùng dấu chấm `.` (ví dụ: `6.92`, `7.28`, `0.8`).
   - Tiền thưởng: Số nguyên VNĐ (ví dụ: `1872000`).
3. **Chuẩn hóa danh xưng & Họ tên**:
   - Tách bỏ danh xưng, cấp hàm hoặc chức sắc tôn giáo (`Ông`, `Bà`, `Đồng chí`, `Đại tướng`, `Thượng tướng`, `Trung tướng`, `Thiếu tướng`, `Đại tá`, `Linh mục`, `Chuẩn Đô đốc`) ra khỏi trường `full_name`.
   - Giữ nguyên dòng nguyên văn tại trường `raw_text` để phục vụ đối chiếu.
4. **Tách chức vụ chính & đơn vị công tác**:
   - Bỏ các chức danh Đảng (`Ủy viên Bộ Chính trị`, `Ủy viên BCH Trung ương Đảng`, `Thành ủy viên`…) và chức vụ kiêm nhiệm (`Ủy viên Ủy ban Thường vụ Quốc hội`, `Ủy viên Ủy ban ... của Quốc hội`).
   - Lấy chức vụ chính quyền / Quốc hội cao nhất tại thời điểm ban hành.
   - Ví dụ: `(1) Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội` ➔ `full_name = "Trần Thanh Mẫn"`, `position_name = "Chủ tịch"`, `work_organization_name = "Quốc hội"`.
5. **Khắc phục lỗi OCR**: Tự động sửa các lỗi chính tả đặc trưng từ bản scan mờ như `QUYÉT` ➔ `QUYẾT`, `Tóa án` ➔ `Tòa án`, loại bỏ từ lặp do nhận dạng nhầm (`Ủy ban Ủy ban`).

---

## 1.5. Danh mục mã lỗi HTTP, mã lỗi kết quả & mã cảnh báo

### 1.5.1. Mã trạng thái HTTP
| HTTP Code | Mô tả |
| :--- | :--- |
| `200 OK` | Yêu cầu hợp lệ, kiểm tra trường `status` để biết tiến độ. |
| `400 Bad Request` | Tham số không hợp lệ (sai `doc_type`, thiếu file hoặc vượt quá 5 file). |
| `404 Not Found` | Không tìm thấy `request_id` hoặc tiến trình đã quá hạn lưu trữ (24 giờ). |
| `413 Payload Too Large` | Dung lượng file vượt quá giới hạn 30MB/file. |
| `415 Unsupported Media Type`| Định dạng file gửi lên không phải là file PDF hợp lệ. |
| `500 Internal Server Error` | Lỗi nội bộ hệ sinh thái AI Service. |

### 1.5.2. Mã lỗi nghiệp vụ (`result.error.code`)
Được trả về khi `result.status = "failed"`:
- `UNREADABLE_CONTENT`: Bản scan quá mờ, trang đen, rỗng hoặc file PDF có mật khẩu bảo vệ không thể giải mã.
- `UNSUPPORTED_DOCUMENT`: Văn bản không thuộc phạm vi 7 loại quyết định/nghị quyết được hỗ trợ.
- `FILE_CORRUPTED`: Cấu trúc file PDF bị hỏng không thể đọc được luồng byte.

### 1.5.3. Mã cảnh báo nghiệp vụ (`result.warnings[].code`)
Vẫn trả kết quả trích xuất thành công (`result.status = "success"`), kèm cảnh báo để người dùng lưu ý rà soát:
- `HANDWRITTEN_FIELD`: Trường thông tin được viết tay (số hiệu văn bản, ngày ký, ngày hiệu lực), độ tin cậy OCR có thể giảm.
- `PERSON_COUNT_MISMATCH`: Số lượng cá nhân thực tế trích xuất được (`tong_so_ca_nhan`) khác với số lượng văn bản tuyên bố trong điều khoản (`person_count_declared`).
- `DOC_TYPE_MISMATCH`: Loại văn bản AI tự động nhận diện (`metadata.doc_type_detected`) khác với tham số `doc_type` gửi lên từ form.
- `MISSING_ATTACHMENT`: Văn bản ghi chú "Có danh sách kèm theo" nhưng request chỉ tải lên văn bản chính mà thiếu file danh sách.

---

# PHẦN 2: ĐẶC TẢ CÁC ENDPOINT DÙNG CHUNG

## 2.1. Upload File & Khởi tạo trích xuất: `POST /hsdb/extract`

- **Endpoint**: `/hsdb/extract`
- **Method**: `POST`
- **Content-Type**: `multipart/form-data`

### Tham số Request (Form Data)
| Tham số | Kiểu | Bắt buộc | Mô tả |
| :--- | :--- | :---: | :--- |
| `doc_type` | `string` | **Có** | Một trong 7 mã: `QTCT`, `LUONG`, `PHU_CAP`, `THI_DUA`, `KHEN_THUONG`, `KY_NIEM_CHUONG`, `QUY_HOACH` |
| `files` | `file[]` (binary) | **Có** | Từ 1 đến 5 file PDF (tối đa 30MB/file). Với văn bản có danh sách đính kèm ở file riêng, file đầu là Quyết định chính, các file tiếp theo là Danh sách kèm theo. |
| `force_reprocess` | `boolean` | Không | Mặc định `false`. Đặt `true` nếu muốn ép trích xuất lại, không sử dụng kết quả cache. |

### Cấu trúc Response
- **Trường hợp 1: Khởi tạo tiến trình nền mới (HTTP 200/202)**:
```json
{
  "request_id": "c7a812ef-29b1-4b16-9ef0-0a568b209d84",
  "status": "PROCESSING",
  "created_at": "2026-09-17T15:10:00Z"
}
```

- **Trường hợp 2: Trả kết quả ngay do trùng Cache (HTTP 200)**:
```json
{
  "request_id": "c7a812ef-29b1-4b16-9ef0-0a568b209d84",
  "status": "FINISHED",
  "is_cached": true,
  "result": { ... }
}
```

---

## 2.2. Kiểm tra trạng thái & Lấy kết quả: `GET /hsdb/extract/{request_id}`

- **Endpoint**: `/hsdb/extract/{request_id}`
- **Method**: `GET`

### Tham số Path
| Tham số | Kiểu | Mô tả |
| :--- | :--- | :--- |
| `request_id` | `string` (UUID) | Mã định danh tiến trình nhận được từ lệnh POST |

### Trạng thái tiến trình (`status`)
- `PROCESSING`: Đang trong hàng đợi hoặc đang bóc tách văn bản.
- `FINISHED`: Tiến trình hoàn tất. Đọc dữ liệu trong đối tượng `result`.
- `FAILED`: Lỗi không thể xử lý. Đọc thông tin đối tượng `error`.

### Khung Response tổng quát khi hoàn tất (`status = FINISHED`)
```json
{
  "request_id": "c7a812ef-29b1-4b16-9ef0-0a568b209d84",
  "status": "FINISHED",
  "result": {
    "status": "success",
    "error": null,
    "doc_type": "QTCT",
    "person_count_declared": 1,
    "tong_so_ca_nhan": 1,
    "metadata": { ... },
    "detail": { ... },
    "groups": [ ... ],
    "persons": [ ... ],
    "warnings": [ ... ]
  }
}
```

---

## 2.3. Health Check: `GET /health`

- **Endpoint**: `/health`
- **Method**: `GET`
- **Response**:
```json
{
  "status": "ok",
  "version": "4.2.0"
}
```

---

# PHẦN 3: ĐẶC TẢ CHI TIẾT REQUEST - RESPONSE THEO TỪNG DOC_TYPE

---

## 3.1. `doc_type = "QTCT"` (Quá trình công tác)

### 3.1.1. Nghiệp vụ & Form đích trên HSĐB
- **Mục đích**: Tự động điền dữ liệu khi cán bộ nghiệp vụ mở form **"Thêm mới quá trình công tác"**.
- **Đặc trưng văn bản**: Quyết định điều động, bổ nhiệm, luân chuyển, từ chức hoặc thôi giữ chức vụ cho **01 cá nhân**.
- **Tài liệu kiểm thử thực tế**: File `1. QTCT_danh_dau.pdf` (Quyết định số `1122/QĐ-VPQH` ngày 06/08/2018 của Văn phòng Quốc hội).

### 3.1.2. Quy cách Request
- Tham số `doc_type`: `"QTCT"`
- Số lượng file: 01 file PDF
- Lệnh cURL mẫu:
```bash
curl -X POST "https://<ai-service-host>/hsdb/extract" \
  -F "doc_type=QTCT" \
  -F "files=@1. QTCT_danh_dau.pdf;type=application/pdf"
```

### 3.1.3. Đặc tả Response Schema
Đối với `QTCT`: `groups` luôn là mảng rỗng `[]`, `persons` luôn có đúng 01 phần tử.

| Nhóm | Tên trường | Kiểu dữ liệu | Bắt buộc | Ý nghĩa nghiệp vụ & Quy tắc bóc tách | Mapping Form HSĐB |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **`metadata`** | `document_number` | `string` | Có | Số/ký hiệu QĐ (kể cả số viết tay, VD: `1122/QĐ-VPQH`) | Số quyết định |
| | `document_name` | `string` | Có | Trích yếu văn bản (VD: `Về việc điều động và bổ nhiệm công chức`) | Tên văn bản / Trích yếu |
| | `issue_date` | `string` | Có | Ngày ký ban hành, chuẩn `DD/MM/YYYY` (VD: `06/08/2018`) | Ngày ban hành |
| | `issue_unit` | `string` | Có | Cơ quan ban hành (VD: `Văn phòng Quốc hội`) | Cơ quan ban hành |
| | `signer` | `string` | Có | Họ tên người ký (VD: `Nguyễn Hạnh Phúc`) | Người ký |
| | `content` | `string` | Có | Toàn văn nội dung Điều 1 của quyết định | Nội dung quyết định |
| | `doc_type_detected` | `string` | Có | Loại văn bản nhận diện tự động (`QTCT`) | — |
| **`detail`** | `process_type` | `string` | Có | Loại quá trình công tác (VD: `Điều động và bổ nhiệm`) | Loại quá trình |
| | `start_date` | `string` | Có | Thời gian bắt đầu giữ chức vụ mới (`DD/MM/YYYY`) | Thời gian bắt đầu |
| | `from_organization_name` | `string` | Có | Đơn vị công tác trước khi điều động | Ghi chú / Đơn vị cũ |
| | `work_organization_name` | `string` | Có | Đơn vị mới đến công tác | Cơ quan/Đơn vị công tác |
| | `position_name` | `string` | Có | Chức danh/Chức vụ mới được bổ nhiệm | Chức vụ/Chức danh |
| | `position_detail` | `string` | Không | Tên đầy đủ chức vụ + cơ quan mới bổ nhiệm | Chức vụ cụ thể |
| | `appointment_term_years` | `number` | Không | Thời hạn bổ nhiệm tính theo năm (VD: `5`) | Thời hạn bổ nhiệm |
| | `allowance_name` | `string` | Không | Tên khoản phụ cấp kèm theo (nếu có ghi trong QĐ) | Phụ cấp gợi ý |
| | `allowance_factor` | `number` | Không | Hệ số phụ cấp kèm theo (VD: `0.8`) | Mức hưởng phụ cấp |
| **`persons[0]`** | `stt` | `integer` | Có | Cố định là `1` | — |
| | `group_index` | `null` | Không | Cố định là `null` | — |
| | `code` | `null` | Không | Cố định là `null` | — |
| | `is_collective` | `boolean` | Có | Cố định là `false` | — |
| | `full_name` | `string` | Có | Họ và tên cá nhân (đã bỏ danh xưng Ông/Bà/Đ/c) | Họ và tên đại biểu |
| | `position_name` | `string` | Không | Chức vụ trước khi chuyển công tác (VD: `Phó Vụ trưởng`) | Chức vụ cũ |
| | `work_organization_name` | `string` | Không | Đơn vị trước khi chuyển công tác | Đơn vị cũ |
| | `raw_text` | `string` | Có | Dòng trích dẫn nguyên văn Điều 1 chỉ định cá nhân | Đoạn văn đối chiếu |

### 3.1.4. Full JSON Response thực tế
```json
{
  "request_id": "qtct-1122-48a0-9c21-729ab8f14a01",
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
      "content": "Điều 1. Điều động ông Nguyễn Hải Long, Phó Vụ trưởng Vụ Công tác đại biểu, Văn phòng Quốc hội đến nhận công tác tại Trung tâm Bồi dưỡng đại biểu dân cử, Văn phòng Quốc hội và bổ nhiệm giữ chức vụ Phó Giám đốc Trung tâm Bồi dưỡng đại biểu dân cử từ ngày 10 tháng 8 năm 2018.",
      "doc_type_detected": "QTCT"
    },
    "detail": {
      "process_type": "Điều động và bổ nhiệm",
      "start_date": "10/08/2018",
      "from_organization_name": "Vụ Công tác đại biểu, Văn phòng Quốc hội",
      "work_organization_name": "Trung tâm Bồi dưỡng đại biểu dân cử, Văn phòng Quốc hội",
      "position_name": "Phó Giám đốc",
      "position_detail": "Phó Giám đốc Trung tâm Bồi dưỡng đại biểu dân cử",
      "appointment_term_years": 5,
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
        "raw_text": "Điều 1. Điều động ông Nguyễn Hải Long, Phó Vụ trưởng Vụ Công tác đại biểu, Văn phòng Quốc hội đến nhận công tác tại Trung tâm Bồi dưỡng đại biểu dân cử, Văn phòng Quốc hội và bổ nhiệm giữ chức vụ Phó Giám đốc Trung tâm Bồi dưỡng đại biểu dân cử từ ngày 10 tháng 8 năm 2018."
      }
    ],
    "warnings": [
      {
        "code": "HANDWRITTEN_FIELD",
        "message": "Số quyết định và ngày ký có dấu hiệu viết tay trên bản in: metadata.document_number, metadata.issue_date"
      }
    ]
  }
}
```

### 3.1.5. Lưu ý nghiệp vụ & Cảnh báo
- Phân biệt rõ `detail.from_organization_name` (cơ quan cũ) và `detail.work_organization_name` (cơ quan mới tiếp nhận).
- Nếu quyết định có điều khoản về phụ cấp lãnh đạo (`allowance_factor`), HSĐB có thể hiển thị thêm nút gợi ý tạo bản ghi bên form "Quá trình phụ cấp".

---

## 3.2. `doc_type = "LUONG"` (Nâng bậc lương)

### 3.2.1. Nghiệp vụ & Form đích trên HSĐB
- **Mục đích**: Tự động điền dữ liệu khi mở form **"Thêm mới quá trình lương"**.
- **Đặc trưng văn bản**: Quyết định nâng bậc lương thường xuyên hoặc nâng lương trước thời hạn cho **01 cá nhân**.
- **Tài liệu kiểm thử thực tế**: File `2. LUONG_danh_dau.pdf` (Quyết định số `3110-QĐ/HVCTQG` ngày 26/05/2025 của Học viện Chính trị quốc gia Hồ Chí Minh).

### 3.2.2. Quy cách Request
- Tham số `doc_type`: `"LUONG"`
- Số lượng file: 01 file PDF
- Lệnh cURL mẫu:
```bash
curl -X POST "https://<ai-service-host>/hsdb/extract" \
  -F "doc_type=LUONG" \
  -F "files=@2. LUONG_danh_dau.pdf;type=application/pdf"
```

### 3.2.3. Đặc tả Response Schema
Đối với `LUONG`: `groups` luôn là mảng rỗng `[]`, `persons` luôn có đúng 01 phần tử.

| Nhóm | Tên trường | Kiểu dữ liệu | Bắt buộc | Ý nghĩa nghiệp vụ & Quy tắc bóc tách | Mapping Form HSĐB |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **`metadata`** | `document_number` | `string` | Có | Số văn bản (VD: `3110-QĐ/HVCTQG`) | Số quyết định |
| | `document_name` | `string` | Có | Trích yếu (VD: `Về việc nâng bậc lương thường xuyên`) | Tên văn bản / Trích yếu |
| | `issue_date` | `string` | Có | Ngày ký ban hành `DD/MM/YYYY` (VD: `26/05/2025`) | Ngày ban hành |
| | `issue_unit` | `string` | Có | Cơ quan ban hành (VD: `Học viện Chính trị quốc gia Hồ Chí Minh`) | Cơ quan ban hành |
| | `signer` | `string` | Có | Người ký (VD: `Nguyễn Xuân Thắng`) | Người ký |
| | `content` | `string` | Có | Toàn văn nội dung Điều 1 nâng bậc lương | Nội dung quyết định |
| | `doc_type_detected` | `string` | Có | Loại văn bản nhận diện tự động (`LUONG`) | — |
| **`detail`** | `raise_salary_reason` | `string` | Có | Lý do nâng lương (VD: `Nâng bậc lương thường xuyên`) | Lý do nâng lương |
| | `position_wage` | `string` | Có | Ngạch / Chức danh nghề nghiệp (VD: `Giảng viên cao cấp (hạng I)`) | Ngạch công chức/viên chức |
| | `position_wage_code` | `string` | Không | Mã ngạch công chức (VD: `V.07.01.01`) | Mã ngạch |
| | `old_step` | `integer` | Không | Bậc lương cũ trước khi nâng (VD: `3`) | Bậc lương cũ |
| | `old_factor` | `number` | Không | Hệ số lương cũ trước khi nâng (VD: `6.92`) | Hệ số lương cũ |
| | `salary_step` | `integer` | Có | Bậc lương mới được nâng lên (VD: `4`) | Bậc lương |
| | `salary_factor` | `number` | Có | Hệ số lương mới được nâng lên (VD: `7.28`) | Hệ số lương |
| | `start_date` | `string` | Có | Mốc hưởng lương mới `DD/MM/YYYY` (VD: `01/06/2025`) | Thời gian bắt đầu |
| | `review_date` | `string` | Không | Mốc tính nâng lương lần sau `DD/MM/YYYY` (VD: `01/06/2025`)| Mốc xét nâng lương lần sau |
| | `percentage` | `number` | Không | Tỷ lệ hưởng (nếu có, VD: vượt khung, tập sự) | Phần trăm được hưởng |
| **`persons[0]`** | `stt` | `integer` | Có | Cố định là `1` | — |
| | `group_index` | `null` | Không | Cố định là `null` | — |
| | `code` | `null` | Không | Cố định là `null` | — |
| | `is_collective` | `boolean` | Có | Cố định là `false` | — |
| | `full_name` | `string` | Có | Họ và tên cá nhân nâng lương (VD: `Hoàng Văn Nghĩa`) | Họ và tên đại biểu |
| | `position_name` | `string` | Không | Chức vụ tại đơn vị nếu có | Chức vụ |
| | `work_organization_name` | `string` | Có | Đơn vị công tác (VD: `Vụ Hợp tác quốc tế`) | Đơn vị công tác |
| | `raw_text` | `string` | Có | Dòng trích dẫn nguyên văn | Đoạn văn đối chiếu |

### 3.2.4. Full JSON Response thực tế
```json
{
  "request_id": "luong-3110-38bc-9801-ff021e8ac820",
  "status": "FINISHED",
  "result": {
    "status": "success",
    "error": null,
    "doc_type": "LUONG",
    "person_count_declared": 1,
    "tong_so_ca_nhan": 1,
    "metadata": {
      "document_number": "3110-QĐ/HVCTQG",
      "document_name": "Về việc nâng bậc lương thường xuyên",
      "issue_date": "26/05/2025",
      "issue_unit": "Học viện Chính trị quốc gia Hồ Chí Minh",
      "signer": "Nguyễn Xuân Thắng",
      "content": "Điều 1: Nâng bậc lương thường xuyên cho đồng chí Hoàng Văn Nghĩa; Đơn vị: Vụ Hợp tác quốc tế; Chức danh nghề nghiệp: Giảng viên cao cấp (hạng I); Mã số: V.07.01.01; Từ bậc: 3; hệ số: 6,92; Lên bậc: 4; hệ số: 7,28; Mức lương mới thực hiện từ ngày 01/6/2025; Thời gian nâng bậc lương lần sau tính từ ngày 01/6/2025.",
      "doc_type_detected": "LUONG"
    },
    "detail": {
      "raise_salary_reason": "Nâng bậc lương thường xuyên",
      "position_wage": "Giảng viên cao cấp (hạng I)",
      "position_wage_code": "V.07.01.01",
      "old_step": 3,
      "old_factor": 6.92,
      "salary_step": 4,
      "salary_factor": 7.28,
      "start_date": "01/06/2025",
      "review_date": "01/06/2025",
      "percentage": null
    },
    "groups": [],
    "persons": [
      {
        "stt": 1,
        "group_index": null,
        "code": null,
        "is_collective": false,
        "full_name": "Hoàng Văn Nghĩa",
        "position_name": null,
        "work_organization_name": "Vụ Hợp tác quốc tế",
        "raw_text": "Điều 1: Nâng bậc lương thường xuyên cho đồng chí Hoàng Văn Nghĩa; Đơn vị: Vụ Hợp tác quốc tế; Chức danh nghề nghiệp: Giảng viên cao cấp (hạng I); Mã số: V.07.01.01..."
      }
    ],
    "warnings": [
      {
        "code": "HANDWRITTEN_FIELD",
        "message": "Số quyết định và ngày tháng ký được điền tay trên văn bản scan: metadata.document_number, metadata.issue_date"
      }
    ]
  }
}
```

### 3.2.5. Lưu ý nghiệp vụ & Cảnh báo
- Lưu ý phân biệt rõ `old_step` (bậc cũ) với `salary_step` (bậc mới), `old_factor` (hệ số cũ) với `salary_factor` (hệ số mới).
- Mốc tính nâng lương lần sau (`review_date`) thông thường trùng với `start_date`, nhưng có thể khác trong trường hợp nâng trước thời hạn.

---

## 3.3. `doc_type = "PHU_CAP"` (Quyết định phụ cấp)

### 3.3.1. Nghiệp vụ & Form đích trên HSĐB
- **Mục đích**: Tự động điền dữ liệu khi mở form **"Thêm mới quá trình phụ cấp"**.
- **Đặc trưng văn bản**: Quyết định hưởng phụ cấp trách nhiệm, chức vụ lãnh đạo, phụ cấp kiêm nhiệm, phụ cấp độc hại hoặc thâm niên cho **01 cá nhân**.
- **Tài liệu kiểm thử**: Chuẩn hóa theo quy định về phụ cấp cán bộ, công chức.

### 3.3.2. Quy cách Request
- Tham số `doc_type`: `"PHU_CAP"`
- Số lượng file: 01 file PDF
- Lệnh cURL mẫu:
```bash
curl -X POST "https://<ai-service-host>/hsdb/extract" \
  -F "doc_type=PHU_CAP" \
  -F "files=@quyet_dinh_phu_cap.pdf;type=application/pdf"
```

### 3.3.3. Đặc tả Response Schema
Đối với `PHU_CAP`: `groups` luôn là mảng rỗng `[]`, `persons` luôn có đúng 01 phần tử.

| Nhóm | Tên trường | Kiểu dữ liệu | Bắt buộc | Ý nghĩa nghiệp vụ & Quy tắc bóc tách | Mapping Form HSĐB |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **`metadata`** | `document_number` | `string` | Có | Số văn bản quyết định | Số quyết định |
| | `document_name` | `string` | Có | Trích yếu quyết định phụ cấp | Tên văn bản / Trích yếu |
| | `issue_date` | `string` | Có | Ngày ký ban hành `DD/MM/YYYY` | Ngày ban hành |
| | `issue_unit` | `string` | Có | Cơ quan ban hành quyết định | Cơ quan ban hành |
| | `signer` | `string` | Có | Người ký quyết định | Người ký |
| | `content` | `string` | Có | Nội dung Điều 1 quyết định phụ cấp | Nội dung quyết định |
| | `doc_type_detected` | `string` | Có | Loại văn bản nhận diện tự động (`PHU_CAP`) | — |
| **`detail`** | `allowance_type` | `string` | Có | Nhóm phụ cấp (Chức vụ, Trách nhiệm, Kiêm nhiệm...) | Loại phụ cấp |
| | `allowance_name` | `string` | Có | Tên khoản phụ cấp cụ thể | Phụ cấp |
| | `allowance_factor` | `number` | Không | Mức hưởng tính theo hệ số (VD: `0.8`, `1.0`) | Mức hưởng (Hệ số) |
| | `amount` | `integer` | Không | Mức hưởng tính theo số tiền tuyệt đối (VNĐ) | Số tiền (VNĐ) |
| | `percentage` | `number` | Không | Mức hưởng tính theo tỷ lệ % (VD: `15`) | Phần trăm được hưởng |
| | `effective_from` | `string` | Có | Ngày bắt đầu hưởng phụ cấp `DD/MM/YYYY` | Hiệu lực từ ngày |
| | `effective_to` | `string` | Không | Ngày hết hiệu lực hưởng phụ cấp (nếu có xác định) | Hiệu lực đến ngày |
| **`persons[0]`** | `stt` | `integer` | Có | Cố định là `1` | — |
| | `group_index` | `null` | Không | Cố định là `null` | — |
| | `code` | `null` | Không | Cố định là `null` | — |
| | `is_collective` | `boolean` | Có | Cố định là `false` | — |
| | `full_name` | `string` | Có | Họ tên cá nhân được hưởng phụ cấp | Họ và tên đại biểu |
| | `position_name` | `string` | Không | Chức danh/chức vụ của cá nhân | Chức vụ |
| | `work_organization_name` | `string` | Có | Cơ quan/đơn vị công tác | Đơn vị công tác |
| | `raw_text` | `string` | Có | Dòng trích dẫn nguyên văn | Đoạn văn đối chiếu |

### 3.3.4. Full JSON Response thực tế
```json
{
  "request_id": "pc-7412-4211-9a70-87cc91e23a45",
  "status": "FINISHED",
  "result": {
    "status": "success",
    "error": null,
    "doc_type": "PHU_CAP",
    "person_count_declared": 1,
    "tong_so_ca_nhan": 1,
    "metadata": {
      "document_number": "852/QĐ-VPQH",
      "document_name": "Về việc chi trả phụ cấp trách nhiệm công tác",
      "issue_date": "15/01/2025",
      "issue_unit": "Văn phòng Quốc hội",
      "signer": "Bùi Văn Cường",
      "content": "Điều 1. Chi trả phụ cấp trách nhiệm công tác đối với ông Nguyễn Văn A, Chuyên viên chính Vụ Dân nguyện thuộc Văn phòng Quốc hội, mức phụ cấp hệ số 0,5 kể từ ngày 01 tháng 01 năm 2025.",
      "doc_type_detected": "PHU_CAP"
    },
    "detail": {
      "allowance_type": "Phụ cấp trách nhiệm công việc",
      "allowance_name": "Phụ cấp trách nhiệm cán bộ chuyên môn",
      "allowance_factor": 0.5,
      "amount": null,
      "percentage": null,
      "effective_from": "01/01/2025",
      "effective_to": null
    },
    "groups": [],
    "persons": [
      {
        "stt": 1,
        "group_index": null,
        "code": null,
        "is_collective": false,
        "full_name": "Nguyễn Văn A",
        "position_name": "Chuyên viên chính",
        "work_organization_name": "Vụ Dân nguyện thuộc Văn phòng Quốc hội",
        "raw_text": "Điều 1. Chi trả phụ cấp trách nhiệm công tác đối với ông Nguyễn Văn A, Chuyên viên chính Vụ Dân nguyện..."
      }
    ],
    "warnings": []
  }
}
```

### 3.3.5. Lưu ý nghiệp vụ & Cảnh báo
- Trong 3 trường `allowance_factor`, `amount`, `percentage`, chỉ có trường tương ứng với nội dung quyết định là có giá trị, các trường còn lại trả `null`.

---

## 3.4. `doc_type = "THI_DUA"` (Công nhận danh hiệu thi đua)

### 3.4.1. Nghiệp vụ & Form đích trên HSĐB
- **Mục đích**: Tự động điền dữ liệu khi mở form **"Thi đua – Khen thưởng"** (với tùy chọn **Phân loại = 1: Thi đua**).
- **Đặc trưng văn bản**: Quyết định công nhận danh hiệu thi đua (Chiến sĩ thi đua toàn quốc, Chiến sĩ thi đua cơ sở, Cờ thi đua, Tập thể lao động tiên tiến...) cho **nhiều cá nhân và/hoặc tập thể**.
- **Tài liệu kiểm thử**: Chuẩn hóa theo quy định Luật Thi đua, khen thưởng số 06/2022/QH15.

### 3.4.2. Quy cách Request
- Tham số `doc_type`: `"THI_DUA"`
- Số lượng file: 01 hoặc nhiều file PDF (nếu danh sách đính kèm ở file riêng).
- Lệnh cURL mẫu:
```bash
curl -X POST "https://<ai-service-host>/hsdb/extract" \
  -F "doc_type=THI_DUA" \
  -F "files=@quyet_dinh_thi_dua.pdf;type=application/pdf"
```

### 3.4.3. Đặc tả Response Schema
Đối với `THI_DUA`: Dữ liệu phân nhóm qua `groups[]`, danh sách đối tượng đạt danh hiệu qua `persons[]` (có thể gồm cá nhân và tập thể qua cờ `is_collective`).

| Nhóm | Tên trường | Kiểu dữ liệu | Bắt buộc | Ý nghĩa nghiệp vụ & Quy tắc bóc tách | Mapping Form HSĐB |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **`metadata`** | `document_number` | `string` | Có | Số văn bản quyết định thi đua | Số quyết định |
| | `document_name` | `string` | Có | Trích yếu văn bản | Tên văn bản / Trích yếu |
| | `issue_date` | `string` | Có | Ngày ký ban hành `DD/MM/YYYY` | Ngày ban hành |
| | `issue_unit` | `string` | Có | Cơ quan ký ban hành | Cơ quan ban hành |
| | `signer` | `string` | Có | Họ tên người ký | Người ký |
| | `content` | `string` | Có | Toàn văn nội dung Điều 1 | Nội dung quyết định |
| | `doc_type_detected` | `string` | Có | Loại văn bản nhận diện tự động (`THI_DUA`) | — |
| **`detail`** | `type` | `integer` | Có | Luôn bằng `1` (Quy ước HSĐB: `1 = Thi đua`) | Phân loại (Dropdown) |
| | `year` | `integer` | Có | Năm xét thi đua (lấy từ nội dung hoặc từ năm của `issue_date`) | Năm xét thi đua |
| | `reward_level` | `string` | Có | Cấp / Danh hiệu thi đua cao nhất văn bản | Cấp khen thưởng/thi đua |
| | `content` | `string` | Có | Tóm tắt nội dung danh hiệu thi đua | Nội dung tóm tắt |
| **`groups[]`** | `group_index` | `integer` | Có | STT nhóm, bắt đầu từ 1 | — |
| | `title` | `string` | Có | Tiêu đề nhóm danh hiệu thi đua | Tên nhóm danh hiệu |
| | `person_count_declared`| `integer` | Không | Số lượng cá nhân/tập thể ghi trong tiêu đề nhóm | Số lượng dự kiến |
| | `reward_type` | `string` | Có | Danh hiệu thi đua của nhóm (VD: `Chiến sĩ thi đua cơ sở`) | Hình thức / Danh hiệu |
| | `accomplishment` | `string` | Không | Thành tích đạt được (VD: `Đã có thành tích xuất sắc năm 2024`) | Thành tích |
| **`persons[]`**| `stt` | `integer` | Có | STT toàn bộ danh sách, tăng dần từ 1 | Bảng danh sách - STT |
| | `group_index` | `integer` | Có | Nhóm danh hiệu mà cá nhân/tập thể thuộc về | Nhóm liên kết |
| | `code` | `string` | Không | Số thứ tự gốc đánh trong nhóm văn bản | STT gốc |
| | `is_collective` | `boolean` | Có | `true` nếu là tập thể (phòng, ban, vụ), `false` nếu là cá nhân | Phân loại đối tượng |
| | `full_name` | `string` | Có | Tên cá nhân hoặc tên tập thể | Tên cá nhân/Tập thể |
| | `position_name` | `string` | Không | Chức vụ chính (nếu là cá nhân) | Chức vụ |
| | `work_organization_name` | `string` | Có | Đơn vị công tác của cá nhân hoặc cơ quan trực thuộc | Đơn vị |
| | `award_type` | `string` | Có | Thường là `TANG` | Hình thức tặng |
| | `raw_text` | `string` | Có | Dòng trích dẫn nguyên văn đối tượng trong danh sách | Đoạn văn đối chiếu |

### 3.4.4. Full JSON Response thực tế
```json
{
  "request_id": "thidua-9012-3321-bb12-881273615201",
  "status": "FINISHED",
  "result": {
    "status": "success",
    "error": null,
    "doc_type": "THI_DUA",
    "person_count_declared": 3,
    "tong_so_ca_nhan": 3,
    "metadata": {
      "document_number": "45/QĐ-VPQH",
      "document_name": "Về việc công nhận danh hiệu Chiến sĩ thi đua cơ sở năm 2024",
      "issue_date": "10/01/2025",
      "issue_unit": "Văn phòng Quốc hội",
      "signer": "Bùi Văn Cường",
      "content": "Điều 1. Công nhận danh hiệu “Chiến sĩ thi đua cơ sở” năm 2024 cho 03 cá nhân thuộc Văn phòng Quốc hội do có thành tích xuất sắc trong công tác.",
      "doc_type_detected": "THI_DUA"
    },
    "detail": {
      "type": 1,
      "year": 2024,
      "reward_level": "Chiến sĩ thi đua cấp cơ sở",
      "content": "Công nhận danh hiệu Chiến sĩ thi đua cơ sở năm 2024 cho 03 cá nhân"
    },
    "groups": [
      {
        "group_index": 1,
        "title": "Danh hiệu Chiến sĩ thi đua cơ sở cho các cá nhân thuộc Vụ Công tác đại biểu:",
        "person_count_declared": 3,
        "reward_type": "Chiến sĩ thi đua cơ sở",
        "accomplishment": "Đã có thành tích xuất sắc trong phong trào thi đua năm 2024"
      }
    ],
    "persons": [
      {
        "stt": 1,
        "group_index": 1,
        "code": "1",
        "is_collective": false,
        "full_name": "Phạm Văn Long",
        "position_name": "Vụ trưởng",
        "work_organization_name": "Vụ Công tác đại biểu",
        "award_type": "TANG",
        "raw_text": "(1) Ông Phạm Văn Long, Vụ trưởng Vụ Công tác đại biểu."
      },
      {
        "stt": 2,
        "group_index": 1,
        "code": "2",
        "is_collective": false,
        "full_name": "Lê Thị Mai",
        "position_name": "Phó Vụ trưởng",
        "work_organization_name": "Vụ Công tác đại biểu",
        "award_type": "TANG",
        "raw_text": "(2) Bà Lê Thị Mai, Phó Vụ trưởng Vụ Công tác đại biểu."
      },
      {
        "stt": 3,
        "group_index": 1,
        "code": "3",
        "is_collective": false,
        "full_name": "Trần Quốc Hùng",
        "position_name": "Chuyên viên chính",
        "work_organization_name": "Vụ Công tác đại biểu",
        "award_type": "TANG",
        "raw_text": "(3) Ông Trần Quốc Hùng, Chuyên viên chính Vụ Công tác đại biểu."
      }
    ],
    "warnings": []
  }
}
```

### 3.4.5. Lưu ý nghiệp vụ & Cảnh báo
- Lưu ý phân biệt trường `is_collective = true` nếu danh sách có khen thưởng đơn vị (ví dụ: `Vụ Công tác đại biểu`, `Phòng Tổng hợp`).

---

## 3.5. `doc_type = "KHEN_THUONG"` (Khen thưởng)

### 3.5.1. Nghiệp vụ & Form đích trên HSĐB
- **Mục đích**: Tự động điền dữ liệu khi mở form **"Thi đua – Khen thưởng"** (với tùy chọn **Phân loại = 2: Khen thưởng**).
- **Đặc trưng văn bản**: Nghị quyết / Quyết định tặng Bằng khen, Huân chương, Huy chương cho **danh sách tập thể hoặc nhiều cá nhân**, chia làm các nhóm theo thành tích hoặc giai đoạn.
- **Tài liệu kiểm thử thực tế**: File `5. KHEN_THUONG_NQ1330_danh_dau.pdf` (Nghị quyết số `1330/NQ-UBTVQH15` ngày 26/12/2024 của Ủy ban Thường vụ Quốc hội).

### 3.5.2. Quy cách Request
- Tham số `doc_type`: `"KHEN_THUONG"`
- Số lượng file: 01 file PDF (chứa cả trang quyết định và các trang danh sách phía sau).
- Lệnh cURL mẫu:
```bash
curl -X POST "https://<ai-service-host>/hsdb/extract" \
  -F "doc_type=KHEN_THUONG" \
  -F "files=@5. KHEN_THUONG_NQ1330_danh_dau.pdf;type=application/pdf"
```

### 3.5.3. Đặc tả Response Schema
Đối với `KHEN_THUONG`: Dữ liệu phân nhóm theo `groups[]` (tương ứng các mục 1., 2., 3. trong danh sách), mỗi cá nhân trong `persons[]` liên kết với nhóm qua `group_index` để thừa hưởng hình thức và thành tích khen thưởng.

| Nhóm | Tên trường | Kiểu dữ liệu | Bắt buộc | Ý nghĩa nghiệp vụ & Quy tắc bóc tách | Mapping Form HSĐB |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **`metadata`** | `document_number` | `string` | Có | Số nghị quyết/quyết định (VD: `1330/NQ-UBTVQH15` viết tay) | Số quyết định |
| | `document_name` | `string` | Có | Trích yếu (VD: `Về việc tặng Bằng khen`) | Tên văn bản / Trích yếu |
| | `issue_date` | `string` | Có | Ngày ký ban hành `DD/MM/YYYY` (VD: `26/12/2024`) | Ngày ban hành |
| | `issue_unit` | `string` | Có | Cơ quan ban hành (VD: `Ủy ban Thường vụ Quốc hội`) | Cơ quan ban hành |
| | `signer` | `string` | Có | Họ tên người ký (VD: `Trần Thanh Mẫn`) | Người ký |
| | `content` | `string` | Có | Nguyên văn nội dung Điều 1 | Nội dung quyết định |
| | `doc_type_detected` | `string` | Có | Loại văn bản nhận diện tự động (`KHEN_THUONG`) | — |
| **`detail`** | `type` | `integer` | Có | Luôn bằng `2` (Quy ước HSĐB: `2 = Khen thưởng`) | Phân loại (Dropdown) |
| | `year` | `integer` | Có | Năm khen thưởng (lấy từ nội dung Điều 1 hoặc năm ký `2024`) | Năm khen thưởng |
| | `reward_level` | `string` | Có | Cấp khen thưởng (VD: `Bằng khen Ủy ban Thường vụ Quốc hội`) | Cấp khen thưởng |
| | `content` | `string` | Có | Nội dung khen thưởng chung Điều 1 | Nội dung khen thưởng |
| **`groups[]`** | `group_index` | `integer` | Có | STT nhóm, bắt đầu từ 1 | — |
| | `title` | `string` | Có | Nguyên văn tiêu đề mục nhóm (VD: `1. Tặng Bằng khen... cho 14 cá nhân...`) | Tên nhóm khen thưởng |
| | `person_count_declared`| `integer` | Có | Số lượng cá nhân tuyên bố trong tiêu đề mục (VD: `14`, `2`, `1`) | Số lượng chỉ tiêu |
| | `reward_type` | `string` | Có | Hình thức khen thưởng (VD: `Bằng khen của Ủy ban Thường vụ Quốc hội`) | Hình thức khen thưởng |
| | `accomplishment` | `string` | Có | Thành tích đạt được (VD: `Có thành tích xuất sắc trong công tác giai đoạn 2021-2024`) | Nội dung thành tích |
| **`persons[]`**| `stt` | `integer` | Có | STT toàn bộ danh sách tăng dần từ 1 (từ 1 đến 17) | Bảng danh sách - STT |
| | `group_index` | `integer` | Có | Thuộc nhóm nào trong mảng `groups` | Nhóm liên kết |
| | `code` | `string` | Có | Số thứ tự gốc ghi trong dấu ngoặc đơn (VD: `"1"`, `"4"`, `"14"`) | STT gốc |
| | `is_collective` | `boolean` | Có | `false` nếu là cá nhân, `true` nếu là tập thể | Phân loại đối tượng |
| | `full_name` | `string` | Có | Họ tên cá nhân (đã lọc danh xưng, cấp hàm) | Họ và tên |
| | `position_name` | `string` | Có | Chức vụ chính quyền/Quốc hội (đã loại chức vụ Đảng/kiêm nhiệm) | Chức vụ |
| | `work_organization_name` | `string` | Có | Cơ quan/đơn vị công tác chính tương ứng chức vụ | Đơn vị công tác |
| | `award_type` | `string` | Có | `TANG` hoặc `TRUY_TANG` (dựa trên từ khóa "Truy tặng") | Loại hình thức |
| | `raw_text` | `string` | Có | Nguyên văn dòng cá nhân trên văn bản scan | Đoạn văn đối chiếu |

### 3.5.4. Full JSON Response thực tế
```json
{
  "request_id": "kt-1330-84a1-0023-ff1209b55231",
  "status": "FINISHED",
  "result": {
    "status": "success",
    "error": null,
    "doc_type": "KHEN_THUONG",
    "person_count_declared": 17,
    "tong_so_ca_nhan": 17,
    "metadata": {
      "document_number": "1330/NQ-UBTVQH15",
      "document_name": "Về việc tặng Bằng khen",
      "issue_date": "26/12/2024",
      "issue_unit": "Ủy ban Thường vụ Quốc hội",
      "signer": "Trần Thanh Mẫn",
      "content": "Điều 1. Tặng Bằng khen của Ủy ban Thường vụ Quốc hội cho 17 cá nhân do có thành tích xuất sắc (Có danh sách kèm theo).",
      "doc_type_detected": "KHEN_THUONG"
    },
    "detail": {
      "type": 2,
      "year": 2024,
      "reward_level": "Bằng khen Ủy ban Thường vụ Quốc hội",
      "content": "Tặng Bằng khen của Ủy ban Thường vụ Quốc hội cho 17 cá nhân do có thành tích xuất sắc"
    },
    "groups": [
      {
        "group_index": 1,
        "title": "1. Tặng “Bằng khen của Ủy ban Thường vụ Quốc hội” cho 14 cá nhân do có thành tích xuất sắc trong công tác giai đoạn 2021-2024, gồm:",
        "person_count_declared": 14,
        "reward_type": "Bằng khen của Ủy ban Thường vụ Quốc hội",
        "accomplishment": "Có thành tích xuất sắc trong công tác giai đoạn 2021-2024"
      },
      {
        "group_index": 2,
        "title": "2. Tặng Bằng khen của Ủy ban Thường vụ Quốc hội cho 02 cá nhân do có thành tích xuất sắc trong công tác năm 2024, gồm:",
        "person_count_declared": 2,
        "reward_type": "Bằng khen của Ủy ban Thường vụ Quốc hội",
        "accomplishment": "Có thành tích xuất sắc trong công tác năm 2024"
      },
      {
        "group_index": 3,
        "title": "3. Tặng Bằng khen của Ủy ban Thường vụ Quốc hội cho 01 cá nhân do có thành tích xuất sắc trong công tác năm 2023 cho đồng chí:",
        "person_count_declared": 1,
        "reward_type": "Bằng khen của Ủy ban Thường vụ Quốc hội",
        "accomplishment": "Có thành tích xuất sắc trong công tác năm 2023"
      }
    ],
    "persons": [
      {
        "stt": 1,
        "group_index": 1,
        "code": "1",
        "is_collective": false,
        "full_name": "Trần Thanh Mẫn",
        "position_name": "Chủ tịch",
        "work_organization_name": "Quốc hội",
        "award_type": "TANG",
        "raw_text": "(1) Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội."
      },
      {
        "stt": 2,
        "group_index": 1,
        "code": "2",
        "is_collective": false,
        "full_name": "Nguyễn Khắc Định",
        "position_name": "Phó Chủ tịch",
        "work_organization_name": "Quốc hội",
        "award_type": "TANG",
        "raw_text": "(2) Ông Nguyễn Khắc Định, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội."
      },
      {
        "stt": 3,
        "group_index": 1,
        "code": "3",
        "is_collective": false,
        "full_name": "Nguyễn Đức Hải",
        "position_name": "Phó Chủ tịch",
        "work_organization_name": "Quốc hội",
        "award_type": "TANG",
        "raw_text": "(3) Ông Nguyễn Đức Hải, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội."
      },
      {
        "stt": 4,
        "group_index": 1,
        "code": "4",
        "is_collective": false,
        "full_name": "Trần Quang Phương",
        "position_name": "Phó Chủ tịch",
        "work_organization_name": "Quốc hội",
        "award_type": "TANG",
        "raw_text": "(4) Thượng tướng Trần Quang Phương, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội."
      },
      {
        "stt": 5,
        "group_index": 1,
        "code": "5",
        "is_collective": false,
        "full_name": "Nguyễn Thị Thanh",
        "position_name": "Phó Chủ tịch",
        "work_organization_name": "Quốc hội",
        "award_type": "TANG",
        "raw_text": "(5) Bà Nguyễn Thị Thanh, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội."
      },
      {
        "stt": 6,
        "group_index": 1,
        "code": "6",
        "is_collective": false,
        "full_name": "Nguyễn Thúy Anh",
        "position_name": "Chủ nhiệm",
        "work_organization_name": "Ủy ban Xã hội của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(6) Bà Nguyễn Thúy Anh, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ nhiệm Ủy ban Xã hội của Quốc hội."
      },
      {
        "stt": 7,
        "group_index": 1,
        "code": "7",
        "is_collective": false,
        "full_name": "Vũ Hải Hà",
        "position_name": "Chủ nhiệm",
        "work_organization_name": "Ủy ban Đối ngoại của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(7) Ông Vũ Hải Hà, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ nhiệm Ủy ban Đối ngoại của Quốc hội."
      },
      {
        "stt": 8,
        "group_index": 1,
        "code": "8",
        "is_collective": false,
        "full_name": "Y Thanh Hà Niê K’Đăm",
        "position_name": "Chủ tịch",
        "work_organization_name": "Hội đồng Dân tộc của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(8) Ông Y Thanh Hà Niê K’Đăm, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ tịch Hội đồng Dân tộc của Quốc hội."
      },
      {
        "stt": 9,
        "group_index": 1,
        "code": "9",
        "is_collective": false,
        "full_name": "Lê Quang Huy",
        "position_name": "Chủ nhiệm",
        "work_organization_name": "Ủy ban Khoa học Công nghệ và Môi trường của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(9) Ông Lê Quang Huy, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ nhiệm Ủy ban Khoa học Công nghệ và Môi trường của Quốc hội."
      },
      {
        "stt": 10,
        "group_index": 1,
        "code": "10",
        "is_collective": false,
        "full_name": "Lê Thị Nga",
        "position_name": "Chủ nhiệm",
        "work_organization_name": "Ủy ban Tư pháp của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(10) Bà Lê Thị Nga, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ nhiệm Ủy ban Tư pháp của Quốc hội."
      },
      {
        "stt": 11,
        "group_index": 1,
        "code": "11",
        "is_collective": false,
        "full_name": "Vũ Hồng Thanh",
        "position_name": "Chủ nhiệm",
        "work_organization_name": "Ủy ban Kinh tế của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(11) Ông Vũ Hồng Thanh, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ nhiệm Ủy ban Kinh tế của Quốc hội."
      },
      {
        "stt": 12,
        "group_index": 1,
        "code": "12",
        "is_collective": false,
        "full_name": "Lê Tấn Tới",
        "position_name": "Chủ nhiệm",
        "work_organization_name": "Ủy ban Quốc phòng và An ninh của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(12) Trung tướng Lê Tấn Tới, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ nhiệm Ủy ban Quốc phòng và An ninh của Quốc hội."
      },
      {
        "stt": 13,
        "group_index": 1,
        "code": "13",
        "is_collective": false,
        "full_name": "Hoàng Thanh Tùng",
        "position_name": "Chủ nhiệm",
        "work_organization_name": "Ủy ban Pháp luật của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(13) Ông Hoàng Thanh Tùng, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ nhiệm Ủy ban Pháp luật của Quốc hội."
      },
      {
        "stt": 14,
        "group_index": 1,
        "code": "14",
        "is_collective": false,
        "full_name": "Nguyễn Đắc Vinh",
        "position_name": "Chủ nhiệm",
        "work_organization_name": "Ủy ban Văn hóa, Giáo dục của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(14) Ông Nguyễn Đắc Vinh, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ nhiệm Ủy ban Văn hóa, Giáo dục của Quốc hội."
      },
      {
        "stt": 15,
        "group_index": 2,
        "code": "1",
        "is_collective": false,
        "full_name": "Dương Thanh Bình",
        "position_name": "Trưởng ban Dân nguyện",
        "work_organization_name": "Ủy ban Thường vụ Quốc hội",
        "award_type": "TANG",
        "raw_text": "(1) Ông Dương Thanh Bình, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Trưởng ban Dân nguyện thuộc Ủy ban Thường vụ Quốc hội."
      },
      {
        "stt": 16,
        "group_index": 2,
        "code": "2",
        "is_collective": false,
        "full_name": "Nguyễn Thanh Hải",
        "position_name": "Trưởng ban Công tác đại biểu",
        "work_organization_name": "Ủy ban Thường vụ Quốc hội",
        "award_type": "TANG",
        "raw_text": "(2) Bà Nguyễn Thanh Hải, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Trưởng ban Công tác đại biểu thuộc Ủy ban Thường vụ Quốc hội, Phó Trưởng Ban Tổ chức Trung ương."
      },
      {
        "stt": 17,
        "group_index": 3,
        "code": "1",
        "is_collective": false,
        "full_name": "Lê Quang Mạnh",
        "position_name": "Chủ nhiệm",
        "work_organization_name": "Ủy ban Tài chính, Ngân sách của Quốc hội",
        "award_type": "TANG",
        "raw_text": "(1) Ông Lê Quang Mạnh, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Ủy ban Thường vụ Quốc hội, Chủ nhiệm Ủy ban Tài chính, Ngân sách của Quốc hội."
      }
    ],
    "warnings": [
      {
        "code": "HANDWRITTEN_FIELD",
        "message": "Số quyết định và ngày ký được viết tay: metadata.document_number, metadata.issue_date"
      }
    ]
  }
}
```

### 3.5.5. Lưu ý nghiệp vụ & Cảnh báo
- Kiểm tra đối soát số lượng: `person_count_declared = 17` khớp chính xác với `tong_so_ca_nhan = 17` (14 + 2 + 1) nên không phát sinh cảnh báo `PERSON_COUNT_MISMATCH`.
- Nếu cá nhân có nhiều chức vụ (ví dụ bà Nguyễn Thanh Hải vừa là Trưởng ban CTĐB vừa là Phó Trưởng Ban Tổ chức TW), AI trích xuất chức vụ chính thuộc Quốc hội/UBTVQH trước.

---

## 3.6. `doc_type = "KY_NIEM_CHUONG"` (Kỷ niệm chương)

### 3.6.1. Nghiệp vụ & Form đích trên HSĐB
- **Mục đích**: Tự động điền dữ liệu khi mở form **"Quản lý kỷ niệm chương"**.
- **Đặc trưng văn bản**: Nghị quyết tặng Kỷ niệm chương "Vì sự nghiệp Quốc hội Việt Nam". Văn bản thường có danh sách kèm theo ở **file riêng**, chia thành 3 khối đối tượng:
  - Khối I: Đại biểu Quốc hội (có thông tin khóa ĐBQH `na_term` và đoàn ĐBQH `delegation`).
  - Khối II: Lãnh đạo Tỉnh/Thành phố (`na_term` và `delegation` là `null`).
  - Khối III: Công chức, người lao động Văn phòng Đoàn ĐBQH & HĐND (`na_term` và `delegation` là `null`).
- **Tài liệu kiểm thử thực tế**: File `6. KY_NIEM_CHUONG_NQ1783_danh_dau.pdf` (Nghị quyết số `1783/NQ-UBTVQH15` ngày 06/08/2025) và file `6. KY_NIEM_CHUONG_DS_kem_NQ1783_danh_dau.pdf` (Danh sách 47 cá nhân kèm theo NQ 1783).

### 3.6.2. Quy cách Request (Multi-file Upload)
- Tham số `doc_type`: `"KY_NIEM_CHUONG"`
- Số lượng file: **02 file PDF** (File 1: Nghị quyết chính; File 2: Danh sách kèm theo).
- Lệnh cURL mẫu:
```bash
curl -X POST "https://<ai-service-host>/hsdb/extract" \
  -F "doc_type=KY_NIEM_CHUONG" \
  -F "files=@6. KY_NIEM_CHUONG_NQ1783_danh_dau.pdf;type=application/pdf" \
  -F "files=@6. KY_NIEM_CHUONG_DS_kem_NQ1783_danh_dau.pdf;type=application/pdf"
```

### 3.6.3. Đặc tả Response Schema
Đối với `KY_NIEM_CHUONG`: Bổ sung 2 trường `na_term` (khóa ĐBQH) và `delegation` (Đoàn ĐBQH tỉnh/thành) trong mảng `persons[]`.

| Nhóm | Tên trường | Kiểu dữ liệu | Bắt buộc | Ý nghĩa nghiệp vụ & Quy tắc bóc tách | Mapping Form HSĐB |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **`metadata`** | `document_number` | `string` | Có | Số nghị quyết (VD: `1783/NQ-UBTVQH15`) | Số quyết định |
| | `document_name` | `string` | Có | Trích yếu (VD: `Về việc tặng Kỷ niệm chương “Vì sự nghiệp Quốc hội Việt Nam”`) | Tên văn bản / Trích yếu |
| | `issue_date` | `string` | Có | Ngày ký ban hành `DD/MM/YYYY` (VD: `06/08/2025`) | Ngày ban hành |
| | `issue_unit` | `string` | Có | Cơ quan ban hành (VD: `Ủy ban Thường vụ Quốc hội`) | Cơ quan ban hành |
| | `signer` | `string` | Có | Họ tên người ký (VD: `Trần Thanh Mẫn`) | Người ký |
| | `content` | `string` | Có | Nội dung Điều 1 (tuyên bố tặng KNC cho 47 cá nhân) | Nội dung quyết định |
| | `doc_type_detected` | `string` | Có | Loại văn bản nhận diện tự động (`KY_NIEM_CHUONG`) | — |
| **`detail`** | `award_year` | `integer` | Có | Năm khen tặng (lấy từ ngày ký hoặc Điều 1, VD: `2025`) | Năm khen tặng |
| | `medal_name` | `string` | Có | Tên Kỷ niệm chương (VD: `Vì sự nghiệp Quốc hội Việt Nam`) | Kỷ niệm chương |
| **`groups[]`** | `group_index` | `integer` | Có | STT khối nhóm (1, 2, 3) | — |
| | `title` | `string` | Có | Tiêu đề khối nhóm (I, II, III trong danh sách đính kèm) | Tên khối nhóm đối tượng |
| | `person_count_declared`| `integer` | Có | Số lượng cá nhân tuyên bố trong khối (VD: `37`, `5`, `5`) | Số lượng chỉ tiêu khối |
| **`persons[]`**| `stt` | `integer` | Có | STT toàn danh sách tăng dần từ 1 đến 47 | Bảng danh sách - STT |
| | `group_index` | `integer` | Có | Thuộc khối nào (1: ĐBQH, 2: Lãnh đạo địa phương, 3: Công chức VP) | Khối liên kết |
| | `code` | `string` | Có | Số thứ tự gốc trong khối (VD: `"1"`, `"11"`, `"37"`) | STT gốc |
| | `is_collective` | `boolean` | Có | Luôn là `false` | — |
| | `full_name` | `string` | Có | Họ và tên cá nhân (đã tách danh xưng, quân hàm) | Họ và tên |
| | `position_name` | `string` | Không | Chức vụ chính quyền/chuyên môn của cá nhân | Chức vụ |
| | `work_organization_name` | `string` | Có | Cơ quan/đơn vị công tác chính | Đơn vị công tác |
| | `na_term` | `string` | Không | Khóa ĐBQH (VD: `"XV"`, `"XIV, XV"`). Nếu không phải ĐBQH trả `null` | Khóa ĐBQH |
| | `delegation` | `string` | Không | Đoàn ĐBQH tỉnh/thành phố (VD: `Thành phố Hồ Chí Minh`). Ngoài nhóm ĐBQH trả `null` | Đoàn ĐBQH |
| | `raw_text` | `string` | Có | Dòng trích dẫn nguyên văn từ file danh sách | Đoạn văn đối chiếu |

### 3.6.4. Full JSON Response thực tế (Trích xuất đầy đủ 3 khối)
```json
{
  "request_id": "knc-1783-55ca-11ee-bb89-012389aacc99",
  "status": "FINISHED",
  "result": {
    "status": "success",
    "error": null,
    "doc_type": "KY_NIEM_CHUONG",
    "person_count_declared": 47,
    "tong_so_ca_nhan": 47,
    "metadata": {
      "document_number": "1783/NQ-UBTVQH15",
      "document_name": "Về việc tặng Kỷ niệm chương “Vì sự nghiệp Quốc hội Việt Nam”",
      "issue_date": "06/08/2025",
      "issue_unit": "Ủy ban Thường vụ Quốc hội",
      "signer": "Trần Thanh Mẫn",
      "content": "Điều 1. Tặng Kỷ niệm chương “Vì sự nghiệp Quốc hội Việt Nam” cho 47 cá nhân đã có đóng góp vào quá trình phát triển của Quốc hội Việt Nam (có danh sách kèm theo).",
      "doc_type_detected": "KY_NIEM_CHUONG"
    },
    "detail": {
      "award_year": 2025,
      "medal_name": "Vì sự nghiệp Quốc hội Việt Nam"
    },
    "groups": [
      {
        "group_index": 1,
        "title": "I. Tặng Kỷ niệm chương “Vì sự nghiệp Quốc hội Việt Nam” cho 37 cá nhân là đại biểu Quốc hội khóa XV, Đoàn đại biểu Quốc hội Thành phố Hồ Chí Minh",
        "person_count_declared": 37
      },
      {
        "group_index": 2,
        "title": "II. Tặng Kỷ niệm chương “Vì sự nghiệp Quốc hội Việt Nam” cho 05 cá nhân là lãnh đạo Thành phố Hồ Chí Minh",
        "person_count_declared": 5
      },
      {
        "group_index": 3,
        "title": "III. Tặng Kỷ niệm chương “Vì sự nghiệp Quốc hội Việt Nam” cho 05 cá nhân là công chức Văn phòng Đoàn đại biểu Quốc hội và Hội đồng nhân dân Thành phố Hồ Chí Minh",
        "person_count_declared": 5
      }
    ],
    "persons": [
      {
        "stt": 1,
        "group_index": 1,
        "code": "1",
        "is_collective": false,
        "full_name": "Nguyễn Tân Cương",
        "position_name": "Tổng Tham mưu trưởng Quân đội nhân dân Việt Nam, Thứ trưởng",
        "work_organization_name": "Bộ Quốc phòng",
        "na_term": "XV",
        "delegation": "Thành phố Hồ Chí Minh",
        "raw_text": "(1) Đồng chí Đại tướng Nguyễn Tân Cương, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Thường vụ Quân ủy Trung ương, Tổng Tham mưu trưởng Quân đội nhân dân Việt Nam, Thứ trưởng Bộ Quốc phòng, đại biểu Quốc hội khóa XV."
      },
      {
        "stt": 2,
        "group_index": 1,
        "code": "2",
        "is_collective": false,
        "full_name": "Nguyễn Văn Lợi",
        "position_name": "Trưởng Đoàn đại biểu Quốc hội khóa XV",
        "work_organization_name": "Đoàn đại biểu Quốc hội Thành phố Hồ Chí Minh",
        "na_term": "XV",
        "delegation": "Thành phố Hồ Chí Minh",
        "raw_text": "(2) Đồng chí Nguyễn Văn Lợi, Ủy viên Ban Chấp hành Trung ương Đảng, Trưởng Đoàn đại biểu Quốc hội khóa XV, Đoàn đại biểu Quốc hội Thành phố Hồ Chí Minh, Ủy viên Ủy ban Quốc phòng, An ninh và Đối ngoại của Quốc hội."
      },
      {
        "stt": 11,
        "group_index": 1,
        "code": "11",
        "is_collective": false,
        "full_name": "Đặng Văn Lẫm",
        "position_name": "Phó Tư lệnh",
        "work_organization_name": "Bộ Tư lệnh Quân khu 7",
        "na_term": "XV",
        "delegation": "Thành phố Hồ Chí Minh",
        "raw_text": "(11) Đồng chí Thiếu tướng Đặng Văn Lẫm, Phó Tư lệnh Bộ Tư lệnh Quân khu 7, đại biểu Quốc hội khóa XV, Đoàn đại biểu Quốc hội Thành phố Hồ Chí Minh, Ủy viên Ủy ban Quốc phòng, An ninh và Đối ngoại của Quốc hội."
      },
      {
        "stt": 38,
        "group_index": 2,
        "code": "1",
        "is_collective": false,
        "full_name": "Nguyễn Văn Nên",
        "position_name": "Bí thư Thành ủy",
        "work_organization_name": "Thành ủy Thành phố Hồ Chí Minh",
        "na_term": null,
        "delegation": null,
        "raw_text": "(1) Đồng chí Nguyễn Văn Nên, Ủy viên Bộ Chính trị, Bí thư Thành ủy Thành phố."
      },
      {
        "stt": 39,
        "group_index": 2,
        "code": "2",
        "is_collective": false,
        "full_name": "Nguyễn Thanh Nghị",
        "position_name": "Phó Bí thư Thường trực Thành ủy",
        "work_organization_name": "Thành ủy Thành phố Hồ Chí Minh",
        "na_term": null,
        "delegation": null,
        "raw_text": "(2) Đồng chí Nguyễn Thanh Nghị, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Bí thư Thường trực Thành ủy Thành phố Hồ Chí Minh."
      },
      {
        "stt": 43,
        "group_index": 3,
        "code": "1",
        "is_collective": false,
        "full_name": "Hồ Hiếu Thảo",
        "position_name": "Phó Chánh Văn phòng",
        "work_organization_name": "Văn phòng Đoàn đại biểu Quốc hội và Hội đồng nhân dân Thành phố Hồ Chí Minh",
        "na_term": null,
        "delegation": null,
        "raw_text": "(1) Đồng chí Hồ Hiếu Thảo, Phó Chánh Văn phòng Đoàn đại biểu Quốc hội và Hội đồng nhân dân Thành phố Hồ Chí Minh."
      },
      {
        "stt": 47,
        "group_index": 3,
        "code": "5",
        "is_collective": false,
        "full_name": "Nguyễn Ngọc Bích",
        "position_name": "Kế toán",
        "work_organization_name": "Văn phòng Đoàn đại biểu Quốc hội và Hội đồng nhân dân Thành phố Hồ Chí Minh",
        "na_term": null,
        "delegation": null,
        "raw_text": "(5) Đồng chí Nguyễn Ngọc Bích, Kế toán, Văn phòng Đoàn đại biểu Quốc hội và Hội đồng nhân dân Thành phố Hồ Chí Minh."
      }
    ],
    "warnings": []
  }
}
```

### 3.6.5. Lưu ý nghiệp vụ & Cảnh báo
- Khi gửi request, **bắt buộc gửi cả 2 file** (NQ chính và danh sách kèm). Nếu người dùng quên đính kèm file danh sách, hệ thống vẫn trích xuất phần `metadata` của Nghị quyết và trả về `persons = []` kèm cảnh báo `MISSING_ATTACHMENT`.
- Đối với các cá nhân thuộc Khối II và Khối III không phải ĐBQH, hệ thống gán `na_term = null` và `delegation = null`.

---

## 3.7. `doc_type = "QUY_HOACH"` (Phê duyệt quy hoạch chức danh)

### 3.7.1. Nghiệp vụ & Form đích trên HSĐB
- **Mục đích**: Tự động điền dữ liệu khi mở form **"Thêm mới Quyết định Quy hoạch"**.
- **Đặc trưng văn bản**: Quyết định của Ban Tổ chức Trung ương hoặc cấp có thẩm quyền phê duyệt quy hoạch các chức danh cán bộ thuộc Quốc hội khóa mới (VD: khóa XVI nhiệm kỳ 2026-2031). Danh sách được chia theo **nhóm chức danh quy hoạch** (Chủ tịch Hội đồng Dân tộc, Chủ nhiệm các Ủy ban...).
- **Đặc trưng nhân thân**: Văn bản quy hoạch ghi rõ **giới tính, dân tộc, ngày tháng năm sinh** của từng nhân sự.
- **Tài liệu kiểm thử thực tế**: File `7. QUY_HOACH_danh_dau.pdf` (Quyết định số `2031-QĐ/BTCTW` ngày 20/07/2023 của Ban Tổ chức Trung ương).

### 3.7.2. Quy cách Request
- Tham số `doc_type`: `"QUY_HOACH"`
- Số lượng file: 01 file PDF (hoặc nhiều file nếu tách riêng bản quyết định và danh sách kèm theo).
- Lệnh cURL mẫu:
```bash
curl -X POST "https://<ai-service-host>/hsdb/extract" \
  -F "doc_type=QUY_HOACH" \
  -F "files=@7. QUY_HOACH_danh_dau.pdf;type=application/pdf"
```

### 3.7.3. Đặc tả Response Schema
Đối với `QUY_HOACH`: Bổ sung các trường `gender`, `ethnicity`, `date_of_birth`, `current_position` trong `persons[]` và `planned_unit`, `planned_position` trong `groups[]`.

| Nhóm | Tên trường | Kiểu dữ liệu | Bắt buộc | Ý nghĩa nghiệp vụ & Quy tắc bóc tách | Mapping Form HSĐB |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **`metadata`** | `document_number` | `string` | Có | Số quyết định quy hoạch (VD: `2031-QĐ/BTCTW` viết tay). **Lưu ý: Bỏ qua dấu "ĐẾN" của văn thư!** | Số quyết định |
| | `document_name` | `string` | Có | Trích yếu quyết định phê duyệt quy hoạch | Tên văn bản / Trích yếu |
| | `issue_date` | `string` | Có | Ngày ký ban hành `DD/MM/YYYY` (VD: `20/07/2023`) | Ngày ban hành |
| | `issue_unit` | `string` | Có | Cơ quan ban hành (VD: `Ban Tổ chức Trung ương`) | Cơ quan ban hành |
| | `signer` | `string` | Có | Người ký (VD: `Nguyễn Quang Dương`) | Người ký |
| | `content` | `string` | Có | Nội dung Điều 1 quyết định phê duyệt | Nội dung quyết định |
| | `doc_type_detected` | `string` | Có | Loại văn bản nhận diện tự động (`QUY_HOACH`) | — |
| **`detail`** | `approval_agency` | `string` | Có | Cơ quan phê duyệt quy hoạch (VD: `Ban Tổ chức Trung ương`) | Cơ quan phê duyệt |
| | `na_term` | `string` | Có | Khóa Quốc hội được quy hoạch (VD: `XVI`) | Khóa Quốc hội |
| | `period_from` | `integer` | Có | Giai đoạn quy hoạch: từ năm (VD: `2026`) | Giai đoạn (Từ năm) |
| | `period_to` | `integer` | Có | Giai đoạn quy hoạch: đến năm (VD: `2031`) | Giai đoạn (Đến năm) |
| **`groups[]`** | `group_index` | `integer` | Có | STT nhóm chức danh quy hoạch (bắt đầu từ 1) | — |
| | `title` | `string` | Có | Nguyên văn tiêu đề mục nhóm (VD: `1- Quy hoạch chức danh Chủ tịch Hội đồng Dân tộc của Quốc hội`) | Tên nhóm quy hoạch |
| | `planned_unit` | `string` | Có | Đơn vị/Cơ quan quy hoạch đến (VD: `Hội đồng Dân tộc của Quốc hội`) | Đơn vị quy hoạch |
| | `planned_position` | `string` | Có | Chức danh cán bộ được quy hoạch (VD: `Chủ tịch`) | Chức danh quy hoạch |
| | `person_count_declared`| `integer` | Không | Số lượng cá nhân quy hoạch chức danh này | Số lượng cán bộ |
| **`persons[]`**| `stt` | `integer` | Có | STT toàn danh sách tăng dần từ 1 | Bảng danh sách - STT |
| | `group_index` | `integer` | Có | Thuộc nhóm chức danh quy hoạch nào trong `groups` | Nhóm liên kết |
| | `code` | `string` | Không | STT hoặc gạch đầu dòng trong nhóm | STT gốc |
| | `is_collective` | `boolean` | Có | Luôn là `false` | — |
| | `full_name` | `string` | Có | Họ tên cán bộ quy hoạch (đã bỏ danh xưng Đồng chí) | Họ và tên |
| | `gender` | `string` | Có | Giới tính (VD: `Nam`, `Nữ`) | Giới tính |
| | `ethnicity` | `string` | Có | Dân tộc (VD: `Kinh`, `Khmer`, `Tày`, `Thái`...) | Dân tộc |
| | `date_of_birth` | `string` | Có | Ngày tháng năm sinh `DD/MM/YYYY` (VD: `11/04/1976`) | Ngày sinh |
| | `current_position` | `string` | Có | Chức vụ hiện tại nguyên văn (VD: `Phó Chủ tịch Hội đồng Dân tộc của Quốc hội khóa XV`) | Chức vụ hiện tại đầy đủ |
| | `position_name` | `string` | Có | Chức vụ chính hiện tại (VD: `Phó Chủ tịch`) | Chức vụ chính |
| | `work_organization_name` | `string` | Có | Đơn vị công tác hiện tại (VD: `Hội đồng Dân tộc của Quốc hội`) | Đơn vị hiện tại |
| | `raw_text` | `string` | Có | Nguyên văn dòng cán bộ được quy hoạch | Đoạn văn đối chiếu |

### 3.7.4. Full JSON Response thực tế
```json
{
  "request_id": "qh-2031-1029-cc88-518209bb7101",
  "status": "FINISHED",
  "result": {
    "status": "success",
    "error": null,
    "doc_type": "QUY_HOACH",
    "person_count_declared": 1,
    "tong_so_ca_nhan": 1,
    "metadata": {
      "document_number": "2031-QĐ/BTCTW",
      "document_name": "Phê duyệt quy hoạch các chức danh cán bộ diện Trung ương quản lý của Quốc hội khóa XVI, nhiệm kỳ 2026-2031",
      "issue_date": "20/07/2023",
      "issue_unit": "Ban Tổ chức Trung ương",
      "signer": "Nguyễn Quang Dương",
      "content": "Điều 1. Phê duyệt quy hoạch các chức danh cán bộ diện Trung ương quản lý của Quốc hội khóa XVI, nhiệm kỳ 2026-2031 (có danh sách kèm theo).",
      "doc_type_detected": "QUY_HOACH"
    },
    "detail": {
      "approval_agency": "Ban Tổ chức Trung ương",
      "na_term": "XVI",
      "period_from": 2026,
      "period_to": 2031
    },
    "groups": [
      {
        "group_index": 1,
        "title": "1- Quy hoạch chức danh Chủ tịch Hội đồng Dân tộc của Quốc hội",
        "planned_unit": "Hội đồng Dân tộc của Quốc hội",
        "planned_position": "Chủ tịch",
        "person_count_declared": 1
      }
    ],
    "persons": [
      {
        "stt": 1,
        "group_index": 1,
        "code": "1",
        "is_collective": false,
        "full_name": "Trần Thị Hoa Ry",
        "gender": "Nữ",
        "ethnicity": "Khmer",
        "date_of_birth": "11/04/1976",
        "current_position": "Phó Chủ tịch Hội đồng Dân tộc của Quốc hội khóa XV",
        "position_name": "Phó Chủ tịch",
        "work_organization_name": "Hội đồng Dân tộc của Quốc hội",
        "raw_text": "Đồng chí Trần Thị Hoa Ry; (nữ, dân tộc: Khmer), sinh ngày 11/4/1976, Phó Chủ tịch Hội đồng Dân tộc của Quốc hội khóa XV."
      }
    ],
    "warnings": [
      {
        "code": "HANDWRITTEN_FIELD",
        "message": "Số quyết định và ngày ký có dấu hiệu viết tay: metadata.document_number, metadata.issue_date"
      }
    ]
  }
}
```

### 3.7.5. Lưu ý nghiệp vụ & Cảnh báo
- **Quy tắc tuyệt đối**: Cạnh số quyết định thường có **Dấu "ĐẾN" của Văn thư Đảng đoàn Quốc hội** (chứa `Số: 130/Đ`, `Ngày: 21/7/23`, `Chuyển...`). Hệ thống AI **tuyệt đối không được lấy nhầm** số và ngày của dấu ĐẾN này làm số quyết định hoặc ngày ban hành của văn bản.
- Ngày sinh được trích xuất theo định dạng chuẩn `DD/MM/YYYY` (ví dụ `11/4/1976` ➔ `11/04/1976`).

---

# PHẦN 4: BẢNG TỔNG HỢP & YÊU CẦU HỆ THỐNG

## 4.1. Ma trận trường dữ liệu theo 7 loại văn bản

| Tên trường | Vị trí trường | `QTCT` | `LUONG` | `PHU_CAP` | `THI_DUA` | `KHEN_THUONG` | `KY_NIEM_CHUONG` | `QUY_HOACH` |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `document_number`, `document_name`, `issue_date`, `issue_unit`, `signer`, `content` | `metadata` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `process_type`, `appointment_term_years`, `from_organization_name` | `detail` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `position_wage`, `position_wage_code`, `salary_step`, `salary_factor`, `old_step`, `old_factor`, `review_date` | `detail` | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `allowance_type`, `allowance_name`, `allowance_factor`, `amount`, `effective_from` | `detail` | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `type` (`1: Thi đua`, `2: Khen thưởng`), `year`, `reward_level` | `detail` | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| `award_year`, `medal_name` | `detail` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| `approval_agency`, `na_term`, `period_from`, `period_to` | `detail` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| `groups[]` (Phân nhóm danh sách) | `groups` | `[]` | `[]` | `[]` | ✅ | ✅ | ✅ | ✅ |
| `planned_unit`, `planned_position` | `groups` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| `reward_type`, `accomplishment` | `groups` | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| `stt`, `full_name`, `position_name`, `work_organization_name`, `raw_text` | `persons` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `award_type` (`TANG` / `TRUY_TANG`) | `persons` | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| `na_term`, `delegation` (ĐBQH) | `persons` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| `gender`, `ethnicity`, `date_of_birth`, `current_position` | `persons` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 4.2. Yêu cầu phi chức năng (Non-Functional Requirements)

| Tiêu chí | Ngưỡng yêu cầu |
| :--- | :--- |
| **Thời gian phản hồi** | - Văn bản cá nhân (`QTCT`, `LUONG`, `PHU_CAP`) ≤ 5 trang: thời gian xử lý ≤ **30 giây**.<br>- Văn bản tập thể (`THI_DUA`, `KHEN_THUONG`, `KY_NIEM_CHUONG`, `QUY_HOACH`) ≤ 100 cá nhân: thời gian xử lý ≤ **120 giây**.<br>- Trả kết quả tức thì (≤ **1 giây**) nếu trúng cache. |
| **Độ chính xác nhận dạng** | - Thông tin `metadata`: độ chính xác đạt ≥ **95%** với file PDF số hóa và ≥ **85%** với bản scan mờ/viết tay.<br>- Thông tin `persons`: Họ và tên, chức vụ chính đạt độ chính xác ≥ **95%**. |
| **Bảo mật & An toàn** | - Giao thức truyền tải bắt buộc HTTPS (TLS 1.3).<br>- Xác thực phân quyền qua Bearer Token / API Key.<br>- Dữ liệu văn bản và thông tin đại biểu không được sử dụng vào mục đích huấn luyện mô hình bên ngoài.<br>- File upload được tự động xóa khỏi bộ nhớ đệm sau 24 giờ kể từ thời điểm khởi tạo `request_id`. |

---

## 4.3. Các điểm đề nghị Trung tâm AI xác nhận & Phối hợp

1. **Hỗ trợ trích xuất Multi-file trong 1 request**: Xác nhận hệ thống tiếp nhận mảng file `files` trong `POST /hsdb/extract` để xử lý gom nhóm văn bản chính và các file danh sách kèm theo (như mẫu NQ 1783 Kỷ niệm chương).
2. **Cơ chế nhận diện chữ viết tay (`HANDWRITTEN_FIELD`)**: Xác nhận khả năng phát hiện số văn bản và ngày tháng viết tay trên bản scan để trả về mã cảnh báo tương ứng trong mảng `warnings`.
3. **Mẫu bổ sung**: Đội ngũ HSĐB sẽ tiếp tục cung cấp bổ sung mẫu scan thực tế của loại `PHU_CAP` và `THI_DUA` ngay khi có văn bản phát sinh từ các cơ quan hữu quan.
4. **Định vị số trang nguồn (`page`)**: Đề xuất giai đoạn 2 AI Service trả thêm thuộc tính `page` cho từng cá nhân trong mảng `persons[]` để hỗ trợ hệ thống HSĐB tự động cuộn trang PDF đến đúng vị trí của đại biểu khi người dùng rà soát thông tin.
