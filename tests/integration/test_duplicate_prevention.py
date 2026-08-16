import pytest
from sqlalchemy.orm import Session
from app.models.rule import Rule
from app.models.delivery import Delivery
from app.models.blocked_duplicate import BlockedDuplicate
from app.models.webhook_event import WebhookEvent
from app.repositories.rules_repo import RulesRepository
from app.repositories.deliveries_repo import DeliveriesRepository
from app.repositories.events_repo import EventsRepository
from app.workers.tasks import process_webhook_event_task

def test_same_user_multiple_comments_single_dm(db_session: Session, mocker):
    mock_send = mocker.patch("app.workers.tasks.send_dm_task.delay")

    # 1. Create a Rule
    rule = RulesRepository.create_rule(db_session, keyword="PRICE", dm_message="Price is $99")

    # 2. Simulate 4 comment events from same user_id "usr_100"
    for i in range(1, 5):
        event_id = f"evt_user100_{i}"
        payload = {
            "event_id": event_id,
            "event_type": "comment.created",
            "data": {
                "comment_id": f"cmt_{i}",
                "post_id": "post_1",
                "text": f"PRICE please comment #{i}",
                "from": {
                    "user_id": "usr_100",
                    "username": f"user_name_version_{i}"
                }
            }
        }
        EventsRepository.insert_event_if_not_exists(
            db=db_session,
            event_id=event_id,
            event_type="comment.created",
            sent_at=None,
            payload=payload
        )
        # Process task
        process_webhook_event_task(event_id)

    # 3. Assert only ONE Delivery record exists for usr_100 and rule.id
    deliveries = db_session.query(Delivery).filter(
        Delivery.user_id == "usr_100",
        Delivery.rule_id == rule.id
    ).all()
    assert len(deliveries) == 1
    assert mock_send.call_count == 1

    # 4. Assert 3 blocked duplicate records were recorded in blocked_duplicates
    blocked = db_session.query(BlockedDuplicate).filter(
        BlockedDuplicate.user_id == "usr_100",
        BlockedDuplicate.rule_id == rule.id
    ).all()
    assert len(blocked) == 3

def test_database_level_unique_constraint_enforcement(db_session: Session):
    rule = RulesRepository.create_rule(db_session, keyword="VIP", dm_message="VIP pass")
    
    # First delivery insert succeeds
    d1, is_new1 = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_200",
        rule_id=rule.id,
        comment_id="cmt_a",
        idempotency_key=f"dm:usr_200:{rule.id}"
    )
    assert is_new1 is True
    assert d1 is not None

    # Concurrent second insert for same user_id and rule_id fails cleanly
    d2, is_new2 = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_200",
        rule_id=rule.id,
        comment_id="cmt_b",
        idempotency_key=f"dm:usr_200:{rule.id}"
    )
    assert is_new2 is False
    assert d2.id == d1.id
