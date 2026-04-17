# AGENTS.md - Gateway package

## Ownership
Webhook gateway: accept alert webhooks, normalize them into the shared alert contract, dedupe them, and enqueue into the Redis Stream for the agent.

## Responsibilities
- Implement HTTP endpoints:
  - `POST /webhook/datadog`
  - `POST /webhook/prometheus`
- Normalize payloads into `shared.models.Alert`:
  - `normalise_datadog()` in `normaliser.py`
  - `normalise_prometheus()` in `normaliser.py`
- Implement dedupe fingerprinting and Redis dedupe logic:
  - fingerprint based on service + sorted labels
  - dedupe window of 300 seconds
- Enqueue normalized alerts to Redis Stream `alerts:incoming` using `XADD`
- Emit structlog events for “alert received” and “dedup hit”

## Files
- `main.py`
- `normaliser.py`
- `dedup.py`

