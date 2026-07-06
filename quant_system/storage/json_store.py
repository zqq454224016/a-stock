"""JSON 文件存储（本地默认）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


class JsonStore:
    def __init__(self, config: DBConfig | None = None):
        self.config = config or DBConfig()

    def write(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("JSON 已写入 %s", path)

    def read(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def save_market_snapshot(self, data: dict[str, Any]) -> Path:
        path = self.config.json_data_dir / "latest.json"
        self.write(path, data)
        return path

    def save_stock_analysis(self, code: str, data: dict[str, Any]) -> Path:
        path = self.config.json_data_dir / "stocks" / f"{code}.json"
        self.write(path, data)
        return path

    def save_stock_index(self, stocks: list[dict], updated_at: str) -> Path:
        path = self.config.json_data_dir / "stocks" / "index.json"
        self.write(path, {"updated_at": updated_at, "stocks": stocks})
        return path

    def live_dir(self) -> Path:
        return self.config.json_data_dir / "stocks" / "live"

    def save_live_stock(self, code: str, data: dict[str, Any]) -> Path:
        path = self.live_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_live_index(self, stocks: list[dict], updated_at: str) -> Path:
        path = self.live_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "stocks": stocks})
        return path

    def factors_dir(self) -> Path:
        return self.config.json_data_dir / "factors"

    def save_factors(self, code: str, data: dict[str, Any]) -> Path:
        path = self.factors_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_factor_index(self, stocks: list[dict], updated_at: str) -> Path:
        path = self.factors_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "stocks": stocks})
        return path

    def signals_dir(self) -> Path:
        return self.config.json_data_dir / "signals"

    def save_signal(self, code: str, data: dict[str, Any]) -> Path:
        path = self.signals_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def sentiment_dir(self) -> Path:
        return self.config.json_data_dir / "sentiment"

    def save_sentiment(self, code: str, data: dict[str, Any]) -> Path:
        path = self.sentiment_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_sentiment_index(self, items: list[dict], updated_at: str) -> Path:
        path = self.sentiment_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "stocks": items})
        return path

    def enhance_dir(self) -> Path:
        return self.config.json_data_dir / "enhance"

    def save_enhance(self, code: str, data: dict[str, Any]) -> Path:
        path = self.enhance_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_enhance_index(self, items: list[dict], updated_at: str) -> Path:
        path = self.enhance_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "stocks": items})
        return path

    def indices_dir(self) -> Path:
        return self.config.json_data_dir / "indices"

    def save_index_benchmarks(self, market: dict[str, Any], updated_at: str) -> Path:
        path = self.indices_dir() / "benchmarks.json"
        payload = {
            "updated_at": updated_at,
            "trade_date": market.get("trade_date"),
            "indices": market.get("indices") or [],
            "fund_flow": market.get("fund_flow") or {},
        }
        self.write(path, payload)
        return path

    def agent_dir(self) -> Path:
        return self.config.json_data_dir / "agent"

    def save_agent_report(self, code: str, data: dict[str, Any]) -> Path:
        path = self.agent_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_agent_index(self, items: list[dict], updated_at: str) -> Path:
        path = self.agent_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "reports": items})
        return path

    def decisions_dir(self) -> Path:
        return self.config.json_data_dir / "decisions"

    def save_decision(self, code: str, data: dict[str, Any]) -> Path:
        path = self.decisions_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_decision_index(self, items: list[dict], updated_at: str) -> Path:
        path = self.decisions_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "decisions": items})
        return path

    def selector_dir(self) -> Path:
        return self.config.json_data_dir / "selector"

    def save_selector(self, code: str, data: dict[str, Any]) -> Path:
        path = self.selector_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_selector_index(self, items: list[dict], updated_at: str) -> Path:
        path = self.selector_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "items": items})
        return path

    def impact_dir(self) -> Path:
        return self.config.json_data_dir / "impact"

    def save_impact(self, code: str, data: dict[str, Any]) -> Path:
        path = self.impact_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_impact_index(self, items: list[dict], updated_at: str) -> Path:
        path = self.impact_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "items": items})
        return path

    def quality_dir(self) -> Path:
        return self.config.json_data_dir / "quality"

    def save_quality_report(self, data: dict[str, Any]) -> Path:
        from quant_system.utils.time_utils import today_str
        path = self.quality_dir() / f"inspect_{today_str().replace('-', '')}.json"
        self.write(path, data)
        latest = self.quality_dir() / "latest.json"
        self.write(latest, data)
        return path

    def backtest_dir(self) -> Path:
        return self.config.json_data_dir / "backtest"

    def save_backtest(self, code: str, strategy: str, data: dict[str, Any]) -> Path:
        path = self.backtest_dir() / f"{code}_{strategy}.json"
        self.write(path, data)
        return path

    def save_backtest_index(self, items: list[dict], updated_at: str) -> Path:
        path = self.backtest_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "results": items})
        return path

    def predictions_dir(self) -> Path:
        return self.config.json_data_dir / "predictions"

    def save_prediction(self, code: str, data: dict[str, Any]) -> Path:
        path = self.predictions_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_prediction_index(self, items: list[dict], updated_at: str) -> Path:
        path = self.predictions_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "predictions": items})
        return path

    def trading_dir(self) -> Path:
        return self.config.json_data_dir / "trading"

    def save_trading_account(self, data: dict[str, Any]) -> Path:
        path = self.trading_dir() / "account.json"
        self.write(path, data)
        return path

    def save_trading_index(self, data: dict[str, Any]) -> Path:
        path = self.trading_dir() / "index.json"
        self.write(path, data)
        return path

    def load_mock_market(self) -> dict[str, Any]:
        path = self.config.json_data_dir / "latest.json"
        if path.exists():
            data = self.read(path)
            from quant_system.utils.time_utils import now_str
            data["updated_at"] = now_str()
            return data
        return {
            "trade_date": "",
            "indices": [],
            "market_distribution": [],
            "top_gainers": [],
            "top_losers": [],
            "industries": [],
            "fund_flow": {},
            "updated_at": "",
        }
