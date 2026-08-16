import hmac
import hashlib
import pytest
from app.core.security import verify_webhook_signature
from app.core.config import get_settings

def test_verify_webhook_signature_valid(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "VERIFY_WEBHOOK_SIGNATURE", True)
    monkeypatch.setattr(settings, "PSEUDOGRAM_API_KEY", "secret_key_abc")

    raw_body = b'{"event_id": "evt_123", "event_type": "comment.created"}'
    expected_hex = hmac.new(b"secret_key_abc", raw_body, hashlib.sha256).hexdigest()
    
    # Test with sha256= prefix
    assert verify_webhook_signature(raw_body, f"sha256={expected_hex}") is True
    # Test without prefix
    assert verify_webhook_signature(raw_body, expected_hex) is True

def test_verify_webhook_signature_invalid(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "VERIFY_WEBHOOK_SIGNATURE", True)
    monkeypatch.setattr(settings, "PSEUDOGRAM_API_KEY", "secret_key_abc")

    raw_body = b'{"event_id": "evt_123"}'
    fake_header = "sha256=0000000000000000000000000000000000000000000000000000000000000000"
    
    assert verify_webhook_signature(raw_body, fake_header) is False
    assert verify_webhook_signature(raw_body, None) is False

def test_verify_webhook_signature_tampered_payload(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "VERIFY_WEBHOOK_SIGNATURE", True)
    monkeypatch.setattr(settings, "PSEUDOGRAM_API_KEY", "secret_key_abc")

    raw_body = b'{"event_id": "evt_123"}'
    expected_hex = hmac.new(b"secret_key_abc", raw_body, hashlib.sha256).hexdigest()

    tampered_body = b'{"event_id": "evt_123", "hacked": true}'
    assert verify_webhook_signature(tampered_body, f"sha256={expected_hex}") is False
