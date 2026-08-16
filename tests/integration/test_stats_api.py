from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.delivery import Delivery
from app.models.blocked_duplicate import BlockedDuplicate
from app.repositories.rules_repo import RulesRepository

def test_get_stats_empty(client: TestClient):
    response = client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "sent": 0,
        "failed": 0,
        "queued": 0,
        "duplicates_blocked": 0
    }

def test_get_stats_populated(client: TestClient, db_session: Session):
    rule = RulesRepository.create_rule(db_session, keyword="TEST", dm_message="Test Msg")
    
    # 2 Sent
    for i in range(2):
        d = Delivery(
            id=f"deliv_sent_{i}",
            user_id=f"user_sent_{i}",
            rule_id=rule.id,
            comment_id=f"cmt_{i}",
            idempotency_key=f"dm:sent:{i}",
            status="sent"
        )
        db_session.add(d)

    # 1 Failed
    d_fail = Delivery(
        id="deliv_failed_1",
        user_id="user_failed_1",
        rule_id=rule.id,
        comment_id="cmt_f",
        idempotency_key="dm:failed:1",
        status="failed"
    )
    db_session.add(d_fail)

    # 3 Queued (2 queued, 1 sending)
    d_q1 = Delivery(
        id="deliv_q_1",
        user_id="user_q_1",
        rule_id=rule.id,
        comment_id="cmt_q1",
        idempotency_key="dm:q:1",
        status="queued"
    )
    d_q2 = Delivery(
        id="deliv_q_2",
        user_id="user_q_2",
        rule_id=rule.id,
        comment_id="cmt_q2",
        idempotency_key="dm:q:2",
        status="sending"
    )
    db_session.add(d_q1)
    db_session.add(d_q2)

    # 4 Duplicates blocked
    for i in range(4):
        bd = BlockedDuplicate(
            event_id=f"evt_dup_{i}",
            user_id=f"user_dup_{i}",
            rule_id=rule.id,
            comment_id=f"cmt_dup_{i}"
        )
        db_session.add(bd)

    db_session.commit()

    response = client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "sent": 2,
        "failed": 1,
        "queued": 2,
        "duplicates_blocked": 4
    }
