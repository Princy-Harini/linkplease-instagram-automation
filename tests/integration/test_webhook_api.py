import pytest
from fastapi.testclient import TestClient
from app.core.config import get_settings

def test_webhook_returns_200_and_enqueues(client: TestClient, mocker):
    mock_task = mocker.patch("app.api.v1.webhook.process_webhook_event_task.delay")

    payload = {
        "event_id": "evt_test_001",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22.481Z",
        "data": {
            "comment_id": "cmt_9f2a7c",
            "post_id": "post_44de1b",
            "text": "PRICE please 🙏",
            "created_at": "2026-08-10T09:14:21.900Z",
            "from": {
                "user_id": "usr_3b91fe",
                "username": "arjun.shoots"
            }
        }
    }

    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["event_id"] == "evt_test_001"
    mock_task.assert_called_once_with("evt_test_001")

def test_duplicate_event_id_ignored(client: TestClient, mocker):
    mock_task = mocker.patch("app.api.v1.webhook.process_webhook_event_task.delay")

    payload = {
        "event_id": "evt_test_002",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_123",
            "text": "PRICE",
            "from": {"user_id": "usr_1"}
        }
    }

    # First call: accepts and enqueues
    resp1 = client.post("/webhook", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "ok"
    assert mock_task.call_count == 1

    # Second call with same event_id: returns 200 duplicate_ignored, does not re-enqueue
    resp2 = client.post("/webhook", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate_ignored"
    assert mock_task.call_count == 1

def test_webhook_signature_verification_failure(client: TestClient, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "VERIFY_WEBHOOK_SIGNATURE", True)
    monkeypatch.setattr(settings, "PSEUDOGRAM_API_KEY", "secret_key")

    payload = {
        "event_id": "evt_test_003",
        "event_type": "comment.created",
        "data": {"comment_id": "cmt_1"}
    }

    # Missing signature header -> 401
    response = client.post("/webhook", json=payload)
    assert response.status_code == 401

    # Invalid signature header -> 401
    response = client.post(
        "/webhook",
        json=payload,
        headers={"X-PseudoGram-Signature": "sha256=invalid"}
    )
    assert response.status_code == 401
