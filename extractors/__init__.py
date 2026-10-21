from typing import Dict, Type
from core.config import DocType
from extractors.base import BaseExtractor
from extractors.khen_thuong.extractor import KhenThuongExtractor
from extractors.ky_niem_chuong.extractor import KyNiemChuongExtractor
from extractors.luong.extractor import LuongExtractor
from extractors.phu_cap.extractor import PhuCapExtractor
from extractors.qtct.extractor import QTCTExtractor
from extractors.quy_hoach.extractor import QuyHoachExtractor
from extractors.thi_dua.extractor import ThiDuaExtractor

EXTRACTOR_REGISTRY: Dict[DocType, Type[BaseExtractor]] = {
    DocType.QTCT: QTCTExtractor,
    DocType.LUONG: LuongExtractor,
    DocType.PHU_CAP: PhuCapExtractor,
    DocType.THI_DUA: ThiDuaExtractor,
    DocType.KHEN_THUONG: KhenThuongExtractor,
    DocType.KY_NIEM_CHUONG: KyNiemChuongExtractor,
    DocType.QUY_HOACH: QuyHoachExtractor,
}


from core.exceptions import ExtractorNotFoundError


def get_extractor(doc_type: DocType) -> BaseExtractor:
    """
    Factory function lấy extractor tương ứng với doc_type.
    """
    extractor_cls = EXTRACTOR_REGISTRY.get(doc_type)
    if not extractor_cls:
        raise ExtractorNotFoundError(doc_type.value if hasattr(doc_type, "value") else str(doc_type))
    return extractor_cls()


__all__ = [
    "BaseExtractor",
    "QTCTExtractor",
    "LuongExtractor",
    "PhuCapExtractor",
    "ThiDuaExtractor",
    "KhenThuongExtractor",
    "KyNiemChuongExtractor",
    "QuyHoachExtractor",
    "get_extractor",
    "EXTRACTOR_REGISTRY",
]
