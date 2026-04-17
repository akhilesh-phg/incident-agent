# Generic latency investigation runbook

When an alert fires about increased latency for a service:

1. Check recent deploys or config changes for the service.
2. Inspect upstream dependencies (DB, cache, external APIs) for saturation or errors.
3. Look for hot paths in logs around the time of the spike.
4. If the issue is read-heavy, consider enabling or tuning caching.
5. If the issue is write-heavy, consider queueing or back-pressure mechanisms.

