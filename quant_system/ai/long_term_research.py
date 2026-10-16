"""Evidence-bounded AI long-horizon research lane."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from quant_system.ai.codex_diagnosis import _run_codex
from quant_system.ai.recommendation_evidence import _candidate_metrics
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks.recommendation_job import run_recommendation_job
from quant_system.utils.market_scope import is_research_stock_code

SCHEMA_VERSION = "1.0.0"
PROMPT_VERSION = "ai-long-1.1.0"
MAX_INPUT_CANDIDATES = 12

RULES = """你是A股长线研究模型。任务是在限定候选中进行6-12个月研究推测。
必须综合五个维度：市场行情、基本面、技术面、逻辑面、情绪面。只使用证据JSON，
不得联网补造事实，不得添加候选外股票。数据缺失必须写missing并降低置信度。
这不是已验证量化策略；不得输出买入/卖出/仓位/目标价/收益保证。
仅输出JSON对象，不要Markdown围栏。结构为：
{"market_view":"...","data_date":"YYYY-MM-DD或unknown","recommendations":[
{"code":"6位代码","name":"名称","confidence":0到100整数,"horizon":"6-12个月",
"thesis":"核心推测","market":"市场面","fundamental":"基本面","technical":"技术面",
"logic":"逻辑面","sentiment":"情绪面","risks":["..."],"missing_data":["..."],
"invalidation":["..."]}],"overall_risks":["..."]}
最多5只。若全部候选都缺少长线关键数据，但价格数据仍有效，必须进行相对比较并选择
1到3只“低置信度推测观察”对象，置信度不得超过55，明确说明这不是基本面确认；
只有全部候选价格数据也失效时才允许返回空数组。"""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def build_long_term_evidence(
    ranked: dict[str, Any], data_dir: Path, *, candidate_limit: int = MAX_INPUT_CANDIDATES,
) -> dict[str, Any]:
    rows = ((ranked.get("periods") or {}).get("long") or {}).get("evaluated") or []
    eligible = []
    for row in rows:
        code, name = str(row.get("code") or ""), str(row.get("name") or "")
        if not is_research_stock_code(code) or "ST" in name.upper():
            continue
        eligible.append({
            "code": code, "name": name, "deterministic_score": row.get("score"),
            "quant_status": row.get("status"), "quant_risks": row.get("risks") or [],
            "sector_context": row.get("sector_context") or {},
        })
        if len(eligible) >= max(1, min(candidate_limit, MAX_INPUT_CANDIDATES)):
            break

    metrics: dict[str, Any] = {}
    for row in eligible:
        code = row["code"]
        item = _candidate_metrics(code, data_dir)
        attribution = _read(data_dir / "attribution" / f"{code}.json")
        item["logic_context"] = {
            "causes": (attribution.get("causes") or attribution.get("attributions") or [])[:8],
            "conclusion": attribution.get("conclusion") or attribution.get("summary"),
            "policy": "logic labels are evidence summaries, not confirmed causality",
        }
        metrics[code] = item

    return {
        "schema_version": SCHEMA_VERSION, "prompt_version": PROMPT_VERSION,
        "research_mode": "ai_inference_only_not_formal_recommendation",
        "execution_allowed": False, "used_in_formal_score": False,
        "market_context": ranked.get("market_context") or {},
        "today_change": _read(data_dir / "today_change" / "summary.json"),
        "daily_market_recap": _read(data_dir / "daily_market_recap" / "latest.json"),
        "sector_rotation": _read(data_dir / "sector_data" / "rotation.json"),
        "candidate_scope": eligible, "candidate_metrics": metrics,
        "required_dimensions": ["market", "fundamental", "technical", "logic", "sentiment"],
        "missing_rule": "missing data remains missing; AI may infer scenarios but not facts",
    }


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("AI长线结果必须是JSON对象")
    return value


def _validate_result(result: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    allowed = {row["code"]: row["name"] for row in evidence["candidate_scope"]}
    clean, seen = [], set()
    for row in result.get("recommendations") or []:
        code = str(row.get("code") or "")
        if code not in allowed or code in seen:
            continue
        seen.add(code)
        confidence = max(0, min(100, int(float(row.get("confidence") or 0))))
        missing = [str(x)[:200] for x in (row.get("missing_data") or [])]
        if evidence["candidate_metrics"][code]["interim_report_context"]["status"] == "missing":
            confidence = min(confidence, 55)
            if "fundamental" not in missing:
                missing.append("fundamental")
        clean.append({
            "code": code, "name": allowed[code], "confidence": confidence,
            "horizon": "6-12个月", "thesis": str(row.get("thesis") or "")[:800],
            **{key: str(row.get(key) or "missing")[:800] for key in ("market", "fundamental", "technical", "logic", "sentiment")},
            "risks": [str(x)[:300] for x in (row.get("risks") or [])][:8],
            "missing_data": missing[:8],
            "invalidation": [str(x)[:300] for x in (row.get("invalidation") or [])][:8],
            "ai_generated": True, "research_only": True, "execution_allowed": False,
        })
        if len(clean) >= 5:
            break
    return {
        "schema_version": SCHEMA_VERSION, "prompt_version": PROMPT_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_date": str(result.get("data_date") or evidence["market_context"].get("trade_date") or "unknown"),
        "market_view": str(result.get("market_view") or "")[:1200],
        "recommendations": clean,
        "overall_risks": [str(x)[:300] for x in (result.get("overall_risks") or [])][:10],
        "status": "research_only", "ai_generated": True,
        "used_in_formal_score": False, "execution_allowed": False,
        "candidate_count": len(evidence["candidate_scope"]),
    }


def run_ai_long_term_research(*, focus: str = "", timeout: int = 600) -> dict[str, Any]:
    cfg = CrawlerConfig()
    ranked = run_recommendation_job(limit=10)
    evidence = build_long_term_evidence(ranked, cfg.data_dir)
    if not evidence["candidate_scope"]:
        raise RuntimeError("没有满足基础权限和数据条件的长线AI候选范围")
    prompt = (
        f"{RULES}\n用户关注点：{focus.strip() or '长期质量、持续性与下行风险'}\n"
        f"证据JSON：\n{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}"
    )
    result = _validate_result(_extract_json(_run_codex(prompt, timeout=timeout)), evidence)
    root = cfg.data_dir / "ai_long_term"
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in (("evidence.json", evidence), ("latest.json", result)):
        temporary = root / f".{name}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(root / name)
    return result
