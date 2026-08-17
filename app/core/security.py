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

    # If no signature provided
    if not signature_header:
        if settings.VERIFY_WEBHOOK_SIGNATURE:
            logger.warning("Missing X-PseudoGram-Signature header on webhook request.")
            return False
        return True

    # If signature IS provided, always verify it strictly (Part B)
    raw_key = secret_key or settings.PSEUDOGRAM_API_KEY
    api_key = raw_key.strip().strip("'\"") if raw_key else ""
    if not api_key:
        logger.warning("Webhook signature received, but PSEUDOGRAM_API_KEY is not configured.")
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
