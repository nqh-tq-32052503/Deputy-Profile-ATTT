import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

import httpx

from core.config import (
    LLM_API_BASE_URL,
    LLM_API_KEY,
    LLM_MAX_TOKENS,
    LLM_MODEL_NAME,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
)
from core.exceptions import (
    LLMConnectionError,
    LLMHTTPError,
    LLMResponseParseError,
    LLMServiceException,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)


def clean_text(text: Optional[Any]) -> Optional[str]:
    """Loại bỏ quotes, markdown bold/italic và khoảng trắng thừa mà không dùng regex."""
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    cleaned = text.strip().strip("*_`\"'“”‘’").strip()
    if cleaned.lower() in ("null", "none", "n/a", "không", "không có", "chưa rõ", ""):
        return None
    return cleaned


POSITION_TITLES = [
    # Thường trực / Cấp phó dài
    "Phó Chủ tịch Thường trực",
    "Phó Chủ nhiệm Thường trực",
    "Phó Trưởng ban Thường trực",
    "Phó Bí thư Thường trực",
    "Thứ trưởng Thường trực",
    "Phó Tổng Kiểm toán Thường trực",
    "Phó Tổng Tham mưu trưởng",
    "Phó Tổng Giám đốc",
    "Phó Tổng cục trưởng",
    "Tổng Tham mưu trưởng",
    "Tổng Kiểm toán nhà nước",
    "Tổng Kiểm toán",
    "Tổng Giám đốc",
    "Tổng cục trưởng",
    # Phó cấp ban, sở, viện, vụ, cục, đoàn, hội đồng
    "Phó Chủ tịch",
    "Phó Chủ nhiệm",
    "Phó Trưởng ban",
    "Phó Trưởng Đoàn",
    "Phó Vụ trưởng",
    "Phó Cục trưởng",
    "Phó Viện trưởng",
    "Phó Giám đốc",
    "Phó Hiệu trưởng",
    "Phó Trưởng phòng",
    "Phó Chánh Văn phòng",
    "Phó Chánh Thanh tra",
    "Phó Chánh án",
    "Phó Tư lệnh",
    "Phó Chính ủy",
    "Phó Bí thư",
    "Thứ trưởng",
    "Phó Thủ tướng",
    # Cấp trưởng
    "Thủ tướng",
    "Bộ trưởng",
    "Chủ tịch",
    "Chủ nhiệm",
    "Trưởng ban",
    "Trưởng Đoàn",
    "Vụ trưởng",
    "Cục trưởng",
    "Viện trưởng",
    "Giám đốc",
    "Hiệu trưởng",
    "Trưởng phòng",
    "Chánh Văn phòng",
    "Chánh Thanh tra",
    "Chánh án",
    "Tư lệnh",
    "Chính ủy",
    "Bí thư",
    "Ủy viên Thường trực",
    "Ủy viên Chuyên trách",
    # Vị trí chuyên môn / nghiệp vụ / giúp việc
    "Chuyên viên cao cấp",
    "Chuyên viên chính",
    "Chuyên viên",
    "Thanh tra viên cao cấp",
    "Thanh tra viên chính",
    "Thanh tra viên",
    "Kiểm toán viên cao cấp",
    "Kiểm toán viên chính",
    "Kiểm toán viên",
    "Nghiên cứu viên cao cấp",
    "Nghiên cứu viên chính",
    "Nghiên cứu viên",
    "Giảng viên cao cấp",
    "Giảng viên chính",
    "Giảng viên",
    "Kế toán trưởng",
    "Kế toán",
    "Biên tập viên chính",
    "Biên tập viên",
    "Phóng viên",
    "Thư ký",
    "Trợ lý",
]


FALLBACK_POSITION_PROMPT = """Bạn là chuyên gia trích xuất chức vụ văn bản hành chính Việt Nam.
Nhiệm vụ: Chuẩn hóa chức vụ (position_name) và cơ quan công tác (work_organization_name) từ văn bản mô tả chức vụ của một cá nhân.

QUY TẮC BẮT BUỘC:
1. KHÔNG đưa các chức danh Đảng vào position_name hoặc work_organization_name khi cá nhân có chức vụ chính quyền/Quốc hội/chuyên môn khác.
   - Dấu hiệu nhận biết các chức vụ Đảng là có từ khóa "đảng" ở trong tên chức vụ (hoặc "Bộ Chính trị", "Ban Bí thư", "Trung ương Đảng", "BCH Trung ương Đảng", "Đảng viên"...). BỎ QUA hoàn toàn các chức danh này nếu có chức vụ chính quyền/Quốc hội đi kèm.
   - Bỏ qua các chức vụ kiêm nhiệm (ví dụ: "Ủy viên Ủy ban Thường vụ Quốc hội", "Đại biểu Quốc hội khóa...").
   - Lựa chọn chức vụ chính quyền / Quốc hội / chuyên môn cao nhất.
   - Trường hợp cá nhân chỉ có duy nhất 1 chức vụ thuộc tổ chức Đảng (ví dụ: Bí thư Thành ủy, Phó Bí thư Tỉnh ủy...) mà không có chức vụ chính quyền nào khác thì vẫn giữ chức vụ đó.
2. position_name: CHỈ là tên vị trí, chức danh hoặc vai trò (ví dụ: Chủ tịch, Phó Chủ tịch, Chủ nhiệm, Phó Chủ nhiệm, Vụ trưởng, Phó Vụ trưởng, Thống đốc, Trưởng ban, Phó Trưởng ban, Trưởng phòng, Phó Trưởng phòng, Chuyên viên, Bộ trưởng, Thứ trưởng, Bí thư, Phó Bí thư, Tổng Tham mưu trưởng, Tư lệnh, Phó Tư lệnh, Chỉ huy trưởng, Đặc phái viên, Tổng Biên tập, Trưởng đoàn, Thuyền trưởng, Bếp trưởng...). TUYỆT ĐỐI KHÔNG chứa tên cơ quan, đơn vị phía sau (ví dụ: "Phó Chủ tịch" chứ KHÔNG PHẢI "Phó Chủ tịch Quốc hội"), không chứa dấu phẩy nối nhiều chức vụ.
3. work_organization_name: Tên cơ quan, đơn vị, tổ chức công tác đi liền phía sau chức danh. Nếu trong cụm từ không có tên cơ quan thì trả về null.

Ví dụ:
- "(3) Ông Nguyễn Đức Hải, Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội." -> position_name: "Phó Chủ tịch", work_organization_name: "Quốc hội"
- "Ủy viên Ban Chấp hành Trung ương Đảng, Phó Chủ tịch Quốc hội" -> position_name: "Phó Chủ tịch", work_organization_name: "Quốc hội"
- "Ủy viên Bộ Chính trị, Chủ tịch Quốc hội" -> position_name: "Chủ tịch", work_organization_name: "Quốc hội"
- "Ủy viên Trung ương Đảng, Thống đốc Ngân hàng Nhà nước Việt Nam" -> position_name: "Thống đốc", work_organization_name: "Ngân hàng Nhà nước Việt Nam"
- "Phó Bí thư Thành ủy, Chủ tịch Hội đồng nhân dân thành phố Hà Nội" -> position_name: "Chủ tịch", work_organization_name: "Hội đồng nhân dân thành phố Hà Nội"
- "Bí thư Thành ủy Thành phố Hồ Chí Minh" -> position_name: "Bí thư", work_organization_name: "Thành ủy Thành phố Hồ Chí Minh"
- "Chủ tịch Hội đồng nhân dân thành phố Hà Nội, Phó Trưởng Đoàn đại biểu Quốc hội thành phố Hà Nội" -> position_name: "Chủ tịch", work_organization_name: "Hội đồng nhân dân thành phố Hà Nội"
- "Phó Chủ nhiệm Ủy ban Văn hóa, Giáo dục" -> position_name: "Phó Chủ nhiệm", work_organization_name: "Ủy ban Văn hóa, Giáo dục"
- "Phó Tư lệnh Bộ Tư lệnh Quân khu 7, đại biểu Quốc hội khóa XV" -> position_name: "Phó Tư lệnh", work_organization_name: "Bộ Tư lệnh Quân khu 7"
- "Chỉ huy trưởng Bộ Chỉ huy Quân sự tỉnh Nghệ An" -> position_name: "Chỉ huy trưởng", work_organization_name: "Bộ Chỉ huy Quân sự tỉnh Nghệ An"
- "Tổng Biên tập Báo Nhân Dân" -> position_name: "Tổng Biên tập", work_organization_name: "Báo Nhân Dân"
- "Đặc phái viên Ban Chỉ đạo Cải cách tư pháp Trung ương" -> position_name: "Đặc phái viên", work_organization_name: "Ban Chỉ đạo Cải cách tư pháp Trung ương"
- "Thuyền trưởng" -> position_name: "Thuyền trưởng", work_organization_name: null
- "Vụ trưởng, Thư ký Chủ tịch Quốc hội" -> position_name: "Vụ trưởng", work_organization_name: null

Chỉ trả về duy nhất chuỗi JSON hợp lệ theo định dạng:
{
  "position_name": "...",
  "work_organization_name": "..."
}"""


def parse_json_from_llm(raw_text: str) -> Any:
    """Parse JSON từ chuỗi kết quả trả về của LLM mà không dùng regex."""
    text = raw_text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    else:
        brace_idx = text.find("{")
        bracket_idx = text.find("[")
        if brace_idx != -1 and (bracket_idx == -1 or brace_idx < bracket_idx):
            end_idx = text.rfind("}")
            if end_idx != -1:
                text = text[brace_idx : end_idx + 1]
        elif bracket_idx != -1:
            end_idx = text.rfind("]")
            if end_idx != -1:
                text = text[bracket_idx : end_idx + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        err_msg = f"Không thể phân tích cú pháp JSON từ phản hồi của LLM: {e}"
        logger.exception(
            f"[LLM_PARSE_ERROR] {err_msg}\n"
            f"--- ĐOẠN VĂN BẢN TRÍCH XUẤT TỪ LLM (tối đa 500 ký tự) ---\n"
            f"{text[:500]}\n"
            f"----------------------------------------------------------"
        )
        raise LLMResponseParseError(err_msg, raw_text=text) from e


class LLMService:
    """
    Dịch vụ gửi request tới LLM (OpenAI compatible endpoint).
    """

    def __init__(
        self,
        api_base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
    ):
        self.api_base_url = (api_base_url or LLM_API_BASE_URL).rstrip("/")
        self.model_name = model_name or LLM_MODEL_NAME
        self.api_key = api_key or LLM_API_KEY
        self.temperature = LLM_TEMPERATURE if temperature is None else temperature
        self.max_tokens = max_tokens or LLM_MAX_TOKENS
        self.timeout = timeout or LLM_TIMEOUT_SECONDS

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def ask_async(
        self,
        system_prompt: str,
        content: str,
        client: Optional[httpx.AsyncClient] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Gửi prompt và nội dung văn bản tới LLM qua API chat completions.
        """
        url = f"{self.api_base_url}/chat/completions"
        headers = self._get_headers()
        temp = self.temperature if temperature is None else temperature
        tokens = max_tokens or self.max_tokens

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": f"Nội dung văn bản:\n{content}",
                },
            ],
            "temperature": temp,
            "max_tokens": tokens,
        }

        logger.info(
            f"Bắt đầu gọi LLM [{self.api_base_url}] - model: '{self.model_name}' "
            f"(temp: {temp}, max_tokens: {tokens}, prompt: {len(system_prompt)} chars, content: {len(content)} chars, timeout: {self.timeout}s)..."
        )
        start_time = time.time()

        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=float(self.timeout))
            should_close = True

        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            response_content = data["choices"][0]["message"]["content"].strip()
            elapsed = time.time() - start_time
            logger.info(
                f"LLM [{self.model_name}] phản hồi thành công trong {elapsed:.2f}s "
                f"(output: {len(response_content)} chars)."
            )
            return response_content

        except httpx.TimeoutException as e:
            elapsed = time.time() - start_time
            err_msg = f"Quá thời gian chờ phản hồi ({self.timeout}s) từ LLM Service (sau {elapsed:.2f}s)"
            logger.exception(
                f"[LLM_TIMEOUT_ERROR] {err_msg} tại {self.api_base_url} cho model '{self.model_name}'"
            )
            raise LLMTimeoutError(
                err_msg,
                details={"model": self.model_name, "timeout": self.timeout, "elapsed": elapsed},
            ) from e

        except httpx.ConnectError as e:
            err_msg = f"Không thể kết nối đến LLM Service tại {self.api_base_url}: {e}"
            logger.exception(f"[LLM_CONNECTION_ERROR] {err_msg}")
            raise LLMConnectionError(
                err_msg,
                details={"api_base_url": self.api_base_url, "model": self.model_name, "error": str(e)},
            ) from e

        except httpx.HTTPStatusError as e:
            elapsed = time.time() - start_time
            response_text = e.response.text[:500] if e.response else ""
            err_msg = f"LLM Service trả về mã lỗi HTTP {e.response.status_code}: {response_text}"
            logger.exception(f"[LLM_HTTP_ERROR] {err_msg}")
            raise LLMHTTPError(
                err_msg,
                http_status=e.response.status_code,
                details={"model": self.model_name, "status_code": e.response.status_code, "response": response_text},
            ) from e

        except httpx.RequestError as e:
            err_msg = f"Lỗi giao tiếp với LLM Service: {e}"
            logger.exception(f"[LLM_SERVICE_ERROR] {err_msg}")
            raise LLMServiceException(
                err_msg,
                details={"model": self.model_name, "error": str(e)},
            ) from e

        finally:
            if should_close:
                await client.aclose()

    async def ask_json_async(
        self,
        system_prompt: str,
        content: str,
        client: Optional[httpx.AsyncClient] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        """
        Gửi prompt yêu cầu trả về JSON và parse cấu trúc JSON kết quả.
        """
        raw_text = await self.ask_async(
            system_prompt,
            content,
            client=client,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return parse_json_from_llm(raw_text)

    def ask(
        self,
        system_prompt: str,
        content: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Gửi prompt và nội dung văn bản tới LLM qua API chat completions (đồng bộ).
        Thực hiện HTTP request đồng bộ trực tiếp qua httpx.Client, tương thích an toàn với uvloop và đa luồng.
        """
        url = f"{self.api_base_url}/chat/completions"
        headers = self._get_headers()
        temp = self.temperature if temperature is None else temperature
        tokens = max_tokens or self.max_tokens

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": f"Nội dung văn bản:\n{content}",
                },
            ],
            "temperature": temp,
            "max_tokens": tokens,
        }

        logger.info(
            f"Bắt đầu gọi LLM (sync) [{self.api_base_url}] - model: '{self.model_name}' "
            f"(temp: {temp}, max_tokens: {tokens}, prompt: {len(system_prompt)} chars, content: {len(content)} chars, timeout: {self.timeout}s)..."
        )
        start_time = time.time()

        try:
            with httpx.Client(timeout=float(self.timeout)) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                response_content = data["choices"][0]["message"]["content"].strip()
                elapsed = time.time() - start_time
                logger.info(
                    f"LLM [{self.model_name}] phản hồi thành công trong {elapsed:.2f}s "
                    f"(output: {len(response_content)} chars)."
                )
                return response_content

        except httpx.TimeoutException as e:
            elapsed = time.time() - start_time
            err_msg = f"Quá thời gian chờ phản hồi ({self.timeout}s) từ LLM Service (sau {elapsed:.2f}s)"
            logger.exception(
                f"[LLM_TIMEOUT_ERROR] {err_msg} tại {self.api_base_url} cho model '{self.model_name}'"
            )
            raise LLMTimeoutError(
                err_msg,
                details={"model": self.model_name, "timeout": self.timeout, "elapsed": elapsed},
            ) from e

        except httpx.ConnectError as e:
            err_msg = f"Không thể kết nối đến LLM Service tại {self.api_base_url}: {e}"
            logger.exception(f"[LLM_CONNECTION_ERROR] {err_msg}")
            raise LLMConnectionError(
                err_msg,
                details={"api_base_url": self.api_base_url, "model": self.model_name, "error": str(e)},
            ) from e

        except httpx.HTTPStatusError as e:
            elapsed = time.time() - start_time
            response_text = e.response.text[:500] if e.response else ""
            err_msg = f"LLM Service trả về mã lỗi HTTP {e.response.status_code}: {response_text}"
            logger.exception(f"[LLM_HTTP_ERROR] {err_msg}")
            raise LLMHTTPError(
                err_msg,
                http_status=e.response.status_code,
                details={"model": self.model_name, "status_code": e.response.status_code, "response": response_text},
            ) from e

        except httpx.RequestError as e:
            err_msg = f"Lỗi giao tiếp với LLM Service: {e}"
            logger.exception(f"[LLM_SERVICE_ERROR] {err_msg}")
            raise LLMServiceException(
                err_msg,
                details={"model": self.model_name, "error": str(e)},
            ) from e

    def ask_json(
        self,
        system_prompt: str,
        content: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        """Sync wrapper cho ask_json_async."""
        raw_text = self.ask(system_prompt, content, max_tokens=max_tokens, temperature=temperature)
        return parse_json_from_llm(raw_text)


UY_VIEN_LITERAL = "ủy viên"


def _extract_first_position_chunk(pos_clean: str) -> str:
    """Tách cụm chức vụ đầu tiên, loại bỏ chức vụ thứ hai trở đi (kiêm nhiệm / Đảng)."""
    import re

    first_chunk = pos_clean
    for separator in [" kiêm ", " đồng thời ", ";"]:
        if separator in first_chunk.lower():
            idx = first_chunk.lower().find(separator)
            first_chunk = first_chunk[:idx].strip()

    if "," in first_chunk:
        raw_parts = [p.strip() for p in first_chunk.split(",") if p.strip()]
        if len(raw_parts) > 1:
            reconstructed = [raw_parts[0]]
            position_starters = [
                t.lower() for t in POSITION_TITLES
            ] + [
                "đại biểu quốc hội",
                "đbqh",
                "đại biểu hđnd",
                "đại biểu hội đồng nhân dân",
                "đoàn đại biểu quốc hội",
                "đoàn đbqh",
                UY_VIEN_LITERAL,
                "thành viên",
                "nguyên",
                "quyền",
            ]

            for part in raw_parts[1:]:
                part_lower = part.lower()
                is_subsequent_position = any(
                    part_lower == starter or part_lower.startswith(starter + " ")
                    for starter in position_starters
                )
                if is_subsequent_position:
                    break
                else:
                    reconstructed.append(part)

            first_chunk = ", ".join(reconstructed)

    first_chunk = re.sub(r"^(đồng chí|ông|bà)\s+", "", first_chunk, flags=re.IGNORECASE).strip()
    return first_chunk


def _match_position_from_titles(first_chunk: str) -> tuple[Optional[str], Optional[str]]:
    """Tìm kiếm chức danh trong POSITION_TITLES và tách cơ quan nếu có."""
    import re

    matched_title = None
    remaining_org = None

    for title in POSITION_TITLES:
        if first_chunk.lower() == title.lower():
            matched_title = title
            remaining_org = None
            break
        elif (
            first_chunk.lower().startswith(title.lower() + " ")
            or first_chunk.lower().startswith(title.lower() + ":")
        ):
            matched_title = title
            remaining_org = first_chunk[len(title) :].strip(" :,-")
            break

    if matched_title and remaining_org:
        remaining_org = re.sub(r"^(thuộc|của)\s+", "", remaining_org, flags=re.IGNORECASE).strip()

    return matched_title, remaining_org


def _has_party_indicator(
    pos_clean: Optional[str],
    org_clean: Optional[str],
    raw_text: Optional[str],
) -> bool:
    """Kiểm tra xem có dấu hiệu chức danh/cơ quan thuộc Đảng không."""
    pos_lower = pos_clean.lower() if pos_clean else ""
    org_lower = org_clean.lower() if org_clean else ""
    raw_lower = raw_text.lower() if raw_text else ""

    if "đảng" in pos_lower or "đảng" in org_lower:
        return True
    if raw_text and "đảng" in raw_lower:
        if not pos_clean:
            return True
        party_words = (UY_VIEN_LITERAL, "đảng", "bch", "chính trị")
        if any(w in pos_lower for w in party_words):
            return True
    return False


def _apply_party_llm_result(
    data: Any,
    pos_clean: Optional[str],
    org_clean: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Cập nhật chức vụ và đơn vị công tác từ kết quả LLM lọc chức vụ Đảng."""
    if isinstance(data, dict):
        pos_llm = clean_text(data.get("position_name"))
        org_llm = clean_text(data.get("work_organization_name"))
        if pos_llm:
            pos_clean = pos_llm
        if org_llm and (not org_clean or "đảng" in org_clean.lower()):
            org_clean = org_llm
    return (pos_clean, org_clean)


def _apply_fallback_llm_result(
    data: Any,
    first_chunk: str,
    org_clean: Optional[str],
) -> tuple[str, Optional[str]]:
    """Phân tách chức vụ và đơn vị từ kết quả fallback LLM."""
    if not isinstance(data, dict):
        return (first_chunk, org_clean)
    pos_llm = clean_text(data.get("position_name"))
    org_llm = clean_text(data.get("work_organization_name"))
    pos_clean = pos_llm if pos_llm else first_chunk
    if org_llm and not org_clean:
        org_clean = org_llm
    return (pos_clean, org_clean)


async def arefine_position_and_organization(
    position_name: Optional[str],
    work_organization_name: Optional[str] = None,
    raw_text: Optional[str] = None,
    llm_service: Optional[LLMService] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Chuẩn hóa và bóc tách position_name và work_organization_name bất đồng bộ.
    """
    if not position_name and not raw_text:
        return (None, clean_text(work_organization_name))

    pos_clean = clean_text(position_name)
    org_clean = clean_text(work_organization_name)
    target_llm = llm_service or LLMService()

    if _has_party_indicator(pos_clean, org_clean, raw_text):
        text_to_eval = raw_text if (raw_text and "đảng" in raw_text.lower()) else pos_clean
        try:
            logger.info(
                f"[LLM_POSITION] Phát hiện chức vụ Đảng trong '{text_to_eval}', sử dụng LLM để loại bỏ chức vụ Đảng và trích xuất chức vụ chính quyền..."
            )
            data = await target_llm.ask_json_async(FALLBACK_POSITION_PROMPT, text_to_eval, client=client)
            return _apply_party_llm_result(data, pos_clean, org_clean)
        except Exception as e:
            logger.warning(f"[LLM_POSITION] Lỗi khi gọi LLM cho chức vụ Đảng '{text_to_eval}': {e}")

    if not pos_clean:
        return (None, org_clean)

    first_chunk = _extract_first_position_chunk(pos_clean)
    matched_title, remaining_org = _match_position_from_titles(first_chunk)
    if matched_title:
        pos_clean = matched_title
        if remaining_org and not org_clean:
            org_clean = remaining_org
        return (pos_clean, org_clean)

    try:
        logger.info(
            f"[FALLBACK_LLM] Vị trí '{first_chunk}' chưa có trong POSITION_TITLES, fallback sang LLM để phân tách..."
        )
        data = await target_llm.ask_json_async(FALLBACK_POSITION_PROMPT, first_chunk, client=client)
        return _apply_fallback_llm_result(data, first_chunk, org_clean)
    except Exception as e:
        logger.warning(f"[FALLBACK_LLM] Lỗi khi gọi fallback LLM cho '{first_chunk}': {e}")
        return (first_chunk, org_clean)


def refine_position_and_organization(
    position_name: Optional[str],
    work_organization_name: Optional[str] = None,
    raw_text: Optional[str] = None,
    llm_service: Optional[LLMService] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Phiên bản đồng bộ của arefine_position_and_organization.
    """
    if not position_name and not raw_text:
        return (None, clean_text(work_organization_name))

    pos_clean = clean_text(position_name)
    org_clean = clean_text(work_organization_name)
    target_llm = llm_service or LLMService()

    if _has_party_indicator(pos_clean, org_clean, raw_text):
        text_to_eval = raw_text if (raw_text and "đảng" in raw_text.lower()) else pos_clean
        try:
            logger.info(
                f"[LLM_POSITION] Phát hiện chức vụ Đảng trong '{text_to_eval}', sử dụng LLM để loại bỏ chức vụ Đảng và trích xuất chức vụ chính quyền..."
            )
            data = target_llm.ask_json(FALLBACK_POSITION_PROMPT, text_to_eval)
            return _apply_party_llm_result(data, pos_clean, org_clean)
        except Exception as e:
            logger.warning(f"[LLM_POSITION] Lỗi khi gọi LLM cho chức vụ Đảng '{text_to_eval}': {e}")

    if not pos_clean:
        return (None, org_clean)

    first_chunk = _extract_first_position_chunk(pos_clean)
    matched_title, remaining_org = _match_position_from_titles(first_chunk)
    if matched_title:
        pos_clean = matched_title
        if remaining_org and not org_clean:
            org_clean = remaining_org
        return (pos_clean, org_clean)

    try:
        logger.info(
            f"[FALLBACK_LLM] Vị trí '{first_chunk}' chưa có trong POSITION_TITLES, fallback sang LLM để phân tách..."
        )
        data = target_llm.ask_json(FALLBACK_POSITION_PROMPT, first_chunk)
        return _apply_fallback_llm_result(data, first_chunk, org_clean)
    except Exception as e:
        logger.warning(f"[FALLBACK_LLM] Lỗi khi gọi fallback LLM cho '{first_chunk}': {e}")
        return (first_chunk, org_clean)
