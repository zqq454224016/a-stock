"""Run a research-only stock diagnosis through the current Codex login."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.pipeline.normalizer import normalize_code

SYSTEM_RULES = """你是 A 股研究助手。只基于给定证据进行客观诊断，不补造新闻或财务事实。
输出 Markdown，依次包含：结论摘要、技术状态、关键证据、主要风险、需要补充的数据。
必须明确数据日期和局限性。不得给出买入、卖出、仓位、目标价或收益承诺。"""

RECOMMENDATION_RULES = """你是 A 股候选研究助手。只允许从给定的量化候选中筛选，不得补造股票、新闻或财务事实。
输出 Markdown，依次包含：市场与数据日期、市场情绪、中报/半年度报告分析、趋势策略与过去一年验证、候选结论表、逐只支持证据、反证与风险、失效条件、缺失数据。
候选表必须包含代码、名称、适用周期、证据强度和是否进入研究候选。数据不足时可以不推荐，禁止为了凑数降低标准。
required_background 中每个背景项都是硬性分析章节，不得省略；缺失数据必须标记 missing，不得推测。
不得给出买入卖出指令、仓位、目标价或收益承诺；必须声明仅供研究、不构成投资建议。"""

MAX_CODEX_INPUT_CHARS = 800_000


def _codex_command() -> str:
    command = os.getenv("CODEX_COMMAND", "codex").strip() or "codex"
    resolved = shutil.which(command)
    if resolved:
        return resolved

    # 从 Finder / LaunchAgent 启动的进程通常没有交互式 shell PATH，
    # 因此显式探测 Codex Desktop 和常见 CLI 安装位置。
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.extend([
            Path("/Applications/Codex.app/Contents/Resources/codex"),
            Path.home() / "Applications/Codex.app/Contents/Resources/codex",
            Path("/opt/homebrew/bin/codex"),
            Path("/usr/local/bin/codex"),
            Path.home() / ".local/bin/codex",
        ])
    elif sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            root = Path(local_appdata) / "OpenAI" / "Codex" / "bin"
            candidates.extend(root.glob("*/codex.exe"))
            candidates.append(root / "codex.exe")
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "npm" / "codex.cmd")
    else:
        candidates.extend([
            Path.home() / ".local/bin/codex",
            Path("/usr/local/bin/codex"),
            Path("/usr/bin/codex"),
        ])

    existing = [path for path in candidates if path.is_file() and os.access(path, os.X_OK)]
    if existing:
        return str(max(existing, key=lambda path: path.stat().st_mtime))
    raise RuntimeError(
        "未找到 Codex CLI。已检查系统 PATH、Codex Desktop 和常见安装目录；"
        "可通过 CODEX_COMMAND 指定可执行文件路径"
    )


def _prepare_codex_home(target: Path) -> None:
    """Reuse login/config while keeping Codex runtime state writable and isolated."""
    source = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    target.mkdir(parents=True, exist_ok=True)
    for name in ("auth.json", "config.toml"):
        source_file = source / name
        if source_file.is_file():
            shutil.copy2(source_file, target / name)


CONTEXT_SOURCES = (
    "factors", "enhance", "sentiment", "predictions", "selector", "decisions",
    "replay", "review", "impact", "attribution", "agent", "today_change",
)


def load_diagnosis_context(code: str, cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    path = cfg.stock_data_dir / f"{code}.json"
    if not path.exists():
        raise FileNotFoundError(f"缺少 {code} 数据，请先运行: ./run.sh stock {code}")
    stock = json.loads(path.read_text(encoding="utf-8"))
    # 保留最近 120 根 K 线，避免长历史挤占 Codex 上下文。
    if isinstance(stock.get("kline"), list):
        stock["kline"] = stock["kline"][-120:]
    context: dict[str, Any] = {"stock": stock, "available_sources": ["stock"]}
    for source in CONTEXT_SOURCES:
        source_path = cfg.data_dir / source / f"{code}.json"
        if not source_path.exists():
            continue
        try:
            context[source] = json.loads(source_path.read_text(encoding="utf-8"))
            context["available_sources"].append(source)
        except (OSError, json.JSONDecodeError):
            continue
    market_path = cfg.data_dir / "latest.json"
    if market_path.exists():
        try:
            context["market"] = json.loads(market_path.read_text(encoding="utf-8"))
            context["available_sources"].append("market")
        except (OSError, json.JSONDecodeError):
            pass
    return context


def _run_codex(prompt: str, *, timeout: int) -> str:
    if len(prompt) > MAX_CODEX_INPUT_CHARS:
        raise RuntimeError(f"Codex 上下文仍过大: {len(prompt)} 字符，请减少候选或上下文")
    with tempfile.TemporaryDirectory(prefix="a-stock-codex-") as workspace:
        workspace_path = Path(workspace)
        codex_home = workspace_path / "codex-home"
        _prepare_codex_home(codex_home)
        last_message = workspace_path / "last-message.md"
        command = [
            _codex_command(), "exec", "--ephemeral", "--sandbox", "read-only",
            "--skip-git-repo-check", "--color", "never",
            "--output-last-message", str(last_message), "-",
        ]
        process_env = os.environ.copy()
        process_env["CODEX_HOME"] = str(codex_home)
        result = subprocess.run(
            command, input=prompt, text=True, capture_output=True, timeout=timeout,
            cwd=workspace, env=process_env, check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Codex 调用失败").strip()
            raise RuntimeError(detail[-1000:])
        content = last_message.read_text(encoding="utf-8").strip() if last_message.exists() else ""
    if not content:
        raise RuntimeError("Codex 未返回内容")
    return content


def diagnose_stock(code: str, *, focus: str = "", timeout: int = 600) -> Path:
    cfg = CrawlerConfig()
    normalized = normalize_code(code)
    if not normalized.isdigit() or len(normalized) != 6:
        raise ValueError(f"股票代码无效: {code}")
    evidence = load_diagnosis_context(normalized, cfg)
    stock = evidence["stock"]
    prompt = (
        f"{SYSTEM_RULES}\n\n股票代码：{normalized}\n"
        f"用户关注点：{focus.strip() or '无'}\n"
        f"可用上下文：{', '.join(evidence['available_sources'])}\n\n证据 JSON：\n"
        f"{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}"
    )
    output_dir = cfg.data_dir / "ai_diagnosis"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{normalized}.md"
    content = _run_codex(prompt, timeout=timeout)
    header = (
        f"# {stock.get('name') or normalized}（{normalized}）AI 诊股\n\n"
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  "
        f"数据日期：{stock.get('trade_date') or stock.get('kline_date') or '未知'}  "
        "仅供研究，不构成投资建议。\n\n"
    )
    output_path.write_text(header + content + "\n", encoding="utf-8")
    return output_path


def recommend_stocks(*, limit: int = 5, focus: str = "", timeout: int = 600) -> Path:
    """Generate an auditable Codex summary from rule-ranked candidates."""
    from quant_system.tasks.recommendation_job import run_recommendation_job
    from quant_system.ai.recommendation_evidence import build_recommendation_evidence, render_fixed_appendix

    cfg = CrawlerConfig()
    ranked = run_recommendation_job(limit=max(1, min(limit, 10)))
    bounded_limit = max(1, min(limit, 10))
    evidence = build_recommendation_evidence(ranked, cfg.data_dir, limit=bounded_limit)
    evidence_json = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    prompt = (
        f"{RECOMMENDATION_RULES}\n\n用户关注点：{focus.strip() or '无'}\n"
        f"最多研究候选数：{bounded_limit}\n\n证据 JSON：\n{evidence_json}"
    )
    output_dir = cfg.data_dir / "ai_recommendations"
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / "evidence.json"
    evidence_tmp = output_dir / ".evidence.json.tmp"
    evidence_tmp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence_tmp.replace(evidence_path)
    # 先固化脚本计算结果；即使 Codex 暂时失败，确定性证据也可审计和复用。
    content = _run_codex(prompt, timeout=timeout)
    output_path = output_dir / "latest.md"
    header = (
        "# AI 股票研究候选\n\n"
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  "
        f"量化候选版本：{ranked.get('recommendation_version') or '未知'}  "
        "仅供研究，不构成投资建议。\n\n"
    )
    output_path.write_text(header + content + "\n\n" + render_fixed_appendix(evidence), encoding="utf-8")
    return output_path
