"""MVP 闭环默认参数（Quantification.md §1.3）。"""

from __future__ import annotations

# 回测与历史补录最少 K 线根数（约 3 年交易日）
MVP_HIST_DAYS = 750

# 个股页日 K 展示根数（控制 JSON/HTML 体积）
MVP_DISPLAY_DAYS = 250
