"""
ocr_parser.py
Tiện ích phân tích cấu trúc OCR (JSON tree) cho văn bản KHEN_THUONG.
Cung cấp hàm trích xuất phần danh sách kèm theo từ cây OCR.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from services.llm_service import LLMService, clean_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DANH_SACH_UPPER = "DANH SÁCH"
DANH_SACH_ASCII_UPPER = "DANH SACH"
TAP_THE_LOWER = "tập thể"
CA_NHAN_LOWER = "cá nhân"
WARN_NO_TREE_OR_TABLE = "[OCR_PARSER] Không tìm thấy tree.children và tables trong OCR data."
DETAIL_PREFIX = "detail."
PERSONS_KEY = "persons["
GROUPS_KEY = "groups["
DANH_SACH_GOM_LOWER = "danh sách gồm:"
DOAN_DBQH_LOWER = "đoàn đbqh"
HO_VA_TEN_UPPER = "HỌ VÀ TÊN"
DANH_SACH_KHEN_THUONG = "Danh sách khen thưởng"

UNIT_KEYWORDS: Tuple[str, ...] = (
    "đoàn đbqh",
    "đoàn đại biểu",
    "văn phòng đoàn",
    "đảng bộ",
    "thành ủy",
    "tỉnh ủy",
)
TABLE_HEADER_KEYWORDS: Tuple[str, ...] = ("STT", HO_VA_TEN_UPPER)
HONORIFICS: Tuple[str, ...] = ("ông", "bà", "đồng chí")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_node_text(node: Dict) -> str:
    """Lấy text trực tiếp của node (không đệ quy)."""
    return node.get("text") or ""


def _get_heading_text(node: Dict) -> str:
    """Lấy text của heading trong section node."""
    heading = node.get("heading")
    if isinstance(heading, dict):
        return heading.get("text") or ""
    return ""


def _node_contains_danh_sach(node: Dict) -> bool:
    """Kiểm tra node (heading hoặc text) có chứa từ DANH SÁCH viết hoa không."""
    combined = (_get_node_text(node) + _get_heading_text(node)).upper()
    return DANH_SACH_UPPER in combined or DANH_SACH_ASCII_UPPER in combined


def _collect_all_text(node: Dict) -> str:
    """Thu thập đệ quy toàn bộ text trong một node và con cháu của nó."""
    parts: List[str] = []
    heading_text = _get_heading_text(node)
    if heading_text:
        parts.append(heading_text)
    direct_text = _get_node_text(node)
    if direct_text:
        parts.append(direct_text)
    for child in node.get("children", []):
        child_text = _collect_all_text(child)
        if child_text:
            parts.append(child_text)
    return "\n".join(t for t in parts if t)


# ---------------------------------------------------------------------------
# Tìm phần DANH SÁCH trong OCR tree
# ---------------------------------------------------------------------------

def _node_has_danh_sach_recursive(n: Dict) -> bool:
    if _node_contains_danh_sach(n):
        return True
    for ch in n.get("children", []):
        if ch.get("node_type") == "section" and _node_has_danh_sach_recursive(ch):
            return True
    return False


def _find_fallback_collective_or_individual(root_children: List[Dict]) -> List[Dict]:
    fallback_nodes: List[Dict] = []
    for node in root_children:
        heading = _get_heading_text(node).lower()
        if node.get("node_type") == "section" and (
            TAP_THE_LOWER in heading or CA_NHAN_LOWER in heading
        ):
            fallback_nodes.append(node)
    return fallback_nodes


def collect_danh_sach_nodes(root_children: List[Dict]) -> List[Dict]:
    """
    Trả về danh sách tất cả node thuộc phần danh sách kèm theo.
    """
    for i, node in enumerate(root_children):
        if _node_has_danh_sach_recursive(node):
            return root_children[i:]

    return _find_fallback_collective_or_individual(root_children)


# ---------------------------------------------------------------------------
# Lọc phần Cá nhân (bỏ Tập thể)
# ---------------------------------------------------------------------------

def _is_collective_section(heading_text: str) -> bool:
    """
    Xác định một section có phải là khen thưởng tập thể không
    (ví dụ: 'I. Tập thể:').
    """
    lower = heading_text.lower()
    return TAP_THE_LOWER in lower and CA_NHAN_LOWER not in lower


def _is_individual_section(heading_text: str) -> bool:
    """Xác định section khen thưởng cá nhân (ví dụ: 'II. Cá nhân:')."""
    lower = heading_text.lower()
    return CA_NHAN_LOWER in lower


def _is_appendix_header(text: str) -> bool:
    """
    Kiểm tra xem paragraph/dòng có phải là trích lục / căn cứ ban hành phụ lục hay không:
    Ví dụ:
    - '(Ban hành kèm theo Nghị quyết số .../NQ-UBTVQH15 ngày ...)'
    - 'Tặng Bằng khen... (Ban hành kèm theo Nghị quyết số...)'
    - 'Kèm theo Quyết định số... ngày...'
    """
    if not text:
        return False
    lower = text.lower()
    keywords = [
        "kèm theo nghị quyết",
        "kèm theo quyết định",
        "ban hành kèm theo",
        "(kèm theo",
        "(ban hành kèm theo",
        "danh sách kèm theo",
        "danh sách được khen",
        "danh sách khen thưởng",
    ]
    return any(kw in lower for kw in keywords)


# ---------------------------------------------------------------------------
# Tiện ích nhận diện tiêu đề nhóm và item cá nhân (không dùng regex)
# ---------------------------------------------------------------------------

def _is_group_title(text: str) -> bool:
    """
    Nhận diện tiêu đề nhóm khen thưởng mà không dùng regex.
    Hỗ trợ các dạng: "1. Tặng...", "(1) Tặng...", "I. Tặng...", "Tặng “Bằng khen..."...
    """
    if not text:
        return False
    s = text.strip()
    tokens = s.split(maxsplit=2)
    first_token = tokens[0] if tokens else ""
    first_clean = first_token.strip(".):-()[]")
    if first_clean.isdigit() or first_clean.upper() in (
        "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"
    ):
        remaining = s[len(first_token):].strip()
    else:
        remaining = s

    rem_lower = remaining.lower()
    if rem_lower.startswith(("tặng", "truy tặng")):
        award_keywords = [
            "“", '"', "bằng khen", "huân chương", "huy chương", "kỷ niệm chương", "thưởng", "cho "
        ]
        return any(kw in rem_lower for kw in award_keywords)
    return False


def _is_item_paragraph(text: str) -> bool:
    """
    Nhận diện paragraph là item cá nhân / đối tượng mà không dùng regex:
    Bắt đầu bằng '(N)' hoặc 'N.' theo sau là nội dung.
    """
    if not text:
        return False
    s = text.strip()
    tokens = s.split(maxsplit=1)
    if not tokens or len(tokens) < 2:
        return False
    first = tokens[0]
    if first.startswith("(") and ")" in first:
        idx = first.find(")")
        inner = first[1:idx].strip()
        if inner.isdigit():
            after = first[idx + 1 :]
            if not after or after in (":", ".", "-", "/"):
                return True
    if first[-1] in (".", ":", ")", "-", "/") and first[:-1].isdigit():
        return True
    return False


def _has_flat_group_structure(node: Dict) -> bool:
    """
    Kiểm tra xem node có chứa cấu trúc "flat" không:
    tức là children trực tiếp chứa paragraph tiêu đề nhóm theo pattern
    'N. Tặng...' hoặc '(N) Tặng...' kèm list/paragraph cá nhân.

    Dùng để phát hiện file OCR không có section cha "Cá nhân" mà
    gom tất cả trực tiếp trong section DANH SÁCH.
    """
    for child in node.get("children", []):
        nt = child.get("node_type", "")
        text = _get_node_text(child)
        if nt == "paragraph" and text and _is_group_title(text) and not _is_appendix_header(text):
            return True
    return False


def _has_table_structure(node: Dict) -> bool:
    """
    Kiểm tra xem node hoặc children của nó có chứa node table_ref không.
    Dùng để phát hiện phụ lục danh sách khen thưởng trình bày dưới dạng bảng (tables).
    """
    for child in node.get("children", []):
        if child.get("node_type") == "table_ref":
            return True
        if child.get("node_type") == "section":
            for subchild in child.get("children", []):
                if subchild.get("node_type") == "table_ref":
                    return True
    return False


def _is_individual_section_candidate(node: Dict, heading: str) -> bool:
    if _is_collective_section(heading):
        return True
    if _is_individual_section(heading):
        return True
    if heading and _is_group_title(heading) and not _is_appendix_header(heading):
        return True
    if (_node_contains_danh_sach(node) or DANH_SACH_UPPER in heading.upper()) and (
        _has_flat_group_structure(node) or _has_table_structure(node)
    ):
        return True
    return False


def _find_individual_sections_recursive(node: Dict) -> List[Dict]:
    heading = _get_heading_text(node)
    nt = node.get("node_type", "")
    if nt != "section":
        return []
    if _is_individual_section_candidate(node, heading):
        return [node]
    results = []
    for c in node.get("children", []):
        if c.get("node_type") == "section":
            results.extend(_find_individual_sections_recursive(c))
    return results


def _find_fallback_individual_section(nodes: List[Dict]) -> Optional[Dict]:
    for node in nodes:
        if node.get("node_type") != "section":
            continue
        if _has_flat_group_structure(node) or _has_table_structure(node):
            return node
        for child in node.get("children", []):
            if (
                child.get("node_type") == "section"
                and _node_contains_danh_sach(child)
                and (_has_flat_group_structure(child) or _has_table_structure(child))
            ):
                return child
    return None


def extract_individual_sections(danh_sach_nodes: List[Dict]) -> List[Dict]:
    """
    Từ danh sách nodes của phần DANH SÁCH, lọc ra các sections thuộc đối tượng khen thưởng (cá nhân và tập thể).
    """
    individual_sections: List[Dict] = []
    for node in danh_sach_nodes:
        individual_sections.extend(_find_individual_sections_recursive(node))

    if not individual_sections:
        fb = _find_fallback_individual_section(danh_sach_nodes)
        if fb is not None:
            individual_sections.append(fb)

    return individual_sections


# ---------------------------------------------------------------------------
# Trích xuất groups từ sections cá nhân
# ---------------------------------------------------------------------------

class GroupChunk:
    """Đại diện cho một mục/nhóm khen thưởng cá nhân trong danh sách."""

    def __init__(
        self,
        group_index: int,
        title: str,
        person_count_declared: int,
        reward_type: str,
        accomplishment: str,
        item_texts: List[str],
    ):
        self.group_index = group_index
        self.title = title
        self.person_count_declared = person_count_declared
        self.reward_type = reward_type
        self.accomplishment = accomplishment
        self.item_texts = item_texts  # Danh sách text của từng list_item/paragraph

    def __repr__(self):
        return (
            f"GroupChunk(group_index={self.group_index}, "
            f"title={self.title[:50]!r}, "
            f"items={len(self.item_texts)})"
        )


def _parse_digits_before_keyword(text: str, kw: str) -> int:
    """Lấy số nguyên ngay trước từ khóa mà không dùng regex."""
    if not text:
        return 0
    idx = text.lower().find(kw.lower())
    if idx != -1:
        sub = text[:idx].rstrip()
        digits = []
        for ch in reversed(sub):
            if ch.isdigit():
                digits.append(ch)
            elif digits:
                break
        if digits:
            try:
                return int("".join(reversed(digits)))
            except ValueError:
                pass
    return 0


def _parse_digits_after_keyword(text: str, kw: str) -> int:
    """Lấy số nguyên ngay sau từ khóa mà không dùng regex."""
    if not text:
        return 0
    idx = text.lower().find(kw.lower())
    if idx != -1:
        sub = text[idx + len(kw):].lstrip()
        digits = []
        for ch in sub:
            if ch.isdigit():
                digits.append(ch)
            elif digits:
                break
        if digits:
            try:
                return int("".join(digits))
            except ValueError:
                pass
    return 0


def _parse_count_from_title(title: str) -> int:
    """Trích xuất số lượng đối tượng (cá nhân / tập thể) từ tiêu đề nhóm mà không dùng regex."""
    if not title:
        return 0
    count_tt = _parse_digits_before_keyword(title, TAP_THE_LOWER)
    count_cn = _parse_digits_before_keyword(title, CA_NHAN_LOWER)
    if count_tt or count_cn:
        return count_tt + count_cn
    count_dt = _parse_digits_before_keyword(title, "đối tượng")
    if count_dt:
        return count_dt
    count_cho = _parse_digits_after_keyword(title, "cho")
    if count_cho:
        return count_cho
    return 0


GROUP_HEADER_PROMPT = """Bạn là chuyên gia trích xuất văn bản hành chính Việt Nam.
Nhiệm vụ: Từ tiêu đề hoặc nội dung giới thiệu của nhóm khen thưởng, hãy trích xuất chính xác các thông tin sau dưới dạng JSON:
- reward_type: Tên hình thức khen thưởng / danh hiệu thi đua (ví dụ: "Bằng khen của Ủy ban Thường vụ Quốc hội", "Kỷ niệm chương Vì sự nghiệp Quốc hội Việt Nam", "Huân chương Lao động hạng Ba").
- person_count_declared: Tổng số lượng đối tượng (tổng cả tập thể và cá nhân) được khen thưởng nêu trong tiêu đề (số nguyên).
  Ví dụ: "cho 09 tập thể và 20 cá nhân" -> 29; "cho 14 cá nhân" -> 14; "cho 02 tập thể" -> 2. Nếu không có số lượng cụ thể thì trả về 0.
- accomplishment: Thành tích khen thưởng nêu trong tiêu đề (bắt đầu bằng "Có thành tích..." hoặc nguyên văn lý do, ví dụ: "Có thành tích xuất sắc trong công tác phối hợp..."). Nếu không có thì trả về null.

Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng:
{
  "reward_type": "...",
  "person_count_declared": 29,
  "accomplishment": "..."
}"""


def _extract_group_header_info(
    title: str, llm_service: Optional[LLMService] = None
) -> Dict[str, Any]:
    """Trích xuất thông tin header nhóm (reward_type, count, accomplishment) bằng LLM."""
    if not title or not title.strip():
        return {"reward_type": "", "person_count_declared": 0, "accomplishment": ""}
    service = llm_service or LLMService()
    try:
        data = service.ask_json(GROUP_HEADER_PROMPT, title.strip())
        if isinstance(data, dict):
            return {
                "reward_type": clean_text(data.get("reward_type")) or "",
                "person_count_declared": int(data.get("person_count_declared") or 0),
                "accomplishment": clean_text(data.get("accomplishment")) or "",
            }
    except Exception as e:
        logger.warning(f"[OCR_PARSER] Lỗi khi trích xuất header info qua LLM: {e}")
    return {
        "reward_type": "",
        "person_count_declared": _parse_count_from_title(title),
        "accomplishment": _extract_accomplishment(title),
    }


async def _aextract_group_header_info(
    title: str,
    llm_service: Optional[LLMService] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Trích xuất thông tin header nhóm (reward_type, count, accomplishment) bằng LLM (bất đồng bộ)."""
    if not title or not title.strip():
        return {"reward_type": "", "person_count_declared": 0, "accomplishment": ""}
    service = llm_service or LLMService()
    try:
        data = await service.ask_json_async(GROUP_HEADER_PROMPT, title.strip(), client=client)
        if isinstance(data, dict):
            return {
                "reward_type": clean_text(data.get("reward_type")) or "",
                "person_count_declared": int(data.get("person_count_declared") or 0),
                "accomplishment": clean_text(data.get("accomplishment")) or "",
            }
    except Exception as e:
        logger.warning(f"[OCR_PARSER] Lỗi khi trích xuất header info qua LLM async: {e}")
    return {
        "reward_type": "",
        "person_count_declared": _parse_count_from_title(title),
        "accomplishment": _extract_accomplishment(title),
    }


def _extract_reward_type(title: str, llm_service: Optional[LLMService] = None) -> str:
    """Trích xuất hình thức khen thưởng từ tiêu đề nhóm hoàn toàn bằng LLM."""
    return _extract_group_header_info(title, llm_service=llm_service).get("reward_type", "")


async def _aextract_reward_type(
    title: str,
    llm_service: Optional[LLMService] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Trích xuất hình thức khen thưởng từ tiêu đề nhóm hoàn toàn bằng LLM (bất đồng bộ)."""
    res = await _aextract_group_header_info(title, llm_service=llm_service, client=client)
    return res.get("reward_type", "")


def _extract_accomplishment(title: str) -> str:
    """Trích xuất thành tích từ tiêu đề nhóm mà không dùng regex."""
    if not title:
        return ""
    low = title.lower()
    idx_do_co = low.find("do có")
    if idx_do_co != -1:
        rem = title[idx_do_co + len("do có"):].strip()
        idx_gom = rem.lower().find("gồm")
        if idx_gom != -1:
            rem = rem[:idx_gom].strip().rstrip(",;:-.")
        return ("Có " + rem).strip().rstrip(".")
    idx_co = low.find("có thành tích")
    if idx_co != -1:
        rem = title[idx_co:].strip()
        idx_gom = rem.lower().find("gồm")
        if idx_gom != -1:
            rem = rem[:idx_gom].strip().rstrip(",;:-.")
        return rem.strip().rstrip(".")
    return ""


def _is_item_delimiter_word(w: str) -> bool:
    cleaned = w.strip("().,:-/")
    if not (cleaned.isdigit() and len(cleaned) <= 4):
        return False
    return (w.startswith("(") and w.endswith((")", "):", ")."))) or w.endswith(".")


def _split_paragraph_to_items(text: str) -> List[str]:
    """
    Tách một paragraph có thể chứa nhiều cá nhân (OCR gộp chung) thành các item riêng lẻ mà không dùng regex.
    """
    if not text:
        return []
    words = text.split()
    item_start_indices = [idx for idx, w in enumerate(words) if _is_item_delimiter_word(w)]

    if len(item_start_indices) <= 1:
        return [text.strip()] if text.strip() else []

    items = []
    for i, start_w in enumerate(item_start_indices):
        end_w = item_start_indices[i + 1] if i + 1 < len(item_start_indices) else len(words)
        item = " ".join(words[start_w:end_w]).strip()
        if item:
            items.append(item)
    return items


def _collect_list_items_from_node(node: Dict) -> List[str]:
    """
    Thu thập text của các list_item và paragraph cá nhân trong node.
    Xử lý cả trường hợp OCR gộp nhiều người vào 1 paragraph.
    """
    item_texts: List[str] = []
    for child in node.get("children", []):
        nt = child.get("node_type", "")
        text = _get_node_text(child).strip()

        if nt == "list_item" and text:
            item_texts.append(text)
        elif nt == "list":
            for item in child.get("children", []):
                item_text = _get_node_text(item).strip()
                if item_text and item.get("node_type") == "list_item":
                    item_texts.append(item_text)
        elif nt == "paragraph" and text and _is_item_paragraph(text) and not _is_group_title(text):
            item_texts.extend(_split_paragraph_to_items(text))

    return item_texts


def _is_valid_coll_paragraph(sub_text: str, item_texts: List[str]) -> bool:
    if any(ign in sub_text for ign in [GROUPS_KEY, PERSONS_KEY, DETAIL_PREFIX]):
        return False
    if sub_text.strip().lower() in ["gồm:", "gồm", DANH_SACH_GOM_LOWER]:
        return False
    return sub_text not in item_texts


def _handle_paragraph_child(sub_text: str, is_coll: bool, item_texts: List[str]) -> None:
    if not sub_text or _is_group_title(sub_text):
        return
    if _is_item_paragraph(sub_text):
        item_texts.extend(_split_paragraph_to_items(sub_text))
    elif is_coll and _is_valid_coll_paragraph(sub_text, item_texts):
        item_texts.append(sub_text)


def _handle_table_ref_child(
    child: Dict, tables: Optional[Dict], current_unit: str, item_texts: List[str]
) -> str:
    if not tables:
        return current_unit
    t_obj = tables.get(child.get("table_id"))
    if t_obj:
        t_items, current_unit = _extract_items_from_table(t_obj, current_unit)
        item_texts.extend(t_items)
    return current_unit


def _collect_items_from_child_element(
    child: Dict,
    is_coll: bool,
    tables: Optional[Dict],
    current_unit: str,
    item_texts: List[str],
) -> str:
    """Thu thập items từ một node con (list, list_item, paragraph, table_ref)."""
    sub_nt = child.get("node_type", "")
    sub_text = _get_node_text(child).strip()
    if _is_appendix_header(sub_text):
        return current_unit

    if sub_nt == "list":
        for li in child.get("children", []):
            lit = _get_node_text(li).strip()
            if lit and li.get("node_type") == "list_item":
                item_texts.append(lit)
    elif sub_nt == "list_item" and sub_text:
        item_texts.append(sub_text)
    elif sub_nt == "paragraph":
        _handle_paragraph_child(sub_text, is_coll, item_texts)
    elif sub_nt == "table_ref":
        current_unit = _handle_table_ref_child(child, tables, current_unit, item_texts)

    return current_unit


def _collect_all_items_from_children(
    children: List[Dict],
    is_coll: bool,
    tables: Optional[Dict],
    current_unit: str = "",
) -> Tuple[List[str], str]:
    """Thu thập tất cả item_texts và cập nhật current_unit từ danh sách children."""
    item_texts: List[str] = []
    for c in children:
        current_unit = _collect_items_from_child_element(c, is_coll, tables, current_unit, item_texts)
    return item_texts, current_unit


def _collect_direct_items_from_section(
    section: Dict, tables: Optional[Dict] = None
) -> List[str]:
    """
    Thu thập trực tiếp tất cả items (list_item, table_ref, paragraph cá nhân/tập thể)
    trong section khi section không có tiêu đề nhóm _GROUP_TITLE_RE riêng.
    """
    heading = _get_heading_text(section)
    is_coll = _is_collective_section(heading)
    items, _ = _collect_all_items_from_children(section.get("children", []), is_coll, tables)
    return items


def _clean_unit(text: str) -> str:
    """Loại bỏ tiền tố STT dạng số ở đầu tên đơn vị mà không dùng regex."""
    if not text:
        return ""
    words = text.strip().split(maxsplit=1)
    if words:
        cleaned_first = words[0].strip(".- ")
        if cleaned_first.isdigit():
            return words[1].strip() if len(words) > 1 else ""
    return text.strip()


def _strip_dbqh_prefix(unit_str: str) -> str:
    """Loại bỏ tiền tố Đoàn ĐBQH / Đại biểu Quốc hội khỏi chuỗi đơn vị."""
    s = unit_str.strip()
    low = s.lower()
    prefixes = [
        "đoàn đại biểu quốc hội",
        DOAN_DBQH_LOWER,
        "đại biểu quốc hội",
        "đbqh",
    ]
    for p in prefixes:
        if low.startswith(p):
            return s[len(p):].strip()
    return s


def _should_append_unit(current_unit: str, pos: str) -> bool:
    """
    Kiểm tra xem có cần bổ sung current_unit vào dòng thông tin cá nhân hay không mà không dùng regex.
    Tránh trùng lặp nếu pos đã chứa thông tin về đơn vị hoặc tên địa phương của đơn vị.
    """
    if not current_unit:
        return False
    if current_unit.lower() in pos.lower():
        return False
    clean_u = _strip_dbqh_prefix(current_unit)
    if clean_u and clean_u.lower() in pos.lower():
        return False
    return True


def _is_table_header_row(cols: List[str]) -> bool:
    if not cols or all(not x for x in cols):
        return True
    first = cols[0].upper()
    if any(h in first for h in TABLE_HEADER_KEYWORDS):
        return True
    if len(cols) > 1 and HO_VA_TEN_UPPER in cols[1].upper():
        return True
    return False


def _find_unit_in_row(cols: List[str]) -> Optional[str]:
    for c in cols:
        if any(k in c.lower() for k in UNIT_KEYWORDS):
            return _clean_unit(c)
    return None


def _format_person_row_text(cols: List[str], current_unit: str) -> str:
    first_cell = cols[0]
    cleaned = first_cell.strip("():. ")
    code = f"({cleaned})"
    name = cols[1] if len(cols) > 1 else ""
    pos = cols[2] if len(cols) > 2 else ""
    text = f"{code} {name}"
    if pos:
        text += f", {pos}"
    if _should_append_unit(current_unit, pos):
        text += f", {current_unit}"
    return text


def _process_table_row(cols: List[str], current_unit: str) -> Tuple[Optional[str], str]:
    if _is_table_header_row(cols):
        return None, current_unit

    first_cell = cols[0]
    is_paren_digit = first_cell.startswith("(") and first_cell.rstrip("):.-").lstrip("(").isdigit()
    combined = " ".join(cols).lower()

    if any(k in combined for k in UNIT_KEYWORDS) and not is_paren_digit:
        found_unit = _find_unit_in_row(cols)
        return None, found_unit if found_unit else current_unit

    has_honorific = len(cols) > 1 and any(h in cols[1].lower() for h in HONORIFICS)
    is_person = is_paren_digit or (first_cell.isdigit() and has_honorific)
    if is_person:
        return _format_person_row_text(cols, current_unit), current_unit

    return None, current_unit


def _extract_items_from_table(
    table_obj: dict, current_unit: str = ""
) -> Tuple[List[str], str]:
    """
    Trích xuất danh sách dòng cá nhân từ đối tượng table trong OCR data mà không dùng regex.
    Theo dõi current_unit (Đoàn ĐBQH / Tỉnh / Đơn vị) qua các hàng để bổ sung ngữ cảnh cơ quan công tác nếu cần.
    """
    cells = table_obj.get("cells", [])
    items: List[str] = []
    if not cells:
        md = table_obj.get("representations", {}).get("markdown", "")
        for line in md.splitlines():
            s = line.strip()
            if not s.startswith("|") or "---" in s:
                continue
            cols = [c.strip() for c in s.split("|")[1:-1]]
            item, current_unit = _process_table_row(cols, current_unit)
            if item:
                items.append(item)
        return items, current_unit

    rows: Dict[int, List[Dict]] = {}
    for c in cells:
        rows.setdefault(c.get("row_index", 0), []).append(c)

    for r_idx in sorted(rows.keys()):
        r_cells = sorted(rows[r_idx], key=lambda x: x.get("column_index", 0))
        texts = [c.get("text", "").strip() for c in r_cells]
        item, current_unit = _process_table_row(texts, current_unit)
        if item:
            items.append(item)

    return items, current_unit


def _is_group_stop_node(next_child: Dict) -> bool:
    next_nt = next_child.get("node_type", "")
    next_text = _get_node_text(next_child).strip()
    next_heading = _get_heading_text(next_child)
    if next_nt == "section" and next_heading and _is_group_title(next_heading) and not _is_appendix_header(next_heading):
        return True
    return bool(next_nt == "paragraph" and next_text and _is_group_title(next_text) and not _is_appendix_header(next_text))


def _collect_paragraph_group_items(
    children: List[Dict],
    start_idx: int,
    is_coll: bool,
    tables: Optional[Dict],
    current_unit: str,
) -> Tuple[List[str], str, int]:
    item_texts: List[str] = []
    j = start_idx
    while j < len(children):
        next_child = children[j]
        next_text = _get_node_text(next_child).strip()
        next_heading = _get_heading_text(next_child)
        if _is_appendix_header(next_text) or _is_appendix_header(next_heading):
            j += 1
            continue
        if _is_group_stop_node(next_child):
            break
        current_unit = _collect_items_from_child_element(
            next_child, is_coll, tables, current_unit, item_texts
        )
        j += 1
    return item_texts, current_unit, j


def _build_raw_chunk(group_index: int, title: str, item_texts: List[str]) -> GroupChunk:
    return GroupChunk(
        group_index=group_index,
        title=title,
        person_count_declared=_parse_count_from_title(title),
        reward_type="",
        accomplishment=_extract_accomplishment(title),
        item_texts=item_texts,
    )


def _try_handle_section_group(
    child: Dict,
    sec_is_coll: bool,
    tables: Optional[Dict],
    current_unit: str,
    group_counter: int,
) -> Tuple[Optional[GroupChunk], str, int]:
    heading = _get_heading_text(child)
    if child.get("node_type") == "section" and heading and _is_group_title(heading) and not _is_appendix_header(heading):
        is_coll = sec_is_coll or (TAP_THE_LOWER in heading.lower())
        item_texts, new_unit = _collect_all_items_from_children(
            child.get("children", []), is_coll, tables, current_unit
        )
        return _build_raw_chunk(group_counter + 1, heading, item_texts), new_unit, group_counter + 1
    return None, current_unit, group_counter


def _collect_raw_group_chunks(
    section: Dict, tables: Optional[Dict] = None
) -> List[GroupChunk]:
    """
    Từ một section Cá nhân (ví dụ: 'II. Cá nhân:'), thu thập danh sách GroupChunk thô (chưa trích xuất reward_type).
    """
    chunks: List[GroupChunk] = []
    group_counter = 0
    current_unit = ""
    children = section.get("children", [])
    heading_sec = _get_heading_text(section)
    sec_is_coll = _is_collective_section(heading_sec)

    if heading_sec and _is_group_title(heading_sec) and not _is_appendix_header(heading_sec):
        is_coll = sec_is_coll or (TAP_THE_LOWER in heading_sec.lower())
        item_texts, _ = _collect_all_items_from_children(section.get("children", []), is_coll, tables)
        return [_build_raw_chunk(1, heading_sec, item_texts)]

    i = 0
    while i < len(children):
        child = children[i]
        heading = _get_heading_text(child)
        text = _get_node_text(child)

        if _is_appendix_header(text) or _is_appendix_header(heading):
            i += 1
            continue

        sec_chunk, current_unit, group_counter = _try_handle_section_group(
            child, sec_is_coll, tables, current_unit, group_counter
        )
        if sec_chunk:
            chunks.append(sec_chunk)
            i += 1
            continue

        p_chunk, current_unit, i = _try_handle_paragraph_group(
            child, children, i, sec_is_coll, tables, current_unit, group_counter
        )
        if p_chunk:
            group_counter += 1
            chunks.append(p_chunk)
            continue

        i += 1

    chunks = _filter_and_reindex_valid_chunks(chunks)
    if not chunks:
        fb_chunk = _handle_empty_chunks_table_fallback(children, section, tables, current_unit)
        if fb_chunk:
            chunks.append(fb_chunk)
    return chunks


def _try_handle_paragraph_group(
    child: Dict,
    children: List[Dict],
    idx: int,
    sec_is_coll: bool,
    tables: Optional[Dict],
    current_unit: str,
    group_counter: int,
) -> Tuple[Optional[GroupChunk], str, int]:
    text = _get_node_text(child)
    if not (child.get("node_type") == "paragraph" and text and _is_group_title(text) and not _is_appendix_header(text)):
        return None, current_unit, idx + 1
    is_coll = sec_is_coll or (TAP_THE_LOWER in text.lower())
    item_texts, current_unit, next_idx = _collect_paragraph_group_items(
        children, idx + 1, is_coll, tables, current_unit
    )
    return _build_raw_chunk(group_counter + 1, text, item_texts), current_unit, next_idx


def _handle_empty_chunks_table_fallback(
    children: List[Dict],
    section: Dict,
    tables: Optional[Dict],
    current_unit: str,
) -> Optional[GroupChunk]:
    if not tables or not any(c.get("node_type") == "table_ref" for c in children):
        return None
    sec_heading = _get_heading_text(section)
    title_text = ""
    for c in children:
        c_text = _get_node_text(c).strip()
        if c_text and not _is_group_title(c_text):
            title_text = c_text
            break
    if not title_text:
        title_text = sec_heading or DANH_SACH_KHEN_THUONG

    item_texts, _ = _collect_all_items_from_children(children, False, tables, current_unit)
    if not item_texts:
        return None
    return GroupChunk(
        group_index=1,
        title=title_text,
        person_count_declared=_parse_count_from_title(title_text) or len(item_texts),
        reward_type="",
        accomplishment=_extract_accomplishment(title_text),
        item_texts=item_texts,
    )

def build_group_chunks_from_individual_section(
    section: Dict, tables: Optional[Dict] = None, llm_service: Optional[LLMService] = None
) -> List[GroupChunk]:
    """
    Từ một section Cá nhân (ví dụ: 'II. Cá nhân:'), xây dựng danh sách GroupChunk (đồng bộ).
    """
    chunks = _collect_raw_group_chunks(section, tables=tables)
    for chunk in chunks:
        header_info = _extract_group_header_info(chunk.title, llm_service=llm_service)
        if header_info.get("reward_type"):
            chunk.reward_type = header_info["reward_type"]
        if header_info.get("person_count_declared"):
            chunk.person_count_declared = header_info["person_count_declared"]
        if header_info.get("accomplishment"):
            chunk.accomplishment = header_info["accomplishment"]
    return chunks


async def abuild_group_chunks_from_individual_section(
    section: Dict,
    tables: Optional[Dict] = None,
    llm_service: Optional[LLMService] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[GroupChunk]:
    """
    Từ một section Cá nhân (ví dụ: 'II. Cá nhân:'), xây dựng danh sách GroupChunk (bất đồng bộ).
    """
    chunks = _collect_raw_group_chunks(section, tables=tables)
    if chunks:
        header_infos = await asyncio.gather(
            *[_aextract_group_header_info(c.title, llm_service=llm_service, client=client) for c in chunks]
        )
        for c, info in zip(chunks, header_infos):
            if info.get("reward_type"):
                c.reward_type = info["reward_type"]
            if info.get("person_count_declared"):
                c.person_count_declared = info["person_count_declared"]
            if info.get("accomplishment"):
                c.accomplishment = info["accomplishment"]
    return chunks


def _extract_items_from_all_tables(tables: Dict) -> List[str]:
    item_texts: List[str] = []
    current_unit = ""
    for tid in sorted(tables.keys()):
        t_items, current_unit = _extract_items_from_table(tables[tid], current_unit)
        item_texts.extend(t_items)
    return item_texts


def _find_title_in_snippet(content_snippet: str, default_title: str = "Danh sách cá nhân khen thưởng") -> str:
    for line in content_snippet.split("\n"):
        if _is_group_title(line):
            return line.strip()
    return default_title


def _handle_section_direct_items(
    section: Dict,
    tables: Optional[Dict],
    all_chunks: List[GroupChunk],
    llm_service: Optional[LLMService] = None,
) -> int:
    direct_items = _collect_direct_items_from_section(section, tables=tables)
    if not direct_items:
        return all_chunks[-1].group_index if all_chunks else 0
    if all_chunks and len(all_chunks[-1].item_texts) < all_chunks[-1].person_count_declared:
        all_chunks[-1].item_texts.extend(direct_items)
        return all_chunks[-1].group_index

    sec_heading = _get_heading_text(section) or DANH_SACH_KHEN_THUONG
    chunk = GroupChunk(
        group_index=len(all_chunks) + 1,
        title=sec_heading,
        person_count_declared=_parse_count_from_title(sec_heading) or len(direct_items),
        reward_type=_extract_reward_type(sec_heading, llm_service=llm_service),
        accomplishment=_extract_accomplishment(sec_heading),
        item_texts=direct_items,
    )
    all_chunks.append(chunk)
    return chunk.group_index


def _build_tables_fallback_chunk(
    tables: Dict,
    ocr_data: Dict,
    llm_service: Optional[LLMService] = None,
) -> Optional[GroupChunk]:
    logger.info("[OCR_PARSER] Cây OCR không có section chứa cá nhân, trích xuất trực tiếp từ tables.")
    item_texts = _extract_items_from_all_tables(tables)
    if not item_texts:
        return None
    content_snippet = ocr_data.get("content", "")
    title = _find_title_in_snippet(content_snippet)
    return GroupChunk(
        group_index=1,
        title=title,
        person_count_declared=_parse_count_from_title(title) or len(item_texts),
        reward_type=_extract_reward_type(title, llm_service=llm_service),
        accomplishment=_extract_accomplishment(title),
        item_texts=item_texts,
    )


async def _ahandle_section_direct_items(
    section: Dict,
    tables: Optional[Dict],
    all_chunks: List[GroupChunk],
    llm_service: Optional[LLMService] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> int:
    direct_items = _collect_direct_items_from_section(section, tables=tables)
    if not direct_items:
        return all_chunks[-1].group_index if all_chunks else 0
    if all_chunks and len(all_chunks[-1].item_texts) < all_chunks[-1].person_count_declared:
        all_chunks[-1].item_texts.extend(direct_items)
        return all_chunks[-1].group_index

    sec_heading = _get_heading_text(section) or DANH_SACH_KHEN_THUONG
    header_info = await _aextract_group_header_info(sec_heading, llm_service=llm_service, client=client)
    chunk = GroupChunk(
        group_index=len(all_chunks) + 1,
        title=sec_heading,
        person_count_declared=header_info.get("person_count_declared") or len(direct_items),
        reward_type=header_info.get("reward_type", ""),
        accomplishment=header_info.get("accomplishment", ""),
        item_texts=direct_items,
    )
    all_chunks.append(chunk)
    return chunk.group_index


async def _abuild_tables_fallback_chunk(
    tables: Dict,
    ocr_data: Dict,
    llm_service: Optional[LLMService] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[GroupChunk]:
    logger.info("[OCR_PARSER] Cây OCR không có section chứa cá nhân, trích xuất trực tiếp từ tables.")
    item_texts = _extract_items_from_all_tables(tables)
    if not item_texts:
        return None
    content_snippet = ocr_data.get("content", "")
    title = _find_title_in_snippet(content_snippet)
    header_info = await _aextract_group_header_info(title, llm_service=llm_service, client=client)
    return GroupChunk(
        group_index=1,
        title=title,
        person_count_declared=header_info.get("person_count_declared") or len(item_texts),
        reward_type=header_info.get("reward_type", ""),
        accomplishment=header_info.get("accomplishment", ""),
        item_texts=item_texts,
    )


def _filter_and_reindex_valid_chunks(all_chunks: List[GroupChunk]) -> List[GroupChunk]:
    valid_chunks = [c for c in all_chunks if len(c.item_texts) > 0]
    if valid_chunks and len(valid_chunks) < len(all_chunks):
        for idx, c in enumerate(valid_chunks, start=1):
            c.group_index = idx
        return valid_chunks
    return all_chunks


def _parse_chunks_from_list(
    ocr_list: List[Any], llm_service: Optional[LLMService]
) -> Optional[List[GroupChunk]]:
    for single_ocr in ocr_list:
        if isinstance(single_ocr, dict):
            chunks = parse_individual_group_chunks(single_ocr, llm_service=llm_service)
            if chunks:
                return chunks
    return None


async def _aparse_chunks_from_list(
    ocr_list: List[Any],
    llm_service: Optional[LLMService],
    client: Optional[httpx.AsyncClient],
) -> Optional[List[GroupChunk]]:
    for single_ocr in ocr_list:
        if isinstance(single_ocr, dict):
            chunks = await aparse_individual_group_chunks(
                single_ocr, llm_service=llm_service, client=client
            )
            if chunks:
                return chunks
    return None


def _get_ocr_sections_and_tables(
    ocr_data: Dict,
) -> Optional[Tuple[List[Dict], Dict]]:
    tree = ocr_data.get("tree", {})
    root_children: List[Dict] = tree.get("children", [])
    tables = ocr_data.get("tables", {})

    if not root_children and not tables:
        logger.warning(WARN_NO_TREE_OR_TABLE)
        return None

    danh_sach_nodes = collect_danh_sach_nodes(root_children) if root_children else []
    individual_sections = extract_individual_sections(danh_sach_nodes) if danh_sach_nodes else []
    return individual_sections, tables


def _process_sections_to_chunks(
    individual_sections: List[Dict], tables: Dict, llm_service: Optional[LLMService]
) -> List[GroupChunk]:
    all_chunks: List[GroupChunk] = []
    group_offset = 0
    for section in individual_sections:
        chunks = build_group_chunks_from_individual_section(
            section, tables=tables, llm_service=llm_service
        )
        if chunks:
            for chunk in chunks:
                chunk.group_index += group_offset
            all_chunks.extend(chunks)
            group_offset = all_chunks[-1].group_index
        else:
            group_offset = _handle_section_direct_items(section, tables, all_chunks, llm_service)
    return all_chunks


async def _aprocess_sections_to_chunks(
    individual_sections: List[Dict],
    tables: Dict,
    llm_service: Optional[LLMService],
    client: Optional[httpx.AsyncClient],
) -> List[GroupChunk]:
    all_chunks: List[GroupChunk] = []
    group_offset = 0
    for section in individual_sections:
        chunks = await abuild_group_chunks_from_individual_section(
            section, tables=tables, llm_service=llm_service, client=client
        )
        if chunks:
            for chunk in chunks:
                chunk.group_index += group_offset
            all_chunks.extend(chunks)
            group_offset = all_chunks[-1].group_index
        else:
            group_offset = await _ahandle_section_direct_items(
                section, tables, all_chunks, llm_service, client
            )
    return all_chunks


def parse_individual_group_chunks(
    ocr_data: Any, llm_service: Optional[LLMService] = None
) -> Optional[List[GroupChunk]]:
    """
    Phân tích OCR data, trả về danh sách GroupChunk cho phần cá nhân (đồng bộ).
    Hỗ trợ cả dict (1 file) hoặc list[dict] (nhiều file tải lên).
    Trả về None nếu không tìm thấy phần DANH SÁCH.
    """
    if not ocr_data:
        return None

    if isinstance(ocr_data, list):
        return _parse_chunks_from_list(ocr_data, llm_service)

    if not isinstance(ocr_data, dict):
        return None

    parsed = _get_ocr_sections_and_tables(ocr_data)
    if parsed is None:
        return None
    individual_sections, tables = parsed

    all_chunks = _process_sections_to_chunks(individual_sections, tables, llm_service)
    all_chunks = _filter_and_reindex_valid_chunks(all_chunks)

    if not all_chunks and tables:
        fb_chunk = _build_tables_fallback_chunk(tables, ocr_data, llm_service)
        if fb_chunk:
            all_chunks.append(fb_chunk)

    return all_chunks if all_chunks else None


async def aparse_individual_group_chunks(
    ocr_data: Any,
    llm_service: Optional[LLMService] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[List[GroupChunk]]:
    """
    Phân tích OCR data, trả về danh sách GroupChunk cho phần cá nhân (bất đồng bộ).
    Hỗ trợ cả dict (1 file) hoặc list[dict] (nhiều file tải lên).
    Trả về None nếu không tìm thấy phần DANH SÁCH.
    """
    if not ocr_data:
        return None

    if isinstance(ocr_data, list):
        return await _aparse_chunks_from_list(ocr_data, llm_service, client)

    if not isinstance(ocr_data, dict):
        return None

    parsed = _get_ocr_sections_and_tables(ocr_data)
    if parsed is None:
        return None
    individual_sections, tables = parsed

    all_chunks = await _aprocess_sections_to_chunks(
        individual_sections, tables, llm_service, client
    )
    all_chunks = _filter_and_reindex_valid_chunks(all_chunks)

    if not all_chunks and tables:
        fb_chunk = await _abuild_tables_fallback_chunk(tables, ocr_data, llm_service, client)
        if fb_chunk:
            all_chunks.append(fb_chunk)

    return all_chunks if all_chunks else None


ATTACHMENT_KEYWORDS = [
    "có danh sách kèm theo",
    "danh sách kèm theo",
    "kèm theo danh sách",
    "danh sách đính kèm",
    "ban hành kèm theo",
    "theo danh sách",
    "phụ lục kèm theo",
    "theo phụ lục",
    "kèm theo nghị quyết",
    "kèm theo quyết định",
]

ATTACHMENT_PROMPT = """Bạn là chuyên gia phân tích văn bản hành chính Việt Nam.
Nhiệm vụ: Phân tích nội dung văn bản (đặc biệt là Điều 1 và/hoặc phần đầu danh sách đính kèm) và trích xuất thông tin dưới dạng JSON:
1. has_attachment (boolean): Văn bản có danh sách hoặc phụ lục đính kèm danh sách khen thưởng hay không (true nếu có các cụm từ "có danh sách kèm theo", "theo danh sách kèm theo", "kèm theo nghị quyết", "kèm theo quyết định", hoặc có mục "DANH SÁCH").
2. person_count_declared (integer): Tổng số lượng đối tượng khen thưởng (cộng cả tập thể và cá nhân) được tuyên bố trong Điều 1 hoặc trong tiêu đề danh sách.
   Ví dụ:
   - "cho 09 tập thể và 20 cá nhân" -> 29
   - "cho 02 tập thể và 21 cá nhân" -> 23
   - "cho 17 cá nhân" -> 17
   - "cho các tập thể, cá nhân ... (Có danh sách kèm theo)" mà trong danh sách nêu "cho 09 tập thể và 20 cá nhân" -> 29
   - Nếu không có số lượng cụ thể thì trả về 0.

Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng:
{
  "has_attachment": true,
  "person_count_declared": 29
}"""


def _extract_declared_count_fallback(text: str) -> int:
    cnt = _parse_digits_before_keyword(text, TAP_THE_LOWER) + _parse_digits_before_keyword(text, CA_NHAN_LOWER)
    if cnt == 0:
        cnt = _parse_digits_before_keyword(text, "đối tượng")
        if cnt == 0:
            cnt = _parse_digits_after_keyword(text, "cho")
    return cnt


def _detect_has_attachment_fallback(dieu1_text: str, full_text: str = "") -> Tuple[bool, int]:
    """Phát hiện attachment và đếm số lượng đối tượng dự phòng mà không dùng regex."""
    lower_dieu1 = (dieu1_text or "").lower()
    has_attachment = any(kw in lower_dieu1 for kw in ATTACHMENT_KEYWORDS)

    if not has_attachment and full_text:
        for line in full_text.split("\n"):
            s = line.strip().lstrip("#").strip().upper()
            if s.startswith((DANH_SACH_UPPER, DANH_SACH_ASCII_UPPER)):
                has_attachment = True
                break

    person_count = _extract_declared_count_fallback(dieu1_text)
    if person_count == 0 and full_text:
        person_count = _extract_declared_count_fallback(full_text[:3000])

    return has_attachment, person_count


async def adetect_has_attachment(
    dieu1_text: str,
    full_text: str = "",
    llm_service: Optional[LLMService] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[bool, int]:
    """
    Phát hiện xem văn bản có danh sách đính kèm và trích xuất số lượng tuyên bố bằng LLM (bất đồng bộ).
    """
    has_att_fast, count_fast = _detect_has_attachment_fallback(dieu1_text, full_text)
    service = llm_service or LLMService()
    context = (dieu1_text + "\n" + full_text[:2500]).strip()
    if not context:
        return False, 0
    try:
        data = await service.ask_json_async(ATTACHMENT_PROMPT, context, client=client)
        if isinstance(data, dict):
            has_att = bool(data.get("has_attachment", has_att_fast))
            count = int(data.get("person_count_declared") or 0)
            return has_att, (count if count > 0 else count_fast)
    except Exception as e:
        logger.warning(f"[OCR_PARSER] Lỗi khi nhận diện attachment qua LLM: {e}")
    return has_att_fast, count_fast


def detect_has_attachment(
    dieu1_text: str,
    full_text: str = "",
    llm_service: Optional[LLMService] = None,
) -> Tuple[bool, int]:
    """
    Phát hiện xem văn bản có danh sách đính kèm và trích xuất số lượng cá nhân (đồng bộ).
    """
    has_att_fast, count_fast = _detect_has_attachment_fallback(dieu1_text, full_text)
    if llm_service is not None:
        context = (dieu1_text + "\n" + full_text[:2500]).strip()
        if context:
            try:
                data = llm_service.ask_json(ATTACHMENT_PROMPT, context)
                if isinstance(data, dict):
                    has_att = bool(data.get("has_attachment", has_att_fast))
                    count = int(data.get("person_count_declared") or 0)
                    return has_att, (count if count > 0 else count_fast)
            except Exception as e:
                logger.warning(f"[OCR_PARSER] Lỗi khi nhận diện attachment qua LLM sync: {e}")
    return has_att_fast, count_fast
