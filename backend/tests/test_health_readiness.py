from fastapi import HTTPException

from app import main


class FakeDb:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.closed = False

    def execute(self, _statement):
        if self.fail:
            raise RuntimeError("database unavailable")
        return None

    def close(self):
        self.closed = True


def test_live_payload_is_lightweight():
    payload = main._live_payload()

    assert payload["status"] == "ok"
    assert payload["app"]


def test_ready_payload_reports_ok_when_database_and_vector_are_available(monkeypatch):
    fake_db = FakeDb()
    monkeypatch.setattr(main, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        main.knowledge_service,
        "vector_status",
        lambda _db: {"available": True, "chunks": 2, "embedded_chunks": 2},
    )

    payload = main._ready_payload()

    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["vector"]["available"] is True
    assert fake_db.closed is True


def test_ready_payload_degrades_when_vector_is_unavailable(monkeypatch):
    fake_db = FakeDb()
    monkeypatch.setattr(main, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        main.knowledge_service,
        "vector_status",
        lambda _db: {"available": False, "error": "pgvector missing"},
    )

    payload = main._ready_payload()

    assert payload["status"] == "degraded"
    assert payload["database"] == "ok"
    assert fake_db.closed is True


def test_ready_payload_returns_503_when_database_is_unavailable(monkeypatch):
    fake_db = FakeDb(fail=True)
    monkeypatch.setattr(main, "SessionLocal", lambda: fake_db)

    try:
        main._ready_payload()
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail["status"] == "unavailable"
        assert exc.detail["database"] == "error"
    else:
        raise AssertionError("Expected HTTPException")

    assert fake_db.closed is True
