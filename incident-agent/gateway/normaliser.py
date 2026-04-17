from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.models import Alert
from gateway.dedup import fingerprint


def _to_str_dict(d: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        if v is None:
            continue
        out[str(k)] = str(v)
    return out


def _parse_timestamp(value: Any) -> datetime:
    """
    Parse timestamps from common webhook formats into an aware UTC datetime.
    """

    if value is None:
        return datetime.now(timezone.utc)

    if isinstance(value, (int, float)):
        # Heuristic: milliseconds vs seconds
        v = float(value)
        if v > 1e12:
            return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(v, tz=timezone.utc)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return datetime.now(timezone.utc)
        # Handle common `...Z` ISO-8601 format.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    return datetime.now(timezone.utc)


def _tags_to_labels(tags: list[str] | None) -> dict[str, str]:
    if not tags:
        return {}

    labels: dict[str, str] = {}
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        if ":" in tag:
            k, v = tag.split(":", 1)
            labels[k] = v
        elif "=" in tag:
            k, v = tag.split("=", 1)
            labels[k] = v
        else:
            # Fall back for tags without a separator.
            labels["tag"] = tag
    return labels


def _severity_from_datadog(priority: Any) -> str:
    if priority is None:
        return "unknown"
    if isinstance(priority, (int, float)):
        n = int(priority)
        return {1: "low", 2: "medium", 3: "high"}.get(n, str(priority))

    s = str(priority).strip().lower()
    if s.isdigit():
        n = int(s)
        return {1: "low", 2: "medium", 3: "high"}.get(n, s)
    if "low" in s:
        return "low"
    if "med" in s:
        return "medium"
    if "high" in s:
        return "high"
    return s


def normalise_datadog(payload: dict[str, Any]) -> Alert:
    """
    Normalize a Datadog alert webhook payload into `shared.models.Alert`.
    """

    # Some integrations wrap payload in a `data` key.
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    title = str(data.get("title") or data.get("alert_title") or data.get("alert_name") or data.get("message") or "")
    if not title:
        title = "datadog-alert"

    tags = data.get("tags")
    tags_list: list[str] = tags if isinstance(tags, list) else []
    labels = _tags_to_labels(tags_list)

    # Enrich with commonly useful fields (keep deterministic and stringified).
    if data.get("alert_id") is not None:
        labels["alert_id"] = str(data["alert_id"])
    if data.get("status") is not None:
        labels["status"] = str(data["status"])
    if data.get("handle") is not None:
        labels["handle"] = str(data["handle"])

    service = (
        labels.get("service")
        or labels.get("app")
        or labels.get("component")
        or str(data.get("host") or "unknown-service")
    )

    severity = _severity_from_datadog(data.get("priority"))
    timestamp = _parse_timestamp(data.get("date_happened") or data.get("timestamp"))

    alert = Alert(
        source="datadog",
        service=service,
        alert_name=title,
        timestamp=timestamp,
        severity=severity,
        labels=labels,
        fingerprint="",  # filled deterministically below
    )
    alert.fingerprint = fingerprint(alert.service, alert.labels)
    return alert


def normalise_prometheus(payload: dict[str, Any]) -> Alert:
    """
    Normalize a Prometheus/Alertmanager-style webhook payload into `shared.models.Alert`.
    """

    alerts = payload.get("alerts")
    chosen: dict[str, Any] | None = None
    if isinstance(alerts, list) and alerts:
        chosen = alerts[0] if isinstance(alerts[0], dict) else None
    chosen = chosen or payload

    labels_in = chosen.get("labels") if isinstance(chosen.get("labels"), dict) else {}
    labels = _to_str_dict(labels_in)

    annotations = chosen.get("annotations") if isinstance(chosen.get("annotations"), dict) else {}
    annotations_str = _to_str_dict(annotations)

    service = labels.get("service") or labels.get("job") or labels.get("instance") or "unknown-service"
    alert_name = labels.get("alertname") or labels.get("alert") or annotations_str.get("summary") or "prometheus-alert"
    severity = labels.get("severity") or annotations_str.get("severity") or "unknown"

    timestamp = _parse_timestamp(chosen.get("startsAt") or chosen.get("timestamp"))

    # Keep extra context in labels for traceability and fingerprint stability.
    if chosen.get("generatorURL") is not None:
        labels["generatorURL"] = str(chosen["generatorURL"])
    if chosen.get("summary") is not None:
        labels["summary"] = str(chosen["summary"])

    alert = Alert(
        source="prometheus",
        service=service,
        alert_name=alert_name,
        timestamp=timestamp,
        severity=severity,
        labels=labels,
        fingerprint="",  # filled deterministically below
    )
    alert.fingerprint = fingerprint(alert.service, alert.labels)
    return alert

