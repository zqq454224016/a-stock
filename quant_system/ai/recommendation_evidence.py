"""Deterministic evidence and appendix for AI stock research candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.utils.market_scope import is_additional_permission_board_code


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _statement_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Keep auditable long-horizon fields without sending entire statements to AI."""
    keywords = (
        "period_end", "营业收入", "营业总收入", "营业利润", "利润总额", "净利润",
        "归属于母公司", "经营活动", "现金流量净额", "货币资金", "应收账款",
        "存货", "总资产", "总负债", "所有者权益", "短期借款", "长期借款",
        "研发费用", "销售费用", "管理费用", "财务费用",
    )
    return {
        str(key): value for key, value in row.items()
        if any(word in str(key) for word in keywords)
    }


def _candidate_metrics(code: str, data_dir: Path) -> dict[str, Any]:
    stock = _read(data_dir / "stocks" / f"{code}.json")
    factors_payload = _read(data_dir / "factors" / f"{code}.json")
    factors = factors_payload.get("factors") or stock.get("factors") or {}
    prediction = _read(data_dir / "predictions" / f"{code}.json")
    selector = _read(data_dir / "selector" / f"{code}.json")
    impact = _read(data_dir / "impact" / f"{code}.json")
    enhance = _read(data_dir / "enhance" / f"{code}.json")
    sentiment = _read(data_dir / "sentiment" / f"{code}.json")
    interim_report = _read(data_dir / "interim_reports" / f"{code}.json")
    strategy = _read(data_dir / "strategy" / f"{code}.json")
    strategy_backtest = _read(data_dir / "strategy_backtest" / f"{code}.json")
    public_statements = _read(data_dir / "normalized/financial.candidate_statements" / f"{code}.json")
    capital_events = _read(data_dir / "normalized/market.candidate_capital_events" / f"{code}.json")
    analysis = stock.get("analysis") or {}
    quality = stock.get("quality") or {}
    fundamentals = enhance.get("fundamentals") or {}
    corporate = enhance.get("corporate") or {}
    forecast = corporate.get("earnings_forecast") or {}
    sentiment_factors = sentiment.get("factors") or sentiment
    report_period = (
        interim_report.get("report_period")
        or
        fundamentals.get("report_period") or fundamentals.get("period_end")
        or forecast.get("report_period") or forecast.get("period_end")
    )
    interim_available = interim_report.get("status") == "available" or bool(report_period or forecast)
    interim_income = interim_report.get("income") or {}
    interim_indicators = interim_report.get("indicators") or {}
    statements = public_statements.get("statements") or {}
    latest_statements = {
        key: _statement_summary(rows[0]) if isinstance(rows, list) and rows else {}
        for key, rows in statements.items()
    }
    statement_available = bool(public_statements.get("quality", {}).get("complete_three_statements"))
    enhance_flow = enhance.get("fund_flow") or {}
    capital_data = capital_events.get("data") or {}
    fund_flow_available = bool(
        (enhance_flow.get("northbound") or enhance_flow.get("margin"))
        or capital_data.get("margin_trading")
    )
    return {
        "code": code,
        "name": stock.get("name") or code,
        "trade_date": stock.get("trade_date"),
        "quote": {key: (stock.get("quote") or {}).get(key) for key in ("close", "change_pct", "volume", "amount_yi")},
        "trend": analysis.get("trend"),
        "returns_pct": analysis.get("returns") or {},
        "ma": analysis.get("ma") or {},
        "range_60d": analysis.get("range_60d") or {},
        "quality": {key: quality.get(key) for key in ("status", "quality_score", "missing_rate", "issues")},
        "factors": {key: factors.get(key) for key in (
            "multi_factor_score", "technical_score", "rsi14", "macd_hist", "atr14",
            "momentum_20", "volume_ratio_20", "above_ma20", "has_sentiment",
            "has_fundamental", "has_fund_flow",
        )},
        "prediction": {key: prediction.get(key) for key in ("horizon", "direction", "probability", "confidence", "status")},
        "selector": {key: selector.get(key) for key in ("upside_score", "status", "risks", "reasons")},
        "impact": {key: impact.get(key) for key in ("impact_score", "direction", "risks", "limitations")},
        "interim_report_context": {
            "status": "available" if interim_available or statement_available else "missing",
            "report_period": report_period,
            "announced_at": interim_report.get("announced_at") or fundamentals.get("published_at") or fundamentals.get("announce_date") or forecast.get("announce_date"),
            "known_at": interim_report.get("known_at"),
            "revenue": interim_income.get("revenue") or fundamentals.get("revenue"),
            "revenue_growth_pct": interim_indicators.get("or_yoy") or fundamentals.get("revenue_growth_pct"),
            "net_profit": interim_income.get("n_income_attr_p") or interim_income.get("n_income") or fundamentals.get("net_profit"),
            "net_profit_growth_pct": interim_indicators.get("netprofit_yoy") or fundamentals.get("net_profit_growth_pct") or forecast.get("change_pct"),
            "roe": interim_indicators.get("roe"),
            "operating_cash_flow": (interim_report.get("cash_flow") or {}).get("n_cashflow_act"),
            "debt_to_assets": interim_indicators.get("debt_to_assets"),
            "pe_ttm": fundamentals.get("pe_ttm"),
            "pb": fundamentals.get("pb"),
            "forecast": forecast or None,
            "limitations": interim_report.get("limitations") or ([] if interim_available else ["interim_report_or_forecast_missing"]),
        },
        "full_statement_context": {
            "status": "available" if statement_available else "missing",
            "source": public_statements.get("source"),
            "known_at": public_statements.get("known_at"),
            "latest_balance_sheet": latest_statements.get("fzb") or None,
            "latest_income_statement": latest_statements.get("lrb") or None,
            "latest_cash_flow": latest_statements.get("llb") or None,
            "complete_three_statements": statement_available,
        },
        "valuation_and_flow_context": {
            "valuation": {key: fundamentals.get(key) for key in ("trade_date", "pe_ttm", "pb", "ps", "peg", "market_cap_yi", "source")},
            "dividends": (corporate.get("dividends") or [])[:5],
            "lockups": (corporate.get("lockups") or [])[:5],
            "earnings_forecast": forecast or None,
            "northbound": enhance_flow.get("northbound"),
            "margin": enhance_flow.get("margin") or (capital_data.get("margin_trading") or [])[:5],
            "block_trades": (capital_data.get("block_trades") or [])[:5],
            "lockup_expiry": capital_data.get("lockup_expiry"),
            "status": "available" if fundamentals.get("source") or fund_flow_available else "missing",
        },
        "stock_sentiment_context": {
            "status": "available" if sentiment else "missing",
            "trade_date": sentiment_factors.get("trade_date"),
            "label": sentiment_factors.get("label"),
            "desire_score": sentiment_factors.get("desire_score"),
            "desire_change": sentiment_factors.get("desire_change"),
            "heat_index": sentiment_factors.get("heat_index"),
            "sentiment_accel": sentiment_factors.get("sentiment_accel"),
            "long_short_ratio": sentiment_factors.get("long_short_ratio"),
            "limitations": sentiment_factors.get("limitations") or (["stock_sentiment_missing"] if not sentiment else []),
        },
        "trend_strategy_context": {
            "status": strategy.get("status") or "missing",
            "strategy": strategy.get("strategy"),
            "trend_stage": strategy.get("trend_stage"),
            "trend_score": strategy.get("trend_score"),
            "confidence": strategy.get("confidence"),
            "outlook": strategy.get("outlook") or {},
            "metrics": strategy.get("metrics") or {},
            "manual_review": strategy.get("manual_review") or {"required": True, "status": "pending"},
            "one_year_validation": strategy_backtest.get("metrics") or {},
            "limitations": list(dict.fromkeys((strategy.get("limitations") or []) + ([] if strategy_backtest else ["one_year_offline_validation_pending"]))),
        },
        "missing_data": [label for flag, label in (
            (factors.get("has_fundamental") or interim_available or statement_available, "fundamental"),
            (factors.get("has_fund_flow") or fund_flow_available, "fund_flow"),
            (factors.get("has_sentiment") or bool(sentiment), "sentiment"),
            (bool(prediction), "prediction"),
        ) if not flag],
    }


def build_recommendation_evidence(ranked: dict[str, Any], data_dir: Path, *, limit: int) -> dict[str, Any]:
    periods: dict[str, Any] = {}
    candidate_codes: list[str] = []
    for key, period in (ranked.get("periods") or {}).items():
        recommended = [
            item for item in (period.get("recommendations") or [])
            if not is_additional_permission_board_code(str(item.get("code") or ""))
        ][:limit]
        observation = [
            item for item in (period.get("observation") or [])
            if not is_additional_permission_board_code(str(item.get("code") or ""))
        ][:limit]
        periods[key] = {
            "label": period.get("label"), "horizon": period.get("horizon"),
            "recommended": recommended, "observation": observation,
            "evaluated_count": len(period.get("evaluated") or []),
            "shortage_count": period.get("shortage_count"),
            "shortage_reason": period.get("shortage_reason"),
        }
        for item in recommended + observation:
            code = str(item.get("code") or "")
            if code and code not in candidate_codes:
                candidate_codes.append(code)
    selected_codes = candidate_codes[:limit]
    return {
        "schema_version": "1.0.0",
        "evidence_policy": {
            "deterministic": True,
            "ai_may_not_recalculate_scores": True,
            "ai_may_not_add_symbols": True,
            "fixed_sections": ["required_background", "market_context", "periods", "candidate_metrics"],
        },
        "required_background": {
            "hard_required": True,
            "sections": [
                "market_rules_and_tradeability", "market_sentiment", "interim_report_and_fundamentals",
                "trend_strategy", "technical_and_fund_flow", "events_and_knowledge_cutoff", "quant_validation", "risk_management",
            ],
            "analysis_rule": "每一项必须分析；数据缺失时必须写明 missing，不得推测或省略。",
            "market_rules_and_tradeability": {
                "t_plus_one": True,
                "excluded_boards": ["STAR", "ChiNext", "BSE"],
                "must_check": ["ST", "suspension", "price_limit", "ex_rights", "fees", "liquidity"],
            },
            "knowledge_cutoff_rule": "公告、中报和事件只能使用 published_at/known_at 不晚于决策时点的事实。",
        },
        "recommendation_version": ranked.get("recommendation_version"),
        "updated_at": ranked.get("updated_at"),
        "market_context": ranked.get("market_context") or {},
        "limitations": ranked.get("limitations") or [],
        "periods": periods,
        "candidate_metrics": {code: _candidate_metrics(code, data_dir) for code in selected_codes},
    }


def render_fixed_appendix(evidence: dict[str, Any]) -> str:
    lines = ["## 固定计算附录", "", "> 以下内容由本地脚本计算，AI 不参与评分或改写。", ""]
    market = evidence.get("market_context") or {}
    lines.append(
        f"- 市场数据日期：{market.get('trade_date') or '未知'}；环境：{market.get('regime') or '未知'}；"
        f"指数均值：{market.get('index_avg_change_pct')}%；降级状态：{bool(market.get('degraded'))}"
    )
    sentiment = market.get("sentiment") or {}
    lines.append(
        f"- 市场情绪：{sentiment.get('label') or '未知'}；固定分数：{sentiment.get('score')}；"
        f"上涨/下跌家数：{sentiment.get('advancing_count')}/{sentiment.get('declining_count')}；"
        f"状态：{sentiment.get('status') or 'missing'}"
    )
    for key, period in (evidence.get("periods") or {}).items():
        lines.extend(["", f"### {period.get('label') or key}（{period.get('horizon') or '周期未知'}）", ""])
        recommendations = period.get("recommended") or []
        if not recommendations:
            lines.append(f"- 无标的通过硬性门槛。{period.get('shortage_reason') or ''}")
            continue
        for item in recommendations:
            evidence_text = "；".join(item.get("evidence") or [])
            risks = "；".join(item.get("risks") or []) or "未记录"
            invalidation = "；".join(item.get("invalidation_conditions") or [])
            lines.append(
                f"- {item.get('code')} {item.get('name')}：固定评分 {item.get('score')}；"
                f"证据：{evidence_text}；风险：{risks}；失效条件：{invalidation}"
            )
            metrics = (evidence.get("candidate_metrics") or {}).get(str(item.get("code") or "")) or {}
            interim = metrics.get("interim_report_context") or {}
            stock_sentiment = metrics.get("stock_sentiment_context") or {}
            lines.append(
                f"  - 中报证据：{interim.get('status') or 'missing'}，报告期：{interim.get('report_period') or '未知'}，"
                f"净利润同比：{interim.get('net_profit_growth_pct')}%；个股情绪："
                f"{stock_sentiment.get('label') or 'missing'}，情绪日期：{stock_sentiment.get('trade_date') or '未知'}"
            )
    return "\n".join(lines).strip() + "\n"
