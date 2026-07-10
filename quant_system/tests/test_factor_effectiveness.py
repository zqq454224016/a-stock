from __future__ import annotations

from quant_system.evaluation.factor_effectiveness import build_factor_effectiveness_payload


def _stock(code: str, days: int = 105) -> dict:
    kline = []
    for i in range(days):
        close = 100 + i * 0.18 + ((i % 9) - 4) * 0.35
        kline.append({
            "date": f"第{i + 1}日",
            "open": close - 0.2,
            "high": close + 0.8,
            "low": close - 0.9,
            "close": close,
            "volume": 100_000 + (i % 13) * 7_000,
        })
    return {"code": code, "kline": kline}


def test_factor_effectiveness_builds_horizon_and_drift_results() -> None:
    payload = build_factor_effectiveness_payload(
        stocks={"600001": _stock("600001")},
        current_factors={
            "600001": {"factors": {"technical_score": 65, "ma20_bias": 2.1, "rsi14": 58}}
        },
        horizons=(1, 5),
    )

    assert payload["sample_count"] > 20
    assert payload["horizons"] == ["1d", "5d"]
    assert payload["factors"]["technical_score"]["1d"]["sample_count"] > 20
    assert payload["factors"]["ma20_bias"]["5d"]["stratified"]["groups"]
    assert payload["drift"]["ma20_bias"]["status"] in {"正常", "异常偏高", "异常偏低"}


def test_factor_effectiveness_handles_short_history() -> None:
    payload = build_factor_effectiveness_payload(
        stocks={"600001": _stock("600001", days=50)},
        horizons=(1,),
    )

    assert payload["sample_count"] == 0
    assert payload["factors"]["technical_score"]["1d"]["direction"] == "样本不足"
    assert payload["drift"]["technical_score"]["status"] == "样本不足"
