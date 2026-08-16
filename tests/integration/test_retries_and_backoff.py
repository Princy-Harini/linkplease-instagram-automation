import respx
import httpx
import pytest
from sqlalchemy.orm import Session
from app.models.delivery import Delivery
from app.repositories.rules_repo import RulesRepository
from app.repositories.deliveries_repo import DeliveriesRepository
from app.workers.tasks import send_dm_task
from app.core.config import get_settings

@respx.mock
def test_pseudogram_500_triggers_retry(db_session: Session, test_rate_limiter, mocker):
    mocker.patch("app.workers.tasks.get_redis_client", return_value=test_rate_limiter.redis)
    mock_apply_async = mocker.patch("app.workers.tasks.send_dm_task.apply_async")

    rule = RulesRepository.create_rule(db_session, keyword="TEST", dm_message="Test Msg")
    delivery, _ = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_500",
        rule_id=rule.id,
        comment_id="cmt_500",
        idempotency_key="dm:usr_500:rule_test",
        max_retries=3
    )

    settings = get_settings()
    respx.post(f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/send").mock(
        return_value=httpx.Response(500, json={"error": "Internal Server Error"})
    )

    send_dm_task(delivery.id)

    db_session.refresh(delivery)
    assert delivery.retry_count == 1
    assert delivery.status == "queued"
    assert "500" in delivery.last_error
    mock_apply_async.assert_called_once()
    assert mock_apply_async.call_args[1]["countdown"] > 0

@respx.mock
def test_network_timeout_triggers_retry(db_session: Session, test_rate_limiter, mocker):
    mocker.patch("app.workers.tasks.get_redis_client", return_value=test_rate_limiter.redis)
    mock_apply_async = mocker.patch("app.workers.tasks.send_dm_task.apply_async")

    rule = RulesRepository.create_rule(db_session, keyword="NET", dm_message="Network test")
    delivery, _ = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_net_timeout",
        rule_id=rule.id,
        comment_id="cmt_net",
        idempotency_key="dm:usr_net:rule_net",
        max_retries=3
    )

    settings = get_settings()
    respx.post(f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/send").mock(
        side_effect=httpx.ConnectTimeout("Connection timed out")
    )

    send_dm_task(delivery.id)

    db_session.refresh(delivery)
    assert delivery.retry_count == 1
    assert delivery.status == "queued"
    assert "Network error" in delivery.last_error
    mock_apply_async.assert_called_once()

@respx.mock
def test_pseudogram_429_respects_retry_after(db_session: Session, test_rate_limiter, mocker):
    mocker.patch("app.workers.tasks.get_redis_client", return_value=test_rate_limiter.redis)
    mock_apply_async = mocker.patch("app.workers.tasks.send_dm_task.apply_async")

    rule = RulesRepository.create_rule(db_session, keyword="TEST", dm_message="Test Msg")
    delivery, _ = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_429",
        rule_id=rule.id,
        comment_id="cmt_429",
        idempotency_key="dm:usr_429:rule_test"
    )

    settings = get_settings()
    respx.post(f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/send").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "45"}, json={"error": "Rate Limited"})
    )

    send_dm_task(delivery.id)

    mock_apply_async.assert_called_once()
    # Countdown should be at least retry_after (45s + 1)
    countdown = mock_apply_async.call_args[1]["countdown"]
    assert countdown >= 45

@respx.mock
def test_pseudogram_400_marks_failed_immediately(db_session: Session, test_rate_limiter, mocker):
    mocker.patch("app.workers.tasks.get_redis_client", return_value=test_rate_limiter.redis)
    mock_apply_async = mocker.patch("app.workers.tasks.send_dm_task.apply_async")

    rule = RulesRepository.create_rule(db_session, keyword="TEST", dm_message="Test Msg")
    delivery, _ = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_400",
        rule_id=rule.id,
        comment_id="cmt_400",
        idempotency_key="dm:usr_400:rule_test"
    )

    settings = get_settings()
    respx.post(f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/send").mock(
        return_value=httpx.Response(400, json={"error": "Invalid Recipient"})
    )

    send_dm_task(delivery.id)

    db_session.refresh(delivery)
    assert delivery.status == "failed"
    assert "400" in delivery.last_error
    # Should not schedule retries
    mock_apply_async.assert_not_called()

@respx.mock
def test_pseudogram_max_retries_exceeded(db_session: Session, test_rate_limiter, mocker):
    mocker.patch("app.workers.tasks.get_redis_client", return_value=test_rate_limiter.redis)

    rule = RulesRepository.create_rule(db_session, keyword="TEST", dm_message="Test Msg")
    delivery, _ = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_max_retries",
        rule_id=rule.id,
        comment_id="cmt_max",
        idempotency_key="dm:usr_max:rule_test",
        max_retries=2
    )
    # Set current retry_count to 2 (already at limit)
    DeliveriesRepository.update_delivery_status(db_session, delivery.id, status="queued", retry_count=2)

    settings = get_settings()
    respx.post(f"{settings.PSEUDOGRAM_BASE_URL}/v1/dm/send").mock(
        return_value=httpx.Response(500, json={"error": "Server error"})
    )

    send_dm_task(delivery.id)

    db_session.refresh(delivery)
    assert delivery.status == "failed"
    assert "exceeded" in delivery.last_error.lower()
