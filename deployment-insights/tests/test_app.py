import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app


# FastAPI TestClient lets us call the API endpoints in tests
# without starting Uvicorn manually.
client = TestClient(app.app)


# Small fake deployment dataset used by the tests.
# These records are intentionally simple so the expected counts,
# failure rate, lead time, and sorting order are easy to verify.
SAMPLE_DEPLOYMENTS = [
    {
        "id": "1",
        "serviceName": "billing-api",
        "version": "1.0.0",
        "environment": "production",
        "deploymentType": "PullRequest",
        "status": "Succeeded",
        "deployedBy": "alice",
        "startedAt": "2026-04-13T10:00:00Z",
        "finishedAt": "2026-04-13T10:10:00Z",
        "commitSha": "abc",
        "pullRequestNumber": 1,
    },
    {
        "id": "2",
        "serviceName": "billing-api",
        "version": "1.0.1",
        "environment": "staging",
        "deploymentType": "Branch",
        "status": "Failed",
        "deployedBy": "bob",
        "startedAt": "2026-04-13T11:00:00Z",
        "finishedAt": "2026-04-13T11:20:00Z",
        "commitSha": "def",
        "pullRequestNumber": None,
    },
    {
        "id": "3",
        "serviceName": "user-service",
        "version": "2.0.0",
        "environment": "production",
        "deploymentType": "Tag",
        "status": "RolledBack",
        "deployedBy": "carol",
        "startedAt": "2026-04-13T12:00:00Z",
        "finishedAt": "2026-04-13T12:30:00Z",
        "commitSha": "ghi",
        "pullRequestNumber": None,
    },
]


def fake_get_deployments():
    """
    Replacement for app.get_deployments during tests.

    This avoids making real HTTP calls to the Deployment Registry API.
    The tests should be fast and deterministic.
    """
    return SAMPLE_DEPLOYMENTS


def test_health_returns_healthy_when_registry_is_healthy(monkeypatch):
    """
    Verifies that /health returns healthy when the Registry API
    dependency returns a healthy response.
    """

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "healthy"}

    def fake_get(url, timeout):
        return FakeResponse()

    # Replace requests.get with our fake response just for this test.
    monkeypatch.setattr(app.requests, "get", fake_get)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
       "status": "healthy",
        "dependencies": {
            "deploymentRegistry": "healthy"
        },
    }


def test_frequency_counts_daily_and_weekly_by_service(monkeypatch):
    """
    Verifies that /insights/frequency counts deployments daily and weekly
    by service.
    """

    monkeypatch.setattr(app, "get_deployments", fake_get_deployments)

    response = client.get("/insights/frequency")
    body = response.json()

    assert response.status_code == 200
    assert body["totalDeployments"] == 3

    daily_results = {
        (item["serviceName"], item["date"]): item["deploymentCount"]
        for item in body["dailyByService"]
    }

    assert daily_results[("billing-api", "2026-04-13")] == 2
    assert daily_results[("user-service", "2026-04-13")] == 1

    weekly_results = {
        (item["serviceName"], item["week"]): item["deploymentCount"]
        for item in body["weeklyByService"]
    }

    assert weekly_results[("billing-api", "2026-W16")] == 2
    assert weekly_results[("user-service", "2026-W16")] == 1


def test_failure_rate_counts_failed_and_rolled_back_by_service_environment(monkeypatch):
    """
    Verifies that /insights/failure-rate calculates failed and rolled back
    deployment rates per service/environment pair.
    """

    monkeypatch.setattr(app, "get_deployments", fake_get_deployments)

    response = client.get("/insights/failure-rate")
    body = response.json()

    assert response.status_code == 200

    results = {
        (item["serviceName"], item["environment"]): item
        for item in body["byServiceAndEnvironment"]
    }

    billing_production = results[("billing-api", "production")]
    assert billing_production["totalDeployments"] == 1
    assert billing_production["failedDeployments"] == 0
    assert billing_production["rolledBackDeployments"] == 0
    assert billing_production["failureRatePercentage"] == 0.0
    assert billing_production["rollbackRatePercentage"] == 0.0

    billing_staging = results[("billing-api", "staging")]
    assert billing_staging["totalDeployments"] == 1
    assert billing_staging["failedDeployments"] == 1
    assert billing_staging["rolledBackDeployments"] == 0
    assert billing_staging["failureRatePercentage"] == 100.0
    assert billing_staging["rollbackRatePercentage"] == 0.0

    user_production = results[("user-service", "production")]
    assert user_production["totalDeployments"] == 1
    assert user_production["failedDeployments"] == 0
    assert user_production["rolledBackDeployments"] == 1
    assert user_production["failureRatePercentage"] == 0.0
    assert user_production["rollbackRatePercentage"] == 100.0


def test_lead_time_calculates_average_successful_minutes_by_service(monkeypatch):
    """
    Verifies that /insights/lead-time calculates average lead time
    for successful deployments grouped by service.
    """

    monkeypatch.setattr(app, "get_deployments", fake_get_deployments)

    response = client.get("/insights/lead-time")
    body = response.json()

    assert response.status_code == 200
    assert body["byService"] == [
        {
            "serviceName": "billing-api",
            "successfulDeployments": 1,
            "averageLeadTimeMinutes": 10.0,
        }
    ]

def test_latest_returns_latest_successful_deployment_per_service_environment(monkeypatch):
    """
    Verifies that /insights/latest returns the latest successful deployment
    for each service/environment pair.
    """

    monkeypatch.setattr(app, "get_deployments", fake_get_deployments)

    response = client.get("/insights/latest")
    body = response.json()

    assert response.status_code == 200
    assert body["count"] == 1
    assert body["latest"][0]["id"] == "1"
    assert body["latest"][0]["serviceName"] == "billing-api"
    assert body["latest"][0]["environment"] == "production"
    assert body["latest"][0]["status"] == "Succeeded"

def test_insight_endpoint_returns_503_when_registry_fails(monkeypatch):
    """
    Verifies that insight endpoints return a 503 error when the
    Registry API cannot provide deployment data.
    """

    def fake_failure():
        raise HTTPException(status_code=503, detail="Registry unavailable")

    monkeypatch.setattr(app, "get_deployments", fake_failure)

    response = client.get("/insights/frequency")

    assert response.status_code == 503
    assert response.json()["detail"] == "Registry unavailable"