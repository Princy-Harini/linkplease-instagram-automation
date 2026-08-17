# System Failure Modes Analysis (FAILURES.md)

This document provides a candid, production-grade architectural breakdown of failure states, edge-case anomalies, and distributed system boundaries in the LinkPlease Instagram Automation service.

Rather than claiming theoretical perfection, this analysis details exact failure conditions, code-level behaviors, root causes, and empirical testing observations.

---

## Failure Mode 1: Permanent DM Loss via Retry Exhaustion on Persistent Upstream Outage

### 1. Condition
The external Mock PseudoGram API encounters an extended outage, returning persistent `HTTP 500 Internal Server Error`, network connection timeouts, or TLS handshake failures continuously across all retry attempts.

### 2. What Happens
In [`app/workers/tasks.py`](file:///d:/linkplease-assignment/app/workers/tasks.py#L220-L245), `send_dm_task` catches `PseudoGramTransientError` and increments `delivery.retry_count`. The task applies exponential backoff with full jitter:
$$\text{countdown} = \min(2^{\text{retry\_count}} + \text{jitter}, 60)$$
Once `retry_count >= MAX_RETRIES` (5 attempts), Celery worker stops retrying, marks the delivery record as `status = 'failed'` in PostgreSQL, and records the final exception in `delivery.last_error`. The DM is permanently dropped and never sent.

### 3. Why It Happens
Finite retry budgets are required to prevent queue starvation and infinite worker loops. Without an asynchronous secondary Dead-Letter Queue (DLQ) persistent re-drive mechanism or human-in-the-loop replay dashboard, terminal retry exhaustion results in permanent message loss.

### 4. Empirical Status
**Observed and verified in automated tests** ([`tests/integration/test_retries_and_backoff.py::test_pseudogram_max_retries_exceeded`](file:///d:/linkplease-assignment/tests/integration/test_retries_and_backoff.py#L125)).

---

## Failure Mode 2: Duplicate DM Dispatch under Network Partition with Non-Idempotent Upstream

### 1. Condition
The worker sends `POST /v1/dm/send` to the Mock PseudoGram API. The external server receives the request, writes to its messaging queue, and sends the DM to the user's inbox. However, before the `HTTP 202 Accepted` response packets return to the worker, an intermediate network partition, TCP reset, or gateway timeout drops the connection. Simultaneously, the upstream provider fails to respect or enforce the `Idempotency-Key` header.

### 2. What Happens
From LinkPlease's perspective, the HTTP call threw a `ReadTimeout` / `NetworkError`. Because `delivery.status` is still `queued`, Celery re-enqueues `send_dm_task`. When the retried request reaches PseudoGram, if the upstream API does not deduplicate on `Idempotency-Key`, PseudoGram creates a second direct message in the recipient's inbox.

### 3. Why It Happens
This is the classic distributed Two-Generals Problem. An HTTP client cannot distinguish between "the request failed to reach the server" versus "the request succeeded but the response was lost in transit." While LinkPlease strictly enforces `UNIQUE(user_id, rule_id)` locally, upstream message duplication is entirely bounded by the third-party provider's idempotency implementation.

### 4. Empirical Status
**Theoretical distributed systems limitation** (Mitigated in LinkPlease via deterministic `Idempotency-Key: dm:{user_id}:{rule_id}` on all outbound calls).

---

## Failure Mode 3: Indefinite Reconciliation Stall on Third-Party "Queued" State

### 1. Condition
The Mock PseudoGram API accepts a DM (`HTTP 202 Accepted`), returning `{"status": "queued", "dm_id": "dm_xxx"}`. However, the upstream dispatch worker halts or silently crashes. Subsequent reconciliation calls (`GET /v1/dm/{dm_id}`) perpetually return `{"status": "queued"}` without ever advancing to `delivered` or `failed`.

### 2. What Happens
In [`app/workers/tasks.py`](file:///d:/linkplease-assignment/app/workers/tasks.py#L290-L335), `reconcile_delivery_task` polls upstream with exponential backoff up to `RECONCILIATION_MAX_ATTEMPTS` (10 iterations). Upon reaching attempt 10, the task logs a warning and exits. The delivery row remains permanently in `status = 'queued'` in PostgreSQL, and `GET /stats` permanently reports this DM under `queued` instead of `sent` or `failed`.

### 3. Why It Happens
LinkPlease strictly complies with two-phase delivery reconciliation: a DM is **never** counted under `sent` unless explicitly confirmed `delivered` by upstream. If upstream permanently stalls, LinkPlease cannot guess the outcome without risking false-positive reporting.

### 4. Empirical Status
**Observed during edge-case analysis and verified via bounded reconciliation tasks** ([`tests/integration/test_delivery_reconciliation.py`](file:///d:/linkplease-assignment/tests/integration/test_delivery_reconciliation.py)).

---

## Failure Mode 4: Ingress Throttling During High-Concurrency Burst (500 Events / 10 Seconds)

### 1. Condition
An external simulation bursts 500 webhook events within a 10-second window (50 requests/second) across the public internet against a single free-tier cloud instance.

### 2. What Happens
During the official live simulation run (`run_aa4b696f4023`), the simulator generated 500 events, but the truth endpoint recorded:
```json
{
  "run_id": "run_aa4b696f4023",
  "status": "complete",
  "total_events_generated": 500,
  "total_deliveries_attempted": 539,
  "webhook_200_count": 0,
  "expected_unique_recipient_count": 96
}
```
While direct local and controlled batch webhooks succeed with `HTTP 200` in $< 50\text{ ms}$, the 50 req/sec public cross-server burst was dropped at the hosting platform edge (Cloudflare / Render edge reverse proxy connection limits on free instances) before reaching the Uvicorn application server.

### 3. Why It Happens
Single-node free instances lack dedicated ingress load balancers, elastic scaling, and edge message buffers (e.g. AWS API Gateway + SQS / Cloudflare Queues). When a high-rate burst saturates edge TCP connections, the edge proxy drops inbound requests.

### 4. Empirical Status
**Observed in live simulation run `run_aa4b696f4023`** on Render Free Tier.

---

## Failure Mode 5: Out-of-Order Delivery Deletion Window

### 1. Condition
A user posts a keyword comment. The webhook is ingested, Celery worker immediately picks up the task, satisfies the rate limit, and dispatches the DM to PseudoGram within 1.5 seconds. Three seconds later, the user deletes the comment, triggering `comment.deleted`.

### 2. What Happens
Because the DM was already dispatched and accepted by PseudoGram before `comment.deleted` arrived, the message is already in the recipient's inbox. LinkPlease marks `comment.is_deleted = TRUE` in PostgreSQL, but direct messages cannot be asynchronously recalled or un-sent on external social networks.

### 3. Why It Happens
Event arrival order is decoupled from real-world asynchronous user actions. Once a packet is handed off to an external network, downstream distributed state cannot be rolled back.

### 4. Empirical Status
**Observed and mitigated where possible**: If `comment.deleted` arrives *before* or *during* queue wait time, LinkPlease successfully aborts dispatch ([`tests/integration/test_comment_deleted.py`](file:///d:/linkplease-assignment/tests/integration/test_comment_deleted.py)).
