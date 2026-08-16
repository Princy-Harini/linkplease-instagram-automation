import app.core.database as db_module
from app.models.delivery import Delivery
from app.repositories.rules_repo import RulesRepository
from app.repositories.deliveries_repo import DeliveriesRepository
from app.repositories.events_repo import EventsRepository
from app.services.stats_service import StatsService

def test_database_persistence_across_session_restart(db_session):
    """
    Simulates application restart: verifies that persisted rules, events, deliveries,
    and stats remain completely intact when a new database session connects.
    """
    # Session 1: Create rule and delivery
    rule = RulesRepository.create_rule(db_session, keyword="PERSIST", dm_message="Persisted DM")
    rule_id = rule.id

    delivery, _ = DeliveriesRepository.create_delivery_if_not_exists(
        db=db_session,
        user_id="usr_persist_1",
        rule_id=rule_id,
        comment_id="cmt_persist_1",
        idempotency_key="dm:usr_persist_1:persist"
    )
    delivery_id = delivery.id

    EventsRepository.insert_event_if_not_exists(
        db=db_session,
        event_id="evt_persist_01",
        event_type="comment.created",
        sent_at=None,
        payload={"event_id": "evt_persist_01"}
    )
    db_session.commit()
    db_session.close()

    # Session 2: "Restart" - fresh session connects to existing database storage
    fresh_session = db_module.SessionLocal()
    try:
        recovered_rule = RulesRepository.get_rule_by_id(fresh_session, rule_id)
        assert recovered_rule is not None
        assert recovered_rule.keyword == "PERSIST"

        recovered_event = EventsRepository.get_event_by_id(fresh_session, "evt_persist_01")
        assert recovered_event is not None
        assert recovered_event.event_type == "comment.created"

        recovered_delivery = DeliveriesRepository.get_delivery_by_id(fresh_session, delivery_id)
        assert recovered_delivery is not None
        assert recovered_delivery.status == "queued"

        stats = StatsService.get_stats(fresh_session)
        assert stats.queued == 1
        assert stats.sent == 0
    finally:
        fresh_session.close()
