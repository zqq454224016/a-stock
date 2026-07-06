"""并发拉取工具（线程池）。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

from quant_system.utils.logger import get_logger

logger = get_logger(__name__)
T = TypeVar("T")
R = TypeVar("R")


def run_parallel_map(
    items: Iterable[T],
    worker: Callable[[T], R],
    *,
    max_workers: int = 4,
    label: str = "任务",
) -> list[R]:
    """对 items 并发执行 worker，保持输入顺序。"""
    seq = list(items)
    if not seq:
        return []
    if len(seq) == 1:
        return [worker(seq[0])]

    workers = max(1, min(max_workers, len(seq)))
    logger.info("%s 并发执行：%s 项，线程数 %s", label, len(seq), workers)
    results: list[R | None] = [None] * len(seq)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(worker, item): idx for idx, item in enumerate(seq)}
        for fut in as_completed(future_map):
            idx = future_map[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                logger.error("%s 第 %s 项失败: %s", label, idx + 1, e)
                raise
    return [r for r in results if r is not None]


def run_parallel_tasks(
    tasks: dict[str, Callable[[], R]],
    *,
    max_workers: int | None = None,
) -> dict[str, R | Exception]:
    """并发执行命名任务，失败时记录异常对象。"""
    if not tasks:
        return {}
    if len(tasks) == 1:
        name, fn = next(iter(tasks.items()))
        try:
            return {name: fn()}
        except Exception as e:
            return {name: e}

    workers = max_workers or min(8, len(tasks))
    out: dict[str, R | Exception] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                out[name] = fut.result()
            except Exception as e:
                out[name] = e
    return out
