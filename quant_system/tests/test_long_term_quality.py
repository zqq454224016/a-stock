from quant_system.strategy.long_term_quality import exit_on_quality_break, quality_gate


def test_quality_gate_fails_closed_on_missing_point_in_time_fields():
    result = quality_gate({"revenue_growth": 1.0})
    assert result["passed"] is False
    assert "profit_growth" in result["missing"]


def test_quality_gate_requires_cashflow_and_debt_discipline():
    good = quality_gate({"revenue_growth": 0.1, "profit_growth": 0.2, "operating_cash_flow": 10, "debt_to_assets": 0.4})
    bad = quality_gate({"revenue_growth": 0.1, "profit_growth": 0.2, "operating_cash_flow": -1, "debt_to_assets": 0.8})
    assert good["passed"] is True
    assert bad["passed"] is False


def test_quality_exit_requires_confirmed_multi_dimension_deterioration():
    prev = {"revenue_growth": .2, "profit_growth": .3, "operating_cash_flow": 10, "debt_to_assets": .4}
    current = {"revenue_growth": -.1, "profit_growth": -.2, "operating_cash_flow": -5, "debt_to_assets": .5}
    assert exit_on_quality_break(prev, current)["exit"] is True
