import pandas as pd

from quant_system.strategy.portfolio_execution import simulate_portfolio


def test_portfolio_enforces_position_capacity_and_cash():
    rows = pd.DataFrame([
        {"code": f"600{i:03d}", "entry_date": "2026-01-02", "exit_date": "2026-01-10", "net_return": 0.10, "signal_score": 100 - i}
        for i in range(12)
    ])
    # Disable daily cap to isolate max_positions behavior.
    result = simulate_portfolio(rows, max_positions=10, max_entries_per_day=0)
    assert result["accepted_trades"] == 10
    assert result["rejected_capacity"] == 2
    assert result["max_concurrent_positions"] == 10
    assert result["total_return_pct"] == 9.5
    assert result["ending_equity"] == 54750.0


def test_portfolio_exits_before_same_day_entries():
    rows = pd.DataFrame([
        {"code": "600001", "entry_date": "2026-01-02", "exit_date": "2026-01-10", "net_return": 0.10},
        {"code": "600002", "entry_date": "2026-01-10", "exit_date": "2026-01-20", "net_return": -0.10},
    ])
    result = simulate_portfolio(
        rows, max_positions=1, max_single_weight=1, max_gross_exposure=1, max_entries_per_day=0,
    )
    assert result["accepted_trades"] == 2
    assert result["rejected_capacity"] == 0
    assert result["total_return_pct"] == -1.0
    assert result["max_drawdown_pct"] == -10.0


def test_portfolio_uses_daily_marks_for_intraholding_drawdown():
    rows = pd.DataFrame([{
        "code": "600001", "entry_date": "2026-01-02", "exit_date": "2026-01-05",
        "net_return": 0.10,
        "daily_marks": [
            {"date": "2026-01-02", "return": 0},
            {"date": "2026-01-03", "return": -0.20},
            {"date": "2026-01-05", "return": 0.10},
        ],
    }])
    result = simulate_portfolio(
        rows, max_positions=1, max_single_weight=1, max_gross_exposure=1, max_entries_per_day=0,
    )
    assert result["model"] == "daily_marking_v2"
    assert result["max_drawdown_pct"] == -20.0
    assert result["ending_equity"] == 55000


def test_portfolio_selects_highest_existing_signal_score_on_same_day():
    rows = pd.DataFrame([
        {
            "code": "600001", "entry_date": "2026-01-02", "exit_date": "2026-01-10",
            "signal_score": 60, "net_return": -0.10,
        },
        {
            "code": "600999", "entry_date": "2026-01-02", "exit_date": "2026-01-10",
            "signal_score": 90, "net_return": 0.10,
        },
    ])
    result = simulate_portfolio(
        rows, max_positions=1, max_single_weight=1, max_gross_exposure=1, max_entries_per_day=0,
    )
    assert result["accepted_trades"] == 1
    assert result["rejected_capacity"] == 1
    assert result["ending_equity"] == 55000
    assert "signal_score_desc" in result["entry_selection"]


def test_portfolio_caps_same_day_entries_to_reduce_correlation_flood():
    rows = pd.DataFrame([
        {
            "code": f"600{i:03d}", "entry_date": "2026-01-02", "exit_date": "2026-01-10",
            "signal_score": 100 - i, "net_return": 0.05,
        }
        for i in range(8)
    ])
    result = simulate_portfolio(rows, max_positions=10, max_entries_per_day=2)
    assert result["accepted_trades"] == 2
    assert result["rejected_daily_cap"] == 6
    assert result["limits"]["max_entries_per_day"] == 2
