import os

import pytest
import requests


REGISTRY_BASE_URL = os.getenv("REGISTRY_BASE_URL", "http://localhost:5176")
INSIGHTS_BASE_URL = os.getenv("INSIGHTS_BASE_URL", "http://localhost:8000")


@pytest.mark.integration
def test_insights_service_can_talk_to_registry_api():
    """
    Integration test that verifies the Deployment Registry API is reachable.
    """
    response = requests.get(f"{REGISTRY_BASE_URL}/api/health", timeout=5)

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "healthy"
    assert body["dependencies"]["mongodb"] == "connected"


@pytest.mark.integration
def test_insights_frequency_returns_seed_data_counts():
    """
    Integration test that verifies the Insights API can calculate
    daily and weekly deployment frequency using real data from the Registry API.
    """
    response = requests.get(f"{INSIGHTS_BASE_URL}/insights/frequency", timeout=5)

    assert response.status_code == 200

    body = response.json()

    assert body["totalDeployments"] == 75
    assert "dailyByService" in body
    assert "weeklyByService" in body

    assert isinstance(body["dailyByService"], list)
    assert isinstance(body["weeklyByService"], list)
    assert len(body["dailyByService"]) > 0
    assert len(body["weeklyByService"]) > 0

    first_daily_item = body["dailyByService"][0]
    assert "serviceName" in first_daily_item
    assert "date" in first_daily_item
    assert "deploymentCount" in first_daily_item

    first_weekly_item = body["weeklyByService"][0]
    assert "serviceName" in first_weekly_item
    assert "week" in first_weekly_item
    assert "deploymentCount" in first_weekly_item