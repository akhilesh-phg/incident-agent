# Generic error-rate investigation runbook

When an alert fires about elevated error rates:

1. Identify the dominant error types and affected endpoints.
2. Roll back any recent deploys that correlate with the spike if safe.
3. Check dependency health (databases, caches, message brokers, third-party APIs).
4. Add structured logging around failing code paths to capture parameters and context.
5. Implement feature flags or circuit breakers to reduce blast radius while investigating.

