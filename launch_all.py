#!/usr/bin/env python3
"""
DeputyProfiling AI Service - Công cụ gửi hàng loạt tài liệu PDF bất đồng bộ (launch_all.py)

Sử dụng:
    python launch_all.py --input-dir private_documents/qtct/ --output-dir tmp/
    python launch_all.py --input-dir private_documents/luong/ --output-dir tmp/ --doc-type LUONG
    python launch_all.py --input-dir private_documents/khen_thuong/ --output-dir tmp/ --force-reprocess
"""

import argparse
import asyncio
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import unicodedata

import httpx

# Thiết lập logging định dạng chuẩn
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("launch_all")

SUPPORTED_DOC_TYPES = {
    "QTCT": ["qtct", "qua_trinh_cong_tac", "quatrinhcongtac"],
    "LUONG": ["luong", "nang_luong", "nangluong", "salary"],
    "KHEN_THUONG": ["khen_thuong", "khenthuong", "khen"],
    "PHU_CAP": ["phu_cap", "phucap"],
    "THI_DUA": ["thi_dua", "thidua"],
    "KY_NIEM_CHUONG": ["ky_niem_chuong", "kyniemchuong"],
    "QUY_HOACH": ["quy_hoach", "quyhoach"],
}


def infer_doc_type(input_path_str: str) -> Optional[str]:
    """
    Tự động nhận diện doc_type dựa trên tên đường dẫn input.
    """
    normalized_path = input_path_str.lower().replace("-", "_").replace("\\", "/")
    path_parts = [p for p in normalized_path.split("/") if p]

    for doc_type, keywords in SUPPORTED_DOC_TYPES.items():
        for kw in keywords:
            for part in path_parts:
                if kw in part:
                    return doc_type

    return None


def get_safe_filename(file_path: Path) -> str:
    """
    Chuẩn hóa tên file theo chuẩn Unicode NFC để tránh lỗi khi gửi qua HTTP header
    với các ký tự đặc biệt hoặc decomposed Unicode (NFD).
    """
    name = file_path.name
    return unicodedata.normalize("NFC", name)


async def _send_extract_request(
    client: httpx.AsyncClient,
    upload_url: str,
    safe_name: str,
    file_bytes: bytes,
    doc_type: str,
    force_reprocess: bool,
) -> Dict[str, Any]:
    files = {"files": (safe_name, file_bytes, "application/pdf")}
    data = {
        "doc_type": doc_type,
        "force_reprocess": "true" if force_reprocess else "false",
    }
    resp = await client.post(upload_url, data=data, files=files)
    resp.raise_for_status()
    return resp.json()


async def _poll_extraction_result(
    client: httpx.AsyncClient,
    poll_url: str,
    request_id: str,
    tag: str,
    safe_name: str,
    file_path: Path,
    output_dir: Optional[Path],
    start_time: float,
    poll_interval: float,
    wait_limit: float,
) -> Dict[str, Any]:
    while True:
        await asyncio.sleep(poll_interval)
        elapsed = time.time() - start_time

        if elapsed > wait_limit:
            err_msg = f"Quá thời gian chờ ({wait_limit}s) cho tiến trình."
            logger.error(f"{tag}: {err_msg}")
            timeout_data = {
                "request_id": request_id,
                "status": "FAILED",
                "error": {"code": "TIMEOUT", "message": err_msg},
                "source_file": safe_name,
            }
            if output_dir:
                _save_result(output_dir, file_path, timeout_data)
            return {
                "file": safe_name,
                "request_id": request_id,
                "status": "TIMEOUT",
                "error": err_msg,
                "elapsed_seconds": round(elapsed, 2),
            }

        try:
            poll_resp = await client.get(poll_url)
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()
            poll_status = poll_data.get("status")

            if poll_status == "FINISHED":
                logger.info(f"{tag}: Hoàn thành thành công trong {elapsed:.2f}s!")
                _save_result(output_dir, file_path, poll_data)
                return {
                    "file": safe_name,
                    "request_id": request_id,
                    "status": "FINISHED",
                    "elapsed_seconds": round(elapsed, 2),
                }

            if poll_status == "FAILED":
                err = poll_data.get("error", {})
                logger.error(f"{tag}: Tiến trình thất bại sau {elapsed:.2f}s: {err}")
                _save_result(output_dir, file_path, poll_data)
                return {
                    "file": safe_name,
                    "request_id": request_id,
                    "status": "FAILED",
                    "error": err,
                    "elapsed_seconds": round(elapsed, 2),
                }

            # Vẫn đang PROCESSING, tiếp tục vòng lặp
            logger.debug(f"{tag}: Đang xử lý... ({elapsed:.1f}s)")

        except Exception as e:
            logger.warning(f"{tag}: Cảnh báo lỗi polling (sẽ thử lại sau {poll_interval}s): {e}")


async def process_single_file(
    client: httpx.AsyncClient,
    file_path: Path,
    server_url: str,
    doc_type: str,
    force_reprocess: bool,
    poll_interval: float,
    max_wait_seconds: float = 300.0,
    output_dir: Optional[Path] = None,
    file_idx: int = 1,
    total_files: int = 1,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Xử lý gửi 01 file PDF tới AI Service và polling kết quả hoàn tất.
    """
    wait_limit = float(kwargs.get("timeout", max_wait_seconds))
    safe_name = get_safe_filename(file_path)
    tag = f"[{file_idx}/{total_files}] '{safe_name}'"
    start_time = time.time()

    # 1. Đọc nội dung file an toàn
    try:
        file_bytes = file_path.read_bytes()
        file_size_kb = len(file_bytes) / 1024
        logger.info(f"{tag}: Bắt đầu đọc file ({file_size_kb:.1f} KB)...")
    except Exception as e:
        err_msg = f"Không thể đọc file từ đĩa: {e}"
        logger.error(f"{tag}: Lỗi - {err_msg}")
        return {
            "file": safe_name,
            "status": "FAILED",
            "error": err_msg,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

    # 2. Gửi request POST /hsdb/extract
    upload_url = f"{server_url.rstrip('/')}/hsdb/extract"
    try:
        logger.info(f"{tag}: Đang gửi request POST /hsdb/extract (doc_type={doc_type})...")
        init_data = await _send_extract_request(
            client, upload_url, safe_name, file_bytes, doc_type, force_reprocess
        )
        request_id = init_data.get("request_id")
        current_status = init_data.get("status")
        is_cached = init_data.get("is_cached", False)

        if is_cached and current_status == "FINISHED":
            elapsed = time.time() - start_time
            logger.info(f"{tag}: Cache HIT! Nhận kết quả ngay lập tức trong {elapsed:.2f}s (request_id: {request_id})")
            _save_result(output_dir, file_path, init_data)
            return {
                "file": safe_name,
                "request_id": request_id,
                "status": "FINISHED",
                "is_cached": True,
                "elapsed_seconds": round(elapsed, 2),
            }

    except httpx.ConnectError:
        err_msg = f"Không thể kết nối đến server tại {server_url}. Hãy chắc chắn rằng API server đang chạy!"
        logger.error(f"{tag}: Lỗi kết nối - {err_msg}")
        return {
            "file": safe_name,
            "status": "FAILED",
            "error": err_msg,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }
    except Exception as e:
        err_msg = f"Lỗi khi gửi yêu cầu trích xuất: {e}"
        logger.error(f"{tag}: {err_msg}")
        return {
            "file": safe_name,
            "status": "FAILED",
            "error": err_msg,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

    if not request_id:
        err_msg = "Không nhận được request_id từ phản hồi khởi tạo."
        logger.error(f"{tag}: {err_msg}")
        return {
            "file": safe_name,
            "status": "FAILED",
            "error": err_msg,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

    # 3. Vòng lặp Polling GET /hsdb/extract/{request_id}
    poll_url = f"{server_url.rstrip('/')}/hsdb/extract/{request_id}"
    logger.info(f"{tag}: Khởi tạo thành công (request_id: {request_id}). Đang polling kết quả...")
    return await _poll_extraction_result(
        client,
        poll_url,
        request_id,
        tag,
        safe_name,
        file_path,
        output_dir,
        start_time,
        poll_interval,
        wait_limit,
    )


def _save_result(output_dir: Path, original_file_path: Path, data: dict):
    """
    Lưu kết quả JSON ra thư mục output với mã hóa UTF-8 đầy đủ.
    """
    safe_stem = unicodedata.normalize("NFC", original_file_path.stem)
    out_file = output_dir / f"{safe_stem}.json"
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"-> Đã lưu kết quả thành công vào: {out_file}")
    except Exception as e:
        logger.exception(f"Lỗi khi lưu kết quả ra file '{out_file}': {e}")


def _resolve_doc_type(args, input_dir: Path) -> str:
    """Xác định mã doc_type từ tham số hoặc tự động nhận diện từ thư mục."""
    doc_type = args.doc_type
    if not doc_type:
        doc_type = infer_doc_type(str(input_dir))
        if not doc_type:
            logger.error(
                f"Không thể tự động nhận diện doc_type từ thư mục: '{input_dir.name}'. "
                f"Vui lòng chỉ định rõ qua tham số --doc-type (ví dụ: --doc-type QTCT)"
            )
            sys.exit(1)
        logger.info(f"Tự động nhận diện doc_type: '{doc_type}' từ thư mục '{input_dir.name}'")
        return doc_type
    return doc_type.strip().upper()


def _collect_pdf_files(input_dir: Path) -> List[Path]:
    """Quét danh sách file PDF trong input_dir."""
    pdf_files: List[Path] = []
    for item in sorted(input_dir.iterdir()):
        if item.is_file() and item.name.lower().endswith(".pdf") and not item.name.startswith("."):
            pdf_files.append(item)
    return pdf_files


def _log_summary(results: List[Dict[str, Any]], total_files: int, total_time: float):
    """In báo cáo tổng kết quá trình xử lý hàng loạt."""
    finished_count = sum(1 for r in results if r.get("status") == "FINISHED")
    failed_count = sum(1 for r in results if r.get("status") in ("FAILED", "TIMEOUT"))

    logger.info("=" * 70)
    logger.info(f"TỔNG KẾT KẾT QUẢ XỬ LÝ ({total_time:.2f}s)")
    logger.info(f"- Thành công: {finished_count}/{total_files} files")
    logger.info(f"- Thất bại  : {failed_count}/{total_files} files")
    logger.info("-" * 70)

    for idx, r in enumerate(results, start=1):
        status = r.get("status")
        fname = r.get("file")
        elapsed = r.get("elapsed_seconds", 0)
        req_id = r.get("request_id", "N/A")
        cached = " (CACHED)" if r.get("is_cached") else ""
        if status == "FINISHED":
            logger.info(f"[{idx:02d}] [OK{cached}] {fname} | {elapsed}s | req_id: {req_id}")
        else:
            logger.error(f"[{idx:02d}] [FAIL] {fname} | {elapsed}s | Lỗi: {r.get('error')}")

    logger.info("=" * 70)


async def main_async(args):
    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        logger.error(f"Thư mục đầu vào không tồn tại: {input_dir}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    doc_type = _resolve_doc_type(args, input_dir)
    pdf_files = _collect_pdf_files(input_dir)

    if not pdf_files:
        logger.warning(f"Không tìm thấy file PDF nào trong thư mục: {input_dir}")
        return

    logger.info("=" * 70)
    logger.info("BẮT ĐẦU TIẾN TRÌNH GỬI TÀI LIỆU BẤT ĐỒNG BỘ")
    logger.info(f"- Thư mục nguồn : {input_dir}")
    logger.info(f"- Thư mục đích   : {output_dir}")
    logger.info(f"- Tổng số file   : {len(pdf_files)} files")
    logger.info(f"- Loại tài liệu  : {doc_type}")
    logger.info(f"- Server AI      : {args.server_url}")
    logger.info(f"- Force reprocess: {args.force_reprocess}")
    logger.info("=" * 70)

    total_files = len(pdf_files)
    client_timeout = httpx.Timeout(timeout=float(args.timeout) + 30.0, connect=30.0)

    async with httpx.AsyncClient(timeout=client_timeout) as client:
        tasks = [
            process_single_file(
                client=client,
                file_path=file_path,
                server_url=args.server_url,
                doc_type=doc_type,
                force_reprocess=args.force_reprocess,
                poll_interval=args.poll_interval,
                max_wait_seconds=args.timeout,
                output_dir=output_dir,
                file_idx=idx,
                total_files=total_files,
            )
            for idx, file_path in enumerate(pdf_files, start=1)
        ]

        overall_start = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=False)
        total_time = time.time() - overall_start

    _log_summary(results, total_files, total_time)


def main():
    parser = argparse.ArgumentParser(
        description="Gửi hàng loạt file PDF tới DeputyProfiling AI Service để bóc tách thông tin bất đồng bộ."
    )
    parser.add_argument(
        "--input-dir",
        "-i",
        type=str,
        required=True,
        help="Đường dẫn thư mục chứa các file PDF (vd: private_documents/qtct/)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="tmp/",
        help="Đường dẫn thư mục lưu kết quả JSON (mặc định: tmp/)",
    )
    parser.add_argument(
        "--doc-type",
        "-d",
        type=str,
        default=None,
        help="Loại văn bản (QTCT, LUONG, KHEN_THUONG...). Nếu bỏ trống sẽ tự động nhận diện từ tên thư mục.",
    )
    parser.add_argument(
        "--server-url",
        "-s",
        type=str,
        default=os.getenv("SERVER_URL", "http://127.0.0.1:8091"),
        help="Địa chỉ gốc của AI Service (mặc định: http://127.0.0.1:8091 hoặc lấy từ SERVER_URL)",
    )
    parser.add_argument(
        "--force-reprocess",
        "-f",
        action="store_true",
        help="Ép trích xuất lại từ đầu, bỏ qua cache SHA-256.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Khoảng thời gian polling trạng thái (giây, mặc định: 2.0s).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Thời gian tối đa chờ 1 file hoàn thành (giây, mặc định: 300s).",
    )

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
