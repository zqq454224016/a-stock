"""Report generation entrypoints used by CLI commands and pipelines."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from quant_system.utils.logger import get_logger
from quant_system.utils.watchlist_utils import ensure_watchlist_stocks

ROOT = Path(__file__).resolve().parents[2]
logger = get_logger("apps.reports")


def _run_report_script(script: str, message: str | None = None) -> None:
    path = ROOT / script
    if path.exists():
        logger.info(message or "生成报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_predict_reports() -> None:
    _run_report_script("script/gen_predict_report.py", "生成预测报表: %s")


def generate_backtest_reports() -> None:
    _run_report_script("script/gen_backtest_report.py", "生成回测报表: %s")


def generate_factor_reports() -> None:
    _run_report_script("script/gen_factor_report.py", "生成因子排名: %s")


def generate_factor_eval_report() -> None:
    _run_report_script("script/gen_factor_eval_report.py", "生成因子有效性报告: %s")


def generate_recommendation_report() -> None:
    _run_report_script("script/gen_recommendation_report.py", "生成多周期推荐报告: %s")


def generate_framework_report() -> None:
    _run_report_script("script/gen_framework_report.py", "生成模块化框架报告: %s")


def generate_console_report() -> None:
    _run_report_script("script/gen_console_report.py", "生成统一控制台: %s")


def generate_monitoring_report() -> None:
    _run_report_script("script/gen_monitoring_report.py", "生成监控告警报告: %s")


def generate_v3_roadmap_report() -> None:
    _run_report_script("script/gen_v3_roadmap_report.py", "生成 v3 路线报告: %s")


def generate_live_dashboard() -> None:
    _run_report_script("script/gen_live_dashboard.py", "生成盘中看板: %s")


def generate_enhance_reports() -> None:
    _run_report_script("script/gen_enhance_report.py", "生成数据增强报表: %s")


def generate_agent_dashboard() -> None:
    _run_report_script("script/gen_agent_dashboard.py", "生成 Agent 看板: %s")


def generate_trading_report() -> None:
    _run_report_script("script/gen_trading_report.py", "生成模拟交易报表: %s")


def generate_portfolio_report() -> None:
    _run_report_script("script/gen_portfolio_report.py", "生成组合管理报表: %s")


def generate_decision_report() -> None:
    _run_report_script("script/gen_decision_report.py", "生成决策报表: %s")


def generate_impact_report() -> None:
    _run_report_script("script/gen_impact_report.py", "生成实际影响数据报表: %s")


def generate_attribution_report() -> None:
    _run_report_script("script/gen_attribution_report.py", "生成每日归因报表: %s")


def generate_selector_report() -> None:
    _run_report_script("script/gen_selector_report.py", "生成上涨候选池报表: %s")


def generate_replay_report() -> None:
    _run_report_script("script/gen_replay_report.py", "生成历史推演报表: %s")


def generate_review_report() -> None:
    _run_report_script("script/gen_review_report.py", "生成后验复盘报表: %s")


def sync_report_index_hubs() -> None:
    _run_report_script("script/report_index_utils.py")


def generate_reports(stock_only: bool = False) -> None:
    """调用现有 HTML 报表生成脚本；生成前补齐 watchlist 缺失个股。"""
    ensure_watchlist_stocks()
    scripts = ("script/gen_stock_report.py",) if stock_only else (
        "script/gen_report.py",
        "script/gen_stock_report.py",
    )
    for script in scripts:
        _run_report_script(script)
