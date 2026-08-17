import hmac
import hashlib
from typing import Optional
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

def verify_webhook_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    secret_key: Optional[str] = None
) -> bool:
    """
    Verify HMAC-SHA256 signature from the Mock PseudoGram webhook.
    
    Header format: X-PseudoGram-Signature: sha256=<hex_digest>
    Uses constant-time comparison to prevent timing attacks.
    """
    settings = get_settings()
    
    # If signature verification is globally disabled (e.g. dev/testing without key), bypass
    if not settings.VERIFY_WEBHOOK_SIGNATURE:
        return True

    api_key = secret_key or settings.PSEUDOGRAM_API_KEY
    if not api_key:
        logger.warning("Webhook signature verification is enabled, but PSEUDOGRAM_API_KEY is not configured.")
        return False

    if not signature_header:
        logger.warning("Missing X-PseudoGram-Signature header on webhook request.")
        return False

    # Normalize header and extract hex digest (handles sha256=, SHA256=, whitespace, and upper/lower hex)
    header_clean = signature_header.strip()
    if header_clean.lower().startswith("sha256="):
        provided_digest = header_clean[7:].strip().lower()
    else:
        provided_digest = header_clean.strip().lower()

    # Calculate expected HMAC-SHA256 digest
    expected_digest = hmac.new(
        key=api_key.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest().lower()

    # Constant-time comparison
    is_valid = hmac.compare_digest(expected_digest, provided_digest)
    if not is_valid:
        logger.warning("Invalid webhook signature received.")
    return is_valid
