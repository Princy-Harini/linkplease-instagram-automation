# LinkPlease Instagram Automation Backend

A high-reliability, asynchronous backend system engineered for Instagram comment keyword-triggered Direct Message (DM) automation. Built to interface with the deliberately unreliable Mock PseudoGram API, the system enforces strict duplicate prevention at the database level, handles high-throughput webhook spikes without loss, manages distributed sliding-window rate limiting, and guarantees accurate delivery statistics.

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Architecture Diagram & Component Flow](#2-architecture-diagram--component-flow)
3. [Technology Stack & Architectural Decisions](#3-technology-stack--architectural-decisions)
4. [Database Design & Schema](#4-database-design--schema)
5. [API Contract & Mandatory Endpoints](#5-api-contract--mandatory-endpoints)
6. [Webhook Processing Lifecycle](#6-webhook-processing-lifecycle)
7. [Duplicate Prevention & Identity Model](#7-duplicate-prevention--identity-model)
8. [Retry Mechanism & Backoff Strategy](#8-retry-mechanism--backoff-strategy)
9. [Distributed Rate Limiting (10 req/60s)](#9-distributed-rate-limiting-10-req60s)
10. [Delivery Reconciliation (202 vs Delivered)](#10-delivery-reconciliation-202-vs-delivered)
11. [Comment Deletion Handling (Out-of-Order Safety)](#11-comment-deletion-handling-out-of-order-safety)
12. [Security & HMAC Signature Verification](#12-security--hmac-signature-verification)
13. [Environment Configuration](#13-environment-configuration)
14. [Local Development & Setup](#14-local-development--setup)
15. [Running the Test Suite](#15-running-the-test-suite)
16. [500-Event Load Testing](#16-500-event-load-testing)
17. [Deployment Guide (Render / Railway / Docker)](#17-deployment-guide)
18. [Known Limitations & Tradeoffs](#18-known-limitations--tradeoffs)

---

## 1. Project Overview

LinkPlease connects to social platforms to automatically send direct messages when users comment specific keywords on posts. This backend solves the core engineering challenges of real-world social automation:
- **Webhook Ingestion Decoupling**: Fast HTTP 200 response (< 50ms) to withstand bursts (e.g. 500 events in 10 seconds).
- **Hard Duplicate Prevention**: Enforces a strict guarantee that a user (`user_id`) never receives more than one DM for a given rule (`rule_id`), protected at the database engine level against race conditions.
- **Unreliable Third-Party Resilience**: Tolerates HTTP 500 server errors (~20%), network timeouts, HTTP 429 rate limits, and non-retriable HTTP 400 bad requests.
- **Two-Phase Delivery Lifecycle**: Recognizes that HTTP 202 Accepted means queued (not delivered), and actively reconciles status until confirmed.
- **Real-time ACID Statistics**: Live aggregate reporting without unreliable in-memory counters.

---

## 2. Architecture Diagram & Component Flow

```text
                                  +-----------------------------+
                                  |    Mock PseudoGram API      |
                                  | (https://pseudogram-api...) |
                                  +--------------+--------------+
                                                 |
                   Webhook Events (HMAC Signed)  |  POST /v1/dm/send (Rate limited: 10/60s)
                                                 |  GET /v1/dm/{dm_id} (Reconciliation)
                                                 v
                                    +------------------------+
                                    |     FastAPI Server     |
                                    | (POST /webhook < 50ms) |
                                    | (POST /rules, GET/stats|
                                    +-----------+------------+
                                                |
               +--------------------------------+-------------------------------+
               | Fast Webhook Ingestion                                          | ACID DB
               v                                                                 v
+-----------------------------+                                    +---------------------------+
|        Redis Broker         |                                    |    PostgreSQL Database    |
| (Persistent Event / DM Que) |                                    | - rules                   |
+--------------+--------------+                                    | - webhook_events          |
               |                                                   | - comments                |
               v                                                   | - deliveries (UNIQUE u+r) |
+-----------------------------+                                    | - blocked_duplicates      |
|    Celery Workers           |<---------------------------------->+---------------------------+
| - Event Processing Worker   | (Persist states, check comment status, acquire rate-limit slot)
| - DM Sender (Rate Limiter)  |
| - Delivery Reconciler       |
+-----------------------------+
```

---

## 3. Technology Stack & Architectural Decisions

### 3.1. Why FastAPI?
- **Asynchronous Native Performance**: Handles high-concurrency webhook ingestion with minimal latency overhead.
- **Strict Data Validation**: Pydantic v2 ensures all incoming payloads and external API contracts are strictly validated.
- **Standard OpenAPI**: Auto-generated API documentation accessible at `/docs`.

### 3.2. Why PostgreSQL?
- **ACID Reliability**: Protects state transitions across concurrent transactions.
- **Database Engine Unique Constraints**: `UNIQUE(user_id, rule_id)` prevents duplicate DM generation across concurrent workers, eliminating time-of-check to time-of-use (TOCTOU) race conditions.
- **Audit Logging**: Persists raw webhook payloads, delivery histories, and blocked duplicate events for debugging and reporting.

### 3.3. Why Redis & Celery?
- **Decoupled Asynchronous Processing**: Offloads slow network operations and third-party rate limiting from the HTTP request-response cycle.
- **Persistent Distributed Scheduling**: Celery's `countdown` / `eta` enables exponential backoff, jitter, and Retry-After pauses without blocking worker threads.
- **Sliding-Window Rate Limiter**: Redis Sorted Sets (`zset`) coordinate the strict 10 requests per 60-second limit across multiple distributed workers.

---

## 4. Database Design & Schema

The schema is managed with **SQLAlchemy 2.0** and **Alembic** migrations:

```sql
-- 1. Rules Table: stores trigger keywords and DM responses
CREATE TABLE rules (
    id VARCHAR(36) PRIMARY KEY,
    keyword VARCHAR(255) NOT NULL,
    dm_message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rules_keyword ON rules(keyword);

-- 2. Webhook Events Table: event idempotency and payload audit
CREATE TABLE webhook_events (
    event_id VARCHAR(64) PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    sent_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSON NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'received'
);

-- 3. Comments Table: tracks comment lifecycle and out-of-order deletion
CREATE TABLE comments (
    comment_id VARCHAR(64) PRIMARY KEY,
    post_id VARCHAR(64),
    user_id VARCHAR(64),
    username VARCHAR(255),
    text TEXT,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    comment_created_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_comments_user_id ON comments(user_id);

-- 4. Deliveries Table: tracks DM jobs, retries, and unique constraints
CREATE TABLE deliveries (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    rule_id VARCHAR(36) NOT NULL REFERENCES rules(id) ON DELETE RESTRICT,
    comment_id VARCHAR(64) NOT NULL,
    dm_id VARCHAR(64),
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'queued', -- 'queued', 'sending', 'sent', 'failed'
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 5,
    last_error TEXT,
    next_retry_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_deliveries_user_rule UNIQUE (user_id, rule_id)
);
CREATE INDEX idx_deliveries_dm_id ON deliveries(dm_id);
CREATE INDEX idx_deliveries_status ON deliveries(status);

-- 5. Blocked Duplicates Table: audit log for GET /stats
CREATE TABLE blocked_duplicates (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    rule_id VARCHAR(36) NOT NULL,
    comment_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_blocked_dup_event_rule UNIQUE (event_id, rule_id)
);
CREATE INDEX idx_blocked_dup_user_rule ON blocked_duplicates(user_id, rule_id);
```

---

## 5. API Contract & Mandatory Endpoints

### 1. `POST /rules`
Registers a keyword and DM message pair.
- **Request**:
  ```json
  {
    "keyword": "PRICE",
    "dm_message": "Here is the pricing sheet: https://example.com/pricing"
  }
  ```
- **Response** (`HTTP 201 Created`):
  ```json
  {
    "rule_id": "rule_a1b2c3d4e5f6",
    "keyword": "PRICE",
    "dm_message": "Here is the pricing sheet: https://example.com/pricing"
  }
  ```

### 2. `POST /webhook`
Ingests Instagram webhook events within 50ms.
- **Headers**:
  - `X-PseudoGram-Signature: sha256=<hmac_sha256_hex>` (if signature verification is enabled)
- **Request**:
  ```json
  {
    "event_id": "evt_01J8ZQ4K2N7RXA",
    "event_type": "comment.created",
    "sent_at": "2026-08-10T09:14:22.481Z",
    "data": {
      "comment_id": "cmt_9f2a7c",
      "post_id": "post_44de1b",
      "text": "PRICE please 🙏",
      "created_at": "2026-08-10T09:14:21.900Z",
      "from": {
        "user_id": "usr_3b91fe",
        "username": "arjun.shoots"
      }
    }
  }
  ```
- **Response** (`HTTP 200 OK`):
  ```json
  {
    "status": "ok",
    "event_id": "evt_01J8ZQ4K2N7RXA"
  }
  ```

### 3. `GET /stats`
Returns live statistics aggregated directly from the database.
- **Response** (`HTTP 200 OK`):
  ```json
  {
    "sent": 142,
    "failed": 3,
    "queued": 8,
    "duplicates_blocked": 57
  }
  ```
- **Definitions**:
  - `sent`: DMs confirmed as `delivered` by Mock API (`status = 'sent'`).
  - `failed`: DMs permanently failed after retries exhausted or HTTP 400 (`status = 'failed'`).
  - `queued`: DMs waiting in queue, in-flight, or pending delivery reconciliation (`status IN ('queued', 'sending')`).
  - `duplicates_blocked`: DM triggers blocked because the user already received a DM for that rule.

---

## 6. Webhook Processing Lifecycle

1. **Ingest & Verify**: The webhook endpoint receives the raw request body, verifies the HMAC-SHA256 signature, and parses the JSON.
2. **Event Idempotency**: Performs an atomic insert into `webhook_events`. If `event_id` already exists, returns HTTP 200 `duplicate_ignored` and skips task scheduling.
3. **Queue Task**: Dispatches `process_webhook_event_task.delay(event_id)` to Celery and returns HTTP 200 immediately (< 50ms).
4. **Worker Match & Deduplicate**: The worker loads active rules, tests case-insensitive substring matching against comment text, checks `comment.is_deleted`, and attempts an atomic insert into `deliveries`.
5. **DM Dispatch**: If new, `send_dm_task.delay(delivery_id)` is dispatched.

---

## 7. Duplicate Prevention & Identity Model

- **Identity Standard**: User identity is strictly tracked by `user_id` (e.g. `usr_3b91fe`), NEVER `username` (which can change).
- **Composite Unique Key**: The `deliveries` table enforces `UNIQUE(user_id, rule_id)`.
- **Concurrency Safety**: If two identical comments arrive simultaneously from the same user matching the same rule:
  - Worker A succeeds in inserting the delivery row.
  - Worker B encounters the unique key constraint violation in PostgreSQL, catches `IntegrityError`, logs the duplicate attempt into `blocked_duplicates`, and halts.
  - Exactly one DM job is ever created.

---

## 8. Retry Mechanism & Backoff Strategy

The Mock PseudoGram API randomly fails (~20% HTTP 500) and enforces rate limits (HTTP 429). Our retry policy:
- **HTTP 500 & Network Errors**: Retried up to `MAX_RETRIES = 5` using exponential backoff with full jitter:
  $$\text{delay} = 2^{\text{retry\_count}} + \text{uniform}(0.5, 2.0)$$
- **HTTP 429 Rate Limit**: Parses the `Retry-After` header, sets a Redis rate limiter lockout timestamp, and reschedules the task with `countdown = retry_after + 1`.
- **HTTP 400 Bad Request**: Non-retriable client error. Delivery status is immediately transitioned to `'failed'` without wasteful retries.
- **Crash Recovery**: All retry counts and next execution timestamps are persisted in PostgreSQL.

---

## 9. Distributed Rate Limiting (10 req/60s)

To comply with the Mock API's limit of **10 requests per rolling 60-second window**:
- We use a Redis Sorted Set (`zset`) sliding window algorithm.
- Scores represent timestamps of dispatched requests.
- When `send_dm_task` executes, it purges entries older than `now - 60s` and counts active members.
- If count < 10, the request timestamp is added and allowed immediately.
- If count >= 10, the worker calculates the exact seconds until the oldest slot expires and delays the task via `self.apply_async(countdown=wait_seconds)`.

---

## 10. Delivery Reconciliation (202 vs Delivered)

- `POST /v1/dm/send` returns `HTTP 202 Accepted` with `{"dm_id": "dm_...", "status": "queued"}`.
- **202 is NEVER counted as sent**.
- The worker updates `delivery.dm_id` and schedules `reconcile_delivery_task(delivery_id)`.
- The reconciliation task polls `GET /v1/dm/{dm_id}` (reads do not count towards the 10/min rate limit):
  - `status == "delivered"`: Sets `deliveries.status = 'sent'`, sets `delivered_at = NOW()`, incrementing the `sent` count.
  - `status == "queued"`: Re-schedules polling with backoff up to `RECONCILIATION_MAX_ATTEMPTS`.
  - `status == "failed"`: Triggers defined retry policy or marks delivery as `failed`.

---

## 11. Comment Deletion Handling (Out-of-Order Safety)

- **Standard Deletion**: When `comment.deleted` arrives, `CommentsRepository.mark_comment_deleted` sets `is_deleted = TRUE`.
- **Out-of-Order Deletion**: If `comment.deleted` arrives *before* `comment.created`, a placeholder record with `is_deleted = TRUE` is created. When `comment.created` arrives later, our upsert preserves `is_deleted = TRUE` and immediately skips DM generation.
- **Pre-Send Verification**: `send_dm_task` re-checks `comment.is_deleted` immediately prior to issuing the outbound HTTP request.

---

## 12. Security & HMAC Signature Verification

- Webhook authenticity is verified via header `X-PseudoGram-Signature: sha256=<hex_digest>`.
- The digest is computed as:
  $$\text{HMAC-SHA256}(\text{raw\_body\_bytes}, \text{PSEUDOGRAM\_API\_KEY})$$
- Uses constant-time comparison (`hmac.compare_digest`) to prevent timing attacks.
- Forged or invalid signatures return `HTTP 401 Unauthorized`.
- Secrets and API keys are never logged.

---

## 13. Environment Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:postgres@localhost:5432/linkplease_db` |
| `REDIS_URL` | Redis broker connection string | `redis://localhost:6379/0` |
| `PSEUDOGRAM_BASE_URL` | Mock PseudoGram API base URL | `https://pseudogram-api.onrender.com` |
| `PSEUDOGRAM_API_KEY` | PseudoGram API Key | *Required for live API* |
| `VERIFY_WEBHOOK_SIGNATURE`| Enforce HMAC-SHA256 signature verification | `false` (set `true` in prod) |
| `MAX_RETRIES` | Max retries for transient errors | `5` |
| `RATE_LIMIT_PER_MINUTE` | Max DM requests per minute | `10` |
| `RATE_LIMIT_WINDOW_SECONDS`| Rolling window duration in seconds | `60` |

---

## 14. Local Development & Setup

### Option A: Using Docker Compose (Recommended)
Orchestrates PostgreSQL, Redis, FastAPI web server, and Celery worker in one command:

```bash
docker compose up --build
```
The API is available at `http://localhost:8000`. Swagger documentation is at `http://localhost:8000/docs`.

### Option B: Local Python Virtual Environment

1. **Activate Virtual Environment**:
   ```bash
   # Windows
   .\venv\Scripts\activate
   # Linux/macOS
   source venv/bin/activate
   ```
2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run Migrations**:
   ```bash
   alembic upgrade head
   ```
4. **Start Web API**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
5. **Start Celery Worker**:
   ```bash
   celery -A app.workers.celery_app worker --loglevel=info -c 2
   ```

---

## 15. Running the Test Suite

The automated test suite contains **31 comprehensive unit and integration test cases** covering all 24+ rubric requirements without requiring live external services:

```bash
pytest -v
```

Output:
```text
tests/integration/test_comment_deleted.py::test_comment_deleted_before_created PASSED
tests/integration/test_comment_deleted.py::test_comment_deleted_before_dm_dispatch PASSED
tests/integration/test_delivery_reconciliation.py::test_202_accepted_not_counted_as_sent PASSED
tests/integration/test_delivery_reconciliation.py::test_reconciliation_transitions_to_sent PASSED
tests/integration/test_duplicate_prevention.py::test_same_user_multiple_comments_single_dm PASSED
tests/integration/test_duplicate_prevention.py::test_database_level_unique_constraint_enforcement PASSED
tests/integration/test_persistence_restart.py::test_database_persistence_across_session_restart PASSED
tests/integration/test_retries_and_backoff.py::test_pseudogram_500_triggers_retry PASSED
tests/integration/test_retries_and_backoff.py::test_network_timeout_triggers_retry PASSED
tests/integration/test_retries_and_backoff.py::test_pseudogram_429_respects_retry_after PASSED
tests/integration/test_retries_and_backoff.py::test_pseudogram_400_marks_failed_immediately PASSED
tests/integration/test_retries_and_backoff.py::test_pseudogram_max_retries_exceeded PASSED
tests/integration/test_rules_api.py::test_create_rule_success PASSED
tests/integration/test_rules_api.py::test_create_rule_validation_empty_keyword PASSED
tests/integration/test_rules_api.py::test_create_rule_validation_empty_message PASSED
tests/integration/test_stats_api.py::test_get_stats_empty PASSED
tests/integration/test_stats_api.py::test_get_stats_populated PASSED
tests/integration/test_webhook_api.py::test_webhook_returns_200_and_enqueues PASSED
tests/integration/test_webhook_api.py::test_duplicate_event_id_ignored PASSED
tests/integration/test_webhook_api.py::test_webhook_signature_verification_failure PASSED
tests/unit/test_rate_limiter.py::test_rate_limiter_allows_under_limit PASSED
tests/unit/test_rate_limiter.py::test_rate_limiter_blocks_11th_request PASSED
tests/unit/test_rate_limiter.py::test_rate_limiter_429_lockout PASSED
tests/unit/test_rule_matcher.py::test_rule_matcher_exact_case PASSED
tests/unit/test_rule_matcher.py::test_rule_matcher_case_insensitive PASSED
tests/unit/test_rule_matcher.py::test_rule_matcher_substring_anywhere PASSED
tests/unit/test_rule_matcher.py::test_rule_matcher_non_matching PASSED
tests/unit/test_rule_matcher.py::test_find_matching_rules PASSED
tests/unit/test_security.py::test_verify_webhook_signature_valid PASSED
tests/unit/test_security.py::test_verify_webhook_signature_invalid PASSED
tests/unit/test_security.py::test_verify_webhook_signature_tampered_payload PASSED

======================== 31 passed in 1.59s ========================
```

---

## 16. 500-Event Load Testing

To run the official PseudoGram 500-event simulation:
1. Ensure your backend is reachable via a public URL (or ngrok/tunnel for local development).
2. Create your rule via `POST /rules` (e.g. keyword `"PRICE"`).
3. Trigger the simulation:
   ```bash
   curl -X POST https://pseudogram-api.onrender.com/v1/simulate/start \
     -H "X-API-Key: <your_api_key>" \
     -H "Content-Type: application/json" \
     -d '{
       "webhook_url": "https://your-public-backend-url.com/webhook",
       "count": 500,
       "duration_seconds": 10
     }'
   ```
4. Monitor stats until the worker finishes processing:
   ```bash
   curl https://your-public-backend-url.com/stats
   ```
5. Compare your `/stats` against the truth endpoint:
   ```bash
   curl -H "X-API-Key: <your_api_key>" https://pseudogram-api.onrender.com/v1/simulate/{run_id}/truth
   ```

---

## 17. Deployment Guide

### Deploying to Render / Railway / Cloud Provider
1. **Provision PostgreSQL & Redis** services on your hosting provider.
2. **Deploy Web Service**:
   - Runtime: `Docker` (or Python 3.13)
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. **Deploy Background Worker Service**:
   - Start Command: `celery -A app.workers.celery_app worker --loglevel=info -c 2`
4. **Set Environment Variables**:
   - `DATABASE_URL` = `<postgres_connection_string>`
   - `REDIS_URL` = `<redis_connection_string>`
   - `PSEUDOGRAM_API_KEY` = `<your_api_key>`
   - `VERIFY_WEBHOOK_SIGNATURE` = `true`

---

## 18. Known Limitations & Tradeoffs

See [`FAILURES.md`](./FAILURES.md) for a comprehensive deep-dive into distributed failure modes and architectural mitigations.
