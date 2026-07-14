"""Enhance bundle provider."""

from __future__ import annotations

from typing import Any

from quant_system.pipeline.normalizer import normalize_code


class BundleProviderMixin:
    def fetch_stock_bundle(self, code: str) -> dict[str, Any]:
        """单只股票增强数据（内部字段并发拉取）。"""
        from quant_system.config.enhance_config import DIVIDEND_LIMIT, LOCKUP_LIMIT, NORTHBOUND_DAYS
        from quant_system.utils.concurrent_fetch import run_parallel_tasks

        code = normalize_code(code)
        raw = run_parallel_tasks({
            "valuation": lambda: self.fetch_valuation(code),
            "dividends": lambda: self.fetch_dividends(code, limit=DIVIDEND_LIMIT),
            "lockups": lambda: self.fetch_lockup(code, limit=LOCKUP_LIMIT),
            "forecast": lambda: self.fetch_earnings_forecast(code),
            "northbound": lambda: self.fetch_northbound(code, days=NORTHBOUND_DAYS),
            "margin": lambda: self.fetch_margin(code),
        }, max_workers=6)

        failed: list[str] = []

        def _take(name: str, default: tuple):
            val = raw.get(name)
            if isinstance(val, Exception):
                failed.append(name)
                return default
            return val

        valuation, f1 = _take("valuation", ({}, []))
        dividends, f2 = _take("dividends", ([], []))
        lockups, f3 = _take("lockups", ([], []))
        forecast, f4 = _take("forecast", (None, []))
        northbound, f5 = _take("northbound", ({}, []))
        margin, f6 = _take("margin", (None, []))
        for part in (f1, f2, f3, f4, f5, f6):
            failed.extend(part)

        return {
            "valuation": valuation,
            "dividends": dividends,
            "lockups": lockups,
            "forecast": forecast,
            "northbound": northbound,
            "margin": margin,
            "failed": failed,
        }
