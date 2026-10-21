import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
import pytest

from extractors.luong.detail import LuongDetailExtractor
from extractors.luong.schemas import LuongDetail, LuongResult
from services.llm_service import LLMService
from tests.assertions import check


def test_luong_detail_zero_converted_to_none():
    mock_llm = MagicMock(spec=LLMService)
    # Giả lập LLM trả về 0 cho salary_step và 0.0 cho salary_factor
    mock_llm.ask_json_async = AsyncMock(
        return_value={
            "raise_salary_reason": "Nâng bậc lương",
            "position_wage": "Chuyên viên chính",
            "position_wage_code": "01.002",
            "old_step": 0,
            "old_factor": 0.0,
            "salary_step": 0,
            "salary_factor": 0.0,
            "start_date": "01/06/2025",
            "review_date": None,
            "percentage": None,
        }
    )

    extractor = LuongDetailExtractor(llm_service=mock_llm)
    result = extractor.extract("Nội dung quyết định lương...")

    check(result.salary_step is None)
    check(result.salary_factor is None)
    check(result.old_step is None)
    check(result.old_factor is None)

    # Kiểm tra serialization sang JSON
    dumped = result.model_dump() if hasattr(result, "model_dump") else result.dict()
    check(dumped["salary_step"] is None)
    check(dumped["salary_factor"] is None)
    check(dumped["old_step"] is None)
    check(dumped["old_factor"] is None)

    json_str = json.dumps(dumped)
    check('"salary_step": null' in json_str)
    check('"salary_factor": null' in json_str)


def test_luong_detail_none_preserved():
    mock_llm = MagicMock(spec=LLMService)
    # Giả lập LLM trả về None
    mock_llm.ask_json_async = AsyncMock(
        return_value={
            "raise_salary_reason": "Nâng bậc lương trước thời hạn",
            "position_wage": "Giảng viên cao cấp",
            "position_wage_code": None,
            "old_step": 3,
            "old_factor": 6.92,
            "salary_step": None,
            "salary_factor": None,
            "start_date": "01/06/2025",
            "review_date": None,
            "percentage": None,
        }
    )

    extractor = LuongDetailExtractor(llm_service=mock_llm)
    result = extractor.extract("Nội dung quyết định lương...")

    check(result.old_step == 3)
    check(result.old_factor == 6.92)
    check(result.salary_step is None)
    check(result.salary_factor is None)
