from fastapi.testclient import TestClient

def test_create_rule_success(client: TestClient):
    payload = {
        "keyword": "PRICE",
        "dm_message": "Here is the price list: $29/mo"
    }
    response = client.post("/rules", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "rule_id" in data
    assert data["rule_id"].startswith("rule_")
    assert data["keyword"] == "PRICE"
    assert data["dm_message"] == "Here is the price list: $29/mo"

def test_create_rule_validation_empty_keyword(client: TestClient):
    payload = {
        "keyword": "   ",
        "dm_message": "Hello"
    }
    response = client.post("/rules", json=payload)
    assert response.status_code == 422

def test_create_rule_validation_empty_message(client: TestClient):
    payload = {
        "keyword": "PRICE",
        "dm_message": ""
    }
    response = client.post("/rules", json=payload)
    assert response.status_code == 422
