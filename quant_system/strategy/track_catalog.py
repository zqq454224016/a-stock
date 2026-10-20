"""把所有并行策略按持有期归并为四条产品轨道。

轨道只由持有天数决定，不看名字：≤2 日为超短线，3–10 日为短线，≥11 日为长线；
防守/反转轨道是 ETF 与现金，不和个股多头混算。
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_system.strategy import aggressive_board, overnight, tail_overnight
from quant_system.strategy.defensive_etf import SPECS as DEFENSIVE_SPECS
from quant_system.strategy.robust_iteration import CANDIDATES

TRACK_LONG = "long"
TRACK_SHORT = "short_3_5"
TRACK_ULTRA = "ultra_1_2"
TRACK_DEFENSIVE = "defensive_reversal"

TRACKS = {
    TRACK_LONG: {"label": "长线持有", "holding": "≥11个交易日（含20日波段与60日中长线）"},
    TRACK_SHORT: {"label": "短线", "holding": "3–10个交易日，目标3–5日"},
    TRACK_ULTRA: {"label": "超短线", "holding": "1–2个交易日（尾盘买次日卖 / 次日开盘买隔日卖）"},
    TRACK_DEFENSIVE: {"label": "防守/反转", "holding": "3–5个交易日，ETF或现金"},
}


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    source: str        # robust | tail | overnight | aggressive | defensive
    track: str
    family: str        # 同一信号形态的不同参数/出场归为一族
    hold_days: int
    baseline: bool = False


def track_for_hold_days(days: int) -> str:
    if days <= 2:
        return TRACK_ULTRA
    if days <= 10:
        return TRACK_SHORT
    return TRACK_LONG


def build_catalog() -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for candidate in CANDIDATES:
        track = track_for_hold_days(candidate.max_hold_days)
        entries.append(CatalogEntry(
            candidate.name, "robust", track,
            f"{track}:robust:{candidate.mode}", candidate.max_hold_days, candidate.mode == "baseline",
        ))
    for spec in tail_overnight.SPECS:
        entries.append(CatalogEntry(spec.name, "tail", TRACK_ULTRA, f"tail:{spec.mode}", 1))
    for spec in overnight.SPECS:
        entries.append(CatalogEntry(spec.name, "overnight", TRACK_ULTRA, f"overnight:{spec.mode}", 1))
    for spec in aggressive_board.SPECS:
        track = track_for_hold_days(spec.max_hold_days)
        entries.append(CatalogEntry(
            spec.name, "aggressive", track, f"{track}:aggressive:{spec.mode}", spec.max_hold_days,
        ))
    for spec in DEFENSIVE_SPECS:
        entries.append(CatalogEntry(
            spec.name, "defensive", TRACK_DEFENSIVE, f"defensive:{spec.kind}", spec.hold_days,
            spec.kind == "baseline",
        ))
    return entries
