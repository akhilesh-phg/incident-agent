from __future__ import annotations

from shared.demo_triage import load_demo_triage
from shared.models import Alert, RiskLevel, TriageResult
from agent.memory import get_top_runbooks


def _risk_from_severity(severity: str) -> RiskLevel:
    s = (severity or "").strip().lower()
    if s in {"high", "critical"}:
        return "high"
    if s in {"medium", "med"}:
        return "medium"
    if s in {"low", "info", "informational"}:
        return "low"
    # Fallback: treat unknown as medium to be safe.
    return "medium"


async def run_triage(alert: Alert) -> TriageResult:
    static = load_demo_triage(alert)
    if static is not None:
        return static

    risk_level = _risk_from_severity(alert.severity)
    suspected_cause = None
    recommended_runbooks = await get_top_runbooks(alert)

    summary = (
        f"Alert '{alert.alert_name}' for service '{alert.service}' "
        f"with severity '{alert.severity}' (source={alert.source})."
    )

    return TriageResult(
        risk_level=risk_level,
        severity=alert.severity,
        summary=summary,
        suspected_cause=suspected_cause,
        recommended_runbooks=recommended_runbooks,
    )

