from datetime import datetime, timezone

import pytest

from quant_system.application import UniverseService
from quant_system.domain.datasets import DataLayer, dataset_spec
from quant_system.domain.evidence import EvidenceMeta


def test_dataset_catalog_marks_point_in_time_data():
    financial = dataset_spec("financial.statements")
    assert financial.layer == DataLayer.NORMALIZED
    assert financial.requires_known_at is True


def test_evidence_rejects_known_at_before_publication():
    published = datetime(2026, 7, 20, 18, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="known_at"):
        EvidenceMeta(
            dataset="events.announcements",
            source="official",
            as_of="2026-07-20",
            fetched_at=published,
            published_at=published,
            known_at=datetime(2026, 7, 20, 17, tzinfo=timezone.utc),
        )


def test_universe_service_uses_ports():
    class Provider:
        name = "test"

        def fetch_instruments(self):
            return [{"code": "600000", "symbol": "600000.SH", "name": "浦发银行", "exchange": "SH"}]

    class Repository:
        def __init__(self):
            self.rows = []

        def save(self, rows, *, source):
            self.rows = rows
            self.source = source

        def load(self):
            return self.rows

    repository = Repository()
    service = UniverseService(Provider(), repository)
    assert service.refresh()[0]["code"] == "600000"
    assert repository.source == "test"
    assert service.load() == repository.rows
