import logging
import os
import time
import uuid
from collections import Counter as CollectionCounter
from datetime import datetime
from typing import Any, Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pythonjsonlogger import json
from starlette.responses import Response

# Create the FastAPI application.
# This is the new Deployment Insights service.
app = FastAPI(title="Deployment Insights API")

# The existing Deployment Registry API.
# Locally this defaults to localhost. Docker Compose overrides it with
# http://deployment-registry:8080 so containers can communicate by service name.
REGISTRY_BASE_URL = os.getenv("REGISTRY_BASE_URL", "http://localhost:5176")
REGISTRY_API_URL = f"{REGISTRY_BASE_URL}/api/deployments"
REGISTRY_HEALTH_URL = f"{REGISTRY_BASE_URL}/api/health"


# Structured JSON logging setup.
logger = logging.getLogger("deployment-insights")
logger.setLevel(logging.INFO)

log_handler = logging.StreamHandler()
log_formatter = json.JsonFormatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s "
    "%(correlation_id)s %(method)s %(path)s %(status_code)s %(duration_ms)s"
)
log_handler.setFormatter(log_formatter)

if not logger.handlers:
    logger.addHandler(log_handler)


# Prometheus metrics.
REQUEST_COUNT = Counter(
    "deployment_insights_http_requests_total",
    "Total HTTP requests handled by the Deployment Insights API.",
    ["method", "path", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "deployment_insights_http_request_duration_seconds",
    "HTTP request latency in seconds for the Deployment Insights API.",
    ["method", "path"],
)

REGISTRY_HEALTH = Gauge(
    "deployment_insights_registry_health",
    "Registry API dependency health. 1 means healthy, 0 means unhealthy.",
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """
    Adds request-level observability.

    - Reads or creates a correlation ID.
    - Measures request duration.
    - Emits Prometheus request count and latency metrics.
    - Writes a structured JSON log for each request.
    """
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    start_time = time.time()

    response = await call_next(request)

    duration_seconds = time.time() - start_time
    duration_ms = round(duration_seconds * 1000, 2)

    method = request.method
    path = request.url.path
    status_code = str(response.status_code)

    REQUEST_COUNT.labels(
        method=method,
        path=path,
        status_code=status_code,
    ).inc()

    REQUEST_LATENCY.labels(
        method=method,
        path=path,
    ).observe(duration_seconds)

    response.headers["X-Correlation-ID"] = correlation_id

    logger.info(
        "request completed",
        extra={
            "correlation_id": correlation_id,
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )

    return response


def get_deployments() -> list[dict[str, Any]]:
    """
    Fetch all deployments from the Deployment Registry API.

    If the Registry API is down or unreachable, return a 503 error from
    this Insights API because the insights depend on registry data.
    """
    try:
        response = requests.get(REGISTRY_API_URL, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as error:
        REGISTRY_HEALTH.set(0)
        raise HTTPException(
            status_code=503,
            detail=f"Could not reach Deployment Registry API: {error}",
        )


def parse_time(value: Optional[str]) -> Optional[datetime]:
    """
    Convert an ISO timestamp string into a Python datetime.

    The Registry API returns timestamps ending in 'Z', which means UTC.
    Python's fromisoformat expects '+00:00' instead, so we replace it.
    """
    if not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@app.get("/metrics")
def metrics():
    """
    Prometheus scrape endpoint.
    """
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    """
    Health check for the Insights API.

    This also checks whether the Deployment Registry API is reachable.
    """
    try:
        response = requests.get(REGISTRY_HEALTH_URL, timeout=5)
        response.raise_for_status()
        registry_health = response.json()

        REGISTRY_HEALTH.set(1)

        return {
            "status": "healthy",
            "dependencies": {
                "deploymentRegistry": registry_health.get("status", "unknown")
            },
        }
    except requests.RequestException:
        REGISTRY_HEALTH.set(0)

        return {
            "status": "degraded",
            "dependencies": {
                "deploymentRegistry": "unreachable"
            },
        }


@app.get("/insights/latest")
def latest():
    """
    Return the latest successfully deployed version per service and environment.

    This groups deployments by serviceName and environment, then keeps the newest
    Succeeded deployment in each group based on startedAt.
    """
    deployments = get_deployments()

    latest_by_service_environment: dict[tuple[str, str], dict[str, Any]] = {}

    for deployment in deployments:
        if deployment.get("status") != "Succeeded":
            continue

        service_name = deployment.get("serviceName", "unknown")
        environment = deployment.get("environment", "unknown")
        started_at = parse_time(deployment.get("startedAt"))

        if not started_at:
            continue

        key = (service_name, environment)

        current_latest = latest_by_service_environment.get(key)

        if current_latest is None:
            latest_by_service_environment[key] = deployment
            continue

        current_started_at = parse_time(current_latest.get("startedAt"))

        if current_started_at is None or started_at > current_started_at:
            latest_by_service_environment[key] = deployment

    latest_deployments = sorted(
        latest_by_service_environment.values(),
        key=lambda item: (
            item.get("serviceName", ""),
            item.get("environment", ""),
        ),
    )

    return {
        "count": len(latest_deployments),
        "latest": latest_deployments,
    }


@app.get("/insights/frequency")
def frequency():
    """
    Calculate deployment frequency per service.

    This returns:
    - total number of deployments
    - daily deployment frequency per service
    - weekly deployment frequency per service
    """
    deployments = get_deployments()

    daily_by_service: CollectionCounter[tuple[str, str]] = CollectionCounter()
    weekly_by_service: CollectionCounter[tuple[str, str]] = CollectionCounter()

    for deployment in deployments:
        service_name = deployment.get("serviceName", "unknown")
        started_at = parse_time(deployment.get("startedAt"))

        if not started_at:
            continue

        day = started_at.date().isoformat()
        iso_year, iso_week, _ = started_at.isocalendar()
        week = f"{iso_year}-W{iso_week:02d}"

        daily_by_service[(service_name, day)] += 1
        weekly_by_service[(service_name, week)] += 1

    daily_results = [
        {
            "serviceName": service_name,
            "date": date,
            "deploymentCount": count,
        }
        for (service_name, date), count in daily_by_service.items()
    ]

    weekly_results = [
        {
            "serviceName": service_name,
            "week": week,
            "deploymentCount": count,
        }
        for (service_name, week), count in weekly_by_service.items()
    ]

    return {
        "totalDeployments": len(deployments),
        "dailyByService": sorted(
            daily_results,
            key=lambda item: (item["serviceName"], item["date"]),
        ),
        "weeklyByService": sorted(
            weekly_results,
            key=lambda item: (item["serviceName"], item["week"]),
        ),
    }


@app.get("/insights/failure-rate")
def failure_rate():
    """
    Calculate failure and rollback rate per service and environment.

    Failed deployments and rolled back deployments are tracked separately.
    """
    deployments = get_deployments()

    groups: dict[tuple[str, str], dict[str, Any]] = {}

    for deployment in deployments:
        service_name = deployment.get("serviceName", "unknown")
        environment = deployment.get("environment", "unknown")
        status = deployment.get("status", "unknown")

        key = (service_name, environment)

        if key not in groups:
            groups[key] = {
                "serviceName": service_name,
                "environment": environment,
                "totalDeployments": 0,
                "failedDeployments": 0,
                "rolledBackDeployments": 0,
            }

        groups[key]["totalDeployments"] += 1

        if status == "Failed":
            groups[key]["failedDeployments"] += 1

        if status == "RolledBack":
            groups[key]["rolledBackDeployments"] += 1

    results = []

    for group in groups.values():
        total = group["totalDeployments"]
        failed = group["failedDeployments"]
        rolled_back = group["rolledBackDeployments"]

        results.append({
            **group,
            "failureRatePercentage": 0 if total == 0 else round((failed / total) * 100, 2),
            "rollbackRatePercentage": 0 if total == 0 else round((rolled_back / total) * 100, 2),
        })

    return {
        "byServiceAndEnvironment": sorted(
            results,
            key=lambda item: (item["serviceName"], item["environment"]),
        )
    }


@app.get("/insights/lead-time")
def lead_time():
    """
    Calculate average lead time from start to success per service.

    Only Succeeded deployments with both startedAt and finishedAt are included.
    """
    deployments = get_deployments()

    by_service: dict[str, list[float]] = {}

    for deployment in deployments:
        if deployment.get("status") != "Succeeded":
            continue

        service_name = deployment.get("serviceName", "unknown")
        started_at = parse_time(deployment.get("startedAt"))
        finished_at = parse_time(deployment.get("finishedAt"))

        if started_at and finished_at:
            duration_minutes = (finished_at - started_at).total_seconds() / 60
            by_service.setdefault(service_name, []).append(duration_minutes)

    results = []

    for service_name, durations in by_service.items():
        average_minutes = sum(durations) / len(durations)

        results.append({
            "serviceName": service_name,
            "successfulDeployments": len(durations),
            "averageLeadTimeMinutes": round(average_minutes, 2),
        })

    return {
        "byService": sorted(results, key=lambda item: item["serviceName"])
    }
