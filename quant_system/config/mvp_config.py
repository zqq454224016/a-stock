"""MVP 闭环默认参数（Quantification.md §1.3）。"""

from __future__ import annotations

# 回测与历史补录目标 K 线根数（约 5 年交易日）
MVP_HIST_DAYS = 1250

# 个股分析保留的日 K 根数（控制 JSON 体积）
MVP_DISPLAY_DAYS = 250
