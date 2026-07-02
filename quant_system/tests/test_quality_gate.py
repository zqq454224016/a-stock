"""质量门禁单元测试。"""

from quant_system.pipeline.quality_gate import factor_block_reason, is_backtest_eligible, is_factor_eligible


def test_factor_eligible_ok():
    q = {"quality_score": 95, "status": "ok"}
    assert is_factor_eligible(q)
    assert factor_block_reason(q) is None


def test_factor_blocked_low_score():
    q = {"quality_score": 65, "status": "error"}
    assert not is_factor_eligible(q)
    assert "65" in factor_block_reason(q)


def test_backtest_eligible():
    assert is_backtest_eligible({"quality_score": 92})
    assert not is_backtest_eligible({"quality_score": 80})
    assert is_backtest_eligible({"quality_score": 80}, allow_warn=True)
