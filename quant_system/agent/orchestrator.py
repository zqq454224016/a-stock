"""Agent 编排。"""

from __future__ import annotations

from typing import Any

from quant_system.agent.audit import build_agent_audit_record
from quant_system.agent.context import StockContext
from quant_system.agent.predict_review import review_prediction
from quant_system.agent.policy import validate_agent_output
from quant_system.agent.providers import LLMStubProvider, RuleAgentProvider
from quant_system.agent.schemas import build_evidence_package
from quant_system.agent.stock_explainer import explain_stock_selection
from quant_system.agent.strategy_diagnosis import diagnose_strategy
from quant_system.config.agent_config import AGENT_DISCLAIMER, AGENT_VERSION
from quant_system.utils.time_utils import now_str


def _data_health(ctx: StockContext) -> dict[str, Any]:
    q = ctx.quality or {}
    stock = ctx.stock or {}
    quality = stock.get("quality") or {}
    score = q.get("quality_score") or quality.get("quality_score")
    return {
        "status": q.get("status") or quality.get("status", "unknown"),
        "quality_score": score,
        "factor_eligible": q.get("factor_eligible", quality.get("factor_eligible")),
        "issues": q.get("issues") or quality.get("issues") or [],
    }


def _overall_summary(selection: dict, diagnosis: dict, review: dict) -> tuple[str, str]:
    verdict = selection.get("verdict", "neutral")
    diag = diagnosis.get("verdict", "unknown")
    align = review.get("alignment", "unknown")

    if verdict == "negative" or diag == "weak":
        return "谨慎", "low"
    if verdict == "positive" and diag in ("ok", "mixed") and align in ("aligned", "partial", "unknown"):
        return selection.get("headline", "偏多观察"), "medium"
    if align == "divergent":
        return "信号分歧，宜观望", "low"
    return selection.get("headline", "中性观察"), "medium"


def _provider_for(name: str):
    if name == "llm":
        return LLMStubProvider()
    return RuleAgentProvider()


def build_agent_report(ctx: StockContext, *, strategy: str = "ma_cross", provider: str = "rule") -> dict[str, Any]:
    selection = explain_stock_selection(ctx)
    diagnosis = diagnose_strategy(ctx, strategy=strategy)
    review = review_prediction(ctx)
    health = _data_health(ctx)
    summary, confidence = _overall_summary(selection, diagnosis, review)

    limitations = ["rule_based_only", "no_auto_trade"]
    if not ctx.prediction:
        limitations.append("prediction_missing")
    if not diagnosis.get("available"):
        limitations.append("backtest_missing")

    base_report = {
        "code": ctx.code,
        "name": ctx.name,
        "trade_date": ctx.trade_date,
        "version": AGENT_VERSION,
        "updated_at": now_str(),
        "summary": summary,
        "confidence": confidence,
        "disclaimer": AGENT_DISCLAIMER,
        "stock_selection": selection,
        "strategy_diagnosis": diagnosis,
        "prediction_review": review,
        "data_health": health,
        "limitations": limitations,
        "audit": {
            "inputs_used": sorted(set(ctx.inputs_used)),
            "strategy_ref": strategy,
        },
    }

    evidence = build_evidence_package(ctx, strategy=strategy).to_dict()
    requested_provider = provider
    fallback_reason = ""
    active_provider = _provider_for(provider)
    try:
        provider_output = active_provider.run(evidence, rule_report=base_report)
    except Exception as exc:
        fallback_reason = str(exc)
        active_provider = RuleAgentProvider()
        provider_output = active_provider.run(evidence, rule_report=base_report)

    policy = validate_agent_output(provider_output, evidence)
    if not policy["passed"]:
        provider_output["requires_human_review"] = True
        provider_output["risks"] = list(dict.fromkeys(
            (provider_output.get("risks") or []) + [f"Agent权限校验：{x}" for x in policy["violations"]]
        ))

    audit_record = build_agent_audit_record(
        code=ctx.code,
        provider=active_provider.name,
        evidence=evidence,
        output=provider_output,
        policy=policy,
        fallback_reason=fallback_reason,
    )

    base_report.update({
        "provider": {
            "requested": requested_provider,
            "active": active_provider.name,
            "model": provider_output.get("model"),
            "prompt_version": provider_output.get("prompt_version"),
            "fallback_reason": fallback_reason,
        },
        "evidence_package": {
            "schema_version": evidence.get("schema_version"),
            "task": evidence.get("task"),
            "allowed_actions": evidence.get("allowed_actions"),
            "missing_inputs": evidence.get("missing_inputs"),
            "inputs_used": evidence.get("inputs_used"),
        },
        "provider_output": provider_output,
        "policy": policy,
        "audit": {
            **base_report["audit"],
            "schema_version": evidence.get("schema_version"),
            "provider": active_provider.name,
            "prompt_version": provider_output.get("prompt_version"),
            "policy_passed": policy["passed"],
            "audit_path": f"agent/audit/{ctx.code}.json",
        },
        "_audit_record": audit_record,
    })
    return base_report
