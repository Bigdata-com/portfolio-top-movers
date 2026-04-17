"""HTTP API tests (auth, public routes, job storage wiring)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from services.job_storage import JobStatus, job_storage


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_watchlist_public_no_bigdata_header(client: TestClient) -> None:
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    data = r.json()
    assert "watchlist" in data
    assert data["count"] >= 1


def test_topics_public(client: TestClient) -> None:
    r = client.get("/api/topics")
    assert r.status_code == 200
    body = r.json()
    assert "topics_mini" in body
    assert "topics_standard" in body
    assert len(body["topics_standard"]) >= 20


def test_public_config_reflects_server_bigdata(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BIGDATA_API_KEY", raising=False)
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["server_has_bigdata_key"] is False

    monkeypatch.setenv("BIGDATA_API_KEY", "srv")
    r2 = client.get("/api/config")
    assert r2.status_code == 200
    assert r2.json()["server_has_bigdata_key"] is True


def test_reports_401_when_no_bigdata_key_available(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BIGDATA_API_KEY", raising=False)
    r = client.get("/api/reports")
    assert r.status_code == 401


def test_reports_200_when_server_bigdata_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIGDATA_API_KEY", "server-bigdata-test")
    r = client.get("/api/reports")
    assert r.status_code == 200
    assert r.json()["jobs"] == []


def test_reports_200_with_client_x_api_key_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BIGDATA_API_KEY", raising=False)
    r = client.get("/api/reports", headers={"X-API-KEY": "client-bigdata-test"})
    assert r.status_code == 200


def test_job_status_404_with_bigdata_auth(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIGDATA_API_KEY", "k")
    r = client.get("/api/status/job-deadbeef0000", headers={"X-API-KEY": "k"})
    assert r.status_code == 404


def test_create_report_401_without_bigdata_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BIGDATA_API_KEY", raising=False)
    body = {
        "tickers": ["A"] * 12,
        "report_name": "t",
        "top_n": 5,
        "days_lookback": 1,
        "use_mini_topics": True,
        "custom_topics": None,
    }
    r = client.post("/api/report", json=body)
    assert r.status_code == 401


def test_create_report_503_when_report_service_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import main as main_module

    monkeypatch.setattr(main_module, "report_service", None)
    monkeypatch.setenv("BIGDATA_API_KEY", "fake-bigdata-for-test")
    body = {
        "tickers": ["A"] * 12,
        "report_name": "t",
        "top_n": 5,
        "days_lookback": 1,
        "use_mini_topics": True,
        "custom_topics": None,
    }
    r = client.post(
        "/api/report",
        json=body,
        headers={"X-API-KEY": "fake-bigdata-for-test"},
    )
    assert r.status_code == 503


def test_job_roundtrip_status_with_x_api_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BIGDATA_API_KEY", raising=False)
    job_id = job_storage.create_job({"tickers": ["XSES:D05"], "report_name": "n", "top_n": 5})
    job_storage.update_job_status(job_id, JobStatus.COMPLETE, result={"ok": True})
    r = client.get(f"/api/status/{job_id}", headers={"X-API-KEY": "any-client-key"})
    assert r.status_code == 200
    assert r.json()["status"] == "complete"
