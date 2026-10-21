# Nghiệp vụ 7 Loại Văn bản Hồ sơ Đại biểu (Document Types)

Hệ thống hỗ trợ 7 loại văn bản (`doc_type`) tương ứng với các biến động trong Hồ sơ Đại biểu (HSĐB).

---

## 1. Bảng Tổng quan 7 Loại Văn bản

| Mã `doc_type` | Tên nghiệp vụ | Form đích tương ứng trên HSĐB | Đối tượng | Mô hình bóc tách |
| :--- | :--- | :--- | :---: | :--- |
| **`QTCT`** | Quá trình công tác | Thêm mới quá trình công tác | 1 cá nhân | Đơn lẻ (Điều 1) |
| **`LUONG`** | Nâng bậc lương | Thêm mới quá trình lương | 1 cá nhân | Đơn lẻ (Điều 1) |
| **`PHU_CAP`** | Quyết định phụ cấp | Thêm mới quá trình phụ cấp | 1 cá nhân | Đơn lẻ (Điều 1) |
| **`THI_DUA`** | Danh hiệu thi đua | Thi đua – Khen thưởng (`type = 1`) | N đối tượng | Danh sách / Nhóm |
| **`KHEN_THUONG`** | Khen thưởng | Thi đua – Khen thưởng (`type = 2`) | N đối tượng | Danh sách kèm theo |
| **`KY_NIEM_CHUONG`** | Kỷ niệm chương | Quản lý kỷ niệm chương | N cá nhân | Danh sách kèm theo |
| **`QUY_HOACH`** | Quy hoạch chức danh | Thêm mới Quyết định Quy hoạch | N cá nhân | Danh mục chức danh |

---

## 2. Quy tắc Nghiệp vụ Cốt lõi Dùng Chung (Core Business Rules)

### 2.1. Chuẩn hóa Họ và tên (`full_name`)
- **Tách bỏ hoàn toàn danh xưng**: `Ông`, `Bà`, `Đồng chí`.
- **Tách bỏ cấp hàm sĩ quan / công an / chức sắc**: `Đại tướng`, `Thượng tướng`, `Trung tướng`, `Thiếu tướng`, `Đại tá`, `Thượng tá`, `Linh mục`, `Chuẩn Đô đốc`.
- *Ví dụ*: `(1) Đồng chí Thượng tướng Trần Quang Phương` ➔ `full_name = "Trần Quang Phương"`.
- Lưu giữ trọn vẹn câu nguyên văn vào trường `raw_text` để phục vụ đối chiếu, kiểm tra.

### 2.2. Tách Chức vụ Chính quyền & Chức vụ Đảng / Kiêm nhiệm
- **Chức vụ Đảng**: Bỏ các chức danh như `Ủy viên Bộ Chính trị`, `Ủy viên BCH Trung ương Đảng`, `Thành ủy viên`, `Bí thư Chi bộ`... khi cá nhân có chức vụ chính quyền / Quốc hội / chuyên môn.
- **Chức vụ kiêm nhiệm**: Bỏ các chức vụ kiêm nhiệm như `Ủy viên Ủy ban Thường vụ Quốc hội`, `Đại biểu Quốc hội khóa XV`.
- **Chức vụ chính quyền cao nhất**: Giữ lại chức danh chính quyền / Quốc hội cao nhất tại thời điểm văn bản ban hành.
- **Tách riêng chức vụ (`position_name`) và đơn vị (`work_organization_name`)**:
  - `position_name`: Chỉ tên chức vụ (VD: `Chủ tịch`, `Phó Chủ tịch`, `Vụ trưởng`, `Thứ trưởng`).
  - `work_organization_name`: Tên cơ quan, đơn vị (VD: `Quốc hội`, `Bộ Quốc phòng`, `Văn phòng Quốc hội`).
  - *Ví dụ*: `Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội` ➔ `position_name = "Chủ tịch"`, `work_organization_name = "Quốc hội"`.

### 2.3. Nguyên tắc Kế thừa Nhóm (`group_index`)
Đối với các văn bản khen thưởng, thi đua hoặc kỷ niệm chương có chia nhóm theo hình thức hoặc thành tích:
- Thông tin chung của nhóm (tiêu đề, hình thức khen thưởng, thành tích) được lưu trong mảng `groups[]`.
- Mỗi phần tử trong `persons[]` liên kết với nhóm tương ứng qua trường `group_index` để tự động kế thừa thông tin nhóm.

---

## 3. Đặc tả Chi tiết Từng Loại Văn bản

### 3.1. `QTCT` — Quá trình Công tác
- **Phạm vi**: Quyết định điều động, bổ nhiệm, luân chuyển, từ chức hoặc thôi giữ chức vụ cho **đúng 01 cá nhân**.
- **Cấu trúc trường `detail`**:
  - `process_type`: Loại quá trình (ví dụ: *Điều động và bổ nhiệm*, *Tiếp nhận và bổ nhiệm*, *Bổ nhiệm lại*).
  - `start_date`: Ngày bắt đầu nhận công tác/giữ chức vụ mới (`DD/MM/YYYY`).
  - `from_organization_name`: Đơn vị công tác trước khi chuyển.
  - `work_organization_name`: Đơn vị mới đến nhận công tác.
  - `position_name`: Chức vụ mới được bổ nhiệm.
  - `position_detail`: Tên đầy đủ chức vụ + cơ quan mới.
  - `appointment_term_years`: Thời hạn bổ nhiệm tính theo năm (ví dụ: `5.0`).
  - `allowance_name` & `allowance_factor`: Phụ cấp chức vụ lãnh đạo kèm theo (nếu có).

### 3.2. `LUONG` — Nâng bậc Lương
- **Phạm vi**: Quyết định nâng bậc lương thường xuyên hoặc nâng bậc lương trước thời hạn cho **đúng 01 cá nhân**.
- **Cấu trúc trường `detail`**:
  - `raise_salary_reason`: Lý do nâng lương (ví dụ: *Nâng bậc lương thường xuyên*, *Nâng bậc lương trước thời hạn*).
  - `position_wage`: Ngạch / Chức danh nghề nghiệp (ví dụ: *Giảng viên cao cấp (hạng I)*, *Chuyên viên chính*).
  - `position_wage_code`: Mã ngạch công chức (ví dụ: *V.07.01.01*, *01.002*).
  - `old_step` & `old_factor`: Bậc lương và hệ số cũ trước khi nâng (ví dụ: Bậc `3`, Hệ số `6.92`).
  - `salary_step` & `salary_factor`: Bậc lương và hệ số mới được nâng lên (ví dụ: Bậc `4`, Hệ số `7.28`).
  - `start_date`: Mốc ngày tháng bắt đầu hưởng mức lương mới (`DD/MM/YYYY`).
  - `review_date`: Mốc tính nâng lương lần sau (`DD/MM/YYYY`).
  - `percentage`: Tỷ lệ hưởng (nếu có, ví dụ: tỷ lệ vượt khung).

### 3.3. `PHU_CAP` — Quyết định Phụ cấp
- **Phạm vi**: Quyết định chi trả phụ cấp chức vụ, kiêm nhiệm, trách nhiệm, thâm niên cho **01 cá nhân**.
- **Cấu trúc trường `detail`**:
  - `allowance_type`: Loại phụ cấp (ví dụ: *Phụ cấp trách nhiệm công tác*, *Phụ cấp kiêm nhiệm*).
  - `allowance_name`: Tên chi tiết khoản phụ cấp.
  - `allowance_factor`: Hệ số phụ cấp (ví dụ: `0.5`, `0.8`).
  - `amount`: Số tiền phụ cấp trực tiếp (nếu tính theo VNĐ).
  - `effective_from`: Ngày bắt đầu hưởng phụ cấp.

### 3.4. `THI_DUA` — Danh hiệu Thi đua
- **Phạm vi**: Quyết định công nhận danh hiệu thi đua (Chiến sĩ thi đua toàn quốc, Chiến sĩ thi đua cơ sở, Cờ thi đua...) cho **N đối tượng (cá nhân và/hoặc tập thể)**.
- **Cấu trúc trường `detail`**:
  - `type`: Cố định là `1` (Thi đua).
  - `year`: Năm đạt danh hiệu (ví dụ: `2024`).
  - `reward_level`: Cấp công nhận danh hiệu.
  - `content`: Trích yếu nội dung công nhận.

### 3.5. `KHEN_THUONG` — Khen thưởng
- **Phạm vi**: Nghị quyết / Quyết định tặng thưởng Huân chương, Huy chương, Bằng khen cho **N đối tượng**.
- **Cấu trúc trường `detail`**:
  - `type`: Cố định là `2` (Khen thưởng).
  - `year`: Năm khen thưởng.
  - `reward_level`: Cấp khen thưởng (ví dụ: *Bằng khen Ủy ban Thường vụ Quốc hội*).
  - `content`: Toàn văn nội dung Điều 1.
- **Cơ chế bóc tách danh sách kèm theo**:
  - Phân tích cây cấu trúc OCR để định vị tiêu đề `DANH SÁCH`.
  - Phân tách từng nhóm danh hiệu (`groups`).
  - Gửi request song song cho từng cá nhân (One person per request) để đảm bảo không bị sót hoặc sai thứ tự cá nhân.

### 3.6. `KY_NIEM_CHUONG` — Kỷ niệm chương
- **Phạm vi**: Tặng Kỷ niệm chương "Vì sự nghiệp Quốc hội Việt Nam" cho **N cá nhân**.
- **Cấu trúc trường `detail`**:
  - `award_year`: Năm trao tặng kỷ niệm chương (ví dụ: `2025`).
  - `medal_name`: Tên kỷ niệm chương (Cố định: *Vì sự nghiệp Quốc hội Việt Nam*).
- **Thông tin bổ sung của từng cá nhân**:
  - `na_term`: Khóa Quốc hội (ví dụ: `XV`).
  - `delegation`: Đoàn Đại biểu Quốc hội địa phương (ví dụ: `Thành phố Hồ Chí Minh`).

### 3.7. `QUY_HOACH` — Phê duyệt Quy hoạch Cán bộ
- **Phạm vi**: Quyết định phê duyệt quy hoạch chức danh cán bộ diện Trung ương quản lý cho **N cá nhân**.
- **Cấu trúc trường `detail`**:
  - `approval_agency`: Cơ quan phê duyệt (ví dụ: *Ban Tổ chức Trung ương*).
  - `na_term`: Khóa quy hoạch (ví dụ: *XVI*).
  - `period_from` & `period_to`: Nhiệm kỳ quy hoạch (ví dụ: `2026` - `2031`).
- **Thông tin quy hoạch theo nhóm**:
  - `planned_position`: Chức danh được quy hoạch (ví dụ: *Chủ tịch Hội đồng Dân tộc*).
  - `planned_unit`: Đơn vị được quy hoạch.
