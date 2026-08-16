from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.rule import Rule, generate_rule_id

class RulesRepository:
    """Data access repository for keyword rules."""

    @staticmethod
    def create_rule(db: Session, keyword: str, dm_message: str) -> Rule:
        rule = Rule(
            id=generate_rule_id(),
            keyword=keyword.strip(),
            dm_message=dm_message.strip()
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule

    @staticmethod
    def get_rule_by_id(db: Session, rule_id: str) -> Optional[Rule]:
        return db.query(Rule).filter(Rule.id == rule_id).first()

    @staticmethod
    def get_all_rules(db: Session) -> List[Rule]:
        return db.query(Rule).all()
