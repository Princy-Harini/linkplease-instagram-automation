# System Failure Modes Analysis (FAILURES.md)

This document provides a candid, production-oriented architectural breakdown of edge cases, failure states, and concurrency boundaries in the LinkPlease Instagram Automation service. As required by engineering best practices, this analysis avoids claiming theoretical perfection and details realistic scenarios where distributed state, network partitions, or third-party behaviors present edge-case anomalies.

---

## Failure Mode 1: Network Partition During HTTP 202 Accepted Response Delivery

### 1. Condition
A worker invokes `POST /v1/dm/send` on the Mock PseudoGram API. The external server successfully receives the request, queues the DM, and returns `HTTP 202 Accepted` with a new `dm_id`. However, before the HTTP response packets reach our worker, an intermediate network partition, TCP reset, or gateway timeout occurs.

### 2. What Could Go Wrong
From the perspective of our backend worker, the request failed with a `NetworkError` or `ReadTimeout`. The worker catches `PseudoGramTransientError`, records a retry attempt, and re-enqueues `send_dm_task` to dispatch the DM again. If the external service does not properly support or validate idempotency, a second duplicate DM could potentially be sent to the end user.

### 3. Why It Happens
This is the classic distributed two-generals problem. In any remote HTTP transaction, the sender cannot distinguish between "request never arrived at destination" versus "request succeeded at destination but response was lost in transit."

### 4. Current Mitigation
- We compute a deterministic `Idempotency-Key` header (`dm:{user_id}:{rule_id}`) and transmit it with every `POST /v1/dm/send` request.
- When the worker retries the call with the exact same `Idempotency-Key`, the Mock PseudoGram API recognizes the duplicate transaction and returns the original `dm_id` rather than dispatching a duplicate message.
- At the database level, our `deliveries` table enforces a `UNIQUE(user_id, rule_id)` constraint, preventing multiple delivery rows from being created internally.

### 5. What Would Be Needed to Eliminate It Completely
If the external third-party provider dropped or failed to respect the `Idempotency-Key` header, total elimination would require a two-phase commit protocol or an external queryable pre-send verification endpoint (e.g. `GET /v1/dm/by-idempotency-key/{key}`) prior to attempting any retransmission.

---

## Failure Mode 2: User Deletion of Comment Arriving Post-Delivery

### 1. Condition
A user posts a comment `"PRICE please"`. Our webhook receives the event, matches the rule, queues the DM, and the worker executes `POST /v1/dm/send` within 2 seconds. Forty seconds later, the user deletes their comment on Instagram/PseudoGram, and our webhook receives a `comment.deleted` event.

### 2. What Could Go Wrong
The user receives an automated DM for a comment that is no longer visible on their post, potentially leading to confusion or privacy concerns.

### 3. Why It Happens
Event arrival order is physically decoupled from external user actions. Once a message has been accepted and dispatched to a recipient's inbox via a third-party messaging API, remote direct messages cannot be asynchronously recalled ("un-sent") via standard Instagram/Meta Graph APIs.

### 4. Current Mitigation
- When `comment.deleted` arrives, our backend immediately marks the comment as `is_deleted = TRUE` in the `comments` table.
- Before executing any outbound HTTP call, `send_dm_task` queries the `comments` table. If `comment.is_deleted == TRUE`, the task immediately aborts and cancels delivery.
- If `comment.deleted` arrives before `comment.created` (out-of-order delivery), our upsert logic initializes a placeholder with `is_deleted = TRUE`, ensuring late-arriving creation events are discarded.

### 5. What Would Be Needed to Eliminate It Completely
Total elimination is impossible in real-world social platforms because external messaging systems lack a distributed "unsend" transaction across third-party inboxes once delivery completes. A deliberate processing delay (e.g., waiting 30 seconds before sending DMs) could reduce the window, but at the cost of user responsiveness.

---

## Failure Mode 3: Indefinite Reconciliation Stall on Third-Party "Queued" State

### 1. Condition
The external Mock PseudoGram API accepts a DM (`HTTP 202 Accepted`), but its internal delivery processing worker halts or silently crashes. Repeated calls to `GET /v1/dm/{dm_id}` perpetually return `{"status": "queued"}` without ever transitioning to `delivered` or `failed`.

### 2. What Could Go Wrong
- The delivery remains permanently in `status = 'queued'`.
- The `GET /stats` endpoint indefinitely reports this DM under `queued` rather than `sent` or `failed`.
- Celery workers could exhaust maximum reconciliation polling iterations.

### 3. Why It Happens
Our system depends on the external provider to update its internal delivery state. If the upstream provider does not advance the state machine, polling reaches the `RECONCILIATION_MAX_ATTEMPTS` limit and stops.

### 4. Current Mitigation
- We bound active polling to `RECONCILIATION_MAX_ATTEMPTS = 10` iterations with increasing backoff intervals to avoid wasteful HTTP churn.
- The delivery record retains its `dm_id` and `queued` state without corrupting the `sent` count.

### 5. What Would Be Needed to Eliminate It Completely
Implement an automated Dead Letter Queue (DLQ) sweeper cron job (e.g. running every 60 minutes) that scans the `deliveries` table for records stuck in `queued` state for more than 24 hours. If an item exceeds the 24-hour threshold with no external progress, the sweeper marks the delivery as `failed` with error `"Upstream delivery confirmation timed out"`.

---

## Failure Mode 4: Redis Outage / Eviction During High-Throughput Burst

### 1. Condition
During a burst of 500 events within 10 seconds, Redis runs out of memory (OOM) or crashes, causing the sliding window rate-limiter keys to be evicted or connection errors to occur.

### 2. What Could Go Wrong
If Redis is unreachable:
1. Celery task broker becomes temporarily unavailable.
2. The sliding window rate limiter fallback mechanism must choose between blocking all outbound traffic (zero throughput) or permitting requests with caution (potential risk of exceeding 10 req/60s).

### 3. Why It Happens
Redis acts as the shared synchronization coordinator for distributed rate limits across multi-process workers. Loss of the coordination layer forces a tradeoff between availability and strict consistency (CAP theorem).

### 4. Current Mitigation
- In our rate limiter service, if Redis throws a connection exception, the error is caught and logged, and the task falls back to local bounded retry behavior.
- If the external Mock API responds with `HTTP 429 Too Many Requests`, our client parses the `Retry-After` header and dynamically pauses worker processing until the cooldown period expires.
- All webhook events and delivery jobs are ACID-persisted in PostgreSQL before queue dispatch, ensuring zero data loss if Redis restarts.

### 5. What Would Be Needed to Eliminate It Completely
- Deploy Redis in High Availability mode (Redis Sentinel or AWS ElastiCache Multi-AZ) with strict persistence (`appendonly yes`).
- Implement an in-process local token-bucket rate limiter per worker node that enforces a hard ceiling even during complete Redis isolation.

---
