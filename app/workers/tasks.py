import random
from datetime import datetime, timezone
from typing import Optional
from app.workers.celery_app import celery_app
import app.core.database as database_module
from app.core.redis import get_redis_client
from app.core.config import get_settings
from app.core.logging import get_logger
from app.repositories.rules_repo import RulesRepository
from app.repositories.events_repo import EventsRepository
from app.repositories.comments_repo import CommentsRepository
from app.repositories.deliveries_repo import DeliveriesRepository
from app.repositories.stats_repo import StatsRepository
from app.services.rule_matcher import RuleMatcher
from app.services.rate_limiter import RateLimiter
from app.services.pseudogram_client import (
    PseudoGramClient,
    PseudoGramRateLimitError,
    PseudoGramTransientError,
    PseudoGramClientError
)

logger = get_logger(__name__)

@celery_app.task(name="app.workers.tasks.process_webhook_event_task", bind=True)
def process_webhook_event_task(self, event_id: str) -> None:
    """
    Background task to process an ingested webhook event.
    Performs keyword rule matching, duplicate checks, and comment deletion tracking.
    """
    logger.info(f"Processing webhook event: {event_id}")
    db = database_module.SessionLocal()
    try:
        event = EventsRepository.get_event_by_id(db, event_id)
        if not event:
            logger.warning(f"Event {event_id} not found in database.")
            return

        payload = event.payload or {}
        event_type = event.event_type
        data = payload.get("data", {})
        comment_id = data.get("comment_id")

        if not comment_id:
            logger.warning(f"Event {event_id} missing comment_id in data payload.")
            EventsRepository.update_event_status(db, event_id, "ignored_invalid_payload")
            return

        # 1. Handle comment.deleted events
        if event_type == "comment.deleted":
            logger.info(f"Processing comment.deleted for comment_id={comment_id}")
            CommentsRepository.mark_comment_deleted(db, comment_id)
            EventsRepository.update_event_status(db, event_id, "processed")
            return

        # 2. Handle comment.created events
        if event_type == "comment.created":
            post_id = data.get("post_id")
            text = data.get("text", "")
            raw_created_at = data.get("created_at")
            comment_created_at = None
            if raw_created_at:
                try:
                    comment_created_at = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
                except ValueError:
                    comment_created_at = None

            from_user = data.get("from", {})
            user_id = from_user.get("user_id") if isinstance(from_user, dict) else None
            username = from_user.get("username") if isinstance(from_user, dict) else None

            if not user_id:
                logger.warning(f"Comment {comment_id} missing user_id. Cannot send DM.")
                EventsRepository.update_event_status(db, event_id, "ignored_missing_user_id")
                return

            # Upsert comment into comments table
            comment = CommentsRepository.upsert_comment_created(
                db=db,
                comment_id=comment_id,
                post_id=post_id,
                user_id=user_id,
                username=username,
                text=text,
                comment_created_at=comment_created_at
            )

            # If comment was deleted before creation event arrived, abort sending DM
            if comment.is_deleted:
                logger.info(f"Comment {comment_id} was already marked deleted. Skipping DM generation.")
                EventsRepository.update_event_status(db, event_id, "ignored_comment_deleted")
                return

            # Fetch active rules and find matches
            rules = RulesRepository.get_all_rules(db)
            matching_rules = RuleMatcher.find_matching_rules(text, rules)

            if not matching_rules:
                logger.info(f"No keyword rules matched comment_id={comment_id} text={text!r}")
                EventsRepository.update_event_status(db, event_id, "processed_no_match")
                return

            logger.info(f"Comment {comment_id} matched {len(matching_rules)} rule(s)")

            settings = get_settings()
            for rule in matching_rules:
                idempotency_key = f"dm:{user_id}:{rule.id}"
                
                # Atomic DB insert enforcing single DM per (user_id, rule_id)
                delivery, is_new = DeliveriesRepository.create_delivery_if_not_exists(
                    db=db,
                    user_id=user_id,
                    rule_id=rule.id,
                    comment_id=comment_id,
                    idempotency_key=idempotency_key,
                    max_retries=settings.MAX_RETRIES
                )

                if is_new and delivery:
                    logger.info(f"Created new delivery record {delivery.id} for user={user_id} rule={rule.id}")
                    send_dm_task.delay(delivery.id)
                else:
                    logger.info(
                        f"Duplicate DM blocked: user {user_id} already has a delivery for rule {rule.id}."
                    )
                    StatsRepository.record_blocked_duplicate(
                        db=db,
                        event_id=event_id,
                        user_id=user_id,
                        rule_id=rule.id,
                        comment_id=comment_id
                    )

            EventsRepository.update_event_status(db, event_id, "processed")

    except Exception as exc:
        logger.error(f"Error processing webhook event {event_id}: {exc}", exc_info=True)
        EventsRepository.update_event_status(db, event_id, "error")
        raise exc
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.send_dm_task", bind=True)
def send_dm_task(self, delivery_id: str) -> None:
    """
    Background worker task to dispatch a direct message via Mock PseudoGram API.
    Enforces Redis-based sliding window rate limits, backoff retries, and failure states.
    """
    logger.info(f"Executing send_dm_task for delivery_id={delivery_id}")
    db = database_module.SessionLocal()
    try:
        delivery = DeliveriesRepository.get_delivery_by_id(db, delivery_id)
        if not delivery:
            logger.warning(f"Delivery {delivery_id} not found.")
            return

        if delivery.status == "sent":
            logger.info(f"Delivery {delivery_id} is already marked as sent. Exiting.")
            return

        rule = RulesRepository.get_rule_by_id(db, delivery.rule_id)
        if not rule:
            logger.error(f"Rule {delivery.rule_id} not found for delivery {delivery_id}.")
            DeliveriesRepository.update_delivery_status(
                db, delivery_id, status="failed", last_error="Rule not found"
            )
            return

        # Check comment deletion state right before dispatching
        comment = CommentsRepository.get_comment(db, delivery.comment_id)
        if comment and comment.is_deleted:
            logger.info(f"Comment {delivery.comment_id} was deleted before DM sent. Cancelling delivery.")
            DeliveriesRepository.update_delivery_status(
                db, delivery_id, status="failed", last_error="Comment was deleted before DM dispatch"
            )
            return

        # Acquire Rate Limiter slot
        redis_client = get_redis_client()
        rate_limiter = RateLimiter(redis_client)
        allowed, wait_seconds = rate_limiter.acquire_slot()

        if not allowed:
            delay = int(wait_seconds) + 1
            logger.info(f"Rate limiter delayed delivery {delivery_id} by {delay}s")
            self.apply_async(args=[delivery_id], countdown=delay)
            return

        # Transition status to 'sending' while in-flight
        DeliveriesRepository.update_delivery_status(db, delivery_id, status="sending")

        pseudogram_client = PseudoGramClient()
        settings = get_settings()

        try:
            resp = pseudogram_client.send_dm(
                recipient_user_id=delivery.user_id,
                message=rule.dm_message,
                idempotency_key=delivery.idempotency_key
            )
            # External API returns 202 Accepted with status='queued'
            DeliveriesRepository.update_delivery_status(
                db, delivery_id, status="queued", dm_id=resp.dm_id
            )
            logger.info(f"DM dispatched: dm_id={resp.dm_id}. Scheduling status reconciliation.")
            reconcile_delivery_task.apply_async(
                args=[delivery_id],
                countdown=settings.RECONCILIATION_INTERVAL_SECONDS
            )

        except PseudoGramRateLimitError as exc:
            logger.warning(f"429 Rate limited sending DM {delivery_id}: {exc}. Cooldown: {exc.retry_after}s")
            rate_limiter.set_lockout(exc.retry_after)
            DeliveriesRepository.update_delivery_status(
                db, delivery_id, status="queued", last_error=f"HTTP 429: {exc}"
            )
            self.apply_async(args=[delivery_id], countdown=int(exc.retry_after) + 1)

        except PseudoGramTransientError as exc:
            new_retry_count = delivery.retry_count + 1
            logger.warning(
                f"Transient failure sending DM {delivery_id} (attempt {new_retry_count}/{delivery.max_retries}): {exc}"
            )
            if new_retry_count <= delivery.max_retries:
                # Exponential backoff with random jitter
                backoff_delay = (2 ** new_retry_count) + random.uniform(0.5, 2.0)
                DeliveriesRepository.update_delivery_status(
                    db,
                    delivery_id,
                    status="queued",
                    retry_count=new_retry_count,
                    last_error=f"Transient error: {exc}"
                )
                self.apply_async(args=[delivery_id], countdown=int(backoff_delay))
            else:
                logger.error(f"Permanent failure for delivery {delivery_id}: Exceeded max retries.")
                DeliveriesRepository.update_delivery_status(
                    db,
                    delivery_id,
                    status="failed",
                    retry_count=new_retry_count,
                    last_error=f"Exceeded max retries: {exc}"
                )

        except PseudoGramClientError as exc:
            logger.error(f"Non-retriable 400 error for delivery {delivery_id}: {exc}")
            DeliveriesRepository.update_delivery_status(
                db, delivery_id, status="failed", last_error=f"400 Client error: {exc}"
            )

        except Exception as exc:
            logger.error(f"Unexpected error sending DM {delivery_id}: {exc}", exc_info=True)
            DeliveriesRepository.update_delivery_status(
                db, delivery_id, status="failed", last_error=f"Unexpected error: {exc}"
            )

    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.reconcile_delivery_task", bind=True)
def reconcile_delivery_task(self, delivery_id: str, attempt: int = 1) -> None:
    """
    Background task to poll GET /v1/dm/{dm_id} and reconcile delivery status.
    Transitions delivery to 'sent' once status is confirmed 'delivered'.
    """
    logger.info(f"Executing reconcile_delivery_task for delivery_id={delivery_id} (attempt {attempt})")
    db = database_module.SessionLocal()
    try:
        delivery = DeliveriesRepository.get_delivery_by_id(db, delivery_id)
        if not delivery or not delivery.dm_id:
            logger.warning(f"Delivery or dm_id not found for reconciliation: {delivery_id}")
            return

        if delivery.status == "sent":
            logger.info(f"Delivery {delivery_id} is already marked as sent.")
            return

        settings = get_settings()
        pseudogram_client = PseudoGramClient()

        try:
            status_resp = pseudogram_client.get_dm_status(delivery.dm_id)
            logger.info(f"Reconciliation result for dm_id={delivery.dm_id}: status={status_resp.status}")

            if status_resp.status == "delivered":
                DeliveriesRepository.update_delivery_status(
                    db,
                    delivery_id,
                    status="sent",
                    delivered_at=datetime.now(timezone.utc)
                )
                logger.info(f"Delivery {delivery_id} successfully confirmed DELIVERED.")

            elif status_resp.status == "failed":
                logger.warning(f"Mock API reported DM delivery failed for dm_id={delivery.dm_id}")
                # If we have retries left, re-enqueue sending
                if delivery.retry_count < delivery.max_retries:
                    new_retry = delivery.retry_count + 1
                    DeliveriesRepository.update_delivery_status(
                        db,
                        delivery_id,
                        status="queued",
                        retry_count=new_retry,
                        last_error="Mock API returned delivery failed status"
                    )
                    send_dm_task.apply_async(args=[delivery_id], countdown=3)
                else:
                    DeliveriesRepository.update_delivery_status(
                        db,
                        delivery_id,
                        status="failed",
                        last_error="Mock API returned delivery failed status"
                    )

            elif status_resp.status == "queued":
                if attempt < settings.RECONCILIATION_MAX_ATTEMPTS:
                    self.apply_async(
                        args=[delivery_id, attempt + 1],
                        countdown=settings.RECONCILIATION_INTERVAL_SECONDS
                    )
                else:
                    logger.info(
                        f"Delivery {delivery_id} still queued after {attempt} reconciliation attempts. Remaining queued."
                    )

        except PseudoGramTransientError as exc:
            logger.warning(f"Transient error reconciling {delivery_id}: {exc}")
            if attempt < settings.RECONCILIATION_MAX_ATTEMPTS:
                self.apply_async(
                    args=[delivery_id, attempt + 1],
                    countdown=settings.RECONCILIATION_INTERVAL_SECONDS * 2
                )
        except Exception as exc:
            logger.error(f"Error during reconciliation for delivery {delivery_id}: {exc}")

    finally:
        db.close()
