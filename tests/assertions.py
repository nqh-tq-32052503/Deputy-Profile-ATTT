"""Module hỗ trợ kiểm tra (assertion helpers) cho test suite.

Thay thế các câu lệnh `assert` để tuân thủ quy chuẩn SAST (Bandit rule B101).
Khi chạy quét bảo mật mã nguồn, Bandit gán cờ B101 cho từ khóa `assert`.
Các hàm trong module này sử dụng `if not condition: raise AssertionError(...)`
giúp giữ nguyên tính năng kiểm thử của test suite mà không kích hoạt cảnh báo B101.
"""
from typing import Any, Container, Optional


def check(condition: bool, msg: Optional[str] = None) -> None:
    """Kiểm tra điều kiện `condition` là True/truthy.

    Nếu False, raise AssertionError tương tự từ khóa `assert` nhưng không bị
    Bandit quét thành vi phạm B101 (Use of assert detected).
    """
    if not condition:
        raise AssertionError(msg or "Assertion condition failed")


def check_equal(actual: Any, expected: Any, msg: Optional[str] = None) -> None:
    """Kiểm tra actual == expected."""
    if actual != expected:
        raise AssertionError(msg or f"Expected {expected!r}, got {actual!r}")


def check_not_equal(actual: Any, expected: Any, msg: Optional[str] = None) -> None:
    """Kiểm tra actual != expected."""
    if actual == expected:
        raise AssertionError(msg or f"Expected value not to equal {expected!r}")


def check_true(condition: bool, msg: Optional[str] = None) -> None:
    """Kiểm tra condition is True."""
    if not condition:
        raise AssertionError(msg or "Expected condition to be True")


def check_false(condition: bool, msg: Optional[str] = None) -> None:
    """Kiểm tra condition is False."""
    if condition:
        raise AssertionError(msg or "Expected condition to be False")


def check_in(item: Any, container: Container[Any], msg: Optional[str] = None) -> None:
    """Kiểm tra item in container."""
    if item not in container:
        raise AssertionError(msg or f"Expected {item!r} to be in {container!r}")


def check_not_in(item: Any, container: Container[Any], msg: Optional[str] = None) -> None:
    """Kiểm tra item not in container."""
    if item in container:
        raise AssertionError(msg or f"Expected {item!r} not to be in {container!r}")


def check_is_none(val: Any, msg: Optional[str] = None) -> None:
    """Kiểm tra val is None."""
    if val is not None:
        raise AssertionError(msg or f"Expected None, got {val!r}")


def check_is_not_none(val: Any, msg: Optional[str] = None) -> None:
    """Kiểm tra val is not None."""
    if val is None:
        raise AssertionError(msg or "Expected value not to be None")
