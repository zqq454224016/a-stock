"""Feishu progress notifications with local deduplication and secret-safe errors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import requests

from quant_system.config.app_config import feishu_config
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.time_utils import now_str


def _summary(payload: dict[str, Any]) -> str:
    actions = payload.get("actions") or []
    succeeded = [str(row.get("name")) for row in actions if row.get("status") == "success"]
    failed = [str(row.get("name")) for row in actions if row.get("status") == "failed"]
    status = payload.get("status") or "unknown"
    status_label = {
        "round_complete": "本轮完成",
        "worker_started": "后台已启动",
        "running": "进行中",
    }.get(str(status), str(status))
    lines = [
        "策略系统 · 自动迭代进度",
        f"时间：{payload.get('updated_at') or now_str()}",
        f"状态：{status_label}",
    ]
    if succeeded:
        lines.append("已完成：" + "、".join(succeeded))
    if failed:
        lines.append("失败/卡点：" + "、".join(failed))
    if not actions:
        lines.append("本轮无上游数据变化，策略与评分未重复计算")
    if payload.get("next_run_after"):
        lines.append(f"下次检查：{payload['next_run_after']}")
    eta = payload.get("eta") or {}
    if eta:
        lines.append(f"本轮预计完成：{eta.get('current_iteration_expected_at') or '待测算'}")
        fast = eta.get("fast_track") or {}
        if fast:
            lines.append(f"模拟系统预计可用：{fast.get('simulation_ready_expected_at') or '待测算'}")
        final = eta.get("final_completion") or {}
        lines.append(f"最终预计完成：{final.get('display') or '待测算'}")
        for stage in eta.get("stages") or []:
            lines.append(
                f"阶段ETA：{stage.get('name')} · {stage.get('expected_at')} · "
                f"{stage.get('confidence')}"
            )
    strategy_state = payload.get("strategy_iteration_state") or {}
    if strategy_state:
        lines.append(f"策略研究：{strategy_state.get('state')}")
        lines.append(f"说明：{strategy_state.get('reason')}")
    lines.append("AI权限：仅处理数据获取方式，不参与评分")
    return "\n".join(lines)


def _fingerprint(payload: dict[str, Any]) -> str:
    """Ignore volatile ETA timestamps so heartbeat rounds do not re-notify."""
    eta = payload.get("eta") or {}
    stages = [
        {"name": stage.get("name"), "status": stage.get("status"), "confidence": stage.get("confidence")}
        for stage in (eta.get("stages") or [])
        if isinstance(stage, dict)
    ]
    strategy = payload.get("strategy_iteration_state") or {}
    material = {
        "status": payload.get("status"),
        "actions": [
            {"name": row.get("name"), "status": row.get("status"), "result_status": row.get("result_status")}
            for row in payload.get("actions") or []
        ],
        "strategy_state": strategy.get("state"),
        "strategy_decision": strategy.get("latest_decision"),
        "eta_stages": stages,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def _should_notify(payload: dict[str, Any], *, force: bool) -> dict[str, Any] | None:
    """Only sync after a finished round (or explicit force); skip mid-round heartbeats."""
    if force:
        return None
    status = str(payload.get("status") or "")
    if status not in {"round_complete", "worker_started"}:
        return {"status": "skipped", "reason": "await_round_complete"}
    return None


def notify_iteration_progress(
    payload: dict[str, Any], *, force: bool = False,
    webhook_url: str | None = None, data_dir: Path | None = None,
) -> dict[str, Any]:
    url = (webhook_url if webhook_url is not None else feishu_config()["webhook_url"]).strip()
    if not url:
        return {"status": "disabled", "reason": "feishu_webhook_not_configured"}
    gated = _should_notify(payload, force=force)
    if gated is not None:
        return gated
    root = data_dir or CrawlerConfig().data_dir
    state_path = root / "notifications/feishu_iteration.json"
    state: dict[str, Any] = {}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except (OSError, ValueError, TypeError):
        state = {}
    fingerprint = _fingerprint(payload)
    if not force and state.get("fingerprint") == fingerprint:
        return {"status": "skipped", "reason": "unchanged"}
    try:
        response = requests.post(
            url,
            json={"msg_type": "text", "content": {"text": _summary(payload)}},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code", result.get("StatusCode", 0)) not in (0, None):
            raise RuntimeError(f"Feishu response code={result.get('code', result.get('StatusCode'))}")
        status = "sent"
        error = None
    except Exception as exc:
        status = "failed"
        error = str(exc).replace(url, "[REDACTED]")[-300:]
    record = {
        "updated_at": now_str(), "status": status, "fingerprint": fingerprint,
        "error": error,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record

def notify_realtime_advice(code: str, payload: dict[str, Any], *, webhook_url: str | None = None) -> dict[str, Any]:
    """推送确定性K线预估，不读取仓位，也不发送自动交易指令。"""
    url = (webhook_url if webhook_url is not None else feishu_config()["webhook_url"]).strip()
    if not url: return {"status": "disabled"}
    latest = payload.get("latest") or {}; analysis = payload.get("analysis") or {}
    features = analysis.get("features") or {}
    market = payload.get("market_context") or {}
    combined = payload.get("combined_analysis") or {}
    plan = payload.get("trade_plan") or {}
    if market.get("status") == "available":
        market_line = (f"大盘：上证 {market.get('sh_change_pct', '--')}%｜深证 {market.get('sz_change_pct', '--')}%｜"
                       f"{market.get('regime', '数据缺失')}\n")
        if market.get("stock_change_pct") is not None and market.get("relative_strength_pct") is not None:
            market_line += (f"相对强弱：个股 {market['stock_change_pct']}%｜{market.get('relative_label', '无法判断')} "
                            f"{market['relative_strength_pct']}个百分点\n")
        else:
            market_line += "相对强弱：个股当日涨跌数据不足，本次不比较\n"
    else:
        market_line = "大盘：实时指数数据缺失，本次不作市场归因\n"
    if plan.get("bias") == "进攻":
        plan_line = (
            f"操作：{plan.get('action')}\n突破买点：{plan.get('breakout_buy')}｜回踩买区："
            f"{(plan.get('pullback_buy_zone') or ['--', '--'])[0]}—{(plan.get('pullback_buy_zone') or ['--', '--'])[1]}\n"
            f"卖出/止损：{plan.get('sell_trigger')}｜目标：{plan.get('target_1')} / {plan.get('target_2')}\n"
            f"确认：{plan.get('buy_confirmation')}\n"
        )
    elif plan.get("bias") == "防守":
        zone = plan.get("rebound_sell_zone") or ["--", "--"]
        plan_line = (
            f"操作：{plan.get('action')}\n反弹卖区：{zone[0]}—{zone[1]}｜跌破卖点：{plan.get('sell_trigger')}\n"
            f"重新买入条件：站上{plan.get('reentry_trigger')}；{plan.get('reentry_confirmation')}\n"
        )
    else:
        plan_line = f"操作：{plan.get('action')}｜突破买点：{plan.get('breakout_buy')}｜跌破卖点：{plan.get('sell_trigger')}\n"
    text = (f"个股×大盘联合信号 · {payload.get('name') or code}（{code}）\n"
            f"结论：{combined.get('conclusion', analysis.get('trend', '未知'))}\n"
            f"关系：{combined.get('relation', '待判断')}｜{combined.get('market_effect', analysis.get('outlook', '暂无预估'))}\n"
            f"触发：{payload.get('notification_reason', '趋势发生实质变化')}\n"
            f"{market_line}"
            f"{plan_line}"
            f"价格：{latest.get('close', '--')}｜支撑：{analysis.get('support', '--')}｜压力：{analysis.get('resistance', '--')}\n"
            f"证据：MA5 {features.get('ma5', '--')} / MA10 {features.get('ma10', '--')}；"
            f"3周期动量 {features.get('momentum_3bar_pct', '--')}%；量比 {features.get('volume_ratio', '--')}\n"
            f"失效：{analysis.get('invalidation', '等待数据')}\n"
            f"联合可信度：{combined.get('confidence', analysis.get('confidence', 0))}%（规则一致性，非上涨概率）\n"
            "范围：5分钟K线未来1—3周期；仅作提醒，不读取仓位、不自动报单")
    try:
        r=requests.post(url,json={"msg_type":"text","content":{"text":text}},timeout=10); r.raise_for_status(); return {"status":"sent"}
    except Exception as exc: return {"status":"failed","error":str(exc).replace(url,"[REDACTED]")[-200:]}
