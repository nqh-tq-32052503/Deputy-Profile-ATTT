import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from extractors.khen_thuong.extractor import KhenThuongExtractor
from extractors.khen_thuong.groups import KhenThuongGroupsExtractor
from extractors.khen_thuong.ocr_parser import (
    detect_has_attachment,
    parse_individual_group_chunks,
)
from extractors.khen_thuong.persons import (
    KhenThuongPersonsExtractor,
    extract_person_items_from_text,
)
from services.ocr_service import OCRService
from tests.assertions import check

_PL_JSON_PATH = Path(__file__).resolve().parent.parent / "PL_1741_0001_1750923323908 (1).json"


@pytest.fixture
def pl_1741_data():
    if not _PL_JSON_PATH.exists():
        pytest.skip("PL_1741_0001_1750923323908 (1).json does not exist")
    with open(_PL_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_ocr_service_enrich_markdown_with_tables(pl_1741_data):
    """Kiểm tra OCRService tự động bổ sung dữ liệu bảng vào markdown content."""
    ocr_service = OCRService()
    raw_content = pl_1741_data.get("content", "")
    check(len(raw_content) < 500)  # Raw content chỉ có 351 ký tự

    enriched = ocr_service._enrich_markdown_with_tables(raw_content, pl_1741_data)
    check(len(enriched) > 10000)
    check("| STT | Họ và tên | Chức vụ |" in enriched)
    check("Bà Phạm Thị Thanh Mai" in enriched)
    check("Ông Nguyễn Quốc Luận" in enriched)


def test_ocr_parser_individual_group_chunks_from_tables(pl_1741_data):
    """Kiểm tra parse_individual_group_chunks đọc chính xác 105 cá nhân từ 10 bảng."""
    chunks = parse_individual_group_chunks(pl_1741_data)
    check(chunks is not None)
    check(len(chunks) == 1)

    chunk = chunks[0]
    check(chunk.group_index == 1)
    check(chunk.person_count_declared == 105)
    check("Bằng khen của Ủy ban Thường vụ Quốc hội" in chunk.reward_type)
    check(len(chunk.item_texts) == 105)

    # Cá nhân đầu tiên: Bà Phạm Thị Thanh Mai (Đoàn ĐBQH TP Hà Nội)
    check("(1) Bà Phạm Thị Thanh Mai" in chunk.item_texts[0])
    check("Hà Nội" in chunk.item_texts[0])

    # Cá nhân cuối cùng: Ông Nguyễn Quốc Luận (Đoàn ĐBQH tỉnh Yên Bái)
    check("(1) Ông Nguyễn Quốc Luận" in chunk.item_texts[-1])
    check("Yên Bái" in chunk.item_texts[-1])


def test_extract_person_items_from_text_fallback_with_tables(pl_1741_data):
    """Kiểm tra fallback extract_person_items_from_text bóc tách đủ 105 cá nhân từ markdown bảng."""
    ocr_service = OCRService()
    enriched = ocr_service._enrich_markdown_with_tables(pl_1741_data.get("content", ""), pl_1741_data)
    items = extract_person_items_from_text(enriched)

    check(len(items) == 105)
    check("(1) Bà Phạm Thị Thanh Mai" in items[0][0])
    check("(1) Ông Nguyễn Quốc Luận" in items[-1][0])


def test_groups_extractor_build_from_table_chunks(pl_1741_data):
    """Kiểm tra build_from_chunks tạo KhenThuongGroup chính xác từ OCR table chunks."""
    chunks = parse_individual_group_chunks(pl_1741_data)
    check(chunks is not None)

    extractor = KhenThuongGroupsExtractor()
    groups = extractor.build_from_chunks(chunks)

    check(len(groups) == 1)
    check(groups[0].group_index == 1)
    check(groups[0].person_count_declared == 105)
    check("Bằng khen của Ủy ban Thường vụ Quốc hội" in groups[0].reward_type)


def test_detect_has_attachment_on_pl_document(pl_1741_data):
    """Kiểm tra detect_has_attachment nhận diện đúng phụ lục kèm theo và 105 cá nhân."""
    content = pl_1741_data.get("content", "")
    has_att, count = detect_has_attachment("", full_text=content)
    check(has_att is True)
    check(count == 105)


@pytest.mark.anyio
async def test_khen_thuong_extractor_pipeline_with_table_ocr(pl_1741_data):
    """Kiểm tra toàn bộ pipeline KhenThuongExtractor xử lý văn bản dạng bảng OCR."""
    mock_llm = MagicMock()

    async def mock_ask_json_async(prompt, text, **kwargs):
        # Giả lập LLM trích xuất từng người
        return {
            "full_name": "Nguyễn Văn A",
            "position_name": "Phó Trưởng đoàn",
            "work_organization_name": "Đoàn ĐBQH",
            "award_type": "TANG",
            "raw_text": text,
        }

    mock_llm.ask_json_async = AsyncMock(side_effect=mock_ask_json_async)
    mock_llm.ask_async = AsyncMock(return_value="{}")
    mock_llm.timeout = 30

    persons_extractor = KhenThuongPersonsExtractor(llm_service=mock_llm)
    extractor = KhenThuongExtractor(persons_extractor=persons_extractor)

    from extractors.khen_thuong.schemas import KhenThuongDetail, KhenThuongMetadata

    mock_metadata = KhenThuongMetadata(doc_type_detected="KHEN_THUONG")
    mock_detail = KhenThuongDetail(year=2025, reward_level="Bằng khen", content="Khen thưởng")

    with patch.object(extractor.metadata_extractor, "aextract", AsyncMock(return_value=mock_metadata)), \
         patch.object(extractor.detail_extractor, "aextract", AsyncMock(return_value=mock_detail)):

        result = await extractor.aextract(
            markdown_text=pl_1741_data.get("content", ""),
            ocr_data=pl_1741_data,
        )

        check(result.person_count_declared == 105)
        check(result.tong_so_ca_nhan == 105)
        check(len(result.persons) == 105)
        check(len(result.groups) == 1)
        check(len(result.warnings) == 0)
