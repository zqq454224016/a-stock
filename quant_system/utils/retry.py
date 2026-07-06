"""重试装饰器与工具函数。"""

from __future__ import annotations

import time
from functools import wraps
from typing import Callable, TypeVar

from quant_system.utils.logger import get_logger

logger = get_logger(__name__)
T = TypeVar("T")


def retry(
    retries: int = 3,
    delay: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            last_err = None
            for i in range(retries):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_err = e
                    if i < retries - 1:
                        logger.warning("第 %s/%s 次重试 %s: %s", i + 1, retries - 1, fn.__name__, e)
                        time.sleep(delay)
            raise last_err  # type: ignore[misc]
        return wrapper
    return decorator


def call_with_retry(
    fn: Callable[..., T],
    retries: int = 3,
    delay: float = 2.0,
    *args,
    **kwargs,
) -> T:
    last_err = None
    for i in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if i < retries - 1:
                logger.warning("第 %s/%s 次重试: %s", i + 1, retries - 1, e)
                time.sleep(delay)
    raise last_err  # type: ignore[misc]
