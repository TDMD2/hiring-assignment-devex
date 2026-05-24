# Deployment Insights API

This service provides deployment insights by calling the existing Deployment Registry API.

It is built with Python and FastAPI.

## Prerequisites

- Python 3.9+
- The Deployment Registry API running on `http://localhost:5176`
- MongoDB running through Docker
- Seed data already imported into MongoDB
- Docker Desktop for running the full stack with Docker Compose
- Prometheus and Grafana are started through Docker Compose for observability

## Project Location

This README belongs inside:

```text
hiring-assignment-devex-main/deployment-insights
```

## Setup

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Save dependencies:

```powershell
pip freeze > requirements.txt
```

## Run the Registry API First

The Deployment Insights API depends on the Deployment Registry API from Task 1.

Make sure the Registry API is running at:

```text
http://localhost:5176
```

You can verify it with:

```powershell
curl.exe http://localhost:5176/api/health
```

Expected result:

```json
{
  "status": "healthy",
  "dependencies": {
    "mongodb": "connected"
  }
}
```

## Run the Insights Service

From the `deployment-insights` folder, start the API:

```powershell
python -m uvicorn app:app --reload --port 8000
```

The Insights API will run at:

```text
http://localhost:8000
```


## Running the Full Stack with Docker Compose

Task 3 adds Docker support so MongoDB, the Deployment Registry API, and the Deployment Insights API can be started together.

From the repository root:

```powershell
docker compose up --build
```

Docker Compose starts:

- `mongodb` on port `27017`
- `deployment-registry` on `http://localhost:5176`
- `deployment-insights` on `http://localhost:8000`

The Insights API uses this environment variable inside Docker Compose:

```text
REGISTRY_BASE_URL=http://deployment-registry:8080
```

This is needed because containers communicate by service name. Inside Docker, `localhost` would point to the current container, not the Registry API container.

After the containers start, test the full stack from a second PowerShell window:

```powershell
curl.exe http://localhost:5176/api/health
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/insights/frequency
curl.exe http://localhost:8000/metrics
```

Expected results:

```text
Registry API health: healthy
MongoDB dependency: connected
Insights API health: healthy
Insights dependency deploymentRegistry: healthy
Frequency endpoint returns 75 deployments
Metrics endpoint returns Prometheus-formatted metrics
```

To stop the stack:

```powershell
CTRL + C
```

Or from another terminal:

```powershell
docker compose down
```

## Observability and Monitoring

Track C adds basic observability for the Deployment Insights API.

The Insights API exposes Prometheus metrics at:

```http
GET /metrics
```

Example:

```powershell
curl.exe http://localhost:8000/metrics
```

The metrics include:

```text
deployment_insights_http_requests_total
deployment_insights_http_request_duration_seconds
deployment_insights_registry_health
```

These metrics provide:

- Request counts by HTTP method, path, and status code
- Request latency histograms by HTTP method and path
- Registry API dependency health, where `1` means healthy and `0` means unhealthy

The API also adds structured JSON request logging with correlation IDs. If a request includes an `X-Correlation-ID` header, the service reuses it. Otherwise, the service creates a new correlation ID and returns it in the response headers.

### Prometheus

Prometheus is configured to scrape the Insights API `/metrics` endpoint.

Prometheus runs at:

```text
http://localhost:9090
```

The Prometheus scrape config is stored at:

```text
observability/prometheus/prometheus.yml
```

The scrape target is:

```text
deployment-insights:8000
```

This works inside Docker Compose because `deployment-insights` is the Docker Compose service name.

### Grafana

Grafana runs at:

```text
http://localhost:3000
```

Default local credentials:

```text
Username: admin
Password: admin
```

The Grafana dashboard is provisioned from JSON so it can be version-controlled and recreated automatically.

Dashboard files:

```text
observability/grafana/provisioning/datasources/prometheus.yml
observability/grafana/provisioning/dashboards/dashboards.yml
observability/grafana/dashboards/deployment-insights-dashboard.json
```

The dashboard is named:

```text
Deployment Insights API
```

It includes panels for:

- Registry API health
- Request rate by endpoint
- Error rate
- P95 request latency

To generate normal dashboard traffic:

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/insights/frequency
curl.exe http://localhost:8000/insights/failure-rate
curl.exe http://localhost:8000/insights/lead-time
curl.exe http://localhost:8000/insights/latest
```

To generate test `4xx` error traffic:

```powershell
for ($i = 1; $i -le 10; $i++) {
  curl.exe http://localhost:8000/does-not-exist
}
```

This should create a metric similar to:

```text
deployment_insights_http_requests_total{method="GET",path="/does-not-exist",status_code="404"} 10.0
```


## Endpoints

### Health

```http
GET /health
```

Checks whether the Insights API is running and whether the Deployment Registry API is reachable.

Example:

```powershell
curl.exe http://localhost:8000/health
```

Example response:

```json
{
  "status": "healthy",
  "dependencies": {
    "deploymentRegistry": "healthy"
  }
}
```

### Latest Deployed Versions

```http
GET /insights/latest
```

Returns the latest successfully deployed version for each service and environment.

The endpoint groups deployments by `serviceName` and `environment`, filters to `Succeeded` deployments, and keeps the newest deployment in each group based on `startedAt`.

Example:

```powershell
curl.exe http://localhost:8000/insights/latest
```

Example response shape:

```json
{
  "count": 12,
  "latest": [
    {
      "serviceName": "billing-api",
      "environment": "production",
      "version": "3.12.5",
      "status": "Succeeded",
      "startedAt": "2026-04-13T10:47:11Z",
      "finishedAt": "2026-04-13T11:11:52Z"
    }
  ]
}
```

### Deployment Frequency

```http
GET /insights/frequency
```

Returns deployment frequency per service, grouped by day and by ISO week.

The endpoint returns:

- Total number of deployments
- Daily deployment counts by service
- Weekly deployment counts by service

Example:

```powershell
curl.exe http://localhost:8000/insights/frequency
```

Example response shape from the seed data:

```json
{
  "totalDeployments": 75,
  "dailyByService": [
    {
      "serviceName": "billing-api",
      "date": "2026-04-13",
      "deploymentCount": 2
    }
  ],
  "weeklyByService": [
    {
      "serviceName": "billing-api",
      "week": "2026-W16",
      "deploymentCount": 5
    }
  ]
}
```

### Failure and Rollback Rate

```http
GET /insights/failure-rate
```

Calculates deployment failure and rollback rates per service and environment.

The endpoint groups deployments by `serviceName` and `environment`, then reports:

- Total deployments
- Failed deployments
- Rolled back deployments
- Failure rate percentage
- Rollback rate percentage

Example:

```powershell
curl.exe http://localhost:8000/insights/failure-rate
```

Example response shape:

```json
{
  "byServiceAndEnvironment": [
    {
      "serviceName": "billing-api",
      "environment": "production",
      "totalDeployments": 8,
      "failedDeployments": 0,
      "rolledBackDeployments": 2,
      "failureRatePercentage": 0.0,
      "rollbackRatePercentage": 25.0
    }
  ]
}
```

### Lead Time

```http
GET /insights/lead-time
```

Calculates average lead time from deployment start to successful completion per service.

Only deployments with `status` equal to `Succeeded` and both `startedAt` and `finishedAt` values are included. Failed, rolled back, and incomplete deployments are excluded from the lead-time average.

Example:

```powershell
curl.exe http://localhost:8000/insights/lead-time
```

Example response from the seed data:

```json
{
  "byService": [
    {
      "serviceName": "billing-api",
      "successfulDeployments": 6,
      "averageLeadTimeMinutes": 19.44
    }
  ]
}
```

## Verified Results

With the provided seed data, the service returned:

```text
Total deployments: 75
Frequency returned by service per day and per ISO week
Latest successful deployments per service/environment: 12
Failure and rollback rates returned per service/environment
Successful deployment lead time returned per service
Prometheus metrics exposed at /metrics
Grafana dashboard shows Registry health, request rate, error rate, and p95 latency
Full local test run: 8 passed
CI unit test command: 6 passed, 2 integration tests deselected
```


## Tests

From the `deployment-insights` folder, activate the virtual environment and run:

```powershell
pytest
```

The test suite includes unit tests for the aggregation logic and integration tests for live service connectivity.

Current verified result:

```text
8 passed
```

The unit tests use a small fake deployment dataset and mock the Registry API dependency so the calculation logic can be tested quickly and deterministically.

The integration tests require the Docker Compose stack to be running because they make real HTTP calls to the Registry API and Insights API.

To run only the unit tests, use:

```powershell
pytest -m "not integration"
```

## Docker Files Added

Task 3 adds these files:

```text
docker-compose.yml
deployment-registry/src/DeploymentRegistry.Api/Dockerfile
deployment-insights/Dockerfile
```

The Registry API Dockerfile builds and runs the .NET API on container port `8080`.

The Insights API Dockerfile builds and runs the Python FastAPI service on container port `8000`.

The root `docker-compose.yml` wires together MongoDB, the Registry API, the Insights API, Prometheus, and Grafana.

Observability files added:

```text
observability/prometheus/prometheus.yml
observability/grafana/provisioning/datasources/prometheus.yml
observability/grafana/provisioning/dashboards/dashboards.yml
observability/grafana/dashboards/deployment-insights-dashboard.json
```

## Notes

The Deployment Registry project originally targeted `.NET 10`, but this local setup used `.NET 8`, so the Registry API project file was changed from:

```xml
<TargetFramework>net10.0</TargetFramework>
```

to:

```xml
<TargetFramework>net8.0</TargetFramework>
```

This change was made so the existing Registry API could run locally with the installed .NET 8 SDK.
