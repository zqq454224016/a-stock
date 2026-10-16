import json
import sys
from pathlib import Path
from types import SimpleNamespace

from quant_system.ai import codex_diagnosis


def test_diagnosis_uses_read_only_ephemeral_codex(monkeypatch, tmp_path):
    stock_dir = tmp_path / "stocks"
    stock_dir.mkdir()
    (stock_dir / "600519.json").write_text(json.dumps({"code": "600519", "name": "贵州茅台", "trade_date": "2026-07-17"}), encoding="utf-8")
    cfg = SimpleNamespace(stock_data_dir=stock_dir, data_dir=tmp_path)
    monkeypatch.setattr(codex_diagnosis, "CrawlerConfig", lambda: cfg)
    monkeypatch.setattr(codex_diagnosis, "_codex_command", lambda: "/usr/bin/codex")

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("## 结论摘要\n趋势中性。", encoding="utf-8")
        assert "--ephemeral" in command
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert "不得给出买入" in kwargs["input"]
        assert kwargs["env"]["CODEX_HOME"].endswith("codex-home")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(codex_diagnosis.subprocess, "run", fake_run)
    output = codex_diagnosis.diagnose_stock("600519")
    content = output.read_text(encoding="utf-8")
    assert "贵州茅台" in content
    assert "仅供研究" in content


def test_context_merges_available_evidence(tmp_path):
    stock_dir = tmp_path / "stocks"
    factor_dir = tmp_path / "factors"
    stock_dir.mkdir()
    factor_dir.mkdir()
    (stock_dir / "600519.json").write_text(json.dumps({"code": "600519", "kline": list(range(150))}), encoding="utf-8")
    (factor_dir / "600519.json").write_text(json.dumps({"rsi": 55}), encoding="utf-8")
    cfg = SimpleNamespace(stock_data_dir=stock_dir, data_dir=tmp_path)
    context = codex_diagnosis.load_diagnosis_context("600519", cfg)
    assert context["available_sources"] == ["stock", "factors"]
    assert len(context["stock"]["kline"]) == 120
    assert context["factors"]["rsi"] == 55


def test_codex_command_finds_macos_desktop_when_path_is_minimal(monkeypatch):
    monkeypatch.delenv("CODEX_COMMAND", raising=False)
    monkeypatch.setattr(codex_diagnosis.shutil, "which", lambda _: None)
    monkeypatch.setattr(codex_diagnosis.sys, "platform", "darwin")
    original_is_file = Path.is_file
    original_access = codex_diagnosis.os.access

    monkeypatch.setattr(Path, "is_file", lambda self: str(self) == "/Applications/Codex.app/Contents/Resources/codex")
    monkeypatch.setattr(codex_diagnosis.os, "access", lambda path, mode: str(path) == "/Applications/Codex.app/Contents/Resources/codex")
    monkeypatch.setattr(Path, "stat", lambda self: SimpleNamespace(st_mtime=1))
    try:
        assert codex_diagnosis._codex_command() == "/Applications/Codex.app/Contents/Resources/codex"
    finally:
        monkeypatch.setattr(Path, "is_file", original_is_file)
        monkeypatch.setattr(codex_diagnosis.os, "access", original_access)


def test_ai_recommendation_uses_ranked_candidates(monkeypatch, tmp_path):
    stock_dir = tmp_path / "stocks"
    stock_dir.mkdir()
    (stock_dir / "600519.json").write_text(json.dumps({
        "code": "600519", "name": "贵州茅台", "trade_date": "2026-07-21",
    }), encoding="utf-8")
    cfg = SimpleNamespace(stock_data_dir=stock_dir, data_dir=tmp_path)
    monkeypatch.setattr(codex_diagnosis, "CrawlerConfig", lambda: cfg)

    from quant_system.tasks import recommendation_job
    monkeypatch.setattr(recommendation_job, "run_recommendation_job", lambda limit: {
        "recommendation_version": "test", "periods": {
            "short": {
                "recommendations": [{"code": "600519", "name": "贵州茅台", "score": 80}],
                "evaluated": [{"code": f"{index:06d}", "debug_blob": "x" * 1000} for index in range(6000)],
            },
        },
    })
    captured = {}

    def fake_codex(prompt, timeout):
        captured["prompt"] = prompt
        return "## 候选结论表\n600519 进入研究候选。"

    monkeypatch.setattr(codex_diagnosis, "_run_codex", fake_codex)
    output = codex_diagnosis.recommend_stocks(limit=3, focus="现金流")

    assert "600519" in captured["prompt"]
    assert "不得给出买入卖出指令" in captured["prompt"]
    assert "现金流" in captured["prompt"]
    assert "debug_blob" not in captured["prompt"]
    assert '"evaluated_count":6000' in captured["prompt"]
    assert len(captured["prompt"]) < codex_diagnosis.MAX_CODEX_INPUT_CHARS
    report = output.read_text(encoding="utf-8")
    assert "仅供研究" in report
    assert "固定计算附录" in report
    assert "固定评分 80" in report
    evidence = json.loads((tmp_path / "ai_recommendations" / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["evidence_policy"]["ai_may_not_recalculate_scores"] is True
    assert evidence["periods"]["short"]["evaluated_count"] == 6000


def test_recommendation_evidence_excludes_raw_market_rows(tmp_path):
    from quant_system.ai.recommendation_evidence import build_recommendation_evidence

    stock_dir = tmp_path / "stocks"
    factor_dir = tmp_path / "factors"
    enhance_dir = tmp_path / "enhance"
    sentiment_dir = tmp_path / "sentiment"
    stock_dir.mkdir()
    factor_dir.mkdir()
    enhance_dir.mkdir()
    sentiment_dir.mkdir()
    (stock_dir / "600519.json").write_text(json.dumps({
        "code": "600519", "name": "贵州茅台", "trade_date": "2026-07-21",
        "kline": [{"trade_date": str(index), "close": index} for index in range(5000)],
        "analysis": {"trend": "up", "returns": {"20d": 8.5}},
    }), encoding="utf-8")
    (factor_dir / "600519.json").write_text(json.dumps({
        "factors": {"multi_factor_score": 72.5, "debug_blob": "x" * 2_000_000},
    }), encoding="utf-8")
    (enhance_dir / "600519.json").write_text(json.dumps({
        "fundamentals": {"report_period": "2026-06-30", "net_profit_growth_pct": 12.3, "pe_ttm": 20},
    }), encoding="utf-8")
    (sentiment_dir / "600519.json").write_text(json.dumps({
        "factors": {"trade_date": "2026-07-21", "label": "看多", "heat_index": 80},
    }), encoding="utf-8")
    ranked = {
        "market_context": {"trade_date": "2026-07-21"},
        "periods": {"short": {
            "recommendations": [{"code": "600519", "name": "贵州茅台", "score": 80}],
            "evaluated": [{"code": str(index), "raw": "x" * 1000} for index in range(100)],
        }},
    }

    evidence = build_recommendation_evidence(ranked, tmp_path, limit=5)
    encoded = json.dumps(evidence, ensure_ascii=False)

    assert "kline" not in encoded
    assert "debug_blob" not in encoded
    assert '"raw"' not in encoded
    assert evidence["candidate_metrics"]["600519"]["factors"]["multi_factor_score"] == 72.5
    assert evidence["candidate_metrics"]["600519"]["interim_report_context"]["status"] == "available"
    assert evidence["candidate_metrics"]["600519"]["stock_sentiment_context"]["label"] == "看多"
    assert evidence["required_background"]["hard_required"] is True
    assert len(encoded) < 10_000


def test_recommendation_evidence_filters_stale_permission_board_candidates(tmp_path):
    from quant_system.ai.recommendation_evidence import build_recommendation_evidence

    ranked = {"periods": {"short": {
        "recommendations": [
            {"code": "688001", "name": "科创测试", "score": 99},
            {"code": "300750", "name": "创业板测试", "score": 98},
            {"code": "920001", "name": "北交所测试", "score": 97},
            {"code": "600001", "name": "主板测试", "score": 80},
        ],
        "observation": [{"code": "689009", "name": "科创观察", "score": 70}],
    }}}

    evidence = build_recommendation_evidence(ranked, tmp_path, limit=5)

    assert [item["code"] for item in evidence["periods"]["short"]["recommended"]] == ["600001"]
    assert evidence["periods"]["short"]["observation"] == []
    assert set(evidence["candidate_metrics"]) == {"600001"}


def test_codex_rejects_oversized_prompt_before_subprocess(monkeypatch):
    monkeypatch.setattr(codex_diagnosis.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")))
    try:
        codex_diagnosis._run_codex("x" * (codex_diagnosis.MAX_CODEX_INPUT_CHARS + 1), timeout=1)
    except RuntimeError as exc:
        assert "上下文仍过大" in str(exc)
    else:
        raise AssertionError("oversized prompt must fail before spawning Codex")
