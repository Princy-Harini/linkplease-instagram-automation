from typing import Optional, Dict, Any
import httpx
from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.pseudogram import DMSendResponse, DMStatusResponse

logger = get_logger(__name__)

class PseudoGramAPIError(Exception):
    """Base exception for PseudoGram API interactions."""
    pass

class PseudoGramRateLimitError(PseudoGramAPIError):
    """Raised when external API returns HTTP 429."""
    def __init__(self, message: str, retry_after: float = 60.0):
        super().__init__(message)
        self.retry_after = retry_after

class PseudoGramTransientError(PseudoGramAPIError):
    """Raised when external API returns HTTP 500 or encounters connection timeouts."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code

class PseudoGramClientError(PseudoGramAPIError):
    """Raised when external API returns non-retriable HTTP 400/4xx."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code

class PseudoGramClient:
    """Client for interacting with the Mock PseudoGram API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 10.0
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.PSEUDOGRAM_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.PSEUDOGRAM_API_KEY
        self.timeout = timeout

    def _get_headers(self, idempotency_key: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def send_dm(
        self,
        recipient_user_id: str,
        message: str,
        idempotency_key: Optional[str] = None
    ) -> DMSendResponse:
        """
        Send a direct message via POST /v1/dm/send.
        
        Returns:
            DMSendResponse: with dm_id and status='queued'
        Raises:
            PseudoGramRateLimitError: on HTTP 429
            PseudoGramTransientError: on HTTP 500, network error, timeout
            PseudoGramClientError: on HTTP 400
        """
        url = f"{self.base_url}/v1/dm/send"
        headers = self._get_headers(idempotency_key=idempotency_key)
        payload = {
            "recipient_user_id": recipient_user_id,
            "message": message
        }

        logger.info(f"Sending DM to user={recipient_user_id} with idempotency_key={idempotency_key}")

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(f"Network exception connecting to PseudoGram API: {exc}")
            raise PseudoGramTransientError(f"Network error: {exc}")

        if response.status_code in (200, 201, 202):
            data = response.json()
            logger.info(f"PseudoGram accepted DM: dm_id={data.get('dm_id')} status={data.get('status')}")
            return DMSendResponse(**data)

        if response.status_code == 429:
            retry_after_hdr = response.headers.get("Retry-After")
            try:
                retry_after = float(retry_after_hdr) if retry_after_hdr else 60.0
            except ValueError:
                retry_after = 60.0
            logger.warning(f"PseudoGram Rate Limit (429). Retry-After: {retry_after}s")
            raise PseudoGramRateLimitError(f"Rate limited by PseudoGram API", retry_after=retry_after)

        if response.status_code >= 500:
            logger.warning(f"PseudoGram returned server error {response.status_code}: {response.text}")
            raise PseudoGramTransientError(
                f"PseudoGram server error {response.status_code}",
                status_code=response.status_code
            )

        if 400 <= response.status_code < 500:
            logger.error(f"PseudoGram client error {response.status_code}: {response.text}")
            raise PseudoGramClientError(
                f"PseudoGram client error {response.status_code}: {response.text}",
                status_code=response.status_code
            )

        raise PseudoGramAPIError(f"Unexpected status code {response.status_code}: {response.text}")

    def get_dm_status(self, dm_id: str) -> DMStatusResponse:
        """
        Reconcile delivery status via GET /v1/dm/{dm_id}.
        Does not count towards the 10/min rate limit.
        """
        url = f"{self.base_url}/v1/dm/{dm_id}"
        headers = self._get_headers()

        logger.info(f"Reconciling DM status for dm_id={dm_id}")

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(f"Network error querying DM status for {dm_id}: {exc}")
            raise PseudoGramTransientError(f"Network error: {exc}")

        if response.status_code == 200:
            data = response.json()
            return DMStatusResponse(**data)

        if response.status_code >= 500:
            raise PseudoGramTransientError(
                f"Server error {response.status_code} while querying DM status",
                status_code=response.status_code
            )

        if 400 <= response.status_code < 500:
            raise PseudoGramClientError(
                f"Client error {response.status_code} fetching DM status: {response.text}",
                status_code=response.status_code
            )

        raise PseudoGramAPIError(f"Unexpected status code {response.status_code}: {response.text}")
