"""任务重试引擎。"""

from __future__ import annotations

from typing import Callable, TypeVar

from quant_system.utils.logger import get_logger
from quant_system.utils.retry import call_with_retry

logger = get_logger(__name__)
T = TypeVar("T")


class RetryEngine:
    def __init__(self, retries: int = 3, delay: float = 2.0):
        self.retries = retries
        self.delay = delay

    def run(self, fn: Callable[..., T], *args, **kwargs) -> T:
        return call_with_retry(fn, self.retries, self.delay, *args, **kwargs)

    def run_job(self, job_fn: Callable[[], None], job_name: str) -> bool:
        try:
            self.run(job_fn)
            logger.info("任务成功: %s", job_name)
            return True
        except Exception as e:
            logger.error("任务失败: %s - %s", job_name, e)
            return False
