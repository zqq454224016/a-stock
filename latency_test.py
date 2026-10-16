"""TickFlow 端点延迟测试。

通过标准库 HTTP GET /health 测量各端点延迟，不读取或输出 API Key。
用法：python latency_test.py
"""

from __future__ import annotations

import http.client
import statistics
import time
import urllib.parse


ENDPOINTS = [
    ("https://api.tickflow.org/health", "默认端点", False),
    ("https://hk-api.tickflow.org/health", "香港端点", False),
    ("https://jp-api.tickflow.org/health", "日本端点", False),
    ("https://us-api.tickflow.org/health", "美国端点", False),
    ("https://139.196.55.234:50443/health", "中国大陆端点（Beta）", False),
    ("https://106.15.238.72:50443/health", "中国大陆专线端点", True),
]
ROUNDS = 5


def http_ping(url: str, timeout: float = 10.0) -> float | None:
    """请求 /health 一次，返回毫秒延迟；失败返回 None。"""
    parsed = urllib.parse.urlparse(url)
    connection_cls = (
        http.client.HTTPSConnection
        if parsed.scheme == "https"
        else http.client.HTTPConnection
    )
    conn = None
    try:
        conn = connection_cls(parsed.netloc, timeout=timeout)
        start = time.perf_counter()
        conn.request("GET", parsed.path or "/")
        response = conn.getresponse()
        response.read(64)
        return round((time.perf_counter() - start) * 1000, 2)
    except (OSError, http.client.HTTPException):
        return None
    finally:
        if conn is not None:
            conn.close()


def main() -> None:
    print("=" * 60)
    print("TickFlow 端点延迟测试 (HTTP /health)")
    print(f"测试轮次: {ROUNDS}")
    print("=" * 60)

    results: list[tuple[str, str, float, float, float, int, bool]] = []
    for url, label, is_premium in ENDPOINTS:
        tag = " [专线加速]" if is_premium else ""
        print(f"测试 {label}{tag} ({url}) ...")
        latencies: list[float] = []
        for index in range(ROUNDS):
            ms = http_ping(url)
            if ms is None:
                print(f"  第 {index + 1} 次: 超时/失败")
            else:
                latencies.append(ms)
                print(f"  第 {index + 1} 次: {ms:.2f} ms")
            time.sleep(0.3)

        if latencies:
            median = statistics.median(latencies)
            results.append((label, url, median, min(latencies), max(latencies), len(latencies), is_premium))
            print(f"  → 中位数: {median:.2f} ms | 最小: {min(latencies):.2f} | 最大: {max(latencies):.2f}")
        else:
            results.append((label, url, float("inf"), 0.0, 0.0, 0, is_premium))
            print("  → 全部超时")
        print()

    results.sort(key=lambda item: item[2])
    print("=" * 60)
    print("测试结果汇总 (按延迟排序)")
    print("-" * 60)
    for label, _url, median, minimum, maximum, success, is_premium in results:
        tag = " ⚡" if is_premium else ""
        if median == float("inf"):
            print(f"  {label:20s}{tag} : 不可达")
        else:
            print(f"  {label:20s}{tag} : {median:7.2f} ms (min={minimum:.2f}, max={maximum:.2f}, {success}/{ROUNDS})")
    print("=" * 60)

    best = results[0]
    if best[2] == float("inf"):
        print("没有可用端点，请检查网络、DNS 或 TickFlow 服务状态。")
        return

    label, url, median, _minimum, _maximum, _success, is_premium = best
    base_url = url.removesuffix("/health")
    print(f"推荐使用: {label}")
    print(f"对应 base_url: {base_url}")
    print(f"中位延迟: {median:.2f} ms")
    if is_premium:
        print("注意：该端点需要专线加速权限；无权限时请选择下一个可达端点。")
    print("Python SDK:")
    print(f'  TickFlow(api_key="your-key", base_url="{base_url}")')
    print("配置文件中的 tickflow.base_url 应填写上述地址，不要包含 /health。")


if __name__ == "__main__":
    main()
