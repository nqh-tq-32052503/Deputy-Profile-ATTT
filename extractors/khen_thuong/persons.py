import asyncio
import logging
from typing import Any, List, Optional, Tuple

from extractors.khen_thuong.ocr_parser import (
    GroupChunk,
    UNIT_KEYWORDS,
    _clean_unit,
    _is_appendix_header,
    _is_group_title,
    _strip_dbqh_prefix,
)
from extractors.khen_thuong.schemas import KhenThuongPerson
from services.llm_service import (
    LLMService,
    arefine_position_and_organization,
    clean_text,
    refine_position_and_organization,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt cho luồng cũ (markdown text, không có OCR tree)
# ---------------------------------------------------------------------------

PERSONS_PROMPT = """Bạn là chuyên gia trích xuất văn bản hành chính Việt Nam.
Nhiệm vụ: Trích xuất toàn bộ danh sách cá nhân/tập thể được khen thưởng trong văn bản Khen thưởng (KHEN_THUONG) dưới dạng JSON mảng danh sách đối tượng.

Mỗi đối tượng gồm các trường sau:
- stt: Số thứ tự tăng dần từ 1 đến hết toàn bộ danh sách (1, 2, 3, ..., N).
- group_index: Thuộc nhóm nào trong các mục phân loại (1 cho mục 1, 2 cho mục 2, 3 cho mục 3...).
- code: Số thứ tự gốc ghi trong dấu ngoặc đơn ở đầu dòng (chuỗi ký tự, ví dụ: "1", "2", "14").
- is_collective: false nếu là cá nhân, true nếu là tập thể.
- full_name: Tên của đối tượng:
  * Nếu là tập thể (is_collective = true): là tên đầy đủ của tập thể (ví dụ: "Văn phòng Quốc hội", "Viện Nghiên cứu lập pháp", "Ban Dân nguyện"...).
  * Nếu là cá nhân (is_collective = false): là họ và tên cá nhân (loại bỏ hoàn toàn danh xưng Ông, Bà, Đồng chí và cấp bậc hàm quân đội/công an như Đại tướng, Thượng tướng, Trung tướng, Thiếu tướng, Đại tá... ví dụ: "Trần Thanh Mẫn", "Nguyễn Đức Hải", "Lê Tấn Tới").
- position_name:
  * Nếu là tập thể (is_collective = true): null (tập thể TUYỆT ĐỐI không có chức vụ).
  * Nếu là cá nhân (is_collective = false): Chức vụ của cá nhân.
- work_organization_name:
  * Nếu là tập thể (is_collective = true): Tên của chính tập thể đó (trùng với full_name, ví dụ: "Văn phòng Quốc hội", "Viện Nghiên cứu lập pháp").
  * Nếu là cá nhân (is_collective = false): Tên cơ quan, đơn vị công tác của cá nhân.
- award_type: Hình thức trao tặng, giá trị là "TANG" hoặc "TRUY_TANG" (nếu có từ khóa "Truy tặng" thì điền "TRUY_TANG", thông thường là "TANG").
- raw_text: Dòng hoặc đoạn văn trích dẫn nguyên văn đối tượng trên văn bản scan (ví dụ: "(1) Văn phòng Quốc hội." hoặc "(1) Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội.").

QUY TẮC BÓC TÁCH CHỨC VỤ (position_name) VÀ CƠ QUAN CÔNG TÁC (work_organization_name) CHO CÁ NHÂN (BẮT BUỘC TUÂN THỦ):
1. Lựa chọn chức vụ chính:
   - TUYỆT ĐỐI KHÔNG đưa các chức danh Đảng vào position_name hoặc work_organization_name khi cá nhân có chức vụ chính quyền/Quốc hội/chuyên môn.
     * Dấu hiệu nhận biết các chức vụ Đảng là có từ khóa "đảng" ở trong tên chức vụ (hoặc "Bộ Chính trị", "Ban Bí thư", "Trung ương Đảng", "BCH Trung ương Đảng", "Cấp ủy", "Đảng ủy", "Đảng viên"...).
     * Ví dụ: "Ủy viên Ban Chấp hành Trung ương Đảng", "Ủy viên Trung ương Đảng", "Ủy viên Bộ Chính trị", "Ủy viên Ban Bí thư"... là các chức danh Đảng và BẮT BUỘC PHẢI BỎ QUA.
   - BỎ QUA các chức vụ kiêm nhiệm như "Ủy viên Ủy ban Thường vụ Quốc hội", "Ủy viên Hội đồng...", "Ủy viên Ủy ban... của Quốc hội", "đại biểu Quốc hội khóa...".
   - LỰA CHỌN chức vụ chính quyền / Quốc hội / chuyên môn cao nhất tại thời điểm ban hành.
   - Trường hợp cá nhân chỉ có duy nhất chức vụ thuộc tổ chức Đảng (ví dụ: Bí thư Thành ủy, Phó Bí thư Tỉnh ủy...) mà không có chức vụ chính quyền nào khác thì lấy chức vụ Đảng đó.
2. Phân tách position_name và work_organization_name từ chức vụ được chọn:
   - position_name: CHỈ là tên của chức danh/vị trí (ví dụ: Chủ tịch, Phó Chủ tịch, Chủ nhiệm, Phó Chủ nhiệm, Vụ trưởng, Phó Vụ trưởng, Cục trưởng, Viện trưởng, Giám đốc, Phó Giám đốc, Trưởng phòng, Phó Trưởng phòng, Chuyên viên, Thư ký, Kế toán, Tổng Tham mưu trưởng, Thứ trưởng, Bộ trưởng, Thống đốc, Bí thư, Phó Bí thư, Trưởng Đoàn đại biểu Quốc hội, Phó Trưởng Đoàn đại biểu Quốc hội, Phó Chánh Văn phòng, Chánh Văn phòng, Tư lệnh, Phó Tư lệnh...). TUYỆT ĐỐI KHÔNG ghép tên cơ quan vào position_name, KHÔNG chứa dấu phẩy nối nhiều chức vụ.
   - work_organization_name: Tên cơ quan, đơn vị công tác đi liền phía sau chức danh đó (ví dụ: "Quốc hội", "Hội đồng nhân dân thành phố Hà Nội", "Ngân hàng Nhà nước Việt Nam", "Ủy ban Văn hóa, Giáo dục", "Văn phòng Quốc hội", "Bộ Tư lệnh Quân khu 7", "Bộ Quốc phòng"...). Nếu chức vụ đứng riêng không kèm tên cơ quan ngay sau (ví dụ: "Vụ trưởng"), lấy tên cơ quan công tác tương ứng được nêu trong văn bản (hoặc null nếu văn bản không nhắc đến).

Ví dụ minh họa:
- "(1) Văn phòng Quốc hội." -> is_collective: true, full_name: "Văn phòng Quốc hội", position_name: null, work_organization_name: "Văn phòng Quốc hội"
- "(2) Viện Nghiên cứu lập pháp." -> is_collective: true, full_name: "Viện Nghiên cứu lập pháp", position_name: null, work_organization_name: "Viện Nghiên cứu lập pháp"
- "(1) Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội" -> is_collective: false, full_name: "Trần Thanh Mẫn", position_name: "Chủ tịch", work_organization_name: "Quốc hội" (bỏ chức danh Đảng "Ủy viên Bộ Chính trị").
- "(3) Ông Nguyễn Đức Hải, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội." -> is_collective: false, full_name: "Nguyễn Đức Hải", position_name: "Phó Chủ tịch", work_organization_name: "Quốc hội" (bỏ chức danh Đảng "Ủy viên Ban Chấp hành Trung ương Đảng").
- "(1) Bà Nguyễn Thị Hồng, Ủy viên Trung ương Đảng, Thống đốc Ngân hàng Nhà nước Việt Nam;" -> is_collective: false, full_name: "Nguyễn Thị Hồng", position_name: "Thống đốc", work_organization_name: "Ngân hàng Nhà nước Việt Nam" (bỏ chức danh Đảng "Ủy viên Trung ương Đảng").
- "(2) Ông Nguyễn Ngọc Tuần, Phó Bí thư Thành ủy, Chủ tịch Hội đồng nhân dân thành phố Hà Nội, Phó Trưởng Đoàn đại biểu Quốc hội thành phố Hà Nội;" -> is_collective: false, full_name: "Nguyễn Ngọc Tuần", position_name: "Chủ tịch", work_organization_name: "Hội đồng nhân dân thành phố Hà Nội" (lấy chức vụ chính quyền cao nhất, bỏ chức vụ kiêm nhiệm).
- "Chủ tịch Hội đồng nhân dân thành phố Hà Nội, Phó Trưởng Đoàn đại biểu Quốc hội thành phố Hà Nội" -> is_collective: false, position_name: "Chủ tịch", work_organization_name: "Hội đồng nhân dân thành phố Hà Nội" (bỏ chức vụ kiêm nhiệm thứ hai).
- "Phó Chủ nhiệm Ủy ban Văn hóa, Giáo dục" -> is_collective: false, position_name: "Phó Chủ nhiệm", work_organization_name: "Ủy ban Văn hóa, Giáo dục".
- "Vụ trưởng, Thư ký Chủ tịch Quốc hội" -> is_collective: false, position_name: "Vụ trưởng", work_organization_name: null hoặc cơ quan nếu văn bản có nêu (bỏ chức vụ kiêm nhiệm "Thư ký Chủ tịch Quốc hội").
- "Phó Tư lệnh Bộ Tư lệnh Quân khu 7, đại biểu Quốc hội khóa XV" -> is_collective: false, position_name: "Phó Tư lệnh", work_organization_name: "Bộ Tư lệnh Quân khu 7" (bỏ chức vụ kiêm nhiệm thứ hai).

Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng mảng:
[
  {
    "stt": 1,
    "group_index": 1,
    "code": "1",
    "is_collective": false,
    "full_name": "...",
    "position_name": "...",
    "work_organization_name": "...",
    "award_type": "TANG",
    "raw_text": "..."
  }
]"""

# ---------------------------------------------------------------------------
# Prompt cho luồng mới (từng list_item trong OCR hoặc markdown text)
# ---------------------------------------------------------------------------

PERSON_ITEM_PROMPT = """Bạn là chuyên gia trích xuất văn bản hành chính Việt Nam.
Nhiệm vụ: Từ một dòng văn bản mô tả một đối tượng (cá nhân hoặc tập thể) được khen thưởng trong văn bản Khen thưởng (KHEN_THUONG), trích xuất thông tin và trả về JSON.

QUY TẮC BÓC TÁCH (BẮT BUỘC TUÂN THỦ):

1. Phân loại đối tượng (is_collective):
   - is_collective = true nếu đối tượng được khen thưởng là TẬP THỂ: bao gồm các cơ quan, tổ chức, đơn vị, ban, bộ, ngành, viện, vụ, cục, ủy ban, hội đồng, đoàn, trung tâm, phòng, báo, đài, tạp chí, doanh nghiệp, tổ chức xã hội, tập thể cán bộ/công chức... (ví dụ: "Văn phòng Quốc hội", "Viện Nghiên cứu lập pháp", "Ban Công tác đại biểu", "Ban Dân nguyện", "Báo Đại biểu Nhân dân", "Truyền hình Quốc hội Việt Nam", "Đoàn đại biểu Quốc hội tỉnh Nghệ An", "Tập thể cán bộ, công chức Vụ Pháp luật"...).
   - is_collective = false nếu đối tượng được khen thưởng là CÁ NHÂN (người cụ thể, thường có danh xưng Ông, Bà, Đồng chí hoặc cấp bậc quân hàm/công an hoặc họ tên cá nhân).

2. Nếu là TẬP THỂ (is_collective = true):
   - full_name: Tên của tập thể (ví dụ: "Văn phòng Quốc hội", "Viện Nghiên cứu lập pháp", "Ban Dân nguyện"...).
   - position_name: null (tập thể TUYỆT ĐỐI không có chức vụ).
   - work_organization_name: Tên của chính tập thể đó (trùng với full_name, ví dụ: "Văn phòng Quốc hội", "Viện Nghiên cứu lập pháp").
   - award_type: "TANG" hoặc "TRUY_TANG" (chỉ dùng "TRUY_TANG" nếu dòng văn bản có từ "Truy tặng", thông thường là "TANG").
   - raw_text: Nguyên văn dòng đầu vào, không chỉnh sửa.

3. Nếu là CÁ NHÂN (is_collective = false):
   - full_name: Họ và tên cá nhân. BẮT BUỘC loại bỏ hoàn toàn danh xưng (Ông, Bà, Đồng chí) và cấp bậc quân hàm/công an (Đại tướng, Thượng tướng, Trung tướng, Thiếu tướng, Đại tá, Thượng tá...).
   - position_name: Chức vụ của cá nhân.
   - work_organization_name: Tên cơ quan, đơn vị công tác của cá nhân.
   - award_type: "TANG" hoặc "TRUY_TANG" (chỉ dùng "TRUY_TANG" nếu dòng văn bản có từ "Truy tặng", thông thường là "TANG").
   - raw_text: Nguyên văn dòng đầu vào, không chỉnh sửa.

QUY TẮC BÓC TÁCH position_name VÀ work_organization_name CHO CÁ NHÂN:
1. Lựa chọn chức vụ chính:
   - TUYỆT ĐỐI KHÔNG đưa các chức danh Đảng vào position_name hoặc work_organization_name khi cá nhân có chức vụ chính quyền/Quốc hội/chuyên môn.
     * Dấu hiệu nhận biết các chức vụ Đảng là có từ khóa "đảng" ở trong tên chức vụ (hoặc "Bộ Chính trị", "Ban Bí thư", "Trung ương Đảng", "BCH Trung ương Đảng", "Cấp ủy", "Đảng ủy", "Đảng viên"...).
     * Ví dụ: "Ủy viên Ban Chấp hành Trung ương Đảng", "Ủy viên Trung ương Đảng", "Ủy viên Bộ Chính trị", "Ủy viên Ban Bí thư"... là các chức danh Đảng và BẮT BUỘC PHẢI BỎ QUA.
   - BỎ QUA các chức vụ kiêm nhiệm như "Ủy viên Ủy ban Thường vụ Quốc hội", "Ủy viên Hội đồng...", "Ủy viên Ủy ban... của Quốc hội", "đại biểu Quốc hội khóa...".
   - LỰA CHỌN chức vụ chính quyền / Quốc hội / chuyên môn cao nhất tại thời điểm ban hành.
   - Trường hợp cá nhân chỉ có duy nhất chức vụ thuộc tổ chức Đảng (ví dụ: Bí thư Thành ủy, Phó Bí thư Tỉnh ủy...) mà không có chức vụ chính quyền nào khác thì lấy chức vụ Đảng đó.
2. Phân tách position_name và work_organization_name từ chức vụ được chọn:
   - position_name: CHỈ là tên của chức danh/vị trí (ví dụ: Chủ tịch, Phó Chủ tịch, Chủ nhiệm, Phó Chủ nhiệm, Vụ trưởng, Phó Vụ trưởng, Cục trưởng, Viện trưởng, Giám đốc, Phó Giám đốc, Trưởng phòng, Phó Trưởng phòng, Chuyên viên, Thư ký, Kế toán, Tổng Tham mưu trưởng, Thứ trưởng, Bộ trưởng, Thống đốc, Bí thư, Phó Bí thư, Trưởng Đoàn đại biểu Quốc hội, Phó Trưởng Đoàn đại biểu Quốc hội, Phó Chánh Văn phòng, Chánh Văn phòng, Tư lệnh, Phó Tư lệnh...). TUYỆT ĐỐI KHÔNG ghép tên cơ quan vào position_name, KHÔNG chứa dấu phẩy nối nhiều chức vụ.
   - work_organization_name: Tên cơ quan, đơn vị công tác đi liền phía sau chức danh đó (ví dụ: "Quốc hội", "Hội đồng nhân dân thành phố Hà Nội", "Ngân hàng Nhà nước Việt Nam", "Ủy ban Văn hóa, Giáo dục", "Văn phòng Quốc hội", "Bộ Tư lệnh Quân khu 7", "Bộ Quốc phòng"...). Nếu chức vụ đứng riêng không kèm tên cơ quan ngay sau (ví dụ: "Vụ trưởng"), lấy tên cơ quan công tác tương ứng được nêu trong dòng văn bản (hoặc null nếu không có).

Ví dụ minh họa:
- "(1) Văn phòng Quốc hội." -> is_collective: true, full_name: "Văn phòng Quốc hội", position_name: null, work_organization_name: "Văn phòng Quốc hội"
- "(2) Viện Nghiên cứu lập pháp." -> is_collective: true, full_name: "Viện Nghiên cứu lập pháp", position_name: null, work_organization_name: "Viện Nghiên cứu lập pháp"
- "(1) Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội" -> is_collective: false, full_name: "Trần Thanh Mẫn", position_name: "Chủ tịch", work_organization_name: "Quốc hội" (bỏ chức danh Đảng "Ủy viên Bộ Chính trị").
- "(3) Ông Nguyễn Đức Hải, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội." -> is_collective: false, full_name: "Nguyễn Đức Hải", position_name: "Phó Chủ tịch", work_organization_name: "Quốc hội" (bỏ chức danh Đảng "Ủy viên Ban Chấp hành Trung ương Đảng").
- "(1) Bà Nguyễn Thị Hồng, Ủy viên Trung ương Đảng, Thống đốc Ngân hàng Nhà nước Việt Nam;" -> is_collective: false, full_name: "Nguyễn Thị Hồng", position_name: "Thống đốc", work_organization_name: "Ngân hàng Nhà nước Việt Nam" (bỏ chức danh Đảng "Ủy viên Trung ương Đảng").
- "(2) Ông Nguyễn Ngọc Tuần, Phó Bí thư Thành ủy, Chủ tịch Hội đồng nhân dân thành phố Hà Nội, Phó Trưởng Đoàn đại biểu Quốc hội thành phố Hà Nội;" -> is_collective: false, full_name: "Nguyễn Ngọc Tuần", position_name: "Chủ tịch", work_organization_name: "Hội đồng nhân dân thành phố Hà Nội" (lấy chức vụ chính quyền cao nhất, bỏ chức vụ kiêm nhiệm).
- "(1) Đồng chí Đại tướng Nguyễn Tân Cương, Ủy viên Ban Chấp hành Trung ương Đảng, Ủy viên Thường vụ Quân ủy Trung ương, Tổng Tham mưu trưởng Quân đội nhân dân Việt Nam, Thứ trưởng Bộ Quốc phòng, đại biểu Quốc hội khóa XV." -> is_collective: false, full_name: "Nguyễn Tân Cương", position_name: "Tổng Tham mưu trưởng", work_organization_name: "Bộ Quốc phòng".
- "(11) Đồng chí Thiếu tướng Đặng Văn Lẫm, Phó Tư lệnh Bộ Tư lệnh Quân khu 7, đại biểu Quốc hội khóa XV, Đoàn đại biểu Quốc hội Thành phố Hồ Chí Minh, Ủy viên Ủy ban Quốc phòng, An ninh và Đối ngoại của Quốc hội." -> is_collective: false, full_name: "Đặng Văn Lẫm", position_name: "Phó Tư lệnh", work_organization_name: "Bộ Tư lệnh Quân khu 7".
- "(1) Đồng chí Nguyễn Văn Nên, Ủy viên Bộ Chính trị, Bí thư Thành ủy Thành phố." -> is_collective: false, full_name: "Nguyễn Văn Nên", position_name: "Bí thư Thành ủy", work_organization_name: "Thành ủy Thành phố" (chỉ có chức vụ Đảng địa phương thì lấy chức vụ đó).
- "Chủ tịch Hội đồng nhân dân thành phố Hà Nội, Phó Trưởng Đoàn đại biểu Quốc hội thành phố Hà Nội" -> is_collective: false, position_name: "Chủ tịch", work_organization_name: "Hội đồng nhân dân thành phố Hà Nội" (bỏ chức vụ kiêm nhiệm thứ hai).
- "Phó Chủ nhiệm Ủy ban Văn hóa, Giáo dục" -> is_collective: false, position_name: "Phó Chủ nhiệm", work_organization_name: "Ủy ban Văn hóa, Giáo dục".
- "Vụ trưởng, Thư ký Chủ tịch Quốc hội" -> is_collective: false, position_name: "Vụ trưởng", work_organization_name: null hoặc cơ quan nếu có (bỏ chức vụ kiêm nhiệm "Thư ký Chủ tịch Quốc hội").
- "Phó Tư lệnh Bộ Tư lệnh Quân khu 7, đại biểu Quốc hội khóa XV" -> is_collective: false, position_name: "Phó Tư lệnh", work_organization_name: "Bộ Tư lệnh Quân khu 7" (bỏ chức vụ kiêm nhiệm thứ hai).

Chỉ trả về duy nhất chuỗi JSON hợp lệ:
{
  "is_collective": false,
  "full_name": "...",
  "position_name": "...",
  "work_organization_name": "...",
  "award_type": "TANG",
  "raw_text": "..."
}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_paren_prefix(s: str) -> Optional[Tuple[str, str]]:
    if not s.startswith("("):
        return None
    closing = s.find(")")
    if closing <= 1:
        return None
    digits = s[1:closing].strip()
    if not digits.isdigit():
        return None
    rest = s[closing + 1 :].strip()
    if rest and rest[0] in ":.-/":
        rest = rest[1:].strip()
    return digits, rest


def _parse_digit_prefix(s: str) -> Optional[Tuple[str, str]]:
    idx = 0
    while idx < len(s) and s[idx].isdigit():
        idx += 1
    if 0 < idx < len(s) and s[idx] in ".:-/)":
        return s[:idx], s[idx + 1 :].strip()
    return None


def _match_item_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse item number and rest of line without regex.
    Matches lines starting with:
      - (1), (1):, (1)., (1)-, (1)/
      - 1., 1:, 1-, 1), 1/
    Returns (code_str, remaining_text) or None.
    """
    s = line.strip()
    if not s:
        return None
    return _parse_paren_prefix(s) or _parse_digit_prefix(s)


def _check_paren_marker(line: str, i: int, n: int) -> Tuple[Optional[str], int]:
    close = line.find(")", i + 1)
    if close != -1 and close > i + 1:
        digits = line[i + 1 : close].strip()
        if digits.isdigit():
            after = close + 1
            if after < n and line[after] in ":.-/":
                after += 1
            if after >= n or line[after].isspace():
                return digits, after
    return None, i + 1


def _check_digit_marker(line: str, i: int, n: int) -> Tuple[Optional[str], int]:
    j = i
    while j < n and line[j].isdigit():
        j += 1
    if j < n and line[j] in ".:-/)":
        after = j + 1
        if after >= n or line[after].isspace():
            return line[i:j], after
    return None, i + 1


def _match_marker_at_pos(line: str, i: int, n: int) -> Tuple[Optional[str], int]:
    if line[i] == "(":
        digits, next_i = _check_paren_marker(line, i, n)
        if digits is not None:
            return digits, next_i
    elif line[i].isdigit():
        digits, next_i = _check_digit_marker(line, i, n)
        if digits is not None:
            return digits, next_i
    return None, i + 1


def _find_item_markers(line: str) -> List[Tuple[int, str]]:
    """Finds starting indices and codes of item markers in a line.
    Matches markers at start of string or preceded by whitespace:
      - (1) or (1): or (1). or (1)- or (1)/
      - 1. or 1: or 1- or 1) or 1/
    Returns list of (start_index, code_str).
    """
    markers = []
    n = len(line)
    i = 0
    while i < n:
        if i == 0 or line[i - 1].isspace():
            digits, next_i = _match_marker_at_pos(line, i, n)
            if digits is not None:
                markers.append((i, digits))
                i = next_i
                continue
        i += 1
    return markers


def _split_multi_items(line: str) -> List[Tuple[str, Optional[str]]]:
    markers = _find_item_markers(line)
    if len(markers) <= 1:
        m = _match_item_line(line)
        if m:
            return [(line.strip(), m[0])]
        return [(line.strip(), None)]
    parts = []
    for k in range(len(markers)):
        start_idx, code = markers[k]
        end_idx = markers[k + 1][0] if k + 1 < len(markers) else len(line)
        sub = line[start_idx:end_idx].strip()
        if sub:
            parts.append((sub, code))
    return parts


def _has_tap_the(text: str) -> bool:
    tokens = text.lower().replace(":", " ").replace(".", " ").replace(",", " ").replace(";", " ").split()
    for i in range(len(tokens) - 1):
        if tokens[i] == "tập" and tokens[i + 1] == "thể":
            return True
    return False


def _has_ca_nhan(text: str) -> bool:
    tokens = text.lower().replace(":", " ").replace(".", " ").replace(",", " ").replace(";", " ").split()
    for i in range(len(tokens) - 1):
        if tokens[i] == "cá" and tokens[i + 1] == "nhân":
            return True
    return False


def _is_section_collective(s: str) -> bool:
    tokens = s.replace(":", " ").replace(".", " ").replace("-", " ").split()
    if len(tokens) >= 3:
        prefix = tokens[0].strip("().:-[]")
        if prefix.isdigit() or prefix.upper() in ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"):
            return tokens[1].lower() == "tập" and tokens[2].lower() == "thể"
    return False


def _is_section_individual(s: str) -> bool:
    tokens = s.replace(":", " ").replace(".", " ").replace("-", " ").split()
    if len(tokens) >= 3:
        prefix = tokens[0].strip("().:-[]")
        if prefix.isdigit() or prefix.upper() in ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"):
            return tokens[1].lower() == "cá" and tokens[2].lower() == "nhân"
    return False


def _is_group_title_line(s: str) -> bool:
    if not s:
        return False
    line = s.strip()
    parts = line.split(maxsplit=2)
    if not parts:
        return False
    first = parts[0].strip("():.-[]")
    if first.isdigit() or first.upper() in ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"):
        rem = line[len(parts[0]):].strip()
    else:
        rem = line
    rem_lower = rem.lower()
    if rem_lower.startswith(("tặng", "truy tặng")):
        if rem_lower.startswith("tặng"):
            after = rem_lower[4:]
        else:
            after = rem_lower[9:]
        if not after or after[0] in ' \t\n:;.,-"“':
            return True
    return False


def _has_title_salutation(text: str) -> bool:
    tokens = text.lower().replace(",", " ").replace(".", " ").split()
    for i, tok in enumerate(tokens):
        if tok in ("ông", "bà"):
            return True
        if tok == "đồng" and i + 1 < len(tokens) and tokens[i + 1] == "chí":
            return True
    return False


def _parse_parens_digits(s: str) -> Optional[str]:
    t = s.strip()
    if t.startswith("("):
        close = t.find(")")
        if close > 1:
            digits = t[1:close].strip()
            if digits.isdigit():
                return digits
    return None


def _parse_code_from_text(text: str) -> Optional[str]:
    """Trích xuất số thứ tự gốc từ đầu dòng: '(14)' hoặc '(14):' hoặc '14.' hoặc '14/' -> '14'."""
    res = _match_item_line(text)
    return res[0] if res else None


def _parse_award_type(raw_val: Any) -> str:
    cleaned = clean_text(raw_val) or "TANG"
    return "TRUY_TANG" if "truy" in cleaned.lower() else "TANG"


def _resolve_code_str(item: dict, stt: int, code: Optional[str]) -> str:
    if code:
        return code
    code_val = item.get("code")
    return str(code_val).strip() if code_val is not None else str(stt)


def _build_person(
    item: Any,
    stt: int,
    group_index: int,
    code: Optional[str] = None,
    llm_service: Optional[LLMService] = None,
    raw_text_fallback: str = "",
) -> Optional[KhenThuongPerson]:
    """Xây dựng KhenThuongPerson từ dict LLM trả về."""
    if not isinstance(item, dict):
        return None

    full_name = clean_text(item.get("full_name")) or ""
    if not full_name:
        return None

    award_type = _parse_award_type(item.get("award_type"))
    code_str = _resolve_code_str(item, stt, code)
    raw_val = clean_text(item.get("raw_text")) or raw_text_fallback or ""
    is_collective = (
        bool(item.get("is_collective", False))
        or str(item.get("is_collective", "")).lower() == "true"
    )

    if is_collective:
        pos_name = None
        work_org = clean_text(item.get("work_organization_name")) or full_name
        full_name = full_name or work_org
    else:
        pos_name, work_org = refine_position_and_organization(
            clean_text(item.get("position_name")),
            clean_text(item.get("work_organization_name")),
            raw_text=raw_val,
            llm_service=llm_service,
        )

    return KhenThuongPerson(
        stt=stt,
        group_index=group_index,
        code=code_str,
        is_collective=is_collective,
        full_name=full_name,
        position_name=pos_name,
        work_organization_name=work_org,
        award_type=award_type,
        raw_text=raw_val,
    )


GROUP_HEADER_KEYWORDS = (
    "cá nhân",
    "tập thể",
    "bằng khen",
    "kỷ niệm",
    "huân chương",
    "huy chương",
    "danh hiệu",
)
IGNORE_TEXT_KEYWORDS = (
    "nơi nhận",
    "tm.",
    "tổng thư ký",
    "quyết nghị:",
    "điều 2.",
    "điều 3.",
    "danh sách",
)


def _find_danh_sach_start_line(lines_all: List[str]) -> int:
    for i, l in enumerate(lines_all):
        clean_l = l.strip().lstrip("#").strip().upper()
        if clean_l.startswith(("DANH SÁCH", "DANH SACH")):
            rem = clean_l[9:]
            if not rem or rem[0] in " \t:.-/":
                return i
    return -1


def _is_group_header_line(line_str: str) -> bool:
    if not (_is_group_title(line_str) or _is_group_title_line(line_str)):
        return False
    low = line_str.lower()
    return any(w in low for w in GROUP_HEADER_KEYWORDS)


def _is_valid_item_text(text: str) -> bool:
    if not text or _is_group_title(text) or _is_group_title_line(text):
        return False
    low = text.lower()
    return not any(k in low for k in IGNORE_TEXT_KEYWORDS)


def _is_table_skip_row(line_str: str, cols: List[str]) -> bool:
    if "---" in line_str or not cols:
        return True
    c0 = cols[0].upper()
    if any(h in c0 for h in ["STT", "HỌ VÀ TÊN"]):
        return True
    return len(cols) > 1 and "HỌ VÀ TÊN" in cols[1].upper()


def _check_table_unit(
    cols: List[str], tbl_digits: Optional[str], current_unit: str
) -> Tuple[bool, str]:
    combined = " ".join(cols).lower()
    if any(k in combined for k in UNIT_KEYWORDS) and not tbl_digits:
        for c in cols:
            if any(k in c.lower() for k in UNIT_KEYWORDS):
                return True, _clean_unit(c)
        return True, current_unit
    return False, current_unit


def _build_table_person_text(cols: List[str], code_val: str, current_unit: str) -> str:
    name = cols[1] if len(cols) > 1 else ""
    pos = cols[2] if len(cols) > 2 else ""
    text_line = f"({code_val}) {name}"
    if pos:
        text_line += f", {pos}"
    clean_u = _strip_dbqh_prefix(current_unit)
    if (
        current_unit
        and current_unit.lower() not in pos.lower()
        and (not clean_u or clean_u.lower() not in pos.lower())
    ):
        text_line += f", {current_unit}"
    return text_line


def _parse_table_person_line(
    line_str: str, current_unit: str
) -> Tuple[Optional[str], Optional[str], str]:
    """Parse một dòng markdown table. Trả về (line_text, code_val, new_current_unit)."""
    cols = [c.strip() for c in line_str.split("|")[1:-1]]
    if _is_table_skip_row(line_str, cols):
        return None, None, current_unit

    tbl_digits = _parse_parens_digits(cols[0])
    is_unit, new_unit = _check_table_unit(cols, tbl_digits, current_unit)
    if is_unit:
        return None, None, new_unit

    is_person = bool(
        tbl_digits
        or (
            len(cols) >= 2
            and cols[0].strip().isdigit()
            and _has_title_salutation(cols[1])
        )
    )
    if is_person:
        code_val = tbl_digits if tbl_digits else cols[0].strip()
        text_line = _build_table_person_text(cols, code_val, current_unit)
        return text_line, code_val, current_unit

    return None, None, current_unit


def _is_dieu1_start(line_low: str) -> bool:
    return line_low.startswith("điều 1") and (
        len(line_low) == 6 or line_low[6] in ".: \t-"
    )


def _collect_dieu1_lines(lines_cnt: List[str]) -> List[str]:
    dieu1_lines = []
    found = False
    for line in lines_cnt:
        stripped = line.strip()
        low = stripped.lower()
        if not found:
            if _is_dieu1_start(low):
                found = True
                dieu1_lines.append(stripped)
            continue
        if low.startswith("điều 2") or len(dieu1_lines) >= 6:
            break
        dieu1_lines.append(stripped)
    return dieu1_lines


def _extract_single_person_from_dieu1(content: str) -> List[Tuple[str, int, int, str]]:
    dieu1_lines = _collect_dieu1_lines(content.split("\n"))
    single_text = "\n".join(dieu1_lines).strip() if dieu1_lines else content.strip()
    return [(single_text, 1, 1, "1")]


def _check_group_transition(line_str: str) -> Tuple[bool, Optional[bool], bool]:
    if _is_section_collective(line_str):
        return True, True, False
    if _is_section_individual(line_str):
        return True, False, False
    if _is_appendix_header(line_str):
        return True, None, False
    if _is_group_header_line(line_str):
        return True, _has_tap_the(line_str), True
    return False, None, False


def _append_unmatched_line(
    line_str: str, current_lines: List[str], is_current_group_coll: bool, stt_counter: int
) -> Optional[str]:
    if current_lines:
        current_lines.append(line_str)
        return None
    if (
        is_current_group_coll
        and not line_str.startswith("#")
        and "danh sách" not in line_str.lower()
        and line_str.lower() not in ["gồm:", "gồm", "danh sách:", "danh sách gồm:"]
    ):
        current_lines.append(line_str)
        return str(stt_counter + 1)
    return None


class _PersonItemCollector:
    def __init__(self):
        self.extracted: List[Tuple[str, int, int, str]] = []
        self.current_group = 1
        self.current_code: Optional[str] = None
        self.current_lines: List[str] = []
        self.stt_counter = 0
        self.current_unit = ""
        self.is_current_group_coll = False

    def flush(self):
        if self.current_lines:
            text = " ".join(self.current_lines).strip()
            if _is_valid_item_text(text):
                self.stt_counter += 1
                code_str = self.current_code or str(self.stt_counter)
                self.extracted.append((text, self.stt_counter, self.current_group, code_str))
            self.current_lines = []
            self.current_code = None

    def add_item(self, text: str, code: Optional[str]):
        self.flush()
        self.stt_counter += 1
        self.extracted.append((text, self.stt_counter, self.current_group, code or str(self.stt_counter)))

    def handle_table(self, line_str: str) -> bool:
        if not line_str.startswith("|"):
            return False
        t_text, t_code, self.current_unit = _parse_table_person_line(line_str, self.current_unit)
        if t_text:
            self.add_item(t_text, t_code)
        return True

    def handle_transition(self, line_str: str) -> bool:
        is_hdr, is_coll, is_new_grp = _check_group_transition(line_str)
        if not is_hdr:
            return False
        self.flush()
        if is_coll is not None:
            self.is_current_group_coll = is_coll
        if is_new_grp and self.extracted:
            self.current_group += 1
        return True

    def handle_split_or_item(self, line_str: str):
        splits = _split_multi_items(line_str)
        if len(splits) > 1:
            self.flush()
            for sub_text, sub_code in splits:
                self.stt_counter += 1
                self.extracted.append((sub_text, self.stt_counter, self.current_group, sub_code or str(self.stt_counter)))
            return

        matched = _match_item_line(line_str)
        if matched:
            self.flush()
            self.current_code = matched[0]
            self.current_lines.append(line_str)
        else:
            new_code = _append_unmatched_line(
                line_str, self.current_lines, self.is_current_group_coll, self.stt_counter
            )
            if new_code:
                self.current_code = new_code


def extract_person_items_from_text(content: str) -> List[Tuple[str, int, int, str]]:
    """
    Tách nội dung markdown/text thành danh sách các cá nhân độc lập.
    Trả về danh sách tuple: (item_text, stt, group_index, code)

    Đảm bảo mọi cá nhân được phân chia rõ ràng để gửi 1 request LLM cho mỗi cá nhân.
    """
    if not content or not content.strip():
        return []

    lines_all = content.split("\n")
    ds_idx = _find_danh_sach_start_line(lines_all)
    lines = lines_all[ds_idx:] if ds_idx != -1 else lines_all

    collector = _PersonItemCollector()
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        if collector.handle_table(line_str) or collector.handle_transition(line_str):
            continue
        low = line_str.lower()
        if any(low.startswith(stop) for stop in ["ghi chú:", "lưu ý:"]):
            collector.flush()
            break
        collector.handle_split_or_item(line_str)

    collector.flush()
    if not collector.extracted:
        return _extract_single_person_from_dieu1(content)
    return collector.extracted


# ---------------------------------------------------------------------------
# Extractor class
# ---------------------------------------------------------------------------


class KhenThuongPersonsExtractor:
    """
    Trích xuất danh sách nhân sự (persons) cho văn bản Khen thưởng (KHEN_THUONG).

    NGUYÊN TẮC THIẾT KẾ BẮT BUỘC:
    Mỗi request gửi tới LLM chỉ trích xuất thông tin cho DUY NHẤT 1 CÁ NHÂN.
    Tuyệt đối không gửi batch nhiều người trong 1 request để tránh tràn max-tokens
    và triệt tiêu hoàn toàn lỗi LLM Parse Error.

    Hỗ trợ hai phương thức đầu vào:
    1. aextract_from_group_chunks: Nhận danh sách GroupChunk từ cây OCR,
       gửi async LLM requests song song cho từng item cá nhân (1 cá nhân / 1 request).
    2. aextract: Nhận raw markdown/text (fallback hoặc văn bản scan không có OCR tree),
       tự động phân tách từng cá nhân bằng extract_person_items_from_text và
       gửi async LLM requests song song (1 cá nhân / 1 request).
    """

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        max_concurrency: int = 20,
    ):
        self.llm_service = llm_service or LLMService()
        self.max_concurrency = max_concurrency

    # ------------------------------------------------------------------
    # Hàm trích xuất thông tin cho 1 cá nhân (1 LLM request)
    # ------------------------------------------------------------------

    async def _extract_one_item(
        self,
        item_text: str,
        stt: int,
        group_index: int,
        client: Optional[Any] = None,
        semaphore: Optional[asyncio.Semaphore] = None,
        code: Optional[str] = None,
    ) -> Optional[KhenThuongPerson]:
        """
        Gửi 1 request LLM để trích xuất thông tin của DUY NHẤT 1 đối tượng (cá nhân hoặc tập thể) từ 1 dòng text.
        """
        async def _call():
            data = await self.llm_service.ask_json_async(
                PERSON_ITEM_PROMPT,
                item_text,
                client=client,
            )
            item_code = code or _parse_code_from_text(item_text)
            if isinstance(data, dict):
                is_coll = (
                    bool(data.get("is_collective", False))
                    or str(data.get("is_collective", "")).lower() == "true"
                )
                if is_coll:
                    collective_name = (
                        clean_text(data.get("full_name"))
                        or clean_text(data.get("work_organization_name"))
                        or clean_text(item_text)
                    )
                    data["is_collective"] = True
                    data["full_name"] = collective_name
                    data["position_name"] = None
                    data["work_organization_name"] = collective_name
                else:
                    pos_name, work_org = await arefine_position_and_organization(
                        clean_text(data.get("position_name")),
                        clean_text(data.get("work_organization_name")),
                        raw_text=item_text,
                        llm_service=self.llm_service,
                        client=client,
                    )
                    data["is_collective"] = False
                    data["position_name"] = pos_name
                    data["work_organization_name"] = work_org
            return _build_person(
                data,
                stt=stt,
                group_index=group_index,
                code=item_code,
                llm_service=self.llm_service,
                raw_text_fallback=item_text,
            )

        try:
            if semaphore is not None:
                async with semaphore:
                    return await _call()
            return await _call()
        except Exception as exc:
            logger.warning(
                f"[PERSONS] Lỗi khi trích xuất person stt={stt} group={group_index}: {exc}. "
                f"item_text={item_text[:80]!r}"
            )
            return None

    # ------------------------------------------------------------------
    # Luồng OCR GroupChunks: xử lý song song từng list_item
    # ------------------------------------------------------------------

    async def aextract_from_group_chunks(
        self, group_chunks: List[GroupChunk]
    ) -> List[KhenThuongPerson]:
        """
        Nhận GroupChunk từ OCR parser, xử lý song song từng list_item.
        Mỗi cá nhân = 1 LLM request riêng biệt.
        """
        import httpx

        tasks = []
        stt_counter = 0

        for chunk in group_chunks:
            for item_text in chunk.item_texts:
                stt_counter += 1
                tasks.append((item_text, stt_counter, chunk.group_index))

        if not tasks:
            return []

        semaphore = asyncio.Semaphore(self.max_concurrency)
        limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
        async with httpx.AsyncClient(
            timeout=float(self.llm_service.timeout),
            limits=limits,
        ) as client:
            coroutines = [
                self._extract_one_item(
                    item_text=item_text,
                    stt=stt,
                    group_index=group_idx,
                    client=client,
                    semaphore=semaphore,
                )
                for item_text, stt, group_idx in tasks
            ]
            results = await asyncio.gather(*coroutines, return_exceptions=True)

        persons: List[KhenThuongPerson] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[PERSONS] Lỗi không mong đợi khi gather: {result}")
                continue
            if result is not None:
                persons.append(result)

        persons.sort(key=lambda p: p.stt)
        return persons

    # ------------------------------------------------------------------
    # Luồng Text/Markdown: phân tách từng dòng và gọi 1 request / người
    # ------------------------------------------------------------------

    async def aextract(self, content: str) -> List[KhenThuongPerson]:
        """
        Trích xuất danh sách nhân sự từ nội dung markdown text.
        TUÂN THỦ NGUYÊN TẮC: Phân tách văn bản thành từng cá nhân riêng biệt,
        mỗi cá nhân được gửi trong 1 request LLM độc lập (không gửi batch).
        """
        import httpx

        items = extract_person_items_from_text(content)
        if not items:
            return []

        logger.info(
            f"[PERSONS] Bắt đầu trích xuất {len(items)} cá nhân từ markdown text "
            f"(1 request / 1 cá nhân, max_concurrency={self.max_concurrency})..."
        )

        semaphore = asyncio.Semaphore(self.max_concurrency)
        limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
        async with httpx.AsyncClient(
            timeout=float(self.llm_service.timeout),
            limits=limits,
        ) as client:
            coroutines = [
                self._extract_one_item(
                    item_text=item_text,
                    stt=stt,
                    group_index=group_idx,
                    client=client,
                    semaphore=semaphore,
                    code=code,
                )
                for item_text, stt, group_idx, code in items
            ]
            results = await asyncio.gather(*coroutines, return_exceptions=True)

        persons: List[KhenThuongPerson] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[PERSONS] Lỗi không mong đợi khi gather: {result}")
                continue
            if result is not None:
                persons.append(result)

        persons.sort(key=lambda p: p.stt)
        return persons

    def extract(self, content: str) -> List[KhenThuongPerson]:
        """Sync wrapper cho aextract."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(self.aextract(content))
            return loop.run_until_complete(self.aextract(content))
        except RuntimeError:
            return asyncio.run(self.aextract(content))
