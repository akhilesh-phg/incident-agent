from __future__ import annotations

from datetime import datetime, timezone

from gateway.normaliser import normalise_datadog, normalise_prometheus


def test_normalise_datadog_basic() -> None:
    payload = {
        "title": "High latency on api",
        "tags": ["service:payments-api", "env:prod"],
        "priority": "high",
        "date_happened": 1_700_000_000,
    }

    alert = normalise_datadog(payload)

    assert alert.source == "datadog"
    assert alert.service == "payments-api"
    assert alert.alert_name == "High latency on api"
    assert alert.severity == "high"
    assert alert.labels["env"] == "prod"
    assert alert.fingerprint
    assert alert.timestamp.tzinfo is not None
    assert alert.timestamp.tzinfo == timezone.utc


def test_normalise_prometheus_basic() -> None:
    payload = {
        "alerts": [
            {
                "labels": {
                    "service": "checkout",
                    "alertname": "ErrorRateHigh",
                    "severity": "critical",
                },
                "annotations": {
                    "summary": "High error rate on checkout",
                },
                "startsAt": datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
            }
        ]
    }

    alert = normalise_prometheus(payload)

    assert alert.source == "prometheus"
    assert alert.service == "checkout"
    assert alert.alert_name == "ErrorRateHigh"
    assert alert.severity == "critical"
    assert alert.labels["alertname"] == "ErrorRateHigh"
    assert alert.timestamp.tzinfo is not None
    assert alert.timestamp.tzinfo == timezone.utc

