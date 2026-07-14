"""Shared runtime helpers for enhance providers."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from quant_system.utils.i18n_labels import humanize_fetch_error, translate_source_fail
from quant_system.utils.retry import call_with_retry
from quant_system.utils.source_guard import is_eastmoney_disabled, note_eastmoney_failure


def safe_float(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def latest_row(df: pd.DataFrame) -> pd.Series | None:
    if df is None or df.empty:
        return None
    return df.iloc[-1]


class EnhanceRuntimeMixin:
    def _retry(self, fn, *args, **kwargs):
        return call_with_retry(
            fn,
            retries=self.config.enhance_probe_retries,
            delay=min(self.config.retry_delay, 1.0),
            *args,
            **kwargs,
        )

    def _is_disabled(self, label: str) -> bool:
        if label in self._disabled:
            return True
        return any(label.startswith(p) for p in self._disabled_prefixes)

    def _disable(self, label: str) -> None:
        with self._lock:
            if label.startswith("earnings_forecast"):
                self._disabled_prefixes.add("earnings_forecast")
            elif label.startswith("margin_"):
                self._disabled_prefixes.add("margin_")
            else:
                self._disabled.add(label)

    def _is_eastmoney_label(self, label: str) -> bool:
        return not label.startswith("valuation_baidu")

    def _call(self, label: str, fn: Callable, *args, **kwargs) -> tuple[Any | None, str | None]:
        if self._is_eastmoney_label(label) and is_eastmoney_disabled():
            return None, label
        if self._is_disabled(label):
            return None, label
        try:
            return self._retry(fn, *args, **kwargs), None
        except Exception as e:
            if self._is_eastmoney_label(label):
                note_eastmoney_failure(e)
            self._disable(label)
            human = humanize_fetch_error(e)
            with self._lock:
                first = label not in self._logged_failures
                if first:
                    self._logged_failures.add(label)
            if first:
                self.log_fail(f"{translate_source_fail(label)}: {human}")
            return None, label
