"""可选复用 tickflow-stock-panel 的 stock-sdk 桥接。"""
from __future__ import annotations
import json, os, subprocess
from pathlib import Path
import pandas as pd

BRIDGE = Path(os.getenv("STOCK_SDK_BRIDGE", "/Users/zhangqiqi/stock/tickflow-stock-panel/backend/app/plugins/stocksdk/bridge.mjs"))
NODE = os.getenv("STOCK_SDK_NODE", "node")

def fetch_daily(symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    if not BRIDGE.exists(): return pd.DataFrame()
    job = {"op":"daily", "symbols":[symbol], "adjust":"none", "period":"daily"}
    if start: job["start"] = start.replace("-", "")
    if end: job["end"] = end.replace("-", "")
    try:
        p = subprocess.run([NODE, str(BRIDGE)], input=json.dumps(job)+"\n", text=True,
                           capture_output=True, timeout=120, cwd=str(BRIDGE.parent))
        payload = json.loads((p.stdout or "").strip())
        rows = (payload.get("rows") or {}).get(symbol) or []
        return pd.DataFrame(rows)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
        return pd.DataFrame()

def fetch_minute(symbol: str, period: int = 5) -> pd.DataFrame:
    if not BRIDGE.exists(): return pd.DataFrame()
    try:
        p = subprocess.run([NODE, str(BRIDGE)], input=json.dumps({"op":"minute","symbols":[symbol],"period":period})+"\n", text=True, capture_output=True, timeout=90, cwd=str(BRIDGE.parent))
        payload=json.loads((p.stdout or '').strip()); rows=(payload.get('rows') or {}).get(symbol) or []
        return pd.DataFrame(rows)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
        return pd.DataFrame()
