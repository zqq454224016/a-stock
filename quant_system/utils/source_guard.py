"""进程级数据源可用性守卫（东财等）。"""

from __future__ import annotations

import threading

from quant_system.utils.i18n_labels import humanize_fetch_error
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_eastmoney_disabled = False
_eastmoney_logged = False


def is_eastmoney_disabled() -> bool:
    return _eastmoney_disabled


def is_eastmoney_error(err: Exception | str) -> bool:
    msg = str(err).lower()
    return (
        "eastmoney" in msg
        or "push2.eastmoney" in msg
        or "push2his.eastmoney" in msg
        or "proxy" in msg
        or "remote end closed" in msg
    )


def disable_eastmoney(err: Exception | str | None = None, *, reason: str = "") -> None:
    """关闭东财源；本会话内只打印一次。"""
    global _eastmoney_disabled, _eastmoney_logged
    with _lock:
        _eastmoney_disabled = True
        if _eastmoney_logged:
            return
        _eastmoney_logged = True
        detail = reason or (humanize_fetch_error(err) if err else "网络不可用")
        logger.warning("东财源本会话内已关闭（%s），后续自动走新浪/腾讯", detail)


def note_eastmoney_failure(err: Exception | str) -> None:
    if is_eastmoney_error(err):
        disable_eastmoney(err)


def ensure_eastmoney_policy(force_disable: bool = False) -> None:
    if force_disable:
        disable_eastmoney(reason="已配置跳过东财")


def reset_eastmoney_guard() -> None:
    """仅用于测试。"""
    global _eastmoney_disabled, _eastmoney_logged
    with _lock:
        _eastmoney_disabled = False
        _eastmoney_logged = False


_ths_disabled = False
_ths_logged = False


def is_ths_disabled() -> bool:
    return _ths_disabled


def disable_ths(err: Exception | str | None = None, *, reason: str = "") -> None:
    global _ths_disabled, _ths_logged
    with _lock:
        _ths_disabled = True
        if _ths_logged:
            return
        _ths_logged = True
        detail = reason or (humanize_fetch_error(err) if err else "网络不可用")
        logger.warning("同花顺源本会话内已关闭（%s）", detail)


def note_ths_failure(err: Exception | str) -> None:
    msg = str(err).lower()
    if "10jqka" in msg or "同花顺" in msg or "proxy" in msg or "timeout" in msg:
        disable_ths(err)


def reset_ths_guard() -> None:
    global _ths_disabled, _ths_logged
    with _lock:
        _ths_disabled = False
        _ths_logged = False


def reset_all_source_guards() -> None:
    reset_eastmoney_guard()
    reset_ths_guard()
