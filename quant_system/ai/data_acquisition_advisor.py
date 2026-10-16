"""Codex advisor restricted to data-acquisition methods and source gaps."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from quant_system.ai.codex_diagnosis import _run_codex
from quant_system.ai.prompts.data_acquisition import (
    PROMPT_VERSION,
    build_planner_prompt,
    extract_json_object,
    normalize_plan,
    render_plan_markdown,
    score_plan,
    validate_plan,
)
from quant_system.config.app_config import tickflow_config, tushare_config
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.time_utils import now_str

RULES = "Prompt 已迁移到 quant_system.ai.prompts.data_acquisition，保留此常量用于兼容审计。"


def acquisition_evidence(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()

    def read(rel: str) -> dict[str, Any]:
        try:
            value = json.loads((cfg.data_dir / rel).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    iteration = read("iteration/status.json")
    interim = read("interim_reports/index.json")
    phase1 = read("manifests/phase1_market_data.json")
    return {
        "iteration": {
            "policy_version": iteration.get("policy_version"),
            "phase": iteration.get("phase"),
            "failed_gates": iteration.get("failed_gates") or [],
            "data": iteration.get("data") or {},
            "next_actions": iteration.get("next_actions") or [],
        },
        "configured_sources": {
            "tickflow": bool(tickflow_config()["api_key"]),
            "tushare": bool(cfg.tushare_enabled and tushare_config()["token"]),
        },
        "financial_dataset": {
            "status": interim.get("status"),
            "period": interim.get("period"),
            "count": interim.get("count"),
            "failed_endpoints": sorted((interim.get("source_errors") or {}).keys()),
        },
        "phase1": {
            "status": phase1.get("status"),
            "datasets": phase1.get("datasets") or phase1.get("results") or [],
        },
        "constraints": {
            "ai_scope": "data_acquisition_methods_only",
            "no_strategy_parameter_changes": True,
            "no_source_credentials_in_prompt": True,
        },
    }


def evidence_fingerprint(evidence: dict[str, Any]) -> str:
    canonical = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def generate_data_acquisition_advice(
    cfg: CrawlerConfig | None = None,
    *,
    timeout: int = 600,
) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    evidence = acquisition_evidence(cfg)
    fingerprint = evidence_fingerprint(evidence)
    prompt = build_planner_prompt(evidence)
    root = cfg.data_dir / "iteration"
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root / "data_acquisition_advice.raw.txt"
    previous_path = root / "data_acquisition_advice.json"
    try:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        previous = {}
    reuse_rejected_raw = (
        previous.get("status") in {"failed", "rejected"}
        and previous.get("fingerprint") == fingerprint
        and raw_path.exists()
    )
    content = raw_path.read_text(encoding="utf-8") if reuse_rejected_raw else _run_codex(prompt, timeout=timeout)
    payload = extract_json_object(content)
    repairs = normalize_plan(payload)
    errors = validate_plan(payload)
    evaluation = score_plan(payload, errors)
    if not reuse_rejected_raw:
        raw_path.write_text(content, encoding="utf-8")
    if not evaluation["passed"]:
        rejected = {
            "updated_at": now_str(),
            "fingerprint": fingerprint,
            "status": "rejected",
            "scope": "data_acquisition_methods_only",
            "prompt_version": PROMPT_VERSION,
            "evaluation": evaluation,
            "raw_artifact": "iteration/data_acquisition_advice.raw.txt",
        }
        temporary = (root / "data_acquisition_advice.json").with_suffix(".tmp")
        temporary.write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(root / "data_acquisition_advice.json")
        raise RuntimeError(f"AI 数据获取方案未通过契约评分: {evaluation}")
    advice_path = root / "data_acquisition_advice.md"
    advice_path.write_text(render_plan_markdown(payload, evaluation), encoding="utf-8")
    plan_path = root / "data_acquisition_plan.json"
    plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata = {
        "updated_at": now_str(),
        "fingerprint": fingerprint,
        "status": "complete",
        "scope": "data_acquisition_methods_only",
        "prompt_version": PROMPT_VERSION,
        "evaluation": evaluation,
        "contract_repairs": repairs,
        "reused_rejected_raw": reuse_rejected_raw,
        "artifact": "iteration/data_acquisition_advice.md",
        "plan_artifact": "iteration/data_acquisition_plan.json",
    }
    temporary = (root / "data_acquisition_advice.json").with_suffix(".tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(root / "data_acquisition_advice.json")
    return metadata
