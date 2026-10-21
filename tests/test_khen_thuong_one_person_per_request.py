import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from extractors.khen_thuong.extractor import KhenThuongExtractor
from extractors.khen_thuong.ocr_parser import GroupChunk, detect_has_attachment, parse_individual_group_chunks
from extractors.khen_thuong.persons import (
    PERSON_ITEM_PROMPT,
    KhenThuongPersonsExtractor,
    extract_person_items_from_text,
)
from services.llm_service import LLMService
from tests.assertions import check


class TestKhenThuongItemSplitting:
    """Kiểm tra chức năng tách văn bản thành từng cá nhân độc lập."""

    def test_split_sample_khen_thuong(self):
        import os
        if not os.path.exists("sample_KHEN_THUONG.json"):
            # Sử dụng sample text mẫu 17 cá nhân nếu không có file fixture
            sample_text = """DANH SÁCH
1. Tặng Bằng khen cho 17 cá nhân:
(1) Ông Trần Thanh Mẫn, Chủ tịch Quốc hội
(2) Ông Nguyễn Khắc Định, Phó Chủ tịch Quốc hội
(3) Ông Nguyễn Đức Hải, Phó Chủ tịch Quốc hội
(4) Bà Nguyễn Thị Thanh, Phó Chủ tịch Quốc hội
(5) Ông Bùi Văn Cường, Chủ nhiệm Văn phòng
(6) Ông Nguyễn Đắc Vinh, Chủ nhiệm Ủy ban
(7) Ông Lê Tấn Tới, Chủ nhiệm Ủy ban
(8) Ông Hoàng Thanh Tùng, Chủ nhiệm Ủy ban
(9) Ông Lê Quang Huy, Chủ nhiệm Ủy ban
(10) Ông Vũ Hồng Thanh, Chủ nhiệm Ủy ban
(11) Bà Lê Thị Nga, Chủ nhiệm Ủy ban
(12) Ông Nguyễn Phú Cường, Chủ nhiệm Ủy ban
(13) Ông Y Thanh Hà Niê Kđăm, Chủ tịch Hội đồng Dân tộc
(14) Ông Dương Thanh Bình, Trưởng Ban Dân nguyện
(15) Bà Nguyễn Thanh Hải, Trưởng Ban Công tác đại biểu
(16) Ông Phạm Thái Hà, Phó Chủ nhiệm Văn phòng Quốc hội
(17) Ông Vũ Minh Tuấn, Phó Chủ nhiệm Văn phòng Quốc hội
"""
            items = extract_person_items_from_text(sample_text)
            check(len(items) == 17)
            check("Trần Thanh Mẫn" in items[0][0])
            check(items[0][1] == 1)
            check(items[0][2] == 1)
            check(items[0][3] == "1")
            return

        with open("sample_KHEN_THUONG.json") as f:
            d = json.load(f)
        text = d.get("content", "")
        items = extract_person_items_from_text(text)
        check(len(items) == 17)
        check("(1) Ông Trần Thanh Mẫn" in items[0][0])
        check(items[0][1] == 1)  # stt
        check(items[0][2] == 1)  # group_index
        check(items[0][3] == "1")  # code

    def test_split_difficult_ocr_v1(self):
        import os
        if not os.path.exists("khen_thuong_difficult_ocr.json"):
            pytest.skip("khen_thuong_difficult_ocr.json not found")
        with open("khen_thuong_difficult_ocr.json") as f:
            d = json.load(f)
        text = d.get("content", "")
        items = extract_person_items_from_text(text)
        # Bao gồm cả 13 tập thể và 89 cá nhân = 102
        check(len(items) == 102)
        check(items[0][1] == 1)
        check(items[-1][1] == 102)

    def test_split_difficult_ocr_v2(self):
        import os
        if not os.path.exists("khen_thuong_difficult_ocr_v2.json"):
            pytest.skip("khen_thuong_difficult_ocr_v2.json not found")
        with open("khen_thuong_difficult_ocr_v2.json") as f:
            d = json.load(f)
        text = d.get("content", "")
        items = extract_person_items_from_text(text)
        check(len(items) == 243)
        check(items[0][1] == 1)
        check(items[-1][1] == 243)

    def test_split_single_person_doc(self):
        doc = """NGHỊ QUYẾT
Điều 1. Tặng Bằng khen của Ủy ban Thường vụ Quốc hội cho đồng chí Trần Văn Nam, Phó Chủ nhiệm Ủy ban Pháp luật do có thành tích xuất sắc.
Điều 2. Nghị quyết này có hiệu lực từ ngày ký.
"""
        items = extract_person_items_from_text(doc)
        check(len(items) == 1)
        check("Trần Văn Nam" in items[0][0])
        check(items[0][1] == 1)
        check(items[0][2] == 1)
        check(items[0][3] == "1")


class TestKhenThuongOnePersonPerRequest:
    """
    Kiểm tra nguyên tắc cốt lõi:
    Mỗi request gửi tới LLM chỉ trích xuất cho 1 người duy nhất.
    """

    @pytest.mark.anyio
    async def test_aextract_markdown_calls_llm_per_person(self):
        content = """DANH SÁCH
1. Tặng Bằng khen cho 3 cá nhân:
(1) Ông Nguyễn Văn A, Chủ tịch Hội đồng nhân dân thành phố Hà Nội.
(2) Bà Lê Thị B, Phó Chủ nhiệm Ủy ban Văn hóa, Giáo dục.
(3) Ông Trần Văn C, Vụ trưởng, Thư ký Chủ tịch Quốc hội.
"""
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.timeout = 30
        mock_llm.ask_json_async = AsyncMock(
            side_effect=[
                {
                    "full_name": "Nguyễn Văn A",
                    "position_name": "Chủ tịch",
                    "work_organization_name": "Hội đồng nhân dân thành phố Hà Nội",
                    "award_type": "TANG",
                    "raw_text": "(1) Ông Nguyễn Văn A, Chủ tịch Hội đồng nhân dân thành phố Hà Nội.",
                },
                {
                    "full_name": "Lê Thị B",
                    "position_name": "Phó Chủ nhiệm",
                    "work_organization_name": "Ủy ban Văn hóa, Giáo dục",
                    "award_type": "TANG",
                    "raw_text": "(2) Bà Lê Thị B, Phó Chủ nhiệm Ủy ban Văn hóa, Giáo dục.",
                },
                {
                    "full_name": "Trần Văn C",
                    "position_name": "Vụ trưởng",
                    "work_organization_name": None,
                    "award_type": "TANG",
                    "raw_text": "(3) Ông Trần Văn C, Vụ trưởng, Thư ký Chủ tịch Quốc hội.",
                },
            ]
        )

        extractor = KhenThuongPersonsExtractor(llm_service=mock_llm)
        persons = await extractor.aextract(content)

        check(len(persons) == 3)
        # Đảm bảo LLM được gọi CHÍNH XÁC 3 lần (1 người = 1 request)
        check(mock_llm.ask_json_async.call_count == 3)

        # Đảm bảo prompt được dùng là PERSON_ITEM_PROMPT cho từng dòng
        for call_args in mock_llm.ask_json_async.call_args_list:
            prompt_arg = call_args[0][0]
            item_text_arg = call_args[0][1]
            check(prompt_arg == PERSON_ITEM_PROMPT)
            check(any(name in item_text_arg for name in ["Nguyễn Văn A", "Lê Thị B", "Trần Văn C"]))

        check(persons[0].full_name == "Nguyễn Văn A")
        check(persons[0].position_name == "Chủ tịch")
        check(persons[0].work_organization_name == "Hội đồng nhân dân thành phố Hà Nội")

        check(persons[1].full_name == "Lê Thị B")
        check(persons[1].position_name == "Phó Chủ nhiệm")
        check(persons[1].work_organization_name == "Ủy ban Văn hóa, Giáo dục")

        check(persons[2].full_name == "Trần Văn C")
        check(persons[2].position_name == "Vụ trưởng")

    @pytest.mark.anyio
    async def test_aextract_from_group_chunks_calls_llm_per_person(self):
        chunks = [
            GroupChunk(
                group_index=1,
                title="1. Tặng Bằng khen cho 2 cá nhân",
                person_count_declared=2,
                reward_type="Bằng khen",
                accomplishment="",
                item_texts=[
                    "(1) Ông Nguyễn Văn A, Phó Chủ tịch Quốc hội",
                    "(2) Bà Trần Thị B, Phó Chủ tịch Quốc hội",
                ],
            )
        ]

        mock_llm = MagicMock(spec=LLMService)
        mock_llm.timeout = 30
        mock_llm.ask_json_async = AsyncMock(
            side_effect=[
                {
                    "full_name": "Nguyễn Văn A",
                    "position_name": "Phó Chủ tịch",
                    "work_organization_name": "Quốc hội",
                    "award_type": "TANG",
                },
                {
                    "full_name": "Trần Thị B",
                    "position_name": "Phó Chủ tịch",
                    "work_organization_name": "Quốc hội",
                    "award_type": "TANG",
                },
            ]
        )

        extractor = KhenThuongPersonsExtractor(llm_service=mock_llm)
        persons = await extractor.aextract_from_group_chunks(chunks)

        check(len(persons) == 2)
        # Đảm bảo LLM được gọi CHÍNH XÁC 2 lần (1 người = 1 request)
        check(mock_llm.ask_json_async.call_count == 2)


class TestKhenThuongExtractorMultiFileAndFallback:
    """Kiểm tra pipeline KhenThuongExtractor hoàn chỉnh."""

    def test_detect_has_attachment_variations(self):
        check(detect_has_attachment("Điều 1. Tặng thưởng (có danh sách kèm theo)")[0] is True)
        check(detect_has_attachment("Điều 1. Khen thưởng theo danh sách đính kèm")[0] is True)
        check(detect_has_attachment("Điều 1. Ban hành kèm theo Quyết định này")[0] is True)
        check(detect_has_attachment("", full_text="DANH SÁCH\nCác cá nhân được khen thưởng")[0] is True)

    @pytest.mark.anyio
    async def test_khen_thuong_extractor_multi_file_support(self):
        # File 1 không có danh sách
        file1_ocr = {"tree": {"children": [{"node_type": "paragraph", "text": "Quyết định"}]}}
        # File 2 có danh sách kèm theo
        file2_ocr = {
            "tree": {
                "children": [
                    {
                        "node_type": "section",
                        "heading": {"text": "DANH SÁCH"},
                        "children": [
                            {
                                "node_type": "paragraph",
                                "text": "1. Tặng Bằng khen cho 1 cá nhân do có thành tích xuất sắc, gồm:",
                            },
                            {
                                "node_type": "paragraph",
                                "text": "(1) Ông Nguyễn Văn A, Chủ tịch Quốc hội",
                            },
                        ],
                    }
                ]
            }
        }

        # parse_individual_group_chunks tìm thấy chunks từ list các files
        chunks = parse_individual_group_chunks([file1_ocr, file2_ocr])
        check(chunks is not None)
        check(len(chunks) == 1)
        check(len(chunks[0].item_texts) == 1)

    def test_case_1_appendix_header_not_parsed_as_group(self):
        """Case 1: Dòng trích lục ban hành kèm theo không được nhận nhầm là nhóm khen thưởng."""
        import os
        case_1_path = "test_cases/Case_1/input.json"
        if not os.path.exists(case_1_path):
            pytest.skip("Không tìm thấy file test_cases/Case_1/input.json")

        with open(case_1_path) as f:
            data = json.load(f)

        chunks = parse_individual_group_chunks(data)
        check(chunks is not None)
        check(len(chunks) == 1)
        check(chunks[0].group_index == 1)
        check(chunks[0].person_count_declared == 7)
        check(chunks[0].reward_type == "Bằng khen của Ủy ban Thường vụ Quốc hội")
        check(len(chunks[0].item_texts) == 7)

        items = extract_person_items_from_text(data.get("content", ""))
        check(len(items) == 7)
        for it in items:
            check(it[2] == 1)  # group_index của tất cả cá nhân phải là 1

    @pytest.mark.anyio
    async def test_case_1_async_parse_individual_group_chunks(self):
        """Kiểm tra aparse_individual_group_chunks chạy an toàn trong async context."""
        import os
        from extractors.khen_thuong.ocr_parser import aparse_individual_group_chunks

        case_1_path = "test_cases/Case_1/input.json"
        if not os.path.exists(case_1_path):
            pytest.skip("Không tìm thấy file test_cases/Case_1/input.json")

        with open(case_1_path) as f:
            data = json.load(f)

        chunks = await aparse_individual_group_chunks(data)
        check(chunks is not None)
        check(len(chunks) == 1)
        check(chunks[0].group_index == 1)
        check(chunks[0].person_count_declared == 7)
        check(chunks[0].reward_type == "Bằng khen của Ủy ban Thường vụ Quốc hội")
        check(len(chunks[0].item_texts) == 7)

    def test_llm_service_ask_does_not_crash_in_running_event_loop(self):
        """Đảm bảo LLMService.ask() hoạt động đồng bộ an toàn ngay cả khi được gọi trong context có loop."""
        import asyncio
        from unittest.mock import patch, MagicMock
        service = LLMService(api_base_url="http://127.0.0.1:8000/v1")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Chào bạn, tôi là trợ lý ảo."}}]
        }

        async def inner():
            with patch("httpx.Client.post", return_value=mock_resp):
                # Trong một running loop, gọi ask() (sync) phải không quăng lỗi Can't patch loop
                return service.ask("Bạn là trợ lý ảo.", "Chào bạn", max_tokens=10)

        # Chạy inner bằng asyncio.run
        res = asyncio.run(inner())
        check(isinstance(res, str))
        check("Chào bạn" in res)

    @pytest.mark.anyio
    async def test_khen_thuong_extract_one_item_party_title_nguyen_duc_hai(self):
        """Case Nguyễn Đức Hải: Chức danh Đảng bị loại bỏ, nhận diện chức vụ Quốc hội."""
        from extractors.khen_thuong.persons import KhenThuongPersonsExtractor
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json_async = AsyncMock(
            return_value={
                "is_collective": False,
                "full_name": "Nguyễn Đức Hải",
                "position_name": "Phó Chủ tịch",
                "work_organization_name": "Quốc hội",
                "award_type": "TANG",
                "raw_text": "(3) Ông Nguyễn Đức Hải, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội.",
            }
        )
        extractor = KhenThuongPersonsExtractor(llm_service=mock_llm)
        item_text = "(3) Ông Nguyễn Đức Hải, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội."
        person = await extractor._extract_one_item(item_text, stt=2, group_index=1, code="3")
        check(person is not None)
        check(person.full_name == "Nguyễn Đức Hải")
        check(person.position_name == "Phó Chủ tịch")
        check(person.work_organization_name == "Quốc hội")

    @pytest.mark.anyio
    async def test_khen_thuong_extract_one_item_tran_thanh_man(self):
        """Case Trần Thanh Mẫn: Định dạng '(1):', bỏ chức danh Đảng, lấy Chủ tịch Quốc hội."""
        from extractors.khen_thuong.persons import KhenThuongPersonsExtractor
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json_async = AsyncMock(
            return_value={
                "is_collective": False,
                "full_name": "Trần Thanh Mẫn",
                "position_name": "Chủ tịch",
                "work_organization_name": "Quốc hội",
                "award_type": "TANG",
                "raw_text": "(1): Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội.",
            }
        )
        extractor = KhenThuongPersonsExtractor(llm_service=mock_llm)
        item_text = "(1): Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội."
        person = await extractor._extract_one_item(item_text, stt=1, group_index=1, code="1")
        check(person is not None)
        check(person.full_name == "Trần Thanh Mẫn")
        check(person.position_name == "Chủ tịch")
        check(person.work_organization_name == "Quốc hội")
        check(person.code == "1")
        check(person.award_type == "TANG")

    def test_case_2_colon_delimiter_extraction_17_persons(self):
        """Case 2: Kiểm tra extract_person_items_from_text bóc tách đủ 17 cá nhân từ markdown text."""
        import json
        from pathlib import Path
        from extractors.khen_thuong.extractor import KhenThuongExtractor
        from extractors.khen_thuong.persons import extract_person_items_from_text

        case_2_path = Path("test_cases/Case_2/input.json")
        if not case_2_path.exists():
            pytest.skip("Case 2 input not available")
        with open(case_2_path) as f:
            data = json.load(f)
        content = data.get("content", "")
        ext = KhenThuongExtractor()
        ds_text = ext._extract_danh_sach_text(content)
        items = extract_person_items_from_text(ds_text)
        check(len(items) == 17)
        check(items[0][3] == "1")
        check("Trần Thanh Mẫn" in items[0][0])

    def test_case_2_ocr_chunks_17_items(self):
        """Case 2: Kiểm tra parse_individual_group_chunks bóc tách đủ 3 nhóm với 17 items từ OCR tree."""
        import json
        from pathlib import Path
        from extractors.khen_thuong.ocr_parser import parse_individual_group_chunks

        case_2_path = Path("test_cases/Case_2/input.json")
        if not case_2_path.exists():
            pytest.skip("Case 2 input not available")
        with open(case_2_path) as f:
            data = json.load(f)
        chunks = parse_individual_group_chunks(data)
        check(chunks is not None)
        check(len(chunks) == 3)
        total_items = sum(len(c.item_texts) for c in chunks)
        check(total_items == 17)
        check("Trần Thanh Mẫn" in chunks[0].item_texts[0])



