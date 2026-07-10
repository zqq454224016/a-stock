from __future__ import annotations

from quant_system.planning import build_v3_roadmap


def test_v3_roadmap_has_unique_next_step() -> None:
    payload = build_v3_roadmap()

    assert payload["roadmap_version"].startswith("3.")
    assert payload["current_next"]["id"] == "V3-03"
    assert sum(1 for item in payload["phases"] if item["status"] == "next") == 1
    assert payload["current_next"]["acceptance"]


def test_v3_roadmap_prioritizes_stability_before_expansion() -> None:
    payload = build_v3_roadmap()
    ids = [item["id"] for item in payload["phases"]]

    assert ids.index("V3-01") < ids.index("V3-03")
    assert ids.index("V3-02") < ids.index("V3-04")
