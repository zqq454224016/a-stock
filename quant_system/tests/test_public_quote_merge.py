from quant_system.tasks.public_quote_merge_job import _merge_row


def test_merge_row_scales_raw_quote_into_existing_qfq_basis():
    row = _merge_row(
        {"close": 10.0},
        {
            "symbol": "600000.SH", "name": "浦发银行", "previous_close": 20,
            "open": 20.2, "high": 21, "low": 20, "price": 20.8,
            "volume_lot": 100, "amount_yi": 1.5, "turnover_pct": 0.8,
        },
        "2026-07-24", "600000",
    )
    assert row is not None
    assert row["qfq_scale"] == 0.5
    assert row["close"] == 10.4
    assert row["amount"] == 150_000_000
