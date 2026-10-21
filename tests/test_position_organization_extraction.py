import pytest
from unittest.mock import AsyncMock, MagicMock

from services.llm_service import LLMService, refine_position_and_organization
from extractors.luong.persons import LuongPersonsExtractor
from extractors.qtct.persons import QTCTPersonsExtractor
from extractors.khen_thuong.persons import KhenThuongPersonsExtractor, _build_person
from tests.assertions import check


class TestRefinePositionAndOrganization:
    """Kiểm tra hàm chuẩn hóa chức vụ và cơ quan công tác refine_position_and_organization."""

    def test_two_positions_first_retained_org_extracted(self):
        # Ví dụ 1 từ yêu cầu: Có 2 chức vụ -> lấy chức vụ đầu, tách position và org, bỏ chức vụ kiêm nhiệm/Đảng thứ hai
        pos_raw = "Chủ tịch Hội đồng nhân dân thành phố Hà Nội, Phó Trưởng Đoàn đại biểu Quốc hội thành phố Hà Nội"
        pos, org = refine_position_and_organization(pos_raw, None)
        check(pos == "Chủ tịch")
        check(org == "Hội đồng nhân dân thành phố Hà Nội")

    def test_single_position_extracted(self):
        # Ví dụ 2 từ yêu cầu: Chỉ có 1 chức vụ -> mặc định lấy luôn chức vụ đó, tách position và org
        pos_raw = "Phó Chủ nhiệm Ủy ban Văn hóa, Giáo dục"
        pos, org = refine_position_and_organization(pos_raw, None)
        check(pos == "Phó Chủ nhiệm")
        check(org == "Ủy ban Văn hóa, Giáo dục")

    def test_position_with_concurrent_position_vu_truong(self):
        # Ví dụ mô tả từ yêu cầu: Vụ trưởng, Thư ký Chủ tịch Quốc hội
        pos_raw = "Vụ trưởng, Thư ký Chủ tịch Quốc hội"
        pos, org = refine_position_and_organization(pos_raw, None)
        check(pos == "Vụ trưởng")
        check(org is None)

    def test_position_with_existing_org(self):
        # Đã có work_organization_name sẵn
        pos_raw = "Vụ trưởng, Thư ký Chủ tịch Quốc hội"
        pos, org = refine_position_and_organization(pos_raw, "Văn phòng Quốc hội")
        check(pos == "Vụ trưởng")
        check(org == "Văn phòng Quốc hội")

    def test_military_position_two_titles(self):
        # Tổng Tham mưu trưởng Quân đội nhân dân Việt Nam, Thứ trưởng
        pos_raw = "Tổng Tham mưu trưởng Quân đội nhân dân Việt Nam, Thứ trưởng"
        pos, org = refine_position_and_organization(pos_raw, "Bộ Quốc phòng")
        check(pos == "Tổng Tham mưu trưởng")
        check(org == "Bộ Quốc phòng")

    def test_deputy_commander_position(self):
        # Phó Tư lệnh Bộ Tư lệnh Quân khu 7, đại biểu Quốc hội khóa XV
        pos_raw = "Phó Tư lệnh Bộ Tư lệnh Quân khu 7, đại biểu Quốc hội khóa XV"
        pos, org = refine_position_and_organization(pos_raw, None)
        check(pos == "Phó Tư lệnh")
        check(org == "Bộ Tư lệnh Quân khu 7")

    def test_party_position_single(self):
        # 1 chức vụ duy nhất là chức vụ Đảng -> mặc định lấy luôn
        pos_raw = "Bí thư Thành ủy Thành phố Hồ Chí Minh"
        pos, org = refine_position_and_organization(pos_raw, None)
        check(pos == "Bí thư")
        check(org == "Thành ủy Thành phố Hồ Chí Minh")

    def test_with_subordinate_conjunction_thuoc(self):
        # Có từ 'thuộc'
        pos_raw = "Phó Trưởng phòng thuộc Vụ Hợp tác quốc tế"
        pos, org = refine_position_and_organization(pos_raw, None)
        check(pos == "Phó Trưởng phòng")
        check(org == "Vụ Hợp tác quốc tế")

    def test_with_conjunction_kiem(self):
        # Dùng từ 'kiêm'
        pos_raw = "Vụ trưởng kiêm Thư ký Phó Chủ tịch Quốc hội"
        pos, org = refine_position_and_organization(pos_raw, None)
        check(pos == "Vụ trưởng")

    def test_clean_input_preserved(self):
        # Đã chuẩn sẵn từ LLM
        pos, org = refine_position_and_organization("Phó Chủ nhiệm", "Ủy ban Văn hóa, Giáo dục")
        check(pos == "Phó Chủ nhiệm")
        check(org == "Ủy ban Văn hóa, Giáo dục")

    def test_none_or_empty(self):
        pos, org = refine_position_and_organization(None, "Văn phòng Quốc hội")
        check(pos is None)
        check(org == "Văn phòng Quốc hội")

    def test_party_title_discarded_state_title_retained_nguyen_duc_hai(self):
        # Trường hợp Nguyễn Đức Hải: Có chức danh Đảng và chức vụ Quốc hội -> Bỏ chức danh Đảng, lấy chức vụ Quốc hội
        pos_raw = "Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội"
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json.return_value = {
            "position_name": "Phó Chủ tịch",
            "work_organization_name": "Quốc hội",
        }
        pos, org = refine_position_and_organization(pos_raw, None, llm_service=mock_llm)
        check(pos == "Phó Chủ tịch")
        check(org == "Quốc hội")

    def test_party_title_discarded_with_raw_text(self):
        # Nhận nhầm Ủy viên và Ban Chấp hành Trung ương Đảng nhưng raw_text có chức vụ Quốc hội
        raw_text = "(3) Ông Nguyễn Đức Hải, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội."
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json.return_value = {
            "position_name": "Phó Chủ tịch",
            "work_organization_name": "Quốc hội",
        }
        pos, org = refine_position_and_organization(
            "Ủy viên", "Ban Chấp hành Trung ương Đảng", raw_text=raw_text, llm_service=mock_llm
        )
        check(pos == "Phó Chủ tịch")
        check(org == "Quốc hội")


@pytest.mark.anyio
async def test_luong_persons_extractor():
    mock_llm = MagicMock(spec=LLMService)
    mock_llm.ask_json_async = AsyncMock(
        return_value=[
            {
                "stt": 1,
                "full_name": "Nguyễn Văn A",
                "position_name": "Chủ tịch Hội đồng nhân dân thành phố Hà Nội, Phó Trưởng Đoàn đại biểu Quốc hội thành phố Hà Nội",
                "work_organization_name": None,
                "raw_text": "Điều 1...",
            }
        ]
    )
    extractor = LuongPersonsExtractor(llm_service=mock_llm)
    persons = await extractor.aextract("Nội dung quyết định lương...")

    check(len(persons) == 1)
    check(persons[0].full_name == "Nguyễn Văn A")
    check(persons[0].position_name == "Chủ tịch")
    check(persons[0].work_organization_name == "Hội đồng nhân dân thành phố Hà Nội")


@pytest.mark.anyio
async def test_qtct_persons_extractor():
    mock_llm = MagicMock(spec=LLMService)
    mock_llm.ask_json_async = AsyncMock(
        return_value=[
            {
                "stt": 1,
                "full_name": "Trần Thị B",
                "position_name": "Phó Chủ nhiệm Ủy ban Văn hóa, Giáo dục",
                "work_organization_name": None,
                "raw_text": "Điều 1...",
            }
        ]
    )
    extractor = QTCTPersonsExtractor(llm_service=mock_llm)
    persons = await extractor.aextract("Nội dung quyết định QTCT...")

    check(len(persons) == 1)
    check(persons[0].full_name == "Trần Thị B")
    check(persons[0].position_name == "Phó Chủ nhiệm")
    check(persons[0].work_organization_name == "Ủy ban Văn hóa, Giáo dục")


def test_khen_thuong_build_person():
    item = {
        "full_name": "Lê Văn C",
        "position_name": "Vụ trưởng, Thư ký Chủ tịch Quốc hội",
        "work_organization_name": "Văn phòng Quốc hội",
        "award_type": "TANG",
        "raw_text": "(1) Đồng chí Lê Văn C, Vụ trưởng, Thư ký Chủ tịch Quốc hội...",
    }
    person = _build_person(item, stt=1, group_index=1, code="1")
    check(person is not None)
    check(person.full_name == "Lê Văn C")
    check(person.position_name == "Vụ trưởng")
    check(person.work_organization_name == "Văn phòng Quốc hội")


# ---------------------------------------------------------------------------
# Test cơ chế FALLBACK sang LLM khi xuất hiện position mới chưa có trong POSITION_TITLES
# ---------------------------------------------------------------------------


class TestPositionFallbackToLLM:
    """Kiểm tra cơ chế fallback sang LLM khi gặp chức vụ mới chưa có trong POSITION_TITLES."""

    @pytest.mark.anyio
    async def test_fallback_called_when_position_not_in_titles_async(self):
        # "Chỉ huy trưởng" là vị trí mới chưa có trong POSITION_TITLES
        pos_raw = "Chỉ huy trưởng Bộ Chỉ huy Quân sự tỉnh Nghệ An"
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json_async = AsyncMock(
            return_value={
                "position_name": "Chỉ huy trưởng",
                "work_organization_name": "Bộ Chỉ huy Quân sự tỉnh Nghệ An",
            }
        )

        from services.llm_service import arefine_position_and_organization

        pos, org = await arefine_position_and_organization(pos_raw, None, llm_service=mock_llm)

        check(pos == "Chỉ huy trưởng")
        check(org == "Bộ Chỉ huy Quân sự tỉnh Nghệ An")
        # Xác nhận mock LLM ĐÃ ĐƯỢC GỌI để phân tách
        check(mock_llm.ask_json_async.call_count == 1)

    def test_fallback_called_when_position_not_in_titles_sync(self):
        pos_raw = "Tổng Biên tập Báo Nhân Dân"
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json = MagicMock(
            return_value={
                "position_name": "Tổng Biên tập",
                "work_organization_name": "Báo Nhân Dân",
            }
        )

        pos, org = refine_position_and_organization(pos_raw, None, llm_service=mock_llm)

        check(pos == "Tổng Biên tập")
        check(org == "Báo Nhân Dân")
        check(mock_llm.ask_json.call_count == 1)

    @pytest.mark.anyio
    async def test_fallback_not_called_when_position_already_in_titles(self):
        # "Chủ tịch" đã có trong POSITION_TITLES -> Không được gọi LLM fallback
        pos_raw = "Chủ tịch Hội đồng nhân dân thành phố Hà Nội"
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json_async = AsyncMock()

        from services.llm_service import arefine_position_and_organization

        pos, org = await arefine_position_and_organization(pos_raw, None, llm_service=mock_llm)

        check(pos == "Chủ tịch")
        check(org == "Hội đồng nhân dân thành phố Hà Nội")
        # Regex xử lý xong ngay, không tốn thêm roundtrip LLM
        check(mock_llm.ask_json_async.call_count == 0)

    @pytest.mark.anyio
    async def test_fallback_llm_handles_exception_gracefully(self):
        # Nếu LLM fallback gặp sự cố, hệ thống không bị crash mà giữ nguyên dữ liệu an toàn
        pos_raw = "Thuyền trưởng Tàu CSB 8001"
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json_async = AsyncMock(side_effect=RuntimeError("LLM service timeout"))

        from services.llm_service import arefine_position_and_organization

        pos, org = await arefine_position_and_organization(pos_raw, None, llm_service=mock_llm)

        check(pos == "Thuyền trưởng Tàu CSB 8001")
        check(org is None)
