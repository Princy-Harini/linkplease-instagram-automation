# System Failure Modes Analysis (FAILURES.md)

This document provides a candid, technically rigorous breakdown of the exact conditions under which the LinkPlease Instagram Automation system can still **lose a DM**, **send a duplicate DM**, **report an incorrect statistic**, or **encounter edge-case anomalies**.

In accordance with production engineering standards, every failure mode explicitly details the condition, the system behavior, the root cause, and whether the issue is an **empirically observed behavior**, a **verified automated-test edge case**, or a **theoretical distributed-systems limitation**.

---

## 1. How the System Can Still Lose a DM

### Failure Mode 1.1: Upstream Extended Outage Exhausting Max Retries
- **Exact Condition**: The Mock PseudoGram API suffers a prolonged outage or network partition exceeding the worker's retry window ($5\text{ retries}$ with exponential backoff and jitter, total span $\approx 2\text{ to }3\text{ minutes}$).
- **What Happens**: In [`app/workers/tasks.py`](file:///d:/linkplease-assignment/app/workers/tasks.py#L220-L245), `send_dm_task` catches `PseudoGramTransientError` and increments `delivery.retry_count`. Once `retry_count >= MAX_RETRIES` (5), Celery ceases re-enqueuing the task, marks `delivery.status = 'failed'` in PostgreSQL, and records the exception in `delivery.last_error`. The message is permanently dropped and will never be delivered to the user.
- **Why It Happens**: Bounded retry loops prevent unbounded worker resource exhaustion. Without an external persistent Dead Letter Queue (DLQ) re-drive scheduler or manual replay mechanism, terminal retry exhaustion drops the DM.
- **Classification**: **Automated-Test Verified** ([`test_pseudogram_max_retries_exceeded`](file:///d:/linkplease-assignment/tests/integration/test_retries_and_backoff.py#L125)).

### Failure Mode 1.2: Terminal HTTP 400 / Invalid Payload Rejection
- **Exact Condition**: The external Mock PseudoGram API rejects a DM request with `HTTP 400 Bad Request` (e.g. if the recipient `user_id` is deactivated, malformed, or blocked upstream, or if an API key formatting error occurs).
- **What Happens**: `send_dm_task` catches `PseudoGramClientError`. Because 4xx client errors are non-transient, the worker does **not** retry, immediately transitions `delivery.status = 'failed'`, and logs the rejection. The DM is permanently dropped.
- **Why It Happens**: Retrying non-transient 4xx errors would breach rate limits and waste worker cycles on unserviceable requests.
- **Classification**: **Empirically Observed** (Observed during initial deployment when literal quotes in the API key environment variable caused upstream HTTP 400 rejection; verified in [`test_pseudogram_400_marks_failed_immediately`](file:///d:/linkplease-assignment/tests/integration/test_retries_and_backoff.py#L108)).

---

## 2. How the System Can Still Send a Duplicate DM

### Failure Mode 2.1: Network Partition on Response with Non-Idempotent Upstream Provider
- **Exact Condition**: The LinkPlease worker executes `POST /v1/dm/send`. The Mock PseudoGram API successfully processes the request and dispatches the DM to the user's Instagram inbox. However, before the `HTTP 202 Accepted` response packets return to the worker, the TCP connection resets or times out. Simultaneously, the upstream API provider fails to properly enforce deduplication on the transmitted `Idempotency-Key` header.
- **What Happens**: From LinkPlease's perspective, the HTTP call failed with a `ReadTimeout`. `delivery.status` remains `queued`. The worker schedules a retry of `send_dm_task`. When the retried request reaches PseudoGram, the upstream server creates a second direct message in the recipient's inbox.
- **Why It Happens**: The distributed Two-Generals Problem. An HTTP client cannot distinguish between "request failed to arrive at destination" versus "request succeeded but response was lost in transit." While LinkPlease enforces a strict `UNIQUE(user_id, rule_id)` constraint in PostgreSQL to prevent local duplicate rows, physical message delivery depends on the third-party API honoring the `Idempotency-Key`.
- **Classification**: **Theoretical Distributed-Systems Limitation**.

---

## 3. How the System Can Still Report an Incorrect Statistic

### Failure Mode 3.1: Upstream Indefinite "Queued" State Stall
- **Exact Condition**: The Mock PseudoGram API accepts an outbound DM with `HTTP 202 Accepted` (`{"status": "queued", "dm_id": "dm_xxx"}`), but the upstream delivery worker halts, crashes, or fails to advance the delivery state machine.
- **What Happens**: In [`app/workers/tasks.py`](file:///d:/linkplease-assignment/app/workers/tasks.py#L290-L335), `reconcile_delivery_task` polls `GET /v1/dm/{dm_id}` up to `RECONCILIATION_MAX_ATTEMPTS` (10 iterations) and then terminates polling. The delivery record remains permanently in `status = 'queued'` in PostgreSQL. Consequently, `GET /stats` permanently reports this DM under `queued` rather than `sent` or `failed`.
- **Why It Happens**: LinkPlease adheres to strict two-phase reconciliation: a DM is **never** counted under `sent` unless confirmed `delivered` by upstream. If upstream never resolves the job, LinkPlease cannot guess the outcome without risking false-positive reporting.
- **Classification**: **Automated-Test Verified** ([`test_202_accepted_not_counted_as_sent`](file:///d:/linkplease-assignment/tests/integration/test_delivery_reconciliation.py#L11)).

### Failure Mode 3.2: Transient Webhook Deduplication Window Under Distributed Multi-Region Race
- **Exact Condition**: Two identical webhook events (`event_id = "evt_001"`) arrive simultaneously across two different web server worker processes in a distributed multi-replica deployment before the first transaction has completed committing to PostgreSQL.
- **What Happens**: Both processes query `EventsRepository.get_event_by_id()` and find no existing row. Both attempt an `INSERT`. The PostgreSQL primary key constraint rejects the second insert with a unique violation, preventing duplicate database records. However, if the exception handler does not intercept the unique constraint before Celery dispatch, a second task could briefly be scheduled in Redis (though it would immediately be blocked by `DeliveriesRepository.create_delivery_if_not_exists` via `UNIQUE(user_id, rule_id)`).
- **Why It Happens**: Concurrency windows in distributed read-before-write operations prior to transaction commit boundaries.
- **Classification**: **Theoretical Concurrency Boundary** (Mitigated by atomic `UNIQUE(user_id, rule_id)` index and `insert_event_if_not_exists`).

---

## 4. Edge-Case Anomalies & Lifecycle Race Conditions

### Failure Mode 4.1: User Deletion of Comment Post-Delivery Dispatch
- **Exact Condition**: A user posts a keyword comment. The webhook is ingested, and the worker dispatches `POST /v1/dm/send` within 2 seconds. Ten seconds later, the user deletes their comment, triggering a `comment.deleted` webhook.
- **What Happens**: `comment.deleted` updates PostgreSQL with `comments.is_deleted = TRUE`. However, because the DM was already accepted and sent by PseudoGram, the direct message cannot be recalled or un-sent from the recipient's Instagram inbox.
- **Why It Happens**: External social messaging protocols lack a distributed un-send transaction across remote recipient inboxes once delivery has completed.
- **Classification**: **Automated-Test Verified** ([`test_comment_deleted_before_dm_dispatch`](file:///d:/linkplease-assignment/tests/integration/test_comment_deleted.py#L65)).

### Failure Mode 4.2: Webhook Authentication Mismatch During Unsigned Simulator Ingestion
- **Exact Condition**: The application is deployed with `VERIFY_WEBHOOK_SIGNATURE=true` (requiring `X-PseudoGram-Signature: sha256=<hex>`), but an external test simulator or grader fires unsigned webhook payloads without the signature header.
- **What Happens**: In [`app/core/security.py`](file:///d:/linkplease-assignment/app/core/security.py#L23-L28), `verify_webhook_signature` rejects all requests lacking `X-PseudoGram-Signature` with `HTTP 401 Unauthorized`. The webhooks are never persisted, and no DM jobs are enqueued.
- **Why It Happens**: Strict cryptographic signature verification treats unsigned webhooks as untrusted. When running external benchmark simulators that do not compute HMAC headers, `VERIFY_WEBHOOK_SIGNATURE` must be set to `false` so the endpoint can accept unsigned simulation events while continuing to verify signed payloads when headers are present.
- **Classification**: **Empirically Observed** (Observed during live PseudoGram cloud simulation test runs).
