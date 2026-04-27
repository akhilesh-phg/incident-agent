from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, Field

from shared.config import settings
from shared.models import Alert, RiskLevel, TriageResult


def _risk_from_severity(severity: str) -> RiskLevel:
    s = (severity or "").strip().lower()
    if s in {"high", "critical"}:
        return "high"
    if s in {"medium", "med"}:
        return "medium"
    if s in {"low", "info", "informational"}:
        return "low"
    return "medium"


KNOWN_SCENARIOS = frozenset({"latency-spike", "error-burst", "cpu-brownout"})

_SCENARIOS_DIR = Path(__file__).resolve().parent / "demo_data" / "scenarios"


class DemoScenarioPack(BaseModel):
    """Static scenario copy for demo triage and Slack/UI surfaces."""

    model_config = {"extra": "ignore"}

    what_is_the_error: str
    likely_cause: str
    remediation_suggestions: list[str] = Field(default_factory=list)
    triage_summary: str = Field(validation_alias=AliasChoices("triage_summary", "summary"))
    suspected_cause: str | None = None
    recommended_runbooks: list[str] = Field(default_factory=list)


def scenario_key_from_alert(alert: Alert) -> str | None:
    raw = (alert.labels.get("scenario") or "").strip()
    if raw in KNOWN_SCENARIOS:
        return raw
    monitor = (alert.labels.get("monitor") or "").strip().lower()
    for key in KNOWN_SCENARIOS:
        if key.replace("-", "") in monitor.replace("-", "") or key in monitor:
            return key
    return None


@lru_cache(maxsize=len(KNOWN_SCENARIOS))
def _load_pack_cached(scenario_key: str) -> DemoScenarioPack | None:
    path = _SCENARIOS_DIR / f"{scenario_key}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return DemoScenarioPack.model_validate(data)


def load_demo_pack(scenario_key: str) -> DemoScenarioPack | None:
    if scenario_key not in KNOWN_SCENARIOS:
        return None
    return _load_pack_cached(scenario_key)


def load_demo_triage(alert: Alert, *, scenario_key: str | None = None) -> TriageResult | None:
    if not settings.USE_DEMO_STATIC_TRIAGE:
        return None
    key = scenario_key or scenario_key_from_alert(alert)
    if not key:
        return None
    pack = load_demo_pack(key)
    if not pack:
        return None

    return TriageResult(
        risk_level=_risk_from_severity(alert.severity),
        severity=alert.severity,
        summary=pack.triage_summary,
        suspected_cause=pack.suspected_cause,
        recommended_runbooks=list(pack.recommended_runbooks),
    )


def demo_slack_fields(alert: Alert) -> dict[str, Any] | None:
    if not settings.USE_DEMO_STATIC_TRIAGE:
        return None
    key = scenario_key_from_alert(alert)
    if not key:
        return None
    pack = load_demo_pack(key)
    if not pack:
        return None
    return {
        "scenario": key,
        "what_is_the_error": pack.what_is_the_error,
        "likely_cause": pack.likely_cause,
        "remediation_suggestions": pack.remediation_suggestions,
    }


def presented_user_snapshot(
    alert: Alert,
    triage: TriageResult,
    *,
    demo_fields: dict[str, Any] | None,
    similar: dict[str, Any] | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "triage": triage.model_dump(),
        "similar_incidents": similar,
    }
    if demo_fields:
        out["what_is_the_error"] = demo_fields.get("what_is_the_error")
        out["likely_cause"] = demo_fields.get("likely_cause")
        out["remediation_suggestions"] = demo_fields.get("remediation_suggestions")
    else:
        out["what_is_the_error"] = triage.summary
        out["likely_cause"] = triage.suspected_cause
        out["remediation_suggestions"] = []
    out["alert_name"] = alert.alert_name
    out["service"] = alert.service
    return out
