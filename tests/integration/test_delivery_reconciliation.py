import respx
import httpx
import pytest
from sqlalchemy.orm import Session
from app.models.delivery import Delivery
from app.repositories.rules_repo import RulesRepository
from app.repositories.deliveries_repo import DeliveriesRepository
from app.repositories.stats_repo import StatsRepository
from app.workers.tasks import send_dm_task, reconcile_delivery_task
from app.core.config import get_settings
from app.services.stats_service import StatsService

@respx.mock
def test_202_accepted_not_counted_as_sent(db_session: Session, test_rate_limiter, mocker):
    mocker.patch("app.workers.tasks.get_redis_client", return_value=test_rate_limiter.redis)
    mock_reconcile = mocker.patch("app.workers.tasks.reconcile_delivery_task.apply_async")

    rule = RulesRepository.create_rule(db_session, keyword="PRICE", dm_message="Price $20")
    delivery, _ = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_202",
        rule_id=rule.id,
        comment_id="cmt_202",
        idempotency_key="dm:usr_202:price"
    )

    settings = get_settings()
    respx.post(f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/send").mock(
        return_value=httpx.Response(202, json={"dm_id": "dm_7c1f0a", "status": "queued"})
    )

    send_dm_task(delivery.id)

    db_session.refresh(delivery)
    assert delivery.status == "queued"
    assert delivery.dm_id == "dm_7c1f0a"

    # Stats: Sent must be 0, Queued must be 1
    stats = StatsService.get_stats(db_session)
    assert stats.sent == 0
    assert stats.queued == 1
    mock_reconcile.assert_called_once()

@respx.mock
def test_reconciliation_transitions_to_sent(db_session: Session):
    rule = RulesRepository.create_rule(db_session, keyword="PRICE", dm_message="Price $20")
    delivery, _ = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_reconcile",
        rule_id=rule.id,
        comment_id="cmt_rec",
        idempotency_key="dm:usr_reconcile:price"
    )
    DeliveriesRepository.update_delivery_status(db_session, delivery.id, status="queued", dm_id="dm_success_99")

    settings = get_settings()
    respx.get(f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/dm_success_99").mock(
        return_value=httpx.Response(
            200,
            json={
                "dm_id": "dm_success_99",
                "status": "delivered",
                "recipient_user_id": "usr_reconcile",
                "updated_at": "2026-08-16T18:00:00Z"
            }
        )
    )

    reconcile_delivery_task(delivery.id)

    db_session.refresh(delivery)
    assert delivery.status == "sent"
    assert delivery.delivered_at is not None

    stats = StatsService.get_stats(db_session)
    assert stats.sent == 1
    assert stats.queued == 0
    assert stats.failed == 0
