from dataclasses import dataclass


@dataclass
class KLine:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    adj_factor: float = 1.0
