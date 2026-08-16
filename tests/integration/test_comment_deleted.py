import pytest
from sqlalchemy.orm import Session
from app.models.delivery import Delivery
from app.models.comment import Comment
from app.repositories.rules_repo import RulesRepository
from app.repositories.events_repo import EventsRepository
from app.repositories.deliveries_repo import DeliveriesRepository
from app.workers.tasks import process_webhook_event_task, send_dm_task

def test_comment_deleted_before_created(db_session: Session, mocker):
    mock_send = mocker.patch("app.workers.tasks.send_dm_task.delay")
    rule = RulesRepository.create_rule(db_session, keyword="INFO", dm_message="Info DM")

    # Step 1: Out-of-order comment.deleted arrives first
    del_event_id = "evt_del_01"
    del_payload = {
        "event_id": del_event_id,
        "event_type": "comment.deleted",
        "data": {
            "comment_id": "cmt_outoforder_99"
        }
    }
    EventsRepository.insert_event_if_not_exists(
        db=db_session,
        event_id=del_event_id,
        event_type="comment.deleted",
        sent_at=None,
        payload=del_payload
    )
    process_webhook_event_task(del_event_id)

    # Verify placeholder comment with is_deleted=True was created
    comment = db_session.query(Comment).filter(Comment.comment_id == "cmt_outoforder_99").first()
    assert comment is not None
    assert comment.is_deleted is True

    # Step 2: Delayed comment.created arrives later
    create_event_id = "evt_create_01"
    create_payload = {
        "event_id": create_event_id,
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_outoforder_99",
            "post_id": "post_1",
            "text": "Can I get some INFO please?",
            "from": {
                "user_id": "usr_99",
                "username": "user_99"
            }
        }
    }
    EventsRepository.insert_event_if_not_exists(
        db=db_session,
        event_id=create_event_id,
        event_type="comment.created",
        sent_at=None,
        payload=create_payload
    )
    process_webhook_event_task(create_event_id)

    # DM task should NEVER be triggered because comment is marked deleted
    mock_send.assert_not_called()
    deliveries = db_session.query(Delivery).filter(Delivery.user_id == "usr_99").all()
    assert len(deliveries) == 0

def test_comment_deleted_before_dm_dispatch(db_session: Session, test_rate_limiter, mocker):
    mocker.patch("app.workers.tasks.get_redis_client", return_value=test_rate_limiter.redis)
    mocker.patch("app.workers.tasks.send_dm_task.delay")
    rule = RulesRepository.create_rule(db_session, keyword="DISCOUNT", dm_message="15% off")

    # 1. Create comment and delivery
    create_event_id = "evt_create_02"
    create_payload = {
        "event_id": create_event_id,
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_queue_88",
            "text": "Give me DISCOUNT",
            "from": {"user_id": "usr_88"}
        }
    }
    EventsRepository.insert_event_if_not_exists(
        db=db_session,
        event_id=create_event_id,
        event_type="comment.created",
        sent_at=None,
        payload=create_payload
    )
    process_webhook_event_task(create_event_id)

    delivery = db_session.query(Delivery).filter(Delivery.user_id == "usr_88").first()
    assert delivery is not None

    # 2. Before send_dm_task runs, user deletes their comment
    del_event_id = "evt_del_02"
    del_payload = {
        "event_id": del_event_id,
        "event_type": "comment.deleted",
        "data": {"comment_id": "cmt_queue_88"}
    }
    EventsRepository.insert_event_if_not_exists(
        db=db_session,
        event_id=del_event_id,
        event_type="comment.deleted",
        sent_at=None,
        payload=del_payload
    )
    process_webhook_event_task(del_event_id)

    # 3. Now send_dm_task executes
    mock_api_send = mocker.patch("app.services.pseudogram_client.PseudoGramClient.send_dm")
    send_dm_task(delivery.id)

    # API call must NOT be made
    mock_api_send.assert_not_called()

    # Delivery must be marked failed/cancelled
    db_session.refresh(delivery)
    assert delivery.status == "failed"
    assert "deleted" in delivery.last_error.lower()
