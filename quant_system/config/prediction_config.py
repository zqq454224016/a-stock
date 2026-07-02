"""走势预测配置。"""

from __future__ import annotations

HORIZON_DAYS: dict[str, int] = {
    "1d": 1,
    "5d": 5,
    "20d": 20,
}

DEFAULT_HORIZON = "5d"
PREDICTION_VERSION = "1.0.0"
MIN_SAMPLES_MEDIUM = 15
MIN_SAMPLES_HIGH = 50
