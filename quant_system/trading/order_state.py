"""Paper-trading order lifecycle (no broker). Used to validate recommendation fills."""

from __future__ import annotations

from typing import Any

ORDER_STATE_MACHINE_VERSION = "1.0.0"

# Terminal and non-terminal states for recommendation paper simulation.
ORDER_STATES = (
    "pending",
    "accepted",
    "partial",
    "filled",
    "rejected",
    "cancelled",
)

_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"accepted", "rejected", "cancelled"}),
    "accepted": frozenset({"partial", "filled", "rejected", "cancelled"}),
    "partial": frozenset({"partial", "filled", "cancelled"}),
    "filled": frozenset(),
    "rejected": frozenset(),
    "cancelled": frozenset(),
}


def can_transition(current: str, nxt: str) -> bool:
    return nxt in _TRANSITIONS.get(str(current), frozenset())


def transition(order: dict[str, Any], nxt: str, *, reason: str | None = None) -> dict[str, Any]:
    """Apply a legal state transition; illegal moves raise ValueError."""
    current = str(order.get("status") or "pending")
    if not can_transition(current, nxt):
        raise ValueError(f"illegal order transition {current} -> {nxt}")
    updated = dict(order)
    updated["status"] = nxt
    updated["previous_status"] = current
    if reason:
        updated["status_reason"] = reason
    return updated


def resolve_fill_status(*, requested_shares: int, filled_shares: int) -> str:
    if filled_shares <= 0:
        return "rejected"
    if filled_shares < requested_shares:
        return "partial"
    return "filled"


def capabilities() -> dict[str, Any]:
    return {
        "version": ORDER_STATE_MACHINE_VERSION,
        "scope": "paper_recommendation_only",
        "broker_integration": False,
        "states": list(ORDER_STATES),
        "supports": [
            "pending_accept_reject",
            "partial_fill",
            "full_fill",
            "cancel_before_terminal",
            "idempotent_client_order_id",
        ],
    }
