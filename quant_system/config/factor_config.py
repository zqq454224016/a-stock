"""因子与质量门禁配置。"""

from __future__ import annotations

# 技术因子库版本（公式/参数变更时递增）
TECHNICAL_FACTOR_VERSION = "1.0.0"
PRIMARY_SIGNAL_VERSION = "1.0.0"
COMPOSITE_FACTOR_VERSION = "1.2.0"

# 多因子合成权重（Next 2 因子增强）
WEIGHT_TECHNICAL = 0.50
WEIGHT_SENTIMENT = 0.25
WEIGHT_FUNDAMENTAL = 0.15
WEIGHT_FUND_FLOW = 0.10

# 跨源收盘价偏差告警（百分比）
CROSS_SOURCE_WARN_PCT = 0.5

# 质量分阈值（Quantification.md §2.3）
QUALITY_OK = 90          # 可进入因子与回测
QUALITY_WARN = 70        # 可展示，回测需显式允许
FACTOR_MIN_SCORE = 70    # 低于此分禁止写入因子
