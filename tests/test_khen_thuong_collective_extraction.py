import pytest
from unittest.mock import AsyncMock, MagicMock

from extractors.khen_thuong.ocr_parser import GroupChunk
from extractors.khen_thuong.persons import (
    KhenThuongPersonsExtractor,
    _build_person,
)
from services.llm_service import LLMService
from tests.assertions import check


class TestKhenThuongCollectiveExtractionMock:
    """Kiểm tra logic bóc tách đối tượng tập thể với mock LLM."""

    @pytest.mark.anyio
    async def test_extract_one_item_collective_mock(self):
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json_async = AsyncMock(
            return_value={
                "is_collective": True,
                "full_name": "Văn phòng Quốc hội",
                "position_name": None,
                "work_organization_name": "Văn phòng Quốc hội",
                "award_type": "TANG",
                "raw_text": "(1) Văn phòng Quốc hội.",
            }
        )

        extractor = KhenThuongPersonsExtractor(llm_service=mock_llm)
        person = await extractor._extract_one_item(
            "(1) Văn phòng Quốc hội.", stt=1, group_index=1, code="1"
        )

        check(person is not None)
        check(person.is_collective is True)
        check(person.full_name == "Văn phòng Quốc hội")
        check(person.position_name is None)
        check(person.work_organization_name == "Văn phòng Quốc hội")
        check(person.award_type == "TANG")
        check(person.raw_text == "(1) Văn phòng Quốc hội.")

    @pytest.mark.anyio
    async def test_extract_one_item_individual_mock(self):
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.ask_json_async = AsyncMock(
            return_value={
                "is_collective": False,
                "full_name": "Trần Thanh Mẫn",
                "position_name": "Chủ tịch",
                "work_organization_name": "Quốc hội",
                "award_type": "TANG",
                "raw_text": "(1) Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội.",
            }
        )

        extractor = KhenThuongPersonsExtractor(llm_service=mock_llm)
        person = await extractor._extract_one_item(
            "(1) Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội.",
            stt=1,
            group_index=1,
            code="1",
        )

        check(person is not None)
        check(person.is_collective is False)
        check(person.full_name == "Trần Thanh Mẫn")
        check(person.position_name == "Chủ tịch")
        check(person.work_organization_name == "Quốc hội")
        check(person.award_type == "TANG")

    def test_build_person_collective(self):
        item = {
            "is_collective": True,
            "full_name": "Viện Nghiên cứu lập pháp",
            "position_name": None,
            "work_organization_name": "Viện Nghiên cứu lập pháp",
            "award_type": "TANG",
            "raw_text": "(2) Viện Nghiên cứu lập pháp.",
        }
        person = _build_person(item, stt=2, group_index=1, code="2")
        check(person is not None)
        check(person.is_collective is True)
        check(person.full_name == "Viện Nghiên cứu lập pháp")
        check(person.position_name is None)
        check(person.work_organization_name == "Viện Nghiên cứu lập pháp")
        check(person.award_type == "TANG")
        check(person.code == "2")

    def test_build_person_individual(self):
        item = {
            "is_collective": False,
            "full_name": "Nguyễn Khắc Định",
            "position_name": "Phó Chủ tịch",
            "work_organization_name": "Quốc hội",
            "award_type": "TANG",
            "raw_text": "(2) Ông Nguyễn Khắc Định, Phó Chủ tịch Quốc hội.",
        }
        person = _build_person(item, stt=2, group_index=1, code="2")
        check(person is not None)
        check(person.is_collective is False)
        check(person.full_name == "Nguyễn Khắc Định")
        check(person.position_name == "Phó Chủ tịch")
        check(person.work_organization_name == "Quốc hội")
        check(person.award_type == "TANG")

    @pytest.mark.anyio
    async def test_aextract_from_group_chunks_with_collective(self):
        chunks = [
            GroupChunk(
                group_index=1,
                title="1. Tặng Bằng khen cho 2 tập thể:",
                person_count_declared=2,
                reward_type="Bằng khen",
                accomplishment="",
                item_texts=[
                    "(1) Văn phòng Quốc hội",
                    "(2) Viện Nghiên cứu lập pháp",
                ],
            )
        ]
        mock_llm = MagicMock(spec=LLMService)
        mock_llm.timeout = 30
        mock_llm.ask_json_async = AsyncMock(
            side_effect=[
                {
                    "is_collective": True,
                    "full_name": "Văn phòng Quốc hội",
                    "position_name": None,
                    "work_organization_name": "Văn phòng Quốc hội",
                    "award_type": "TANG",
                    "raw_text": "(1) Văn phòng Quốc hội",
                },
                {
                    "is_collective": True,
                    "full_name": "Viện Nghiên cứu lập pháp",
                    "position_name": None,
                    "work_organization_name": "Viện Nghiên cứu lập pháp",
                    "award_type": "TANG",
                    "raw_text": "(2) Viện Nghiên cứu lập pháp",
                },
            ]
        )

        extractor = KhenThuongPersonsExtractor(llm_service=mock_llm)
        persons = await extractor.aextract_from_group_chunks(chunks)

        check(len(persons) == 2)
        check(persons[0].is_collective is True)
        check(persons[0].full_name == "Văn phòng Quốc hội")
        check(persons[0].position_name is None)
        check(persons[0].work_organization_name == "Văn phòng Quốc hội")

        check(persons[1].is_collective is True)
        check(persons[1].full_name == "Viện Nghiên cứu lập pháp")
        check(persons[1].position_name is None)
        check(persons[1].work_organization_name == "Viện Nghiên cứu lập pháp")


def _check_live_llm():
    from core.config import LLM_API_BASE_URL
    if "<llm-host>" in LLM_API_BASE_URL or "<port>" in LLM_API_BASE_URL:
        pytest.skip("LLM service is not configured with a valid host/port")


class TestKhenThuongCollectiveExtractionLiveLLM:
    """Kiểm tra trực tiếp với model LLM thật."""

    @pytest.mark.anyio
    async def test_live_llm_van_phong_quoc_hoi(self):
        _check_live_llm()
        extractor = KhenThuongPersonsExtractor()
        item_text = "(1) Văn phòng Quốc hội."
        person = await extractor._extract_one_item(
            item_text, stt=1, group_index=1, code="1"
        )
        check(person is not None)
        check(person.is_collective is True)
        check(person.full_name == "Văn phòng Quốc hội")
        check(person.position_name is None)
        check(person.work_organization_name == "Văn phòng Quốc hội")
        check(person.award_type == "TANG")

    @pytest.mark.anyio
    async def test_live_llm_vien_nghien_cuu_lap_phap(self):
        _check_live_llm()
        extractor = KhenThuongPersonsExtractor()
        item_text = "(2) Viện Nghiên cứu lập pháp."
        person = await extractor._extract_one_item(
            item_text, stt=2, group_index=1, code="2"
        )
        check(person is not None)
        check(person.is_collective is True)
        check(person.full_name == "Viện Nghiên cứu lập pháp")
        check(person.position_name is None)
        check(person.work_organization_name == "Viện Nghiên cứu lập pháp")
        check(person.award_type == "TANG")

    @pytest.mark.anyio
    async def test_live_llm_individual_remains_normal(self):
        _check_live_llm()
        extractor = KhenThuongPersonsExtractor()
        item_text = "(1) Ông Trần Thanh Mẫn, Ủy viên Bộ Chính trị, Chủ tịch Quốc hội."
        person = await extractor._extract_one_item(
            item_text, stt=1, group_index=1, code="1"
        )
        check(person is not None)
        check(person.is_collective is False)
        check(person.full_name == "Trần Thanh Mẫn")
        check(person.position_name == "Chủ tịch")
        check(person.work_organization_name == "Quốc hội")
        check(person.award_type == "TANG")


class TestKhenThuongCase3Integration:
    """Kiểm tra end-to-end cho Case 3 (văn bản có cả tập thể và cá nhân)."""

    def test_parse_count_from_title(self):
        from extractors.khen_thuong.ocr_parser import _parse_count_from_title
        t_tt = '1. Tặng “Bằng khen của Ủy ban Thường vụ Quốc hội” cho 01 tập thể do có thành tích...'
        t_cn = '1. Tặng “Bằng khen của Ủy ban Thường vụ Quốc hội” cho 17 cá nhân do có thành tích...'
        t_both = 'Tặng Bằng khen cho 02 tập thể và 21 cá nhân'
        check(_parse_count_from_title(t_tt) == 1)
        check(_parse_count_from_title(t_cn) == 17)
        check(_parse_count_from_title(t_both) == 23)

    def test_detect_has_attachment(self):
        from extractors.khen_thuong.ocr_parser import detect_has_attachment
        dieu1 = 'Điều 1. Tặng Bằng khen của Ủy ban Thường vụ Quốc hội cho 02 tập thể và 21 cá nhân do có thành tích xuất sắc (Có danh sách kèm theo).'
        has_att, count = detect_has_attachment(dieu1)
        check(has_att is True)
        check(count == 23)

    @pytest.mark.anyio
    async def test_case_3_ocr_chunks(self):
        import json
        from pathlib import Path
        from extractors.khen_thuong.ocr_parser import aparse_individual_group_chunks

        case_3_path = Path("test_cases/Case_3/input.json")
        if not case_3_path.exists():
            pytest.skip("Case 3 input file not found")

        with open(case_3_path) as f:
            d = json.load(f)

        chunks = await aparse_individual_group_chunks(d)
        check(chunks is not None)
        check(len(chunks) == 5)
        check(sum(c.person_count_declared for c in chunks) == 23)
        check(sum(len(c.item_texts) for c in chunks) == 23)

        # Nhóm 1 và 2 là tập thể
        check(chunks[0].person_count_declared == 1)
        check(chunks[0].item_texts == ["Văn phòng Quốc hội"])
        check(chunks[1].person_count_declared == 1)
        check(chunks[1].item_texts == ["Viện Nghiên cứu lập pháp"])

        # Nhóm 3, 4, 5 là cá nhân
        check(chunks[2].person_count_declared == 17)
        check(len(chunks[2].item_texts) == 17)
        check(chunks[3].person_count_declared == 3)
        check(len(chunks[3].item_texts) == 3)
        check(chunks[4].person_count_declared == 1)
        check(len(chunks[4].item_texts) == 1)

    @pytest.mark.anyio
    async def test_case_3_full_extraction(self):
        import json
        from pathlib import Path
        from extractors.khen_thuong.extractor import KhenThuongExtractor

        case_3_path = Path("test_cases/Case_3/input.json")
        if not case_3_path.exists():
            pytest.skip("Case 3 input file not found")

        with open(case_3_path) as f:
            d = json.load(f)

        extractor = KhenThuongExtractor()
        result = await extractor.aextract(d.get("content", ""), ocr_data=d)

        check(result.person_count_declared == 23)
        check(result.tong_so_ca_nhan == 23)
        check(len(result.groups) == 5)
        check(len(result.persons) == 23)
        check(len(result.warnings) == 0)

        # Kiểm tra 2 tập thể
        p1 = result.persons[0]
        check(p1.is_collective is True)
        check(p1.full_name == "Văn phòng Quốc hội")
        check(p1.position_name is None)
        check(p1.work_organization_name == "Văn phòng Quốc hội")

        p2 = result.persons[1]
        check(p2.is_collective is True)
        check(p2.full_name == "Viện Nghiên cứu lập pháp")
        check(p2.position_name is None)
        check(p2.work_organization_name == "Viện Nghiên cứu lập pháp")

        # Kiểm tra cá nhân bình thường
        p3 = result.persons[2]
        check(p3.is_collective is False)
        check(p3.full_name == "Nguyễn Văn Hiển")
        check(p3.position_name == "Viện trưởng")

    @pytest.mark.anyio
    async def test_case_4_ocr_chunks(self):
        import json
        from pathlib import Path
        from extractors.khen_thuong.ocr_parser import aparse_individual_group_chunks

        case_4_path = Path("test_cases/Case_4/input.json")
        if not case_4_path.exists():
            pytest.skip("Case 4 input file not found")

        with open(case_4_path) as f:
            d = json.load(f)

        chunks = await aparse_individual_group_chunks(d)
        check(chunks is not None)
        check(len(chunks) == 1)
        check(chunks[0].person_count_declared == 29)
        check(len(chunks[0].item_texts) == 29)
        check(chunks[0].reward_type == "Bằng khen của Ủy ban Thường vụ Quốc hội")

    @pytest.mark.anyio
    async def test_case_4_full_extraction(self):
        import json
        from pathlib import Path
        from extractors.khen_thuong.extractor import KhenThuongExtractor

        case_4_path = Path("test_cases/Case_4/input.json")
        if not case_4_path.exists():
            pytest.skip("Case 4 input file not found")

        with open(case_4_path) as f:
            d = json.load(f)

        extractor = KhenThuongExtractor()
        result = await extractor.aextract(d.get("content", ""), ocr_data=d)

        check(result.person_count_declared == 29)
        check(result.tong_so_ca_nhan == 29)
        check(len(result.groups) == 1)
        check(len(result.persons) == 29)
        check(len(result.warnings) == 0)

        # Kiểm tra 9 tập thể đầu tiên
        collectives = [p for p in result.persons if p.is_collective]
        check(len(collectives) == 9)
        for c in collectives:
            check(c.is_collective is True)
            check(c.position_name is None)
            check(c.work_organization_name == c.full_name)

        # Kiểm tra 20 cá nhân tiếp theo
        individuals = [p for p in result.persons if not p.is_collective]
        check(len(individuals) == 20)
        for ind in individuals:
            check(ind.is_collective is False)
            check(ind.full_name)
            check(ind.position_name is not None)


