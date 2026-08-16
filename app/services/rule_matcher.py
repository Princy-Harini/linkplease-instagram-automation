from typing import List, Optional
from app.models.rule import Rule

class RuleMatcher:
    """Service for case-insensitive substring keyword matching on comments."""

    @staticmethod
    def is_match(comment_text: Optional[str], keyword: str) -> bool:
        """
        Check if keyword exists anywhere inside comment_text (case-insensitive).
        """
        if not comment_text or not keyword:
            return False
        return keyword.strip().lower() in comment_text.lower()

    @classmethod
    def find_matching_rules(cls, comment_text: Optional[str], rules: List[Rule]) -> List[Rule]:
        """
        Return all rules that match the given comment text.
        """
        if not comment_text or not rules:
            return []
        
        normalized_text = comment_text.lower()
        matching = []
        for rule in rules:
            if rule.keyword and rule.keyword.strip().lower() in normalized_text:
                matching.append(rule)
        return matching
