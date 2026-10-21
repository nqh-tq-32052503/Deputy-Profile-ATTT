import asyncio
import logging
from typing import Any, List, Optional

from extractors.khen_thuong.ocr_parser import (
    GroupChunk,
    _extract_group_header_info,
    _extract_reward_type,
    _is_appendix_header,
    _is_group_title,
)
from extractors.khen_thuong.schemas import KhenThuongGroup
from services.llm_service import LLMService, clean_text

logger = logging.getLogger(__name__)

GROUPS_PROMPT = """Bạn là chuyên gia trích xuất văn bản hành chính Việt Nam.
Nhiệm vụ: Trích xuất danh sách các nhóm phân loại khen thưởng (groups) trong danh sách kèm theo của văn bản Khen thưởng (KHEN_THUONG) dưới dạng JSON mảng.
Đối tượng khen thưởng bao gồm cả cá nhân và tập thể.

Mỗi nhóm tương ứng với một mục phân loại (ví dụ: mục 1., 2., 3. trong danh sách) gồm các trường:
- group_index: Số thứ tự nhóm (số nguyên bắt đầu từ 1: 1, 2, 3...)
- title: Nguyên văn dòng tiêu đề của mục nhóm trong danh sách (ví dụ: "1. Tặng "Bằng khen của Ủy ban Thường vụ Quốc hội" cho 14 cá nhân do có thành tích xuất sắc trong công tác giai đoạn 2021-2024, gồm:")
- person_count_declared: Số lượng đối tượng (cá nhân hoặc tập thể) tuyên bố trong tiêu đề mục (số nguyên, ví dụ: 14, 2, 1)
- reward_type: Hình thức khen thưởng của nhóm (ví dụ: "Bằng khen của Ủy ban Thường vụ Quốc hội")
- accomplishment: Thành tích đạt được nêu trong tiêu đề nhóm (ví dụ: "Có thành tích xuất sắc trong công tác giai đoạn 2021-2024")

Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng mảng:
[
  {
    "group_index": 1,
    "title": "...",
    "person_count_declared": 14,
    "reward_type": "...",
    "accomplishment": "..."
  }
]"""


def _parse_count(val: Any) -> int:
    """Trích xuất số lượng an toàn mà không dùng regex."""
    if val is not None:
        try:
            digits = "".join(c for c in str(val) if c.isdigit())
            if digits:
                return int(digits)
        except (ValueError, TypeError):
            pass
    return 0


def _build_group_from_chunk(chunk: GroupChunk) -> KhenThuongGroup:
    """Tạo KhenThuongGroup trực tiếp từ GroupChunk (không cần LLM)."""
    return KhenThuongGroup(
        group_index=chunk.group_index,
        title=chunk.title,
        person_count_declared=chunk.person_count_declared,
        reward_type=chunk.reward_type,
        accomplishment=chunk.accomplishment,
    )


class KhenThuongGroupsExtractor:
    """
    Trích xuất danh sách nhóm (groups) cho văn bản Khen thưởng (KHEN_THUONG).

    Hỗ trợ hai chế độ:
    1. Từ GroupChunk (OCR-aware): Xây dựng trực tiếp từ dữ liệu đã phân tích,
       không cần gọi LLM thêm.
    2. Từ markdown text (fallback): Gửi toàn bộ text cho LLM để trích xuất.
    """

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()

    def build_from_chunks(self, group_chunks: List[GroupChunk]) -> List[KhenThuongGroup]:
        """
        Luồng mới: Xây dựng danh sách KhenThuongGroup trực tiếp từ GroupChunk.
        Nếu chunk chưa có reward_type, trích xuất bằng LLM.
        """
        groups = []
        for chunk in group_chunks:
            reward_type = chunk.reward_type
            if not reward_type:
                reward_type = _extract_reward_type(chunk.title, llm_service=self.llm_service)
            groups.append(
                KhenThuongGroup(
                    group_index=chunk.group_index,
                    title=chunk.title,
                    person_count_declared=chunk.person_count_declared,
                    reward_type=reward_type,
                    accomplishment=chunk.accomplishment,
                )
            )
        return groups

    def extract_from_text(self, content: str) -> List[KhenThuongGroup]:
        """
        Trích xuất danh sách groups từ text mà không dùng regex.
        reward_type, person_count_declared và accomplishment được nhận diện hoàn toàn bằng LLM.
        """
        lines = content.split("\n")
        ds_idx = 0
        for idx, line in enumerate(lines):
            s = line.strip().lstrip("#").strip().upper()
            if s.startswith(("DANH SÁCH", "DANH SACH")):
                ds_idx = idx
                break
        ds_text = "\n".join(lines[ds_idx:])

        found_groups = []
        for line in ds_text.split("\n"):
            line_str = line.strip()
            if _is_appendix_header(line_str):
                continue
            if _is_group_title(line_str) and any(
                w in line_str.lower()
                for w in [
                    "cá nhân",
                    "tập thể",
                    "bằng khen",
                    "kỷ niệm",
                    "huân chương",
                    "huy chương",
                    "danh hiệu",
                ]
            ):
                found_groups.append(line_str)

        groups = []
        for idx, title in enumerate(found_groups, start=1):
            info = _extract_group_header_info(title, llm_service=self.llm_service)
            g = KhenThuongGroup(
                group_index=idx,
                title=title,
                person_count_declared=info.get("person_count_declared", 0),
                reward_type=info.get("reward_type", ""),
                accomplishment=info.get("accomplishment", ""),
            )
            groups.append(g)

        return groups

    @staticmethod
    def _compact_content_for_llm(content: str) -> str:
        """Rút gọn text trước khi gửi LLM: bỏ qua các dòng cá nhân con."""
        compact_lines = []
        for line in content.split("\n"):
            line_s = line.strip()
            if not line_s:
                continue
            tokens = line_s.split(maxsplit=1)
            prefix = tokens[0].strip("().,:-/") if tokens else ""
            if prefix.isdigit() and len(tokens) > 1:
                second = tokens[1].lower()
                if second.startswith(("ông", "bà", "đồng chí")):
                    continue
            compact_lines.append(line_s)
        return "\n".join(compact_lines[:100])

    @staticmethod
    def _parse_llm_groups(data: Any) -> List[KhenThuongGroup]:
        """Chuyển đổi dữ liệu từ LLM thành danh sách KhenThuongGroup."""
        if isinstance(data, dict):
            data = data.get("groups", [data])
        if not isinstance(data, list):
            data = [data]

        groups = []
        for idx, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            group = KhenThuongGroup(
                group_index=item.get("group_index") or idx,
                title=clean_text(item.get("title")) or "",
                person_count_declared=_parse_count(item.get("person_count_declared")),
                reward_type=clean_text(item.get("reward_type")) or "",
                accomplishment=clean_text(item.get("accomplishment")) or "",
            )
            groups.append(group)
        return groups

    async def aextract(self, content: str) -> List[KhenThuongGroup]:
        """
        Trích xuất danh sách groups từ markdown text hoàn toàn bằng LLM.
        """
        text_groups = self.extract_from_text(content)
        if text_groups:
            return text_groups

        compact_content = self._compact_content_for_llm(content)
        data = await self.llm_service.ask_json_async(GROUPS_PROMPT, compact_content)
        return self._parse_llm_groups(data)

    def extract(self, content: str) -> List[KhenThuongGroup]:
        """Sync wrapper cho aextract (luồng cũ)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(self.aextract(content))
            return loop.run_until_complete(self.aextract(content))
        except RuntimeError:
            return asyncio.run(self.aextract(content))
