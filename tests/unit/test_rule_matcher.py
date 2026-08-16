import pytest
from app.models.rule import Rule
from app.services.rule_matcher import RuleMatcher

def test_rule_matcher_exact_case():
    assert RuleMatcher.is_match("PRICE", "PRICE") is True

def test_rule_matcher_case_insensitive():
    assert RuleMatcher.is_match("price", "PRICE") is True
    assert RuleMatcher.is_match("PrIcE", "price") is True
    assert RuleMatcher.is_match("PRICE PLEASE", "price") is True

def test_rule_matcher_substring_anywhere():
    assert RuleMatcher.is_match("Hey can you send me the PRICE list?", "PRICE") is True
    assert RuleMatcher.is_match("how much is the price? 🙏", "PRICE") is True
    assert RuleMatcher.is_match("what is the linkplease discount code?", "LINKPLEASE") is True

def test_rule_matcher_non_matching():
    assert RuleMatcher.is_match("Hello nice photo!", "PRICE") is False
    assert RuleMatcher.is_match("", "PRICE") is False
    assert RuleMatcher.is_match(None, "PRICE") is False

def test_find_matching_rules():
    rules = [
        Rule(id="rule_1", keyword="PRICE", dm_message="Price is $50"),
        Rule(id="rule_2", keyword="DISCOUNT", dm_message="Here is 10% off"),
        Rule(id="rule_3", keyword="VIP", dm_message="Welcome VIP")
    ]
    
    matches = RuleMatcher.find_matching_rules("Can you give me the price and discount?", rules)
    assert len(matches) == 2
    matched_ids = {r.id for r in matches}
    assert matched_ids == {"rule_1", "rule_2"}
