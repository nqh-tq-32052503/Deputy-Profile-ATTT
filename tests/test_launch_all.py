import asyncio
import json
from pathlib import Path
import shutil
import unicodedata
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from launch_all import (
    get_safe_filename,
    infer_doc_type,
    main_async,
    process_single_file,
)
from tests.assertions import check


class TestLaunchAllUtils:
    def test_infer_doc_type(self):
        check(infer_doc_type("private_documents/qtct/") == "QTCT")
        check(infer_doc_type("private_documents/qtct") == "QTCT")
        check(infer_doc_type("/path/to/luong/files") == "LUONG")
        check(infer_doc_type("private_documents/khen_thuong/") == "KHEN_THUONG")
        check(infer_doc_type("data/phu_cap/") == "PHU_CAP")
        check(infer_doc_type("unknown/folder/") is None)

    def test_get_safe_filename(self):
        decomposed = unicodedata.normalize("NFD", "Quyết_định_lương.pdf")
        safe = get_safe_filename(Path(decomposed))
        check(safe == unicodedata.normalize("NFC", "Quyết_định_lương.pdf"))

    def test_special_filename_processing(self, tmp_path):
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        special_name = "Quye╠é╠üt_─æi╠únh_lu╠¢o╠¢ng_cu╠ëa_─æo╠é╠Çng_Bu╠Çi.pdf"
        dummy_file = tmp_path / special_name
        dummy_file.write_bytes(b"%PDF-1.4 mock")

        # Mock httpx client
        mock_client = AsyncMock()

        # Mock POST /hsdb/extract
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "request_id": "req-special-123",
            "status": "PROCESSING",
        }
        post_resp.raise_for_status = MagicMock()

        # Mock GET /hsdb/extract/{request_id}
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = {
            "request_id": "req-special-123",
            "status": "FINISHED",
            "result": {"status": "success", "doc_type": "LUONG"},
        }
        get_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = post_resp
        mock_client.get.return_value = get_resp

        async def run():
            res = await process_single_file(
                client=mock_client,
                file_path=dummy_file,
                server_url="http://testserver",
                doc_type="LUONG",
                force_reprocess=False,
                poll_interval=0.01,
                timeout=10,
                output_dir=out_dir,
                file_idx=1,
                total_files=1,
            )
            return res

        result = asyncio.run(run())
        check(result["status"] == "FINISHED")
        check(result["request_id"] == "req-special-123")

        # Check output JSON file was written
        expected_stem = unicodedata.normalize("NFC", dummy_file.stem)
        json_file = out_dir / f"{expected_stem}.json"
        check(json_file.exists())
        saved_data = json.loads(json_file.read_text(encoding="utf-8"))
        check(saved_data["status"] == "FINISHED")
        check(saved_data["result"]["doc_type"] == "LUONG")
